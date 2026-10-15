import enum
import uuid
from datetime import datetime

from sqlalchemy import String, Float, Integer, DateTime, JSON, Enum, Text, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


def _described(refs):
    # Lazy: importing `services` loads torch, which every Job child process would pay
    # for at `import models` (plan 046 regression, found by the local job runner tests).
    from services.source_reference import describe

    return describe(refs)


class MeetingStatus(str, enum.Enum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class Meeting(Base):
    __tablename__ = "meetings"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    title: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[MeetingStatus] = mapped_column(Enum(MeetingStatus), default=MeetingStatus.UPLOADED)
    original_filename: Mapped[str] = mapped_column(String, nullable=True)
    audio_filepath: Mapped[str] = mapped_column(String, nullable=True)
    # Dual-track sources. When a Meeting is dual-track (mic + system), these point
    # to the raw source files. For one file carrying both (a stereo file, an OBS file with
    # several tracks) both point to the same file and the pipeline reads the two tracks
    # `track_layout` names. NULL for single-track Meetings.
    mic_audio_filepath: Mapped[str] = mapped_column(String, nullable=True)
    system_audio_filepath: Mapped[str] = mapped_column(String, nullable=True)
    is_dual_track: Mapped[bool] = mapped_column(Boolean, nullable=True)
    # The tracks found in a single uploaded file with more than one (plan 047):
    # {"tracks": [{"stream", "channel", "title", "status", "level_db"}], "mic", "system",
    # "audio", "manual"}. mic/system are {"stream", "channel"} selectors; "audio" is the one
    # track a single-track Meeting reads. NULL for a mono file or two separate files.
    track_layout: Mapped[dict] = mapped_column(JSON, nullable=True)
    # Source References to the original recordings, which live outside the app (plan 046):
    # {"audio" | "mic" | "system": {"path", "name", "size", "hash"}}. NULL for a Meeting that
    # was uploaded before references existed.
    source_refs: Mapped[dict] = mapped_column(JSON, nullable=True)
    duration: Mapped[float] = mapped_column(Float, nullable=True)
    # Which Preset to transcribe with. NULL means "whatever the default is" — only an
    # A/B run against a specific Engine needs to pin one.
    preset_id: Mapped[str] = mapped_column(String, nullable=True)
    min_speakers: Mapped[int] = mapped_column(Integer, nullable=True)
    max_speakers: Mapped[int] = mapped_column(Integer, nullable=True)
    raw_diarization: Mapped[dict] = mapped_column(JSON, nullable=True)
    raw_transcription: Mapped[dict] = mapped_column(JSON, nullable=True)
    # Times (seconds) the user forced a Segment break at; derivation always breaks there.
    split_times: Mapped[list] = mapped_column(JSON, nullable=True)
    vocabulary: Mapped[str] = mapped_column(Text, nullable=True)  # Domain terms for Whisper prompt
    participants: Mapped[str] = mapped_column(Text, nullable=True)  # Meeting attendee names (cleaned)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    speakers = relationship("Speaker", back_populates="meeting", cascade="all, delete-orphan")
    segments = relationship("Segment", back_populates="meeting", cascade="all, delete-orphan", order_by="Segment.order")
    jobs = relationship("Job", back_populates="meeting", cascade="all, delete-orphan")
    review_notes = relationship(
        "ReviewNote", back_populates="meeting", cascade="all, delete-orphan",
        order_by="ReviewNote.start_time",
    )

    @property
    def reprocessable(self) -> bool:
        """Whether Full reprocess, Re-diarize and Duplicate can run from the audio the app holds.

        A single-track Meeting reruns from its ``audio.wav``. A dual-track one needs its
        mic and system tracks: the ones the app still holds, or the original recordings its
        Source References point at (the app drops its own copies once a Meeting is processed).
        """
        if not self.is_dual_track:
            return True
        if self.mic_audio_filepath and self.system_audio_filepath:
            return True
        # The originals live outside the app (plan 046). This only stats them; searching
        # and hashing happen when an operation needs them.
        sources = _described(self.source_refs)
        return bool(sources) and all(source["state"] == "present" for source in sources)

    def to_dict(self, include_segments: bool = False, speaker_count: int | None = None, segment_count: int | None = None) -> dict:
        d = {
            "id": self.id,
            "title": self.title,
            "status": self.status.value,
            "original_filename": self.original_filename,
            "mic_audio_filepath": self.mic_audio_filepath,
            "system_audio_filepath": self.system_audio_filepath,
            "is_dual_track": self.is_dual_track,
            "track_layout": self.track_layout,
            "reprocessable": self.reprocessable,
            "sources": _described(self.source_refs),
            "duration": self.duration,
            "preset_id": self.preset_id,
            "min_speakers": self.min_speakers,
            "max_speakers": self.max_speakers,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "vocabulary": self.vocabulary,
            "participants": self.participants,
            "speaker_count": speaker_count if speaker_count is not None else (len(self.speakers) if self.speakers else 0),
            "segment_count": segment_count if segment_count is not None else (len(self.segments) if self.segments else 0),
        }
        if include_segments:
            d["speakers"] = [s.to_dict() for s in self.speakers]
            d["segments"] = [s.to_dict() for s in self.segments]
            d["review_notes"] = [n.to_dict() for n in self.review_notes]
            from transcript.diarization import MeetingDiarization
            diarization = MeetingDiarization.from_stored(self.raw_diarization)
            d["overlaps"] = diarization.overlaps if diarization is not None else []
        return d
