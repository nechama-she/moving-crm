from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from auth import require_admin
from database import get_db
from models import Company, Lead, LeadDuplicationRule, User


router = APIRouter(prefix="/api/lead-duplication-rules", tags=["Lead Duplication Rules"])


class RuleBody(BaseModel):
    source_company_id: str
    source_referral_source: str
    target_company_id: str
    target_referral_source: str
    delay_minutes: int = Field(ge=0, le=525600)
    active: bool = True


def _serialize(rule: LeadDuplicationRule) -> dict:
    return {
        "id": rule.id,
        "source_company_id": rule.source_company_id,
        "source_company_name": rule.source_company.name if rule.source_company else "",
        "source_referral_source": rule.source_referral_source,
        "target_company_id": rule.target_company_id,
        "target_company_name": rule.target_company.name if rule.target_company else "",
        "target_referral_source": rule.target_referral_source,
        "delay_minutes": rule.delay_minutes,
        "active": rule.active,
    }


def _validate(body: RuleBody, db: Session) -> tuple[Company, Company, str, str]:
    source = db.query(Company).filter(Company.id == body.source_company_id).first()
    target = db.query(Company).filter(Company.id == body.target_company_id).first()
    if not source or not target:
        raise HTTPException(status_code=400, detail="Source and target companies must exist")
    if source.id == target.id:
        raise HTTPException(status_code=400, detail="Source and target companies must be different")
    source_referral = body.source_referral_source.strip()
    target_referral = body.target_referral_source.strip()
    if not source_referral or not target_referral:
        raise HTTPException(status_code=400, detail="Source and target campaigns are required")
    return source, target, source_referral, target_referral


@router.get("")
def list_rules(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    companies = db.query(Company).order_by(Company.name).all()
    campaign_rows = (
        db.query(Lead.company_id, Lead.referral_source)
        .filter(Lead.referral_source.isnot(None), Lead.referral_source != "")
        .distinct()
        .order_by(Lead.company_id, Lead.referral_source)
        .all()
    )
    campaigns: dict[str, list[str]] = {}
    for company_id, referral_source in campaign_rows:
        campaigns.setdefault(company_id, []).append(referral_source)
    rules = (
        db.query(LeadDuplicationRule)
        .options(joinedload(LeadDuplicationRule.source_company), joinedload(LeadDuplicationRule.target_company))
        .order_by(LeadDuplicationRule.source_company_id, LeadDuplicationRule.source_referral_source, LeadDuplicationRule.created_at)
        .all()
    )
    return {
        "rules": [_serialize(rule) for rule in rules],
        "companies": [{"id": company.id, "name": company.name} for company in companies],
        "campaigns": campaigns,
    }


@router.post("", status_code=201)
def create_rule(body: RuleBody, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    source, target, source_referral, target_referral = _validate(body, db)
    rule = LeadDuplicationRule(
        source_company_id=source.id,
        source_referral_source=source_referral,
        target_company_id=target.id,
        target_referral_source=target_referral,
        delay_minutes=body.delay_minutes,
        active=body.active,
    )
    db.add(rule)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="This exact duplication rule already exists")
    db.refresh(rule)
    rule.source_company = source
    rule.target_company = target
    return _serialize(rule)


@router.put("/{rule_id}")
def update_rule(rule_id: str, body: RuleBody, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    rule = db.query(LeadDuplicationRule).filter(LeadDuplicationRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Duplication rule not found")
    source, target, source_referral, target_referral = _validate(body, db)
    rule.source_company_id = source.id
    rule.source_referral_source = source_referral
    rule.target_company_id = target.id
    rule.target_referral_source = target_referral
    rule.delay_minutes = body.delay_minutes
    rule.active = body.active
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="This exact duplication rule already exists")
    db.refresh(rule)
    rule.source_company = source
    rule.target_company = target
    return _serialize(rule)


@router.delete("/{rule_id}")
def delete_rule(rule_id: str, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    rule = db.query(LeadDuplicationRule).filter(LeadDuplicationRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Duplication rule not found")
    db.delete(rule)
    db.commit()
    return {"ok": True}
