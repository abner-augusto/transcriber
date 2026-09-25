"""The two seams an Engine can be swapped in at.

A Transcriber turns audio into Words. A Diarizer turns the same audio into Turns.
They are separate on purpose: nothing local does both at once, and ADR-0001 rules
out the cloud services that would be the only reason to fuse them.

Neither port produces Segments. A Segment is what a reader sees, and it is derived
from Words and Turns together — see transcript.segments.derive_segments.
"""

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class Word:
    """One word of transcript, with the time it was spoken.

    ``text`` is join-ready: the transcript for a run of Words is
    ``"".join(w.text for w in words).strip()``. An adapter must therefore emit
    whatever leading whitespace its language needs, so that words do not run
    together and punctuation still glues to the word before it. Whisper's
    subword tokens already carry that leading space; Parakeet's do not, so its
    adapter adds one. ``confidence`` belongs to the Transcriber;
    ``alignment_score`` is separate evidence from optional CTC alignment.
    """

    start: float
    end: float
    text: str
    confidence: float | None = None
    alignment_score: float | None = None

    def to_dict(self) -> dict:
        return {
            "start": self.start,
            "end": self.end,
            "text": self.text,
            "confidence": self.confidence,
            "alignment_score": self.alignment_score,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Word":
        return cls(
            start=float(d["start"]),
            end=float(d["end"]),
            text=d["text"],
            confidence=d.get("confidence"),
            alignment_score=d.get("alignment_score"),
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


@dataclass(frozen=True)
class Transcription:
    """One Transcriber's output and the provenance it decided while producing it."""

    words: list[Word]
    native: DiarizationResult | None = None
    provenance: dict = field(default_factory=dict)


RESERVED_PROVENANCE_KEYS = frozenset({"engine", "preset", "words"})


def raw_transcription(engine: str, preset_id: str, transcription: Transcription) -> dict:
    """Build the stable stored shape while keeping adapter provenance namespaced by owner."""
    reserved = RESERVED_PROVENANCE_KEYS.intersection(transcription.provenance)
    if reserved:
        raise ValueError(
            "Transcription provenance cannot use reserved key(s): "
            + ", ".join(sorted(reserved))
        )
    return {
        "engine": engine,
        "preset": preset_id,
        "words": [word.to_dict() for word in transcription.words],
        **transcription.provenance,
    }


@runtime_checkable
class Transcriber(Protocol):
    """Turns audio into a Transcription. Implemented by local Transcriber Engines."""

    def load(self) -> None:
        """Load model weights or validate native executable and model paths."""
        ...

    def transcribe(self, audio_path: str, vocabulary: str | None = None) -> Transcription:
        """Return Words in ascending time order and Engine-produced provenance.

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

