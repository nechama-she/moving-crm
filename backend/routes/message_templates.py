"""Message templates a user picks when writing to a lead (SMS, Messenger). Each template has a default text for every
company, and a company can have its own text for it. Not the automatic messages (routes/templates.py)."""
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from auth import get_current_user, require_admin
from database import get_db
from models import Company, Lead, LeadJob, MessageTemplate, MessageTemplateOverride, User

router = APIRouter(prefix="/api", tags=["Message Templates"])

# What a template can show, written @Token in its text: filled from the lead, its company and the rep the lead is
# assigned to. (token, label, group)
LEAD, COMPANY, REP = "Lead info", "Company info", "Rep info"
PLACEHOLDERS = [
    ("FirstName", "First name", LEAD), ("LastName", "Last name", LEAD), ("FullName", "Full name", LEAD),
    ("LeadPhone", "Phone", LEAD), ("LeadEmail", "Email", LEAD), ("MoveDate", "Move date", LEAD),
    ("BookedDate", "Booked date", LEAD), ("MoveSize", "Move size", LEAD), ("MoveType", "Move type", LEAD),
    ("Volume", "Volume (cu ft)", LEAD), ("Weight", "Weight (lb)", LEAD), ("Pickup", "Pickup address", LEAD),
    ("Stops", "Stops", LEAD), ("Delivery", "Delivery address", LEAD), ("JobNumber", "Job number", LEAD),
    ("EstimateTotal", "Estimate total", LEAD), ("ReferralSource", "Referral source", LEAD),
    ("CompanyName", "Name", COMPANY), ("CompanyPhone", "Phone", COMPANY), ("CompanyEmail", "Email", COMPANY),
    ("CompanyWebsite", "Website", COMPANY),
    ("CompanyAddress", "Office address", COMPANY), ("DOTNumber", "DOT number", COMPANY), ("MCNumber", "MC number", COMPANY),
    ("RepFirstName", "First name", REP), ("RepName", "Full name", REP), ("RepPhone", "Phone", REP), ("RepEmail", "Email", REP),
]
# An @ starting a word, as the editor inserts it; one inside a word (an email address) is not a field.
_TOKEN = re.compile(r"(?<![A-Za-z0-9])@([A-Za-z]+)")


def fill(text, values):
    """Each @Token replaced by its value; any other @word (an email address, a handle) is left as written."""
    return _TOKEN.sub(lambda match: values[match.group(1)] if match.group(1) in values else match.group(0), text)


def _phone(value):
    """A US number as people write it, (202) 937-2625; anything else as saved."""
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}" if len(digits) == 10 else (value or "").strip()


def _date(value):
    """12/23/2026 from a saved date (a date, or text such as 2026-12-23); text that is not a date as saved."""
    from datetime import date
    if isinstance(value, date):
        return value.strftime("%m/%d/%Y")
    try:
        return date.fromisoformat((value or "").strip()[:10]).strftime("%m/%d/%Y")
    except ValueError:
        return (value or "").strip()


def _amount(value, unit):
    """60 cu ft, 420 lb: whole numbers without decimals."""
    if value is None:
        return ""
    number = float(value)
    return f"{number:,.0f} {unit}" if number == int(number) else f"{number:,.2f} {unit}"


class TemplateInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=5000)

    @field_validator("name", "body")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class OverrideInput(BaseModel):
    # Blank: the company uses the default text again.
    body: str = Field(default="", max_length=5000)


def _item(template, override=None):
    return {"id": template.id, "name": template.name, "body": template.body,
            "override": override.body if override else None, "sort_order": template.sort_order}


def _template_or_404(template_id, db):
    template = db.get(MessageTemplate, template_id)
    if not template:
        raise HTTPException(404, "Template not found")
    return template


