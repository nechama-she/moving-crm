import uuid
from datetime import datetime, date as _date

from sqlalchemy import Column, String, Text, DateTime, Date, ForeignKey, Boolean
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now()


# ---------------------------------------------------------------------------
# Existing tables — read-only mapping; create_all skips tables that exist
# ---------------------------------------------------------------------------

class Company(Base):
    __tablename__ = "companies"

    id = Column(String(36), primary_key=True)
    name = Column(String(255), nullable=False)
    timezone = Column(String(50), default="America/New_York")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "timezone": self.timezone or "America/New_York",
        }


class UserCompany(Base):
    __tablename__ = "user_companies"

    user_id = Column(String(36), ForeignKey("users.id"), primary_key=True)
    company_id = Column(String(36), ForeignKey("companies.id"), primary_key=True)


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True)
    email = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="sales_rep")
    must_change_password = Column(Boolean, nullable=False, default=False)


# ---------------------------------------------------------------------------
# New table — dispatch jobs only
# ---------------------------------------------------------------------------

class Job(Base):
    __tablename__ = "dispatch_jobs"

    id = Column(String(36), primary_key=True, default=_uuid)
    company_id = Column(String(36), ForeignKey("companies.id"), nullable=False, index=True)
    client_name = Column(String(255), nullable=False)
    move_date = Column(Date, nullable=False, index=True)
    start_time = Column(String(10))   # HH:MM — null means all-day event
    end_time = Column(String(10))     # HH:MM
    origin_address = Column(Text)
    destination_address = Column(Text)
    status = Column(String(20), nullable=False, default="scheduled")
    # status values: scheduled, in_progress, completed, cancelled
    notes = Column(Text)
    created_by = Column(String(36), ForeignKey("users.id"))
    created_at = Column(DateTime(timezone=True), default=_now)

    company = relationship("Company")

    def to_dict(self):
        return {
            "id": self.id,
            "company_id": self.company_id,
            "company_name": self.company.name if self.company else "",
            "client_name": self.client_name,
            "move_date": self.move_date.isoformat() if self.move_date else "",
            "start_time": self.start_time or "",
            "end_time": self.end_time or "",
            "origin_address": self.origin_address or "",
            "destination_address": self.destination_address or "",
            "status": self.status,
            "notes": self.notes or "",
            "created_at": self.created_at.isoformat() if self.created_at else "",
        }
