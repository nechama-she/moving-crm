import uuid
import json
from datetime import datetime

from sqlalchemy import Column, String, Text, DateTime, Date, ForeignKey, Integer, Boolean, UniqueConstraint, LargeBinary, Numeric
from sqlalchemy.orm import declarative_base, relationship

from company_colors import resolve_company_color

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
    color = Column(String(7))
    phone = Column(String(30))
    facebook_page_id = Column(String(100), unique=True, index=True)
    aircall_number_id = Column(String(50))
    aircall_name = Column(String(255))
    samrtmoving_branch_id = Column(String(100))
    granot_api_id = Column(String(100))
    granot_mover_ref = Column(String(100))
    timezone = Column(String(50), default="America/New_York")
    created_at = Column(DateTime(timezone=True), default=_now)

    users = relationship("UserCompany", back_populates="company")
    leads = relationship("Lead", back_populates="company")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "color": resolve_company_color(self.name, self.color),
            "phone": self.phone or "",
            "facebook_page_id": self.facebook_page_id or "",
            "aircall_number_id": self.aircall_number_id or "",
            "aircall_name": self.aircall_name or "",
            "samrtmoving_branch_id": self.samrtmoving_branch_id or "",
            "granot_api_id": self.granot_api_id or "",
            "granot_mover_ref": self.granot_mover_ref or "",
            "timezone": self.timezone or "America/New_York",
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
    aircall_number_id = Column(String(50))
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
            "aircall_number_id": self.aircall_number_id or "",
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
    smartmoving_id = Column(String(100), index=True, unique=True)
    inbox_url = Column(Text)
    notes = Column(Text)

    # Move details
    pickup_zip = Column(Text)
    delivery_zip = Column(Text)
    move_size = Column(Text)
    move_date = Column(Text)
    booked_move_date = Column(Date)
    move_type = Column(Text)
    service_type = Column(String(50))
    referral_source = Column(String(100))
    estimated_total = Column(Text)
    payments = Column(Text)

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
        estimated_total_data = None
        if self.estimated_total:
            try:
                parsed = json.loads(self.estimated_total)
                if isinstance(parsed, dict):
                    estimated_total_data = {
                        "subtotal": float(parsed.get("subtotal") or 0),
                        "taxableAmount": float(parsed.get("taxableAmount") or 0),
                        "tax": float(parsed.get("tax") or 0),
                        "finalTotal": float(parsed.get("finalTotal") or 0),
                    }
            except Exception:
                estimated_total_data = None

        payments_data: list[dict[str, float | str]] = []
        if self.payments:
            try:
                parsed_payments = json.loads(self.payments)
                if isinstance(parsed_payments, list):
                    for row in parsed_payments:
                        if not isinstance(row, dict):
                            continue
                        payments_data.append({
                            "amount": float(row.get("amount") or 0),
                            "takenByUser": str(row.get("takenByUser") or "").strip(),
                        })
            except Exception:
                payments_data = []

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
            "booked_move_date": self.booked_move_date.isoformat() if self.booked_move_date else "",
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
            "estimatedTotal": estimated_total_data,
            "payments": payments_data,
        }


class LeadAttachment(Base):
    __tablename__ = "lead_attachments"

    id = Column(String(36), primary_key=True, default=_uuid)
    lead_id = Column(String(36), ForeignKey("leads.id"), nullable=False, index=True)
    job_id = Column(String(36), ForeignKey("lead_jobs.id"), nullable=True, index=True)
    file_name = Column(String(255), nullable=False)
    content_type = Column(String(120), nullable=False, default="application/octet-stream")
    file_size = Column(Integer, nullable=False, default=0)
    file_blob = Column(LargeBinary, nullable=False)
    uploaded_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=_now, index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "lead_id": self.lead_id,
            "job_id": self.job_id or "",
            "file_name": self.file_name or "",
            "content_type": self.content_type or "application/octet-stream",
            "file_size": self.file_size or 0,
            "uploaded_by": self.uploaded_by or "",
            "created_at": self.created_at.isoformat() if self.created_at else "",
        }