@router.get("/message-templates")
def list_templates(company_id: str = "", user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Every template with its default text, and the company's own text when a company is chosen."""
    overrides = {}
    if company_id:
        overrides = {row.template_id: row for row in db.query(MessageTemplateOverride).filter_by(company_id=company_id)}
    templates = db.query(MessageTemplate).order_by(MessageTemplate.sort_order, MessageTemplate.name).all()
    return {"placeholders": [{"token": token, "label": label, "group": group} for token, label, group in PLACEHOLDERS],
            "templates": [_item(template, overrides.get(template.id)) for template in templates]}


@router.post("/message-templates")
def create_template(body: TemplateInput, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    from sqlalchemy import func
    last = db.query(func.max(MessageTemplate.sort_order)).scalar()
    template = MessageTemplate(name=body.name.strip(), body=body.body, sort_order=(last or 0) + 1, updated_by=user.id)
    db.add(template)
    db.commit()
    return _item(template)


@router.put("/message-templates/{template_id}")
def update_template(template_id: str, body: TemplateInput, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    template = _template_or_404(template_id, db)
    template.name, template.body, template.updated_by = body.name.strip(), body.body, user.id
    db.commit()
    return _item(template)


@router.delete("/message-templates/{template_id}")
def delete_template(template_id: str, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    template = _template_or_404(template_id, db)
    db.query(MessageTemplateOverride).filter_by(template_id=template.id).delete()
    db.delete(template)
    db.commit()
    return {"ok": True}


@router.put("/message-templates/{template_id}/companies/{company_id}")
def save_company_text(template_id: str, company_id: str, body: OverrideInput, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """The company's own text for the template; blank returns the company to the default text."""
    template = _template_or_404(template_id, db)
    if not db.get(Company, company_id):
        raise HTTPException(404, "Company not found")
    override = db.get(MessageTemplateOverride, (template.id, company_id))
    if not body.body.strip():
        if override:
            db.delete(override)
        override = None
    elif override:
        override.body, override.updated_by = body.body, user.id
    else:
        override = MessageTemplateOverride(template_id=template.id, company_id=company_id, body=body.body, updated_by=user.id)
        db.add(override)
    db.commit()
    return _item(template, override)


@router.get("/leads/{lead_id}/message-templates")
def lead_templates(lead_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The templates for this lead's company (its own text where it has one), filled in with the lead's details."""
    from move_types import normalize_move_type
    from models import job_number
    from routes.leads import _get_visible_lead_or_404, _read_job_route
    lead = _get_visible_lead_or_404(lead_id, user, db)
    # The lead's first job: its route, dates and number.
    job = db.query(LeadJob).filter(LeadJob.lead_id == lead.id).order_by(LeadJob.job_order).first()
    pickup, stops, delivery = _read_job_route(db, job) if job else ("", [], "")
    company = db.get(Company, lead.company_id) if lead.company_id else None
    rep = db.get(User, lead.assigned_to) if lead.assigned_to else None
    names = (lead.full_name or "").split()
    rep_names = ((rep.name or "") if rep else "").split()
    total = (lead.estimated_total_data() or {}).get("finalTotal")
    values = {
        "FirstName": names[0] if names else "", "LastName": " ".join(names[1:]), "FullName": " ".join(names),
        "LeadPhone": _phone(lead.phone), "LeadEmail": (lead.email or "").strip(),
        "MoveDate": _date(job.move_date if job and job.move_date else lead.move_date),
        "BookedDate": _date(job.booked_move_date if job and job.booked_move_date else lead.booked_move_date),
        "MoveSize": (lead.move_size or "").strip(), "MoveType": normalize_move_type(lead.move_type),
        "Volume": _amount(lead.volume, "cu ft"), "Weight": _amount(lead.weight, "lb"),
        "Pickup": pickup or "", "Stops": "; ".join(address for address in stops if address), "Delivery": delivery or "",
        "JobNumber": job_number(lead, job) if job else (lead.number or ""),
        "EstimateTotal": f"${total:,.2f}" if total else "", "ReferralSource": (lead.referral_source or "").strip(),
        "CompanyName": company.name if company else "", "CompanyPhone": _phone(company.phone) if company else "",
        "CompanyEmail": (company.sender_email or "") if company else "", "CompanyWebsite": (company.website or "") if company else "", "CompanyAddress": (company.office_address or "") if company else "",
        "DOTNumber": (company.dot_number or "") if company else "", "MCNumber": (company.mc_number or "") if company else "",
        "RepFirstName": rep_names[0] if rep_names else "", "RepName": " ".join(rep_names),
        "RepPhone": _phone(rep.phone) if rep else "", "RepEmail": (rep.email or "") if rep else "",
    }
    overrides = {}
    if lead.company_id:
        overrides = {row.template_id: row.body for row in db.query(MessageTemplateOverride).filter_by(company_id=lead.company_id)}
    templates = db.query(MessageTemplate).order_by(MessageTemplate.sort_order, MessageTemplate.name).all()
    return {"items": [{"id": template.id, "name": template.name,
                       "text": fill(overrides.get(template.id, template.body), values)} for template in templates]}
