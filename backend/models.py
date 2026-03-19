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
    source = Column(String(50), default="facebook_lead")  # facebook_lead, manual, referral, website
    facebook_user_id = Column(String(100), index=True)  # links to DynamoDB conversations
    leadgen_id = Column(String(100), unique=True, index=True)  # original Facebook lead ID
    inbox_url = Column(Text)
    notes = Column(Text)

    # Move details (from lead form)
    pickup_zip = Column(String(20))
    delivery_zip = Column(String(20))
    move_size = Column(String(100))
    move_date = Column(String(50))
    move_type = Column(String(50))  # in_state, out_of_state

    status = Column(String(30), nullable=False, default="new", index=True)
    # new → contacted → quoted → booked → scheduled → completed | lost | cancelled

    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
