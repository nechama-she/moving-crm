"""Per-company SMS message templates."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth import get_current_user, require_admin
from database import get_db
from models import Company, CompanyMessageTemplate, User, UserCompany

logger = logging.getLogger("moving-crm")

router = APIRouter(prefix="/api/companies", tags=["Message Templates"])


# ---------------------------------------------------------------------------
# Default template bodies (used when a company has no row / empty field).
# Placeholders:
#   {first_name}      lead first name
#   {company_name}    company name
#   {company_phone}   company phone
#   {smartmoving_id}  SmartMoving opportunity id
#   {rep_name}        sales rep name (rep_assignment_sms only)
# ---------------------------------------------------------------------------
DEFAULT_WELCOME_SMS = (
    "Hi {first_name},\n"
    "Thank you for reaching out to {company_name} regarding your upcoming move.\n\n"
    "To provide an accurate quote, we can schedule a virtual in-home estimate, "
    "complete the estimate over the phone with one of our estimators, or schedule "
    "a free in-home estimate.\n\n"
    "You can also submit your inventory here for a quick estimate:\n"
    "https://portal.smartmoving.com/home/inventory/{smartmoving_id}/welcome\n\n"
    "Please let us know the best time to discuss your move.\n"
    "You can also call us anytime at {company_phone}.\n\n"
    "{company_name}"
)

DEFAULT_REP_ASSIGNMENT_SMS = (
    "Hi {first_name},\n"
    "This is {rep_name} from {company_name}. I've been assigned to help you with your upcoming move.\n\n"
    "I'll be your point of contact and can assist with the estimate. We can schedule a "
    "virtual in-home estimate, complete the estimate over the phone with one of our estimators, "
    "or schedule a free in-home estimate.\n\n"
    "You can reply here or feel free to give me a call anytime."
)

DEFAULT_DAY2_FOLLOWUP_SMS = (
    "Hi {first_name}, thanks for your interest in {company_name}! "
    "We'd love to help with your move. Reply to this message or call us anytime."
)

DEFAULT_DAY3_FOLLOWUP_SMS = (
    "Hi {first_name}, I just wanted to check in and see if you're still planning your move. "
    "If you received another estimate, feel free to send it over. We have a match or beat "
    "policy and can beat a written quote from a reputable company by up to 10%."
)

DEFAULTS = {
    "welcome_sms": DEFAULT_WELCOME_SMS,
    "rep_assignment_sms": DEFAULT_REP_ASSIGNMENT_SMS,
    "day2_followup_sms": DEFAULT_DAY2_FOLLOWUP_SMS,
    "day3_followup_sms": DEFAULT_DAY3_FOLLOWUP_SMS,
}

TEMPLATE_KEYS = list(DEFAULTS.keys())


def get_company_template(db: Session, company_id: str, key: str) -> str:
    """Return the template body for a company/key, falling back to the hardcoded default."""
    if key not in DEFAULTS:
        raise ValueError(f"unknown template key: {key}")
    row = (
        db.query(CompanyMessageTemplate)
        .filter(CompanyMessageTemplate.company_id == company_id)
        .first()
    )
    if row:
        value = (getattr(row, key, "") or "").strip()
        if value:
            return value
    return DEFAULTS[key]


def _resolved_templates(row: CompanyMessageTemplate | None, company_id: str) -> dict:
    out = {"company_id": company_id, "defaults": DEFAULTS}
    if row:
        body = row.to_dict()
    else:
        body = {k: "" for k in TEMPLATE_KEYS}
        body["company_id"] = company_id
        body["updated_by"] = ""
        body["updated_at"] = ""
    out.update(body)
    return out


def _can_access_company(user: User, company_id: str, db: Session) -> bool:
    if user.role == "admin":
        return True
    return (
        db.query(UserCompany)
        .filter(UserCompany.user_id == user.id, UserCompany.company_id == company_id)
        .first()
        is not None
    )


class TemplatesUpdate(BaseModel):
    welcome_sms: str | None = Field(default=None)
    rep_assignment_sms: str | None = Field(default=None)
    day2_followup_sms: str | None = Field(default=None)
    day3_followup_sms: str | None = Field(default=None)


@router.get("/{company_id}/templates", summary="Get per-company SMS templates")
def get_templates(
    company_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    if not _can_access_company(user, company_id, db):
        raise HTTPException(status_code=403, detail="No access to this company")
    row = (
        db.query(CompanyMessageTemplate)
        .filter(CompanyMessageTemplate.company_id == company_id)
        .first()
    )
    return _resolved_templates(row, company_id)


@router.put("/{company_id}/templates", summary="Update per-company SMS templates (admin)")
def update_templates(
    company_id: str,
    body: TemplatesUpdate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    row = (
        db.query(CompanyMessageTemplate)
        .filter(CompanyMessageTemplate.company_id == company_id)
        .first()
    )
    if not row:
        row = CompanyMessageTemplate(company_id=company_id)
        db.add(row)

    for key in TEMPLATE_KEYS:
        val = getattr(body, key)
        if val is not None:
            setattr(row, key, val)

    row.updated_by = user.id
    db.commit()
    db.refresh(row)
    return _resolved_templates(row, company_id)
