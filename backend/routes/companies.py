import logging
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.orm import Session

from auth import require_admin, get_current_user
from company_colors import normalize_company_color, resolve_company_color
from database import get_db
from models import Company, User, UserCompany, Lead, LeadJob
from company_dispatch import validate_dispatches_for

logger = logging.getLogger("moving-crm")

router = APIRouter(prefix="/api/companies", tags=["Companies"])

_SENDER_EMAIL_RE = re.compile(r"^[^@\s<>\"]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$")


def _clean_sender_email(value: str | None) -> str | None:
    value = (value or "").strip().lower()
    if not value:
        return None
    if not _SENDER_EMAIL_RE.match(value):
        raise HTTPException(status_code=400, detail="Sender email must be a valid email address")
    return value


class CompanyLogo(BaseModel):
    dot_number: str | None = Field(default=None, max_length=30)
    logo: Optional[str] = Field(default=None, max_length=400000)

    @field_validator('dot_number')
    @classmethod
    def validate_dot_number(cls, value):
        if value is None:
            return None
        value = value.strip()
        if value and not re.fullmatch(r'[0-9]+', value):
            raise ValueError('USDOT number must contain digits only.')
        return value

    @field_validator('logo')
    @classmethod
    def validate_logo(cls, value):
        if not value:
            return value
        import base64
        import struct
        try:
            if not value.startswith('data:image/png;base64,'):
                raise ValueError()
            raw = base64.b64decode(value.split(',', 1)[1], validate=True)
            if raw[:8] != b'\x89PNG\r\n\x1a\n' or raw[12:16] != b'IHDR':
                raise ValueError()
            width, height = struct.unpack('>II', raw[16:24])
            if width != 256 or height != 256:
                raise ValueError()
        except Exception:
            raise ValueError('Logo must be a cropped 256 by 256 PNG image.')
        return value


class CompanyCreate(CompanyLogo):
    name: str
    color: Optional[str] = None
    phone: str = ""
    office_address: str = Field(default="", max_length=1000)
    sender_email: str = Field(default="", max_length=255)
    facebook_page_id: Optional[str] = None
    aircall_number_id: str = ""
    aircall_name: str = ""
    dispatches_for_company_id: str | None = None
    samrtmoving_branch_id: str = ""
    granot_api_id: str = ""
    granot_mover_ref: str = ""
    timezone: str = "America/New_York"


