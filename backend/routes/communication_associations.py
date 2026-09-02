from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from auth import require_admin
from communication_associations import normalized_key
from database import get_db
from models import CommunicationAssociation, Company, Lead, User, UserCompany

router = APIRouter(prefix="/api/communication-associations", tags=["Communication Associations"])


class ConnectRequest(BaseModel):
    channel: str
    client_identifier: str
    company_identifier: str
    lead_id: str


def _destination_scope(db: Session, channel: str, company_identifier: str) -> tuple[set[str], str]:
    if channel == "phone":
        normalized_company_phone = func.right(func.regexp_replace(Company.phone, r"\D", "", "g"), 10)
        direct_companies = db.query(Company).filter(normalized_company_phone == company_identifier).all()
        direct = {company.id for company in direct_companies}
        if direct:
            return direct, ", ".join(sorted(company.name for company in direct_companies))
        normalized_rep_phone = func.right(func.regexp_replace(User.phone, r"\D", "", "g"), 10)
        reps = db.query(User).filter(normalized_rep_phone == company_identifier).all()
        rep_ids = [rep.id for rep in reps]
        if rep_ids:
            company_ids = {row[0] for row in db.query(UserCompany.company_id).filter(UserCompany.user_id.in_(rep_ids)).all()}
            return company_ids, ", ".join(sorted(rep.name for rep in reps))
        return set(), ""
    companies = db.query(Company).filter(Company.facebook_page_id == company_identifier).all()
    return {company.id for company in companies}, ", ".join(sorted(company.name for company in companies))


def _company_ids(db: Session, channel: str, company_identifier: str) -> set[str]:
    return _destination_scope(db, channel, company_identifier)[0]


@router.get("/candidates")
def candidates(
    channel: str = Query(...),
    client_identifier: str = Query(...),
    company_identifier: str = Query(...),
    search: str = Query(""),
    limit: int = Query(30, ge=1, le=100),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    key = normalized_key(channel, client_identifier, company_identifier)
    if not all(key):
        raise HTTPException(status_code=400, detail="Complete communication identifiers are required")
    company_ids, scope_label = _destination_scope(db, key[0], key[2])
    if not company_ids:
        raise HTTPException(status_code=404, detail="The destination is not connected to a CRM company")
    query = db.query(Lead).filter(Lead.company_id.in_(company_ids))
    needle = search.strip()
    if needle:
        pattern = f"%{needle}%"
        query = query.filter(or_(Lead.full_name.ilike(pattern), Lead.phone.ilike(pattern), Lead.email.ilike(pattern), Lead.smartmoving_id.ilike(pattern)))
    leads = query.order_by(Lead.created_at.desc()).limit(limit).all()
    return {
        "scope_label": scope_label,
        "companies": [{"id": company.id, "name": company.name} for company in db.query(Company).filter(Company.id.in_(company_ids)).order_by(Company.name).all()],
        "items": [{"id": lead.id, "name": lead.full_name, "phone": lead.phone or "", "email": lead.email or "", "company_id": lead.company_id, "company": lead.company.name if lead.company else ""} for lead in leads],
    }


@router.put("")
def connect(body: ConnectRequest, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    key = normalized_key(body.channel, body.client_identifier, body.company_identifier)
    if not all(key):
        raise HTTPException(status_code=400, detail="Complete communication identifiers are required")
    company_ids = _company_ids(db, key[0], key[2])
    lead = db.query(Lead).filter(Lead.id == body.lead_id, Lead.company_id.in_(company_ids)).first()
    if not lead:
        raise HTTPException(status_code=400, detail="The selected lead is not under the communication's destination company")
    statement = insert(CommunicationAssociation).values(
        channel=key[0], client_identifier=key[1], company_identifier=key[2],
        lead_id=lead.id, company_id=lead.company_id, created_by=admin.id,
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
    ).on_conflict_do_update(
        index_elements=[CommunicationAssociation.channel, CommunicationAssociation.client_identifier, CommunicationAssociation.company_identifier],
        set_={"lead_id": lead.id, "company_id": lead.company_id, "created_by": admin.id, "updated_at": datetime.now(timezone.utc)},
    )
    db.execute(statement)
    # Existing work-queue rows immediately inherit the manual association.
    from models import MessageState, MissedCallState
    if key[0] == "phone":
        db.query(MessageState).filter(MessageState.channel == "sms", MessageState.client_identifier == key[1], MessageState.company_identifier == key[2]).update({MessageState.lead_id: lead.id}, synchronize_session=False)
        db.query(MissedCallState).filter(MissedCallState.client_identifier == key[1], MissedCallState.company_identifier == key[2]).update({MissedCallState.lead_id: lead.id}, synchronize_session=False)
    else:
        db.query(MessageState).filter(MessageState.channel == key[0], MessageState.client_identifier == key[1], MessageState.company_identifier == key[2]).update({MessageState.lead_id: lead.id}, synchronize_session=False)
    db.commit()
    return {"ok": True, "lead": {"id": lead.id, "name": lead.full_name, "company": lead.company.name if lead.company else "", "rep": lead.assignee.name if lead.assignee else ""}}
