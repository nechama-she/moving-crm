import uuid
from datetime import datetime

from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Integer, Boolean, UniqueConstraint
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now()


# ---------------------------------------------------------------------------
# Companies
# ---------------------------------------------------------------------------
class Company(Base):
    __tablename__ = "companies"

    id = Column(String(36), primary_key=True, default=_uuid)
    name = Column(String(255), nullable=False, unique=True)
    phone = Column(String(30))
    facebook_page_id = Column(String(100), unique=True, index=True)
    aircall_number_id = Column(String(50))
    samrtmoving_branch_id = Column(String(100))
    timezone = Column(String(50), default="America/New_York")
    created_at = Column(DateTime(timezone=True), default=_now)

    users = relationship("UserCompany", back_populates="company")
    leads = relationship("Lead", back_populates="company")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "phone": self.phone or "",
            "facebook_page_id": self.facebook_page_id or "",
            "aircall_number_id": self.aircall_number_id or "",
            "samrtmoving_branch_id": self.samrtmoving_branch_id or "",
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
    phone = Column(String(30), nullable=False, default="")
    smartmoving_rep_id = Column(String(100), index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="sales_rep")
    must_change_password = Column(Boolean, nullable=False, default=False)
    # roles: admin, sales_rep, dispatch
    created_at = Column(DateTime(timezone=True), default=_now)

    companies = relationship("UserCompany", back_populates="user")

    def to_dict(self):
        return {
            "id": self.id,
            "email": self.email,
            "name": self.name,
            "phone": self.phone or "",
            "smartmoving_rep_id": self.smartmoving_rep_id or "",
            "role": self.role,
            "must_change_password": bool(self.must_change_password),
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
# Admin Unavailability Windows
# ---------------------------------------------------------------------------
class AdminUnavailability(Base):
    __tablename__ = "admin_unavailability"

    id = Column(String(36), primary_key=True, default=_uuid)
    admin_user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    start_at = Column(DateTime(timezone=True), nullable=False, index=True)
    end_at = Column(DateTime(timezone=True), nullable=False, index=True)
    reason = Column(Text)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=_now, index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "admin_user_id": self.admin_user_id,
            "start_at": self.start_at.isoformat() if self.start_at else "",
            "end_at": self.end_at.isoformat() if self.end_at else "",
            "reason": self.reason or "",
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else "",
        }


class AdminUnavailabilityRep(Base):
    __tablename__ = "admin_unavailability_reps"

    id = Column(String(36), primary_key=True, default=_uuid)
    window_id = Column(String(36), ForeignKey("admin_unavailability.id"), nullable=False, index=True)
    rep_user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=_now)


class RepAvailabilityWindow(Base):
    __tablename__ = "rep_availability_windows"

    id = Column(String(36), primary_key=True, default=_uuid)
    rep_user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    start_at = Column(DateTime(timezone=True), nullable=False, index=True)
    end_at = Column(DateTime(timezone=True), nullable=False, index=True)
    reason = Column(Text)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=_now, index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "rep_user_id": self.rep_user_id,
            "start_at": self.start_at.isoformat() if self.start_at else "",
            "end_at": self.end_at.isoformat() if self.end_at else "",
            "reason": self.reason or "",
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else "",
        }


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
    leadgen_id = Column(String(100), index=True)
    smartmoving_id = Column(String(100), index=True)
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
    created_at = Column(DateTime(timezone=True), default=_now)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now)

    company = relationship("Company", back_populates="leads")
    assignee = relationship("User", foreign_keys=[assigned_to])

    def to_dict(self):
        return {
            "id": self.id,
            "company_id": self.company_id,
            "assigned_to": self.assigned_to or "",
            "assigned_to_name": self.assignee.name if self.assignee else "",
            "company_name": self.company.name if self.company else "",
            "company_phone": self.company.phone if self.company else "",
            "aircall_number_id": self.company.aircall_number_id if self.company else "",
            "leadgen_id": self.leadgen_id or "",
            "smartmoving_id": self.smartmoving_id or "",
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


# ---------------------------------------------------------------------------
# Followups
# ---------------------------------------------------------------------------
class Followup(Base):
    __tablename__ = "followups"

    note_id = Column(String(36), primary_key=True)
    smartmoving_id = Column(String(36), nullable=False, index=True)
    type = Column(Integer)
    title = Column(Text)
    assigned_to_id = Column(String(36))
    due_date_time = Column(DateTime(timezone=True))
    completed_at_utc = Column(DateTime(timezone=True))
    notes = Column(Text)
    completed = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=_now)

    def to_dict(self):
        return {
            "note_id": self.note_id,
            "smartmoving_id": self.smartmoving_id,
            "type": self.type,
            "title": self.title or "",
            "assigned_to_id": self.assigned_to_id or "",
            "due_date_time": self.due_date_time.isoformat() if self.due_date_time else "",
            "completed_at_utc": self.completed_at_utc.isoformat() if self.completed_at_utc else "",
            "notes": self.notes or "",
            "completed": self.completed or False,
            "created_at": self.created_at.isoformat() if self.created_at else "",
        }


