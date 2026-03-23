import logging

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


@router.get("")
def list_companies(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    companies = db.query(Company).order_by(Company.name).all()
    return [c.to_dict() for c in companies]


@router.post("")
def create_company(body: CompanyCreate, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    existing = db.query(Company).filter(Company.name == body.name).first()
    if existing:
        raise HTTPException(status_code=409, detail="Company already exists")
    company = Company(name=body.name, phone=body.phone)
    db.add(company)
    db.commit()
    db.refresh(company)
    return company.to_dict()
