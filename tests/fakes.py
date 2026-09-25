"""Fake Engines.

The reason the Transcriber and Diarizer ports exist is so that everything downstream
of them can be tested without a GPU, a model file, or a subprocess. These two classes
are the whole cost of that.
"""

from engines import DiarizationResult, Transcription, Turn, Word


class FakeTranscriber:
    """Returns the Words it was constructed with, and remembers how it was called."""

    def __init__(self, words: list[Word]):
        self.words = words
        self.calls: list[tuple[str, str | None]] = []
        self.lifecycle: list[str] = []

    def load(self) -> None:
        self.lifecycle.append("load")

    def transcribe(self, audio_path: str, vocabulary: str | None = None) -> Transcription:
        self.calls.append((audio_path, vocabulary))
        self.lifecycle.append("transcribe")
        return Transcription(words=list(self.words))

    def unload(self) -> None:
        self.lifecycle.append("unload")


class FakeDiarizer:
    """Returns the Turns or DiarizationResult it was constructed with, and remembers how it was called."""

    def __init__(
        self,
        turns: list[Turn] | DiarizationResult,
        exclusive_turns: list[Turn] | None = None,
        overlaps: list[dict] | None = None,
    ):
        if isinstance(turns, DiarizationResult):
            self.result = turns
        else:
            self.result = DiarizationResult(
                turns=list(turns),
                exclusive_turns=list(exclusive_turns) if exclusive_turns is not None else None,
                overlaps=overlaps,
            )
        self.turns = self.result.turns
        self.calls: list[tuple[str, int | None, int | None]] = []

    def diarize(
        self,
        audio_path: str,
        min_speakers: int | None = None,
        max_speakers: int | None = None,
    ) -> DiarizationResult:
        self.calls.append((audio_path, min_speakers, max_speakers))
        return self.result


def spoken(text: str, start: float, end: float, confidence: float | None = None) -> Word:
    """A Word, written the way an adapter must emit it: with its leading space."""
    return Word(start=start, end=end, text=" " + text, confidence=confidence)