class LeadJob(Base):
    __tablename__ = "lead_jobs"

    id = Column(String(36), primary_key=True, default=_uuid)
    lead_id = Column(String(36), ForeignKey("leads.id"), nullable=False, index=True)
    company_id = Column(String(36), ForeignKey("companies.id"), nullable=False, index=True)
    job_order = Column(Integer, nullable=False, default=1)
    pickup_zip = Column(Text)
    delivery_zip = Column(Text)
    move_date = Column(Text)
    booked_move_date = Column(Date)
    price = Column(Numeric(12, 2))
    created_at = Column(DateTime(timezone=True), default=_now, index=True)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now, index=True)

    lead = relationship("Lead", foreign_keys=[lead_id])
    company = relationship("Company", foreign_keys=[company_id])
    charges = relationship("LeadJobCharge", back_populates="job", cascade="all, delete-orphan", order_by="LeadJobCharge.sort_order.asc(), LeadJobCharge.created_at.asc()")

    __table_args__ = (
        UniqueConstraint("lead_id", "job_order", name="uq_lead_jobs_lead_order"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "lead_id": self.lead_id,
            "company_id": self.company_id,
            "company_name": self.company.name if self.company else "",
            "job_order": self.job_order,
            "pickup_zip": self.pickup_zip or "",
            "delivery_zip": self.delivery_zip or "",
            "move_date": self.move_date or "",
            "booked_move_date": self.booked_move_date.isoformat() if self.booked_move_date else "",
            "price": float(self.price) if self.price is not None else None,
            "charges": [row.to_dict() for row in self.charges],
            "created_at": self.created_at.isoformat() if self.created_at else "",
            "updated_at": self.updated_at.isoformat() if self.updated_at else "",
        }


class LeadJobCharge(Base):
    __tablename__ = "lead_job_charges"

    id = Column(String(36), primary_key=True, default=_uuid)
    job_id = Column(String(36), ForeignKey("lead_jobs.id"), nullable=False, index=True)
    name = Column(Text, nullable=False)
    description = Column(Text)
    sort_order = Column(Integer, nullable=False, default=0)
    subtotal = Column(Numeric(12, 2), nullable=False, default=0)
    discount_amount = Column(Numeric(12, 2), nullable=False, default=0)
    total_cost = Column(Numeric(12, 2), nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), default=_now, index=True)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now, index=True)

    job = relationship("LeadJob", back_populates="charges")

    def to_dict(self):
        return {
            "id": self.id,
            "job_id": self.job_id,
            "name": self.name or "",
            "description": self.description or "",
            "sort_order": int(self.sort_order or 0),
            "subtotal": float(self.subtotal) if self.subtotal is not None else 0,
            "discount_amount": float(self.discount_amount) if self.discount_amount is not None else 0,
            "total_cost": float(self.total_cost) if self.total_cost is not None else 0,
            "created_at": self.created_at.isoformat() if self.created_at else "",
            "updated_at": self.updated_at.isoformat() if self.updated_at else "",
        }


class DispatchCalendarDay(Base):
    __tablename__ = "dispatch_calendar_days"

    id = Column(String(36), primary_key=True, default=_uuid)
    company_id = Column(String(36), ForeignKey("companies.id"), nullable=False, index=True)
    day_date = Column(Date, nullable=False, index=True)
    is_full = Column(Boolean, nullable=False, default=False)
    note = Column(Text)
    updated_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=_now, index=True)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now, index=True)

    __table_args__ = (
        UniqueConstraint("company_id", "day_date", name="uq_dispatch_calendar_days_company_day"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "company_id": self.company_id,
            "day_date": self.day_date.isoformat() if self.day_date else "",
            "is_full": bool(self.is_full),
            "note": self.note or "",
            "updated_by": self.updated_by or "",
            "created_at": self.created_at.isoformat() if self.created_at else "",
            "updated_at": self.updated_at.isoformat() if self.updated_at else "",
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


# ---------------------------------------------------------------------------
# Tasks (linked to a lead, visible to anyone who can see the lead)
# ---------------------------------------------------------------------------
class Task(Base):
    __tablename__ = "tasks"

    id = Column(String(36), primary_key=True, default=_uuid)
    lead_id = Column(String(36), ForeignKey("leads.id"), nullable=False, index=True)
    title = Column(String(500), nullable=False)
    due_date = Column(String(10))          # YYYY-MM-DD, nullable
    status = Column(String(20), nullable=False, default="open", index=True)
    # statuses: open, in_progress, done
    task_type = Column(String(20), nullable=False, default="other", index=True)
    # types: call, email, text, messenger, instagram, other
    notes = Column(Text, nullable=False, default="")
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=_now)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now)

    def to_dict(self):
        return {
            "id": self.id,
            "lead_id": self.lead_id,
            "title": self.title,
            "due_date": self.due_date or "",
            "status": self.status,
            "task_type": self.task_type or "other",
            "notes": self.notes or "",
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else "",
            "updated_at": self.updated_at.isoformat() if self.updated_at else "",
        }


# ---------------------------------------------------------------------------
# App Settings (simple key/value runtime settings)
# ---------------------------------------------------------------------------
class AppSetting(Base):
    __tablename__ = "app_settings"

    key = Column(String(120), primary_key=True)
    value = Column(Text, nullable=False, default="")
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now)

    def to_dict(self):
        return {
            "key": self.key,
            "value": self.value or "",
            "updated_at": self.updated_at.isoformat() if self.updated_at else "",
        }


# ---------------------------------------------------------------------------
# Per-Company Message Templates (SMS bodies the system sends)
# ---------------------------------------------------------------------------
class CompanyMessageTemplate(Base):
    __tablename__ = "company_message_templates"

    company_id = Column(String(36), ForeignKey("companies.id"), primary_key=True)
    welcome_sms = Column(Text, nullable=False, default="")
    rep_assignment_sms = Column(Text, nullable=False, default="")
    day2_followup_sms = Column(Text, nullable=False, default="")
    day3_followup_sms = Column(Text, nullable=False, default="")
    updated_by = Column(String(36), ForeignKey("users.id"))
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now)

    def to_dict(self):
        return {
            "company_id": self.company_id,
            "welcome_sms": self.welcome_sms or "",
            "rep_assignment_sms": self.rep_assignment_sms or "",
            "day2_followup_sms": self.day2_followup_sms or "",
            "day3_followup_sms": self.day3_followup_sms or "",
            "updated_by": self.updated_by or "",
            "updated_at": self.updated_at.isoformat() if self.updated_at else "",
        }
