import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Integer
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Companies
# ---------------------------------------------------------------------------
class Company(Base):
    __tablename__ = "companies"

    id = Column(String(36), primary_key=True, default=_uuid)
    name = Column(String(255), nullable=False, unique=True)
    phone = Column(String(30))
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    users = relationship("UserCompany", back_populates="company")
    leads = relationship("Lead", back_populates="company")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "phone": self.phone or "",
            "created_at": self.created_at.isoformat() if self.created_at else "",
        }


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=_uuid)
    email = Column(String(255), nullable=False, unique=True, index=True)
    name = Column(String(255), nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="sales_rep")
    # roles: admin, sales_rep, dispatch
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    companies = relationship("UserCompany", back_populates="user")

    def to_dict(self):
        return {
            "id": self.id,
            "email": self.email,
            "name": self.name,
            "role": self.role,
            "companies": [uc.company.to_dict() for uc in self.companies],
            "created_at": self.created_at.isoformat() if self.created_at else "",
        }


# ---------------------------------------------------------------------------
# User ↔ Company (many-to-many)
# ---------------------------------------------------------------------------
class UserCompany(Base):
    __tablename__ = "user_companies"

    user_id = Column(String(36), ForeignKey("users.id"), primary_key=True)
    company_id = Column(String(36), ForeignKey("companies.id"), primary_key=True)

    user = relationship("User", back_populates="companies")
    company = relationship("Company", back_populates="users")


# ---------------------------------------------------------------------------
# Leads
# ---------------------------------------------------------------------------
class Lead(Base):
    __tablename__ = "leads"

    id = Column(String(36), primary_key=True, default=_uuid)
    company_id = Column(String(36), ForeignKey("companies.id"), nullable=False, index=True)
    assigned_to = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)

    full_name = Column(String(255), nullable=False, index=True)
    email = Column(String(255), index=True)
    phone = Column(String(30), index=True)
    source = Column(String(50), default="facebook")
    # sources: facebook, website, referral, manual
    facebook_user_id = Column(String(100), index=True)
    leadgen_id = Column(String(100), unique=True, index=True)
    inbox_url = Column(Text)
    notes = Column(Text)

    # Move details
    pickup_zip = Column(Text)
    delivery_zip = Column(Text)
    move_size = Column(Text)
    move_date = Column(Text)
    move_type = Column(Text)
    service_type = Column(String(50))
    referral_source = Column(String(100))

    status = Column(String(30), nullable=False, default="new", index=True)
    # new → contacted → quoted → booked → scheduled → completed | lost | cancelled
    priority = Column(Integer, nullable=False, default=0, index=True)
    # 0=normal, 1=high, 2=urgent

    created_time = Column(Text)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    company = relationship("Company", back_populates="leads")
    assignee = relationship("User", foreign_keys=[assigned_to])

    def to_dict(self):
        return {
            "id": self.id,
            "company_id": self.company_id,
            "assigned_to": self.assigned_to or "",
            "assigned_to_name": self.assignee.name if self.assignee else "",
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
            "referral_source": self.referral_source or "",
            "service_type": self.service_type or "",
            "status": self.status or "new",
            "priority": self.priority or 0,
            "notes": self.notes or "",
        }
