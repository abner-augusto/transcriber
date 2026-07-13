"""whisper.cpp as a Transcriber.

whisper-cli emits subword tokens, not words: "Rádio" arrives as " R" + "ád" + "io".
This adapter stitches them back into Words. A token that starts with whitespace
starts a new word; every other token — including bare punctuation — belongs to the
word before it, which is what keeps "ar," together.

Whisper's token timestamps are approximate unless it is built with DTW, so a Word's
start and end here are looser than Parakeet's. They are accurate enough to attribute
a word to a Turn, which is all the pipeline asks of them.
"""

import json
import logging
import subprocess
from pathlib import Path

from .ports import Word

log = logging.getLogger(__name__)

# whisper.cpp token ids at or above this are control tokens ([_BEG_], timestamps),
# not text. They carry no offsets and must not reach the transcript.
FIRST_SPECIAL_TOKEN_ID = 50257

TRANSCRIBE_TIMEOUT_SECONDS = 1800
MAX_PROMPT_CHARS = 500


class WhisperCppTranscriber:
    def __init__(
        self,
        cli_path: str,
        model_path: str,
        language: str = "auto",
        timeout: int = TRANSCRIBE_TIMEOUT_SECONDS,
    ):
        self.cli_path = cli_path
        self.model_path = model_path
        self.language = language
        self.timeout = timeout

    def transcribe(self, audio_path: str, vocabulary: str | None = None) -> list[Word]:
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

        words = parse_words(data)
        log.info(f"[whisper.cpp] {len(words)} words from {Path(self.model_path).name}")
        return words


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
