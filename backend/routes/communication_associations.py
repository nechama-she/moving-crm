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
    only_if_unconnected: bool = False


class CreateAndConnectRequest(BaseModel):
    channel: str
    client_identifier: str
    company_identifier: str
    company_id: str
    full_name: str
    phone: str = ""
    email: str = ""
    pickup_zip: str = ""
    delivery_zip: str = ""
    move_date: str = ""
    move_size: str = ""
    referral_source: str = ""


def _destination_scope(db: Session, channel: str, company_identifier: str) -> tuple[set[str], set[str], str]:
    if channel == "phone":
        normalized_company_phone = func.right(func.regexp_replace(Company.phone, r"\D", "", "g"), 10)
        direct_companies = db.query(Company).filter(normalized_company_phone == company_identifier).all()
        direct = {company.id for company in direct_companies}
        if direct:
            return direct, set(), ", ".join(sorted(company.name for company in direct_companies))
        normalized_rep_phone = func.right(func.regexp_replace(User.phone, r"\D", "", "g"), 10)
        reps = db.query(User).filter(normalized_rep_phone == company_identifier).all()
        rep_ids = [rep.id for rep in reps]
        if rep_ids:
            company_ids = {row[0] for row in db.query(UserCompany.company_id).filter(UserCompany.user_id.in_(rep_ids)).all()}
            return company_ids, set(rep_ids), ", ".join(sorted(rep.name for rep in reps))
        return set(), set(), ""
    companies = db.query(Company).filter(Company.facebook_page_id == company_identifier).all()
    return {company.id for company in companies}, set(), ", ".join(sorted(company.name for company in companies))


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
    company_ids, rep_ids, scope_label = _destination_scope(db, key[0], key[2])
    if not company_ids:
        raise HTTPException(status_code=404, detail="The destination is not connected to a CRM company")
    query = db.query(Lead).filter(Lead.company_id.in_(company_ids))
    if rep_ids:
        query = query.filter(Lead.assigned_to.in_(rep_ids))
    needle = search.strip()
    if needle:
        pattern = f"%{needle}%"
        query = query.filter(or_(Lead.full_name.ilike(pattern), Lead.phone.ilike(pattern), Lead.email.ilike(pattern), Lead.smartmoving_id.ilike(pattern)))
    leads = query.order_by(Lead.created_at.desc()).limit(limit).all()
    return {
        "scope_label": scope_label,
        "companies": [{"id": company.id, "name": company.name} for company in db.query(Company).filter(Company.id.in_(company_ids)).order_by(Company.name).all()],
        "items": [{
            "id": lead.id,
            "name": lead.full_name,
            "phone": lead.phone or "",
            "email": lead.email or "",
            "company_id": lead.company_id,
            "company": lead.company.name if lead.company else "",
            "smartmoving_id": lead.smartmoving_id or "",
            "pickup_zip": lead.pickup_zip or "",
            "delivery_zip": lead.delivery_zip or "",
            "move_date": lead.move_date or "",
            "move_size": lead.move_size or "",
            "status": lead.status or "",
            "rep": lead.assignee.name if lead.assignee else "",
        } for lead in leads],
    }


