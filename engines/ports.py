"""The two seams an Engine can be swapped in at.

A Transcriber turns audio into Words. A Diarizer turns the same audio into Turns.
They are separate on purpose: nothing local does both at once, and ADR-0001 rules
out the cloud services that would be the only reason to fuse them.

Neither port produces Segments. A Segment is what a reader sees, and it is derived
from Words and Turns together — see tasks.shared.build_segments.
"""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class Word:
    """One word of transcript, with the time it was spoken.

    ``text`` is join-ready: the transcript for a run of Words is
    ``"".join(w.text for w in words).strip()``. An adapter must therefore emit
    whatever leading whitespace its language needs, so that words do not run
    together and punctuation still glues to the word before it. Whisper's
    subword tokens already carry that leading space; Parakeet's do not, so its
    adapter adds one.
    """

    start: float
    end: float
    text: str
    confidence: float | None = None

    def to_dict(self) -> dict:
        return {
            "start": self.start,
            "end": self.end,
            "text": self.text,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Word":
        return cls(
            start=float(d["start"]),
            end=float(d["end"]),
            text=d["text"],
            confidence=d.get("confidence"),
        )


@dataclass(frozen=True)
class Turn:
    """One unbroken stretch of speech by one Speaker.

    ``speaker`` is a Diarizer-local label (``SPEAKER_00``), not a name. Naming is
    the Speaker Namer's job.
    """

    start: float
    end: float
    speaker: str

    def to_dict(self) -> dict:
        return {"start": self.start, "end": self.end, "speaker": self.speaker}

    @classmethod
    def from_dict(cls, d: dict) -> "Turn":
        return cls(start=float(d["start"]), end=float(d["end"]), speaker=d["speaker"])


@dataclass(frozen=True)
class DiarizationResult:
    """The outcome of running a Diarizer over audio.

    ``turns`` contains the original (potentially overlapping) Turns.
    ``exclusive_turns`` contains single-speaker exclusive Turns when available
    (e.g., from Community-1), used for unambiguous Word/Segment attribution.
    ``overlaps`` contains computed or model-provided overlapping speech regions.
    """

    turns: list[Turn]
    exclusive_turns: list[Turn] | None = None
    overlaps: list[dict] | None = None

    def __iter__(self):
        return iter(self.turns)

    def __len__(self):
        return len(self.turns)

    def __getitem__(self, index):
        return self.turns[index]


@runtime_checkable
class Transcriber(Protocol):
    """Turns audio into Words. Implemented by whisper.cpp and parakeet.cpp."""

    def transcribe(self, audio_path: str, vocabulary: str | None = None) -> list[Word]:
        """Words in ascending time order.

        ``vocabulary`` is a hint, not a promise: an Engine that cannot be primed
        with domain terms is free to ignore it. Raises RuntimeError if the Engine
        fails; the caller fails the Job.
        """
        ...


@runtime_checkable
class Diarizer(Protocol):
    """Turns audio into Turns. Implemented by pyannote."""

    def diarize(
        self,
        audio_path: str,
        min_speakers: int | None = None,
        max_speakers: int | None = None,
    ) -> DiarizationResult | list[Turn]:
        """Turns in ascending time order. May overlap when people talk over each other."""
        ...


@runtime_checkable
class Aligner(Protocol):
    """Refines timestamps of existing Words against audio without altering text or order."""

    def align(self, audio_path: str, words: list[Word]) -> list[Word]:
        """Aligned Words with refined start and end timestamps."""
        ...

