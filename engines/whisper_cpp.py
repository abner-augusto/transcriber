"""whisper.cpp as a Transcriber.

whisper-cli emits subword tokens, not words: "Rádio" arrives as " R" + "ád" + "io".
This adapter stitches them back into Words. A token that starts with whitespace
starts a new word; every other token — including bare punctuation — belongs to the
word before it, which is what keeps "ar," together.

Whisper's token timestamps are approximate unless it is built with DTW, so a Word's
start and end here are looser than Parakeet's. They are accurate enough to attribute
a word to a Turn, which is all the pipeline asks of them.

whisper-cli already processes audio in internal 30s windows, so — unlike Parakeet —
nothing here is VRAM-bound. Long audio is still cut into chunks (see .chunking): one
whisper-cli call over a full meeting can run past TRANSCRIBE_TIMEOUT_SECONDS, and an
occasional GPU-detection flake should cost one chunk's worth of work, not the whole
recording's transcript.
"""

import json
import logging
import subprocess
import tempfile
from pathlib import Path

import soundfile as sf

from .chunking import chunk_bounds
from .ports import Word

log = logging.getLogger(__name__)

# whisper.cpp token ids at or above this are control tokens ([_BEG_], timestamps),
# not text. They carry no offsets and must not reach the transcript.
FIRST_SPECIAL_TOKEN_ID = 50257

TRANSCRIBE_TIMEOUT_SECONDS = 1800
MAX_PROMPT_CHARS = 500

# Long enough that most meetings need no cut at all; short enough that one chunk's
# whisper-cli call stays comfortably under TRANSCRIBE_TIMEOUT_SECONDS even on a CPU
# fallback. whisper.cpp's own per-30s-window cost means there is no VRAM ceiling
# forcing this smaller, unlike Parakeet's CHUNK_SECONDS.
CHUNK_SECONDS = 900

# A tail shorter than this rides along with the chunk before it — see parakeet_cpp's
# MIN_TAIL_SECONDS for why.
MIN_TAIL_SECONDS = 10


class WhisperCppTranscriber:
    def __init__(
        self,
        cli_path: str,
        model_path: str,
        language: str = "auto",
        timeout: int = TRANSCRIBE_TIMEOUT_SECONDS,
        chunk_seconds: float = CHUNK_SECONDS,
    ):
        self.cli_path = cli_path
        self.model_path = model_path
        self.language = language
        self.timeout = timeout
        self.chunk_seconds = chunk_seconds

    def transcribe(self, audio_path: str, vocabulary: str | None = None) -> list[Word]:
        audio, sample_rate = sf.read(audio_path, dtype="float32", always_2d=True)
        audio = audio[:, 0]
        duration = len(audio) / sample_rate

        if duration <= self.chunk_seconds:
            words = self._transcribe_file(audio_path, vocabulary)
            log.info(f"[whisper.cpp] {len(words)} words from {Path(self.model_path).name}")
            return words

        cuts = chunk_bounds(audio, sample_rate, self.chunk_seconds, MIN_TAIL_SECONDS)
        log.info(f"[whisper.cpp] {duration / 60:.1f} min of audio -> {len(cuts)} chunks")

        words: list[Word] = []
        with tempfile.TemporaryDirectory(prefix="whisper-chunks-") as tmp:
            for i, (start, end) in enumerate(cuts, 1):
                chunk_path = str(Path(tmp) / f"chunk_{i:03d}.wav")
                sf.write(
                    chunk_path,
                    audio[int(start * sample_rate) : int(end * sample_rate)],
                    sample_rate,
                )

                chunk_words = self._transcribe_file(chunk_path, vocabulary)
                # The chunk's Words are timed from the chunk's own zero; put them back
                # on the meeting's timeline.
                words.extend(
                    Word(
                        start=round(w.start + start, 3),
                        end=round(w.end + start, 3),
                        text=w.text,
                        confidence=w.confidence,
                    )
                    for w in chunk_words
                )
                log.info(
                    f"[whisper.cpp] chunk {i}/{len(cuts)} "
                    f"({start / 60:.1f}-{end / 60:.1f} min): {len(chunk_words)} words"
                )

        log.info(f"[whisper.cpp] {len(words)} words from {Path(self.model_path).name}")
        return words

    def _transcribe_file(self, audio_path: str, vocabulary: str | None = None) -> list[Word]:
        """One whisper-cli run over one file, whose Words start at that file's zero."""
        cmd = [
            self.cli_path,
            "-m", self.model_path,
            "-f", audio_path,
            "-l", self.language,
            "-ojf",            # full JSON — the only mode that includes per-token offsets
            "-of", audio_path,  # writes <audio_path>.json
        ]
        if vocabulary:
            cmd.extend(["--prompt", vocabulary[:MAX_PROMPT_CHARS]])

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=self.timeout,
        )
        if result.returncode != 0:
            raise RuntimeError(f"whisper-cli failed: {result.stderr}")

        output_json = Path(audio_path + ".json")
        with output_json.open("r", encoding="utf-8") as f:
            data = json.load(f)

        return parse_words(data)


def parse_words(data: dict) -> list[Word]:
    """Words from a whisper-cli full-JSON document."""
    words: list[Word] = []
    for item in data.get("transcription", []):
        words.extend(_words_from_tokens(item.get("tokens", [])))
    return words


def _words_from_tokens(tokens: list[dict]) -> list[Word]:
    words: list[Word] = []
    text = ""
    start = end = 0.0
    probs: list[float] = []

    def flush():
        if text.strip():
            words.append(Word(
                start=start,
                end=max(end, start),
                text=text,
                confidence=sum(probs) / len(probs) if probs else None,
            ))

    for token in tokens:
        if token.get("id", 0) >= FIRST_SPECIAL_TOKEN_ID:
            continue
        piece = token.get("text", "")
        if not piece:
            continue

        offsets = token.get("offsets") or {}
        t_start = offsets.get("from", 0) / 1000
        t_end = offsets.get("to", 0) / 1000

        if piece[:1].isspace() and text.strip():
            flush()
            text, probs = "", []
            start = t_start

        if not text:
            start = t_start
        text += piece
        end = t_end
        p = token.get("p")
        if p:
            probs.append(p)

    flush()
    return words
