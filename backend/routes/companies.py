import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth import require_admin
from database import get_db
from models import Company, User

logger = logging.getLogger("moving-crm")

router = APIRouter(prefix="/api/companies", tags=["Companies"])


class CompanyCreate(BaseModel):
    name: str
    phone: str = ""
    facebook_page_id: Optional[str] = None


@router.get("")
def list_companies(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    companies = db.query(Company).order_by(Company.name).all()
    return [c.to_dict() for c in companies]


@router.post("")
def create_company(body: CompanyCreate, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    existing = db.query(Company).filter(Company.name == body.name).first()
    if existing:
        raise HTTPException(status_code=409, detail="Company already exists")
    page_id = (body.facebook_page_id or "").strip() or None
    company = Company(name=body.name, phone=body.phone, facebook_page_id=page_id)
    db.add(company)
    db.commit()
    db.refresh(company)
    return company.to_dict()


class CompanyUpdate(BaseModel):
    phone: str = ""
    facebook_page_id: Optional[str] = None
    aircall_number_id: str = ""


@router.put("/{company_id}")
def update_company(company_id: str, body: CompanyUpdate, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    company.phone = body.phone
    company.facebook_page_id = (body.facebook_page_id or "").strip() or None
    company.aircall_number_id = body.aircall_number_id
    db.commit()
    db.refresh(company)
    return company.to_dict()