# ---------------------------------------------------------------------------
# Sales Reps (maps SmartMoving assignee name → Aircall number)
# ---------------------------------------------------------------------------
class SalesRep(Base):
    __tablename__ = "sales_reps"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True)
    aircall_number_id = Column(String(50))
    created_at = Column(DateTime(timezone=True), default=_now)


# ---------------------------------------------------------------------------
# Sent Messages (deduplication log)
# ---------------------------------------------------------------------------
class SentMessage(Base):
    __tablename__ = "sent_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    smartmoving_id = Column(String(36), nullable=False)
    message_type = Column(String(100), nullable=False)  # e.g. day_2, day_3, followup_{note_id}_{due}
    channel = Column(String(20), nullable=False)        # e.g. aircall, messenger, smartmoving_note
    sent_at = Column(DateTime(timezone=True), default=_now)

    __table_args__ = (
        UniqueConstraint("smartmoving_id", "message_type", "channel", name="uq_sent_messages_dedup"),
    )


# ---------------------------------------------------------------------------
# Outreach Events (frontend audit trail)
# ---------------------------------------------------------------------------
class OutreachEvent(Base):
    __tablename__ = "outreach_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lead_id = Column(String(36), index=True)
    company_id = Column(String(36), index=True)
    smartmoving_id = Column(String(100), index=True)
    note_id = Column(String(36), index=True)
    outreach_type = Column(String(30), nullable=False, index=True)  # due, day_2, day_3, new_lead
    job_id = Column(String(100), index=True)
    qualified = Column(Boolean, nullable=False, default=False)
    qualification_reason = Column(String(100), nullable=False, default="")
    message = Column(Text)
    messenger = Column(Boolean, nullable=False, default=False)
    aircall = Column(Boolean, nullable=False, default=False)
    dry_run = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), default=_now, index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "lead_id": self.lead_id or "",
            "company_id": self.company_id or "",
            "smartmoving_id": self.smartmoving_id or "",
            "note_id": self.note_id or "",
            "outreach_type": self.outreach_type,
            "job_id": self.job_id or "",
            "qualified": bool(self.qualified),
            "qualification_reason": self.qualification_reason or "",
            "message": self.message or "",
            "messenger": bool(self.messenger),
            "aircall": bool(self.aircall),
            "dry_run": bool(self.dry_run),
            "created_at": self.created_at.isoformat() if self.created_at else "",
        }


# ---------------------------------------------------------------------------
# Auto Assignment Events (assignment audit trail)
# ---------------------------------------------------------------------------
class AutoAssignEvent(Base):
    __tablename__ = "auto_assign_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lead_id = Column(String(36), index=True)
    company_id = Column(String(36), index=True)
    assigned_to = Column(String(36), index=True)
    assignment_mode = Column(String(30), nullable=False, index=True)  # auto, queued, manual
    assignment_reason = Column(String(120), nullable=False, default="", index=True)
    note = Column(Text)
    created_at = Column(DateTime(timezone=True), default=_now, index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "lead_id": self.lead_id or "",
            "company_id": self.company_id or "",
            "assigned_to": self.assigned_to or "",
            "assignment_mode": self.assignment_mode or "",
            "assignment_reason": self.assignment_reason or "",
            "note": self.note or "",
            "created_at": self.created_at.isoformat() if self.created_at else "",
        }
