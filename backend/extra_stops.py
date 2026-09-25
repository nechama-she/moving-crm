"""Extra-stop pricing. Saved route distances avoid network requests on page reads."""
import hashlib
import json
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid5, NAMESPACE_URL
from pydantic import BaseModel, Field
from fastapi import HTTPException
from delivery_fees import driving_meters

EXTRA_STOPS_PREFIX = '__extra_stops__:'
class StopRate(BaseModel):
    free_miles: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    stop_fee: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    per_mile: Decimal = Field(ge=0, max_digits=10, decimal_places=2)

class ExtraStopsCard(BaseModel):
    enabled: bool = False
    pickup: StopRate
    delivery: StopRate

def stops_card(services):
    for service in services:
        if service.comments.startswith(EXTRA_STOPS_PREFIX):
            return ExtraStopsCard.model_validate_json(service.comments[len(EXTRA_STOPS_PREFIX):])
    return None

def stop_price(rule, meters):
    exact = Decimal(meters) / Decimal('1609.344')
    billable = max(Decimal(0), exact - rule.free_miles)
    # Pickup stops within their allowance are entirely free. A zero allowance
    # means the delivery stop fee applies even to a zero-mile route.
    amount = Decimal(0) if rule.free_miles > 0 and exact <= rule.free_miles else rule.stop_fee + billable * rule.per_mile
    return {'miles': float(exact.quantize(Decimal('.01'), rounding=ROUND_HALF_UP)),
            'billable_miles': float(billable.quantize(Decimal('.01'), rounding=ROUND_HALF_UP)),
            'total': float(amount.quantize(Decimal('.01'), rounding=ROUND_HALF_UP))}

def route_revision(origin, address):
    return hashlib.sha256(json.dumps([origin.strip().lower(),address.strip().lower()]).encode()).hexdigest()

def stops_state(job, db):
    from routes.leads import _read_job_route
    state = json.loads(job.customer_packing_package or '{}').get('extra_stops', {})
    _, addresses, _ = _read_job_route(db,job)
    typed = json.loads(job.stop_types or '[]')
    old = {row['id']:row for group in state.values() for row in group.get('stops',[])}
    result = {}
    for location in ('pickup','delivery'):
        rows=[]
        for i,address in enumerate(addresses):
            kind=typed[i].get('type') if i<len(typed) and typed[i].get('address')==address else None
            if kind != location: continue
            key=str(uuid5(NAMESPACE_URL, f'extra-stop:{job.id}:{location}:{address}'))
            rows.append({**old.get(key,{}),'id':key,'address':address})
        result[location]={'answer':True if rows else state.get(location,{}).get('answer'), 'stops':rows}
    return result

def option(lead,job,db,plan=None,refresh=False):
    if plan is None:
        from routes.pricing import infer_job_move_type
        _,plan=infer_job_move_type(lead,job,db)
    card=stops_card(plan.services) if plan else None
    if not card or not card.enabled:return None
    state=stops_state(job,db)
    locations=[]
    for location in ('pickup','delivery'):
        origin=getattr(job,location+'_zip') or ''
        rule=getattr(card,location)
        rows=[]
        for row in state[location]['stops']:
            revision=route_revision(origin,row['address'])
            meters=row.get('meters') if row.get('revision')==revision else None
            if meters is None and refresh:
                if not origin.strip(): raise HTTPException(422,'Enter the main '+location+' address first.')
                try: meters=driving_meters(origin,row['address'])
                except HTTPException as exc: raise HTTPException(exc.status_code,'Could not calculate driving miles for extra '+location+' stop: '+row['address']+'. '+str(exc.detail)) from exc
                row.update(meters=meters,revision=revision)
            priced=stop_price(rule,meters) if meters is not None else {'miles':None,'billable_miles':None,'total':None}
            rows.append({**row,**priced})
        locations.append({'location':location,'origin':origin,'answer':state[location]['answer'],'stops':rows,**{k:float(v) for k,v in rule.model_dump().items()}})
    if refresh:
        selection=json.loads(job.customer_packing_package or '{}');selection['extra_stops']=state
        job.customer_packing_package=json.dumps(selection)
    return {'locations':locations}

def add_charges(lead,job,db,plan=None):
    from models import LeadJobCharge
    data=option(lead,job,db,plan,refresh=True)
    total=Decimal(0)
    for group in data['locations'] if data else []:
        for i,row in enumerate(group['stops']):
            amount=Decimal(str(row['total']))
            name='Extra '+group['location']+' stop '+str(i+1)
            description=f"{row['address']}; {row['miles']} driving miles from {group['origin']}. {group['free_miles']:g} miles free; ${group['stop_fee']:.2f} per chargeable stop + ${group['per_mile']:.2f} per mile beyond the allowance."
            db.add(LeadJobCharge(id='extra-stop:'+row['id'],job_id=job.id,name=name,description=description,subtotal=amount,discount_amount=0,total_cost=amount,sort_order=2900+i))
            total+=amount
    return total

def sync_charges(lead,job,db):
    from models import LeadJobCharge,PublicMoveAccess
    # Resolve new routes before deleting any saved charge, including unpriced jobs.
    option(lead,job,db,refresh=True)
    if job.price is None:return
    old=db.query(LeadJobCharge).filter(LeadJobCharge.job_id==job.id,LeadJobCharge.id.like('extra-stop:%')).all()
    previous=sum((row.total_cost for row in old),Decimal(0))
    for row in old:db.delete(row)
    db.flush()
    delta=add_charges(lead,job,db)-previous
    job.price+=delta
    for access in db.query(PublicMoveAccess).filter_by(job_id=job.id).all():
        if access.published_price is not None:access.published_price+=delta
    from routes.leads import _refresh_lead_estimated_total
    _refresh_lead_estimated_total(lead.id,db)
