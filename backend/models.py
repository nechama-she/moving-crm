import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, Text, DateTime
from sqlalchemy.orm import declarative_base

Base = declarative_base()


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Contacts — people (imported from leads + manual entry)
# ---------------------------------------------------------------------------
class Contact(Base):
    __tablename__ = "contacts"

    id = Column(String(36), primary_key=True, default=_uuid)
    full_name = Column(String(255), nullable=False, index=True)
    email = Column(String(255), index=True)
    phone = Column(String(30), index=True)
    source = Column(String(50), default="facebook_lead")
    facebook_user_id = Column(String(100), index=True)
    leadgen_id = Column(String(100), unique=True, index=True)
    inbox_url = Column(Text)
    notes = Column(Text)

    # Move details (from lead form)
    pickup_zip = Column(Text)
    delivery_zip = Column(Text)
    move_size = Column(Text)
    move_date = Column(Text)
    move_type = Column(Text)

    status = Column(String(30), nullable=False, default="new", index=True)
    # new → contacted → quoted → booked → scheduled → completed | lost | cancelled

    created_time = Column(Text)  # original Facebook lead created_time
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    def to_dict(self):
        """Serialize with field names the frontend expects (DynamoDB-compatible)."""
        return {
            "leadgen_id": self.leadgen_id or "",
            "full_name": self.full_name or "",
            "email": self.email or "",
            "phone_number": self.phone or "",
            "pickup_zip": self.pickup_zip or "",
            "delivery_zip": self.delivery_zip or "",
            "move_size": self.move_size or "",
            "when_is_the_move?": self.move_date or "",
            "are_you_moving_within_the_state_or_out_of_state?": self.move_type or "",
            "created_time": self.created_time or "",
            "inbox_url": self.inbox_url or "",
            "user_id": self.facebook_user_id or "",
            "source": self.source or "",
            "status": self.status or "new",
            "notes": self.notes or "",
        }