@router.put("")
def connect(body: ConnectRequest, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    key = normalized_key(body.channel, body.client_identifier, body.company_identifier)
    if not all(key):
        raise HTTPException(status_code=400, detail="Complete communication identifiers are required")
    company_ids, rep_ids, _ = _destination_scope(db, key[0], key[2])
    lead_query = db.query(Lead).filter(Lead.id == body.lead_id, Lead.company_id.in_(company_ids))
    if rep_ids:
        lead_query = lead_query.filter(Lead.assigned_to.in_(rep_ids))
    lead = lead_query.first()
    if not lead:
        raise HTTPException(status_code=400, detail="The selected lead does not match the communication destination")
    if body.only_if_unconnected:
        legacy = db.query(Lead).filter(Lead.facebook_user_id == key[1], Lead.company_id.in_(company_ids)).first()
        if legacy:
            raise HTTPException(409, 'This chat is already connected to a lead')
    statement = insert(CommunicationAssociation).values(
        channel=key[0], client_identifier=key[1], company_identifier=key[2],
        lead_id=lead.id, company_id=lead.company_id, created_by=admin.id,
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
    ).on_conflict_do_update(
        index_elements=[CommunicationAssociation.channel, CommunicationAssociation.client_identifier, CommunicationAssociation.company_identifier],
        set_={"lead_id": lead.id, "company_id": lead.company_id, "created_by": admin.id, "updated_at": datetime.now(timezone.utc)},
    )
    if body.only_if_unconnected:
        statement = insert(CommunicationAssociation).values(
            channel=key[0], client_identifier=key[1], company_identifier=key[2],
            lead_id=lead.id, company_id=lead.company_id, created_by=admin.id,
            created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
        ).on_conflict_do_nothing().returning(CommunicationAssociation.lead_id)
        if db.execute(statement).scalar_one_or_none() is None:
            db.rollback()
            raise HTTPException(409, 'This chat is already connected to a lead')
    else:
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


@router.post("/create-lead")
def create_and_connect(body: CreateAndConnectRequest, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    key = normalized_key(body.channel, body.client_identifier, body.company_identifier)
    if not all(key):
        raise HTTPException(status_code=400, detail="Complete communication identifiers are required")
    company_ids, rep_ids, _ = _destination_scope(db, key[0], key[2])
    if body.company_id not in company_ids:
        raise HTTPException(status_code=400, detail="The selected company is not available for this destination")
    full_name = body.full_name.strip()
    if not full_name:
        raise HTTPException(status_code=400, detail="Lead name is required")
    company = db.query(Company).filter(Company.id == body.company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    # This is the same SmartMoving -> canonical CRM creation path used by lead duplication.
    from routes.leads import create_lead_through_copy_path
    lead, creation = create_lead_through_copy_path(
        db=db,
        target_company=company,
        full_name=full_name,
        phone=(body.phone.strip() or key[1]) if key[0] == "phone" else body.phone.strip(),
        email=body.email.strip(),
        pickup_zip=body.pickup_zip.strip(),
        delivery_zip=body.delivery_zip.strip(),
        move_date=body.move_date.strip(),
        move_size=body.move_size.strip(),
        referral_source=body.referral_source.strip(),
        facebook_user_id=key[1] if key[0] in {"messenger", "instagram"} else "",
        assigned_to=next(iter(rep_ids)) if len(rep_ids) == 1 else "",
        notes=f"Created from an unmatched {body.channel} communication in Moving CRM",
    )
    result = connect(
        ConnectRequest(
            channel=body.channel,
            client_identifier=body.client_identifier,
            company_identifier=body.company_identifier,
            lead_id=lead.id,
        ),
        admin=admin,
        db=db,
    )
    result["creation"] = creation
    return result


@router.get('/unconnected-meta')
def unconnected_meta(lead_id: str, channel: str = Query(..., pattern='^(messenger|instagram)$'),
                     search: str = Query('', max_length=300), cursor: str = '',
                     admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    from routes.leads import _get_visible_lead_or_404
    from routes.chats import _query_meta_page, _decode_cursor, _encode_cursor, _timestamp
    lead = _get_visible_lead_or_404(lead_id, admin, db)
    company = db.get(Company, lead.company_id) if lead.company_id else None
    page_id = str(company.facebook_page_id or '') if company else ''
    if not page_id:
        return {'items': [], 'next_cursor': '', 'has_more': False}
    start, _ = _decode_cursor(cursor)
    messages, next_key = _query_meta_page(start, 100)
    linked = {row[0] for row in db.query(CommunicationAssociation.client_identifier).filter(
        CommunicationAssociation.channel == channel, CommunicationAssociation.company_identifier == page_id).all()}
    linked.update(row[0] for row in db.query(Lead.facebook_user_id).join(Company, Company.id == Lead.company_id).filter(
        Company.facebook_page_id == page_id, Lead.facebook_user_id.isnot(None)).all())
    items = {}
    needle = search.strip().casefold()
    for message in messages:
        client = str(message.get('user_id') or '')
        if not client or client in linked or message.get('platform') != channel or str(message.get('page_id') or '') != page_id:
            continue
        searchable = ' '.join(str(message.get(k) or '') for k in ('text', 'user_id', 'name', 'sender_name'))
        if needle and needle not in searchable.casefold():
            continue
        stamp = _timestamp(message.get('timestamp'))
        if client not in items or stamp > items[client]['timestamp']:
            items[client] = {'client_identifier': client, 'company_identifier': page_id,
                'name': str(message.get('sender_name') or message.get('name') or client),
                'timestamp': stamp, 'preview': str(message.get('text') or '')}
    return {'items': sorted(items.values(), key=lambda row: row['timestamp'], reverse=True),
            'next_cursor': _encode_cursor(next_key, None) if next_key else '', 'has_more': bool(next_key)}


@router.get('/meta-preview')
def meta_preview(lead_id: str, client_identifier: str,
                 channel: str = Query(..., pattern='^(messenger|instagram)$'), cursor: str = '',
                 admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    from routes.leads import _get_visible_lead_or_404
    from routes.chats import _decode_cursor, _encode_cursor
    from db import conversations_table
    from boto3.dynamodb.conditions import Key, Attr
    lead = _get_visible_lead_or_404(lead_id, admin, db)
    company = db.get(Company, lead.company_id) if lead.company_id else None
    if not company or not company.facebook_page_id:
        raise HTTPException(400, 'The lead company has no Meta page')
    start, _ = _decode_cursor(cursor)
    args = dict(KeyConditionExpression=Key('user_id').eq(client_identifier),
        FilterExpression=Attr('platform').eq(channel) & Attr('page_id').eq(company.facebook_page_id), Limit=100)
    if start: args['ExclusiveStartKey'] = start
    result = conversations_table.query(**args)
    next_key = result.get('LastEvaluatedKey')
    return {'messages': result.get('Items', []), 'next_cursor': _encode_cursor(next_key, None) if next_key else ''}


@router.get('/lead-meta-links')
def lead_meta_links(lead_id: str, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    from routes.leads import _get_visible_lead_or_404
    lead = _get_visible_lead_or_404(lead_id, admin, db)
    return {'items': [{'channel': row.channel, 'client_identifier': row.client_identifier, 'company_identifier': row.company_identifier}
        for row in db.query(CommunicationAssociation).filter(CommunicationAssociation.lead_id == lead.id,
            CommunicationAssociation.channel.in_(['messenger', 'instagram'])).all()]}


@router.delete('')
def disconnect(body: ConnectRequest, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    from routes.leads import _get_visible_lead_or_404
    from models import MessageState
    lead = _get_visible_lead_or_404(body.lead_id, admin, db)
    key = normalized_key(body.channel, body.client_identifier, body.company_identifier)
    if key[0] not in ('messenger', 'instagram') or not all(key):
        raise HTTPException(400, 'A Messenger or Instagram connection is required')
    row = db.query(CommunicationAssociation).filter(
        CommunicationAssociation.channel == key[0], CommunicationAssociation.client_identifier == key[1],
        CommunicationAssociation.company_identifier == key[2], CommunicationAssociation.lead_id == lead.id,
    ).with_for_update().first()
    if not row:
        raise HTTPException(404, 'This chat connection no longer exists')
    db.delete(row)
    db.query(MessageState).filter(MessageState.channel == key[0], MessageState.client_identifier == key[1],
        MessageState.company_identifier == key[2], MessageState.lead_id == lead.id).update(
        {MessageState.lead_id: None}, synchronize_session=False)
    db.commit()
    return {'ok': True}
