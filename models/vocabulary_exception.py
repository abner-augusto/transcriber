import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class RejectedForm(Base):
    """A heard form the user said is not a Misheard Form of a term.

    Vocabulary Correction never turns ``heard`` into ``term`` again, in any Meeting.
    """

    __tablename__ = "rejected_forms"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    heard: Mapped[str] = mapped_column(String, nullable=False)
    term: Mapped[str] = mapped_column(String, nullable=False)
    source_meeting_id: Mapped[str] = mapped_column(
        String, ForeignKey("meetings.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "heard": self.heard,
            "term": self.term,
            "source_meeting_id": self.source_meeting_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
