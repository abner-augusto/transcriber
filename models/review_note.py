import uuid
from datetime import datetime

from sqlalchemy import String, Float, Text, DateTime, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class ReviewNote(Base):
    """A question, comment or suggestion anchored at a time range of a Meeting.

    Anchored by time, never by Segment id: Reprocessing recreates Segments, and a
    note keeps its range. The Segment it applies to is picked when it is accepted.
    """

    __tablename__ = "review_notes"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    meeting_id: Mapped[str] = mapped_column(
        String, ForeignKey("meetings.id", ondelete="CASCADE"), index=True
    )
    start_time: Mapped[float] = mapped_column(Float, nullable=False)
    end_time: Mapped[float] = mapped_column(Float, nullable=False)
    author: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="open")
    answer: Mapped[str] = mapped_column(Text, nullable=True)
    reply: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    resolved_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    meeting = relationship("Meeting", back_populates="review_notes")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "meeting_id": self.meeting_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "author": self.author,
            "kind": self.kind,
            "body": self.body,
            "payload": self.payload,
            "status": self.status,
            "answer": self.answer,
            "reply": self.reply,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
        }
