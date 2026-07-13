"""Fake Engines.

The reason the Transcriber and Diarizer ports exist is so that everything downstream
of them can be tested without a GPU, a model file, or a subprocess. These two classes
are the whole cost of that.
"""

from engines import Turn, Word


class FakeTranscriber:
    """Returns the Words it was constructed with, and remembers how it was called."""

    def __init__(self, words: list[Word]):
        self.words = words
        self.calls: list[tuple[str, str | None]] = []

    def transcribe(self, audio_path: str, vocabulary: str | None = None) -> list[Word]:
        self.calls.append((audio_path, vocabulary))
        return list(self.words)


class FakeDiarizer:
    """Returns the Turns it was constructed with, and remembers how it was called."""

    def __init__(self, turns: list[Turn]):
        self.turns = turns
        self.calls: list[tuple[str, int | None, int | None]] = []

    def diarize(
        self,
        audio_path: str,
        min_speakers: int | None = None,
        max_speakers: int | None = None,
    ) -> list[Turn]:
        self.calls.append((audio_path, min_speakers, max_speakers))
        return list(self.turns)


def spoken(text: str, start: float, end: float, confidence: float | None = None) -> Word:
    """A Word, written the way an adapter must emit it: with its leading space."""
    return Word(start=start, end=end, text=" " + text, confidence=confidence)
