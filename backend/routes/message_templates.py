"""Message templates a user picks when writing to a lead (SMS, Messenger). Each template has a default text for every
company, and a company can have its own text for it. Not the automatic messages (routes/templates.py)."""
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from auth import get_current_user, require_admin
from database import get_db
from models import Company, LeadJob, MessageTemplate, MessageTemplateField, MessageTemplateOverride, User

router = APIRouter(prefix="/api", tags=["Message Templates"])

# An @ starting a word, as the editor inserts it; one inside a word (an email address) is not a field.
_TOKEN = re.compile(r"(?<![A-Za-z0-9])@([A-Za-z]+)")


def fill(text, values):
    """Each @Token replaced by its value; any other @word (an email address, a handle) is left as written."""
    return _TOKEN.sub(lambda match: values[match.group(1)] if match.group(1) in values else match.group(0), text)


class TemplateInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=5000)

    @field_validator("name", "body")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class FieldInput(BaseModel):
    enabled: bool


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
    """Every template with its default text, and the company's own text when a company is chosen; and the fields the
    @ list offers."""
    overrides = {}
    if company_id:
        overrides = {row.template_id: row for row in db.query(MessageTemplateOverride).filter_by(company_id=company_id)}
    templates = db.query(MessageTemplate).order_by(MessageTemplate.sort_order, MessageTemplate.name).all()
    from template_fields import offered
    return {"placeholders": [{"token": token, "label": label, "group": group} for token, label, group in offered(db)],
            "templates": [_item(template, overrides.get(template.id)) for template in templates]}


@router.get("/message-templates/fields")
def list_fields(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Every field there is, by group, and whether the @ list offers it."""
    from template_fields import fields
    enabled = {row.token for row in db.query(MessageTemplateField).filter(MessageTemplateField.enabled.is_(True))}
    return {"fields": [{"token": token, "label": label, "group": group, "enabled": token in enabled} for token, label, group in fields()]}


@router.put("/message-templates/fields/{token}")
def set_field(token: str, body: FieldInput, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Turns a field on or off in the @ list. Templates already using a field still fill it in."""
    from template_fields import fields
    if token not in {known for known, _, _ in fields()}:
        raise HTTPException(404, "Field not found")
    row = db.get(MessageTemplateField, token)
    if row is None:
        row = MessageTemplateField(token=token)
        db.add(row)
    row.enabled, row.updated_by = body.enabled, user.id
    db.commit()
    return {"token": token, "enabled": row.enabled}


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
    from routes.leads import _get_visible_lead_or_404, _read_job_route
    from template_fields import values as field_values
    lead = _get_visible_lead_or_404(lead_id, user, db)
    # The lead's first job: its route, dates and number.
    job = db.query(LeadJob).filter(LeadJob.lead_id == lead.id).order_by(LeadJob.job_order).first()
    route = _read_job_route(db, job) if job else ("", [], "")
    company = db.get(Company, lead.company_id) if lead.company_id else None
    rep = db.get(User, lead.assigned_to) if lead.assigned_to else None
    values = field_values(lead, job, route, company, rep)
    overrides = {}
    if lead.company_id:
        overrides = {row.template_id: row.body for row in db.query(MessageTemplateOverride).filter_by(company_id=lead.company_id)}
    templates = db.query(MessageTemplate).order_by(MessageTemplate.sort_order, MessageTemplate.name).all()
    return {"items": [{"id": template.id, "name": template.name,
                       "text": fill(overrides.get(template.id, template.body), values)} for template in templates]}
