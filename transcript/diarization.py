"""What a Meeting knows about who spoke when, in the one shape it is stored in."""

from dataclasses import dataclass

from engines import Turn, compute_overlaps


@dataclass(frozen=True)
class MeetingDiarization:
    """The Turns of one Meeting, as the Diarization stage produced them.

    ``turns`` and ``exclusive_turns`` are bounded to speech. A single-track or native
    diarization also keeps the ``original_*`` Turns the Engine returned before that
    bounding; a dual-track one does not, and instead names its ``host_label``.
    """

    engine: str
    turns: list[Turn]
    exclusive_turns: list[Turn] | None
    overlaps: list[dict]
    host_label: str | None = None
    original_turns: list[Turn] | None = None
    original_exclusive_turns: list[Turn] | None = None
    original_overlaps: list[dict] | None = None

    @property
    def attribution_turns(self) -> list[Turn]:
        """The Turns Words are attributed against: exclusive ones when there are any."""
        return self.exclusive_turns if self.exclusive_turns else self.turns

    @property
    def speaker_labels(self) -> list[str]:
        return sorted({turn.speaker for turn in self.turns + (self.exclusive_turns or [])})

    def to_stored(self) -> dict:
        stored = {
            "engine": self.engine,
            "turns": _dump(self.turns),
            "exclusive_turns": _dump(self.exclusive_turns),
            "overlaps": self.overlaps,
        }
        if self.original_turns is not None:
            stored["original_turns"] = _dump(self.original_turns)
            stored["original_exclusive_turns"] = _dump(self.original_exclusive_turns)
            stored["original_overlaps"] = self.original_overlaps
        if self.host_label is not None:
            stored["host_label"] = self.host_label
        return stored

    @classmethod
    def from_stored(cls, raw) -> "MeetingDiarization | None":
        """Read a Meeting's ``raw_diarization``, whatever era wrote it.

        Meetings diarized before the stored shape became a dict hold a bare list of
        Turns. A stored shape without ``overlaps`` gets them computed from its Turns.
        """
        if not raw:
            return None
        if not isinstance(raw, dict):
            turns = _load(raw)
            return cls(engine="unknown", turns=turns, exclusive_turns=None, overlaps=compute_overlaps(turns))

        turns = _load(raw.get("turns") or [])
        overlaps = raw.get("overlaps")
        return cls(
            engine=raw.get("engine") or "unknown",
            turns=turns,
            exclusive_turns=_load(raw.get("exclusive_turns")),
            overlaps=overlaps if overlaps is not None else compute_overlaps(turns),
            host_label=raw.get("host_label"),
            original_turns=_load(raw.get("original_turns")),
            original_exclusive_turns=_load(raw.get("original_exclusive_turns")),
            original_overlaps=raw.get("original_overlaps"),
        )


def _dump(turns: list[Turn] | None) -> list[dict] | None:
    return [turn.to_dict() for turn in turns] if turns is not None else None


def _load(items) -> list[Turn] | None:
    return [Turn.from_dict(item) for item in items] if items is not None else None
