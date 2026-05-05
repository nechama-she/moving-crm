import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth import require_admin
from database import get_db
from models import Company, User, UserCompany, Lead

logger = logging.getLogger("moving-crm")

router = APIRouter(prefix="/api/companies", tags=["Companies"])


class CompanyCreate(BaseModel):
    name: str
    phone: str = ""
    facebook_page_id: Optional[str] = None
    aircall_number_id: str = ""
    samrtmoving_branch_id: str = ""
    timezone: str = "America/New_York"


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

    existing = db.query(Company).filter(Company.name == company_name).first()
    if existing:
        raise HTTPException(status_code=409, detail="Company already exists")
    page_id = (body.facebook_page_id or "").strip() or None
    company = Company(
        name=company_name,
        phone=(body.phone or "").strip(),
        facebook_page_id=page_id,
        aircall_number_id=(body.aircall_number_id or "").strip(),
        samrtmoving_branch_id=(body.samrtmoving_branch_id or "").strip(),
        timezone=(body.timezone or "").strip() or "America/New_York",
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company.to_dict()


class CompanyUpdate(BaseModel):
    name: str
    phone: str = ""
    facebook_page_id: Optional[str] = None
    aircall_number_id: str = ""
    samrtmoving_branch_id: str = ""
    timezone: str = "America/New_York"


@router.put("/{company_id}")
def update_company(company_id: str, body: CompanyUpdate, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    company_name = (body.name or "").strip()
    if not company_name:
        raise HTTPException(status_code=400, detail="Company name is required")

    duplicate = db.query(Company).filter(Company.name == company_name, Company.id != company_id).first()
    if duplicate:
        raise HTTPException(status_code=409, detail="Company name already exists")

    company.name = company_name
    company.phone = (body.phone or "").strip()
    company.facebook_page_id = (body.facebook_page_id or "").strip() or None
    company.aircall_number_id = (body.aircall_number_id or "").strip()
    company.samrtmoving_branch_id = (body.samrtmoving_branch_id or "").strip()
    company.timezone = (body.timezone or "").strip() or "America/New_York"
    db.commit()
    db.refresh(company)
    return company.to_dict()


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

    db.delete(company)
    db.commit()
    return {"ok": True}