class CompanyDocumentInput(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body_html: str = Field(max_length=100000)
    move_type: str = Field(pattern=r'^(Long Distance|Local|All)$')
    enabled: bool = True
    revision: int = Field(default=0, ge=0)


@router.get('/{company_id}/documents')
def company_documents(company_id: str, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    from sqlalchemy import case
    from models import CompanyDocument
    from company_documents import document_payload, DEFAULT_KEY
    if db.get(Company, company_id) is None:
        raise HTTPException(404, 'Company not found')
    rows = db.query(CompanyDocument).filter_by(company_id=company_id).order_by(
        case((CompanyDocument.key == DEFAULT_KEY, 0), else_=1), CompanyDocument.title).all()
    return {'items': [document_payload(row) for row in rows]}


@router.put('/{company_id}/documents/{document_key}')
def save_company_document(company_id: str, document_key: str, body: CompanyDocumentInput,
                          _: User = Depends(require_admin), db: Session = Depends(get_db)):
    from datetime import datetime
    from models import CompanyDocument
    from company_documents import clean_html, document_payload
    if not re.fullmatch(r'[a-zA-Z0-9-]{1,80}', document_key):
        raise HTTPException(422, 'Invalid document key')
    # Serialize additions and edits for this company, including first-time creates.
    if db.query(Company).filter_by(id=company_id).with_for_update().first() is None:
        raise HTTPException(404, 'Company not found')
    row = db.query(CompanyDocument).filter_by(company_id=company_id, key=document_key).first()
    if body.revision != (row.revision if row else 0):
        raise HTTPException(409, 'This document changed. Reload it before saving again.')
    if not body.title.strip():
        raise HTTPException(422, 'Enter a document title')
    try:
        html = clean_html(body.body_html)
    except ValueError as error:
        raise HTTPException(422, str(error))
    if row is None:
        row = CompanyDocument(company_id=company_id, key=document_key)
        db.add(row)
    row.title, row.body_html = body.title.strip(), html
    row.move_type, row.enabled = body.move_type, body.enabled
    row.revision, row.updated_at = body.revision + 1, datetime.utcnow()
    db.commit()
    return document_payload(row)


@router.post('/{company_id}/documents/preview')
def preview_company_document(company_id: str, body: CompanyDocumentInput,
                             _: User = Depends(require_admin), db: Session = Depends(get_db)):
    from html import escape
    from company_documents import clean_html
    company = db.get(Company, company_id)
    if company is None:
        raise HTTPException(404, 'Company not found')
    try:
        return {'body_html': clean_html(body.body_html.replace('{{company_name}}', escape(company.name)))}
    except ValueError as error:
        raise HTTPException(422, str(error))


@router.get("/mine")
def list_my_companies(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Return companies accessible to the current user."""
    if user.role == "admin":
        admin_rows = db.query(UserCompany.company_id).filter(UserCompany.user_id == user.id).all()
        if admin_rows:
            admin_company_ids = [r[0] for r in admin_rows]
            companies = db.query(Company).filter(Company.id.in_(admin_company_ids)).order_by(Company.name).all()
        else:
            companies = db.query(Company).order_by(Company.name).all()
    else:
        company_ids = [r[0] for r in db.query(UserCompany.company_id).filter(UserCompany.user_id == user.id).all()]
        companies = db.query(Company).filter(Company.id.in_(company_ids)).order_by(Company.name).all()
    return [c.to_dict() for c in companies]


@router.get("")
def list_companies(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    companies = db.query(Company).order_by(Company.name).all()
    return [c.to_dict() for c in companies]


@router.get("/{company_id}")
def get_company(company_id: str, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return company.to_dict()


@router.get("/by-facebook-page/{facebook_page_id}")
def get_company_by_facebook_page_id(
    facebook_page_id: str,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    page_id = facebook_page_id.strip()
    company = db.query(Company).filter(Company.facebook_page_id == page_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return company.to_dict()


@router.post("")
def create_company(body: CompanyCreate, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    company_name = (body.name or "").strip()
    if not company_name:
        raise HTTPException(status_code=400, detail="Company name is required")

    if body.color and not normalize_company_color(body.color):
        raise HTTPException(status_code=400, detail="Company color must be a valid hex color")

    existing = db.query(Company).filter(Company.name == company_name).first()
    if existing:
        raise HTTPException(status_code=409, detail="Company already exists")
    page_id = (body.facebook_page_id or "").strip() or None
    company = Company(
        dispatches_for_company_id=validate_dispatches_for(db, body.dispatches_for_company_id),
        name=company_name,
        logo=body.logo or None,
        color=resolve_company_color(company_name, body.color),
        phone=(body.phone or "").strip(),
        office_address=body.office_address.strip(),
        dot_number=body.dot_number or "",
        sender_email=_clean_sender_email(body.sender_email),
        facebook_page_id=page_id,
        aircall_number_id=(body.aircall_number_id or "").strip(),
        aircall_name=(body.aircall_name or "").strip() or None,
        samrtmoving_branch_id=(body.samrtmoving_branch_id or "").strip(),
        granot_api_id=(body.granot_api_id or "").strip() or None,
        granot_mover_ref=(body.granot_mover_ref or "").strip() or None,
        timezone=(body.timezone or "").strip() or "America/New_York",
    )
    db.add(company)
    db.flush()
    from company_documents import new_company_document
    db.add(new_company_document(company.id))
    db.commit()
    db.refresh(company)
    return company.to_dict()


class CompanyUpdate(CompanyLogo):
    name: str
    color: Optional[str] = None
    phone: str = ""
    office_address: str | None = Field(default=None, max_length=1000)
    sender_email: str | None = Field(default=None, max_length=255)
    facebook_page_id: Optional[str] = None
    aircall_number_id: str = ""
    aircall_name: str = ""
    dispatches_for_company_id: str | None = None
    samrtmoving_branch_id: str = ""
    granot_api_id: str = ""
    granot_mover_ref: str = ""
    timezone: str = "America/New_York"


@router.put("/{company_id}")
def update_company(company_id: str, body: CompanyUpdate, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    company_name = (body.name or "").strip()
    if not company_name:
        raise HTTPException(status_code=400, detail="Company name is required")

    if body.color and not normalize_company_color(body.color):
        raise HTTPException(status_code=400, detail="Company color must be a valid hex color")

    duplicate = db.query(Company).filter(Company.name == company_name, Company.id != company_id).first()
    if duplicate:
        raise HTTPException(status_code=409, detail="Company name already exists")

    if "dispatches_for_company_id" in body.model_fields_set:
        company.dispatches_for_company_id = validate_dispatches_for(db, body.dispatches_for_company_id, company.id)
    if body.logo is not None:
        company.logo = body.logo or None
    company.name = company_name
    company.color = resolve_company_color(company_name, body.color)
    company.phone = (body.phone or "").strip()
    if body.office_address is not None:
        company.office_address = body.office_address.strip()
    if body.dot_number is not None:
        company.dot_number = body.dot_number
    if body.sender_email is not None:
        company.sender_email = _clean_sender_email(body.sender_email)
    company.facebook_page_id = (body.facebook_page_id or "").strip() or None
    company.aircall_number_id = (body.aircall_number_id or "").strip()
    company.aircall_name = (body.aircall_name or "").strip() or None
    company.samrtmoving_branch_id = (body.samrtmoving_branch_id or "").strip()
    company.granot_api_id = (body.granot_api_id or "").strip() or None
    company.granot_mover_ref = (body.granot_mover_ref or "").strip() or None
    company.timezone = (body.timezone or "").strip() or "America/New_York"
    db.commit()
    db.refresh(company)
    return company.to_dict()


class CompanyDefaultUpdate(BaseModel):
    is_default_company: bool


@router.patch("/{company_id}/default")
def set_default_company(company_id: str, body: CompanyDefaultUpdate, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    # Serialize switches, including when no company is currently the default.
    db.execute(text("SELECT pg_advisory_xact_lock(724103, 1)"))
    company = db.query(Company).filter(Company.id == company_id).with_for_update().first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    if body.is_default_company:
        db.query(Company).filter(Company.is_default_company.is_(True)).update(
            {Company.is_default_company: False}, synchronize_session="fetch"
        )
        db.flush()
    company.is_default_company = body.is_default_company
    db.commit()
    return [c.to_dict() for c in db.query(Company).order_by(Company.name).all()]


@router.delete("/{company_id}")
def delete_company(company_id: str, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    linked_users = db.query(UserCompany).filter(UserCompany.company_id == company_id).count()
    if linked_users:
        raise HTTPException(status_code=409, detail="Cannot delete company with assigned users")

    linked_leads = db.query(Lead).filter(Lead.company_id == company_id).count()
    if linked_leads:
        raise HTTPException(status_code=409, detail="Cannot delete company with existing leads")

    if db.query(Company).filter(Company.dispatches_for_company_id == company_id).first():
        raise HTTPException(status_code=409, detail="Cannot delete company used by a subcontractor")
    if db.query(LeadJob).filter((LeadJob.company_id == company_id) | (LeadJob.dispatch_company_id == company_id)).first():
        raise HTTPException(status_code=409, detail="Cannot delete company with existing jobs or subcontractor assignments")

    db.delete(company)
    db.commit()
    return {"ok": True}
