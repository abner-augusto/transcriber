"""parakeet.cpp as a Transcriber.

parakeet-cli already speaks Words — `--timestamps --json` puts them on stdout as
`{"w", "start", "end", "conf"}` — so this adapter is mostly a shape change. The one
thing it must add is the leading space the Word contract asks for: Parakeet's words
arrive bare ("Rádio"), with punctuation already attached ("ar,").

The JSON is the last line of stdout; the lines before it are the CUDA backend
talking to itself.

Long audio is this Engine's sharp edge, and the reason for most of the code below.
parakeet-cli builds one compute graph over the whole clip and that graph grows with the
square of the clip's length, so a long Meeting cannot be transcribed in one piece: it
is cut into chunks here, and the Words are put back on the Meeting's timeline. A cut
lands wherever the audio is quietest nearby, so it falls in a pause rather than through
the middle of a word. See ADR-0003 — the constants below are measurements, not taste,
and a new Parakeet model invalidates them.
"""

import json
import logging
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from .ports import Word

log = logging.getLogger(__name__)

TRANSCRIBE_TIMEOUT_SECONDS = 1800

# Chunk length, and how far from a boundary we will wander to find a pause to cut in.
# 300s peaks at ~5.4 GB of VRAM, which leaves room for both a smaller GPU and for
# pyannote afterwards. Raising it buys little: the graph grows quadratically.
CHUNK_SECONDS = 300
SNAP_SECONDS = 15
QUIET_WINDOW_SECONDS = 0.5

# A tail shorter than this rides along with the chunk before it. Snapping to a pause
# can land a cut all but at the end of the audio — trailing silence is the quietest
# thing there is — and the leftover sliver is not worth a parakeet-cli run of its own.
MIN_TAIL_SECONDS = 10


class ParakeetCppTranscriber:
    def __init__(
        self,
        cli_path: str,
        model_path: str,
        decoder: str = "tdt",
        timeout: int = TRANSCRIBE_TIMEOUT_SECONDS,
        chunk_seconds: float = CHUNK_SECONDS,
    ):
        self.cli_path = cli_path
        self.model_path = model_path
        self.decoder = decoder
        self.timeout = timeout
        self.chunk_seconds = chunk_seconds

    def transcribe(self, audio_path: str, vocabulary: str | None = None) -> list[Word]:
        """Transcribe. `vocabulary` is ignored — Parakeet takes no prompt."""
        audio, sample_rate = sf.read(audio_path, dtype="float32", always_2d=True)
        audio = audio[:, 0]
        duration = len(audio) / sample_rate

        if duration <= self.chunk_seconds:
            words = self._transcribe_file(audio_path)
            log.info(f"[parakeet.cpp] {len(words)} words from {Path(self.model_path).name}")
            return words

        cuts = _chunk_bounds(audio, sample_rate, self.chunk_seconds)
        log.info(
            f"[parakeet.cpp] {duration / 60:.1f} min of audio -> {len(cuts)} chunks "
            f"(the encoder graph will not fit in VRAM in one piece)"
        )

        words: list[Word] = []
        with tempfile.TemporaryDirectory(prefix="parakeet-chunks-") as tmp:
            for i, (start, end) in enumerate(cuts, 1):
                chunk_path = str(Path(tmp) / f"chunk_{i:03d}.wav")
                sf.write(
                    chunk_path,
                    audio[int(start * sample_rate) : int(end * sample_rate)],
                    sample_rate,
                )

                chunk_words = self._transcribe_file(chunk_path)
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
                    f"[parakeet.cpp] chunk {i}/{len(cuts)} "
                    f"({start / 60:.1f}-{end / 60:.1f} min): {len(chunk_words)} words"
                )

        log.info(f"[parakeet.cpp] {len(words)} words from {Path(self.model_path).name}")
        return words

    def _transcribe_file(self, audio_path: str) -> list[Word]:
        """One parakeet-cli run over one file, whose Words start at that file's zero."""
        cmd = [
            self.cli_path,
            "transcribe",
            "--model", self.model_path,
            "--input", audio_path,
            "--decoder", self.decoder,
            "--timestamps",
            "--json",
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=self.timeout,
        )
        if result.returncode != 0:
            raise RuntimeError(f"parakeet-cli failed: {result.stderr}")

        return parse_words(result.stdout)


def _chunk_bounds(audio: np.ndarray, sample_rate: int, chunk_seconds: float) -> list[tuple[float, float]]:
    """(start, end) pairs in seconds covering the audio, cut where it is quietest."""
    duration = len(audio) / sample_rate
    bounds = []
    start = 0.0
    while duration - start > chunk_seconds:
        cut = _quietest_point(audio, sample_rate, start + chunk_seconds)
        if duration - cut < MIN_TAIL_SECONDS:
            break
        bounds.append((start, cut))
        start = cut
    bounds.append((start, duration))
    return bounds


def _quietest_point(audio: np.ndarray, sample_rate: int, target: float) -> float:
    """The centre of the quietest short window within SNAP_SECONDS of `target`.

    A boundary in a pause costs nothing; a boundary through a word costs that word,
    because neither chunk sees enough of it to recognise it.
    """
    lo = max(0, int((target - SNAP_SECONDS) * sample_rate))
    hi = min(len(audio), int((target + SNAP_SECONDS) * sample_rate))
    window = int(QUIET_WINDOW_SECONDS * sample_rate)
    if hi - lo <= window:
        return target

    # Energy of every window in [lo, hi), via a rolling sum of squares.
    squares = np.concatenate(([0.0], np.cumsum(np.square(audio[lo:hi], dtype=np.float64))))
    energy = squares[window:] - squares[:-window]
    quietest = int(np.argmin(energy))

    return (lo + quietest + window / 2) / sample_rate


def parse_words(stdout: str) -> list[Word]:
    """Words from parakeet-cli's `--json` output, which is the last JSON line of stdout."""
    payload = None
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            payload = json.loads(line)
            break
    if payload is None:
        raise RuntimeError("parakeet-cli produced no JSON on stdout")

    return [
        Word(
            start=float(w["start"]),
            end=float(w["end"]),
            text=" " + w["w"],
            confidence=w.get("conf"),
        )
        for w in payload.get("words", [])
        if w.get("w")
    ]
