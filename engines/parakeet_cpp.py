"""parakeet.cpp as a Transcriber.

parakeet-cli already speaks Words — `--timestamps --json` puts them on stdout as
`{"w", "start", "end", "conf"}` — so this adapter is mostly a shape change. The one
thing it must add is the leading space the Word contract asks for: Parakeet's words
arrive bare ("Rádio"), with punctuation already attached ("ar,").

The JSON is the last line of stdout; the lines before it are the CUDA backend
talking to itself.
"""

import json
import logging
import subprocess
from pathlib import Path

from .ports import Word

log = logging.getLogger(__name__)

TRANSCRIBE_TIMEOUT_SECONDS = 1800


class ParakeetCppTranscriber:
    def __init__(
        self,
        cli_path: str,
        model_path: str,
        decoder: str = "tdt",
        timeout: int = TRANSCRIBE_TIMEOUT_SECONDS,
    ):
        self.cli_path = cli_path
        self.model_path = model_path
        self.decoder = decoder
        self.timeout = timeout

    def transcribe(self, audio_path: str, vocabulary: str | None = None) -> list[Word]:
        """Transcribe. `vocabulary` is ignored — Parakeet takes no prompt."""
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

        words = parse_words(result.stdout)
        log.info(f"[parakeet.cpp] {len(words)} words from {Path(self.model_path).name}")
        return words


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
