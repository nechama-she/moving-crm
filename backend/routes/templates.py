"""Per-company automated SMS and email message templates."""

import logging
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth import get_current_user, require_admin
from database import get_db
from models import AppSetting, Company, CompanyMessageTemplate, User, UserCompany

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
#   {customer_link}   the lead's customer page link, made if it has none yet
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
SYSTEM_DEFAULT_PREFIX = "sms_system_default."
# The automated emails: the same system default and company templates as the SMS ones, with no text of their own.
EMAIL_TEMPLATE_KEYS = ["welcome_email_subject", "welcome_email_body"]
EMAIL_SYSTEM_DEFAULT_PREFIX = "email_system_default."
SMS = (TEMPLATE_KEYS, SYSTEM_DEFAULT_PREFIX, DEFAULTS)
EMAIL = (EMAIL_TEMPLATE_KEYS, EMAIL_SYSTEM_DEFAULT_PREFIX, {})


def _system_defaults(db: Session, kind=SMS) -> dict[str, str]:
    keys, prefix, defaults = kind
    rows = (
        db.query(AppSetting)
        .filter(AppSetting.key.in_([f"{prefix}{key}" for key in keys]))
        .all()
    )
    saved = {row.key.removeprefix(prefix): row.value for row in rows}
    return {
        key: (saved.get(key) or "").strip() or defaults.get(key, "")
        for key in keys
    }


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
    return _system_defaults(db)[key]


_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


def render_template(template: str, **values: str) -> str:
    """Safely substitute {placeholder} tokens with the provided values.

    Unlike ``str.format``, this replaces only simple ``{name}`` tokens (no attribute
    or index access), so an admin-authored template can never be abused as a format
    string to reach object internals. Unknown placeholders are left untouched.
    """
    return _PLACEHOLDER_RE.sub(
        lambda m: str(values.get(m.group(1), m.group(0))), template
    )


def complete_message(template: str, **values: str) -> tuple[str | None, list[str]]:
    """The message an automatic text sends: the template with every {placeholder} filled, or None (and the names
    that have no value) when any is missing or empty. A text is never sent partly filled."""
    missing = sorted({name for name in _PLACEHOLDER_RE.findall(template) if not str(values.get(name) or "").strip()})
    return (None, missing) if missing else (render_template(template, **values), [])


def _resolved_templates(
    row: CompanyMessageTemplate | None,
    company_id: str,
    defaults: dict[str, str],
    kind=SMS,
) -> dict:
    keys = kind[0]
    return {"company_id": company_id, "defaults": defaults,
            **{key: (getattr(row, key, "") or "") if row else "" for key in keys},
            "updated_by": (row.updated_by or "") if row else "",
            "updated_at": row.updated_at.isoformat() if row and row.updated_at else ""}


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


class EmailTemplatesUpdate(BaseModel):
    welcome_email_subject: str | None = Field(default=None)
    welcome_email_body: str | None = Field(default=None)


def _defaults_payload(db: Session, kind, updated_by=""):
    defaults = _system_defaults(db, kind)
    return {"company_id": "", **defaults, "defaults": defaults, "updated_by": updated_by, "updated_at": ""}


def _save_defaults(body, user: User, db: Session, kind):
    keys, prefix, defaults = kind
    for key in keys:
        value = getattr(body, key)
        if value is None:
            continue
        setting_key = f"{prefix}{key}"
        row = db.query(AppSetting).filter(AppSetting.key == setting_key).first()
        if not row:
            row = AppSetting(key=setting_key)
            db.add(row)
        row.value = value.strip() or defaults.get(key, "")
    db.commit()
    return _defaults_payload(db, kind, user.id)


def _company_templates(company_id: str, user: User, db: Session, kind):
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
    return _resolved_templates(row, company_id, _system_defaults(db, kind), kind)


def _save_company_templates(company_id: str, body, user: User, db: Session, kind):
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

    for key in kind[0]:
        val = getattr(body, key)
        if val is not None:
            setattr(row, key, val)

    row.updated_by = user.id
    db.commit()
    db.refresh(row)
    return _resolved_templates(row, company_id, _system_defaults(db, kind), kind)


@router.get("/templates/defaults", summary="Get system-default SMS templates")
def get_system_default_templates(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _defaults_payload(db, SMS)


@router.put("/templates/defaults", summary="Update system-default SMS templates (admin)")
def update_system_default_templates(
    body: TemplatesUpdate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return _save_defaults(body, user, db, SMS)


@router.get("/email-templates/defaults", summary="Get system-default email templates")
def get_system_default_email_templates(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _defaults_payload(db, EMAIL)


@router.put("/email-templates/defaults", summary="Update system-default email templates (admin)")
def update_system_default_email_templates(
    body: EmailTemplatesUpdate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return _save_defaults(body, user, db, EMAIL)


@router.get("/{company_id}/templates", summary="Get per-company SMS templates")
def get_templates(
    company_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _company_templates(company_id, user, db, SMS)


@router.put("/{company_id}/templates", summary="Update per-company SMS templates (admin)")
def update_templates(
    company_id: str,
    body: TemplatesUpdate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return _save_company_templates(company_id, body, user, db, SMS)


@router.get("/{company_id}/email-templates", summary="Get per-company email templates")
def get_email_templates(
    company_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _company_templates(company_id, user, db, EMAIL)


@router.put("/{company_id}/email-templates", summary="Update per-company email templates (admin)")
def update_email_templates(
    company_id: str,
    body: EmailTemplatesUpdate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return _save_company_templates(company_id, body, user, db, EMAIL)
