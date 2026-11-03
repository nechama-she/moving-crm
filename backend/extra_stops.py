from charge_errors import isolated_charge, error_description
"""Extra-stop pricing. Saved route distances avoid network requests on page reads."""
import hashlib
import base64
import json
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
from uuid import UUID, uuid5, NAMESPACE_URL
from pydantic import BaseModel, Field
from fastapi import HTTPException

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

LOCATION_FIELDS = ('free_miles', 'stop_fee', 'per_mile')

def plan_stops_card(plan):
    """The plan's additional stop pricing, read from pricing_extra_stops."""
    row = plan.extra_stops
    if row is None:
        return None
    return ExtraStopsCard(enabled=row.enabled, **{location: StopRate(**{field: getattr(row, f'{location}_{field}') for field in LOCATION_FIELDS})
                                                  for location in ('pickup', 'delivery')})

def stops_service_row(plan):
    """The card as the pricing API presents it: a service row holding its settings."""
    card = plan_stops_card(plan)
    if card is None:
        return None
    number = lambda value: format(value.normalize(), 'f')
    config = {'enabled': card.enabled, **{location: {field: number(getattr(getattr(card, location), field)) for field in LOCATION_FIELDS}
                                          for location in ('pickup', 'delivery')}}
    return {'id': f'extra-stops:{plan.id}', 'name': 'Additional stops', 'rate_text': '',
            'comments': EXTRA_STOPS_PREFIX + json.dumps(config), 'sort_order': -1}

def save_stops_card(plan, card):
    """Replace the plan's additional stop pricing; None removes it."""
    from models import PricingExtraStops
    if card is None:
        plan.extra_stops = None
        return
    row = plan.extra_stops or PricingExtraStops()
    row.enabled = card.enabled
    for location in ('pickup', 'delivery'):
        for field in LOCATION_FIELDS:
            setattr(row, f'{location}_{field}', getattr(getattr(card, location), field))
    plan.extra_stops = row

def migrate_stops_cards(connection):
    """Move each plan's card from its pricing_services JSON row into pricing_extra_stops, once."""
    from sqlalchemy import inspect, text
    from models import PricingExtraStops
    if inspect(connection).has_table(PricingExtraStops.__tablename__):
        return 0
    PricingExtraStops.__table__.create(connection)
    moved = set()
    rows = connection.execute(text(
        "SELECT id, plan_id, comments FROM pricing_services WHERE comments LIKE :prefix ORDER BY plan_id, sort_order"),
        {'prefix': EXTRA_STOPS_PREFIX + '%'}).all()
    for service_id, plan_id, comments in rows:
        # Pricing used the first card of a plan; any later copies were never read.
        if plan_id not in moved:
            card = ExtraStopsCard.model_validate_json(comments[len(EXTRA_STOPS_PREFIX):])
            connection.execute(PricingExtraStops.__table__.insert().values(
                plan_id=plan_id, enabled=card.enabled,
                **{f'{location}_{field}': getattr(getattr(card, location), field)
                   for location in ('pickup', 'delivery') for field in LOCATION_FIELDS}))
            moved.add(plan_id)
        connection.execute(text('DELETE FROM pricing_services WHERE id = :id'), {'id': service_id})
    return len(moved)

def stop_price(rule, meters):
    exact = Decimal(meters) / Decimal('1609.344')
    miles = exact.to_integral_value(rounding=ROUND_CEILING)
    billable = max(Decimal(0), miles - rule.free_miles)
    # Pickup stops within their allowance are entirely free. A zero allowance
    # means the delivery stop fee applies even to a zero-mile route.
    amount = Decimal(0) if rule.free_miles > 0 and miles <= rule.free_miles else rule.stop_fee + billable * rule.per_mile
    return {'miles': float(miles),
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
    card=plan_stops_card(plan) if plan else None
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
            priced=stop_price(rule,meters) if meters is not None else {'miles':None,'billable_miles':None,'total':None}
            rows.append({**row,**priced})
        locations.append({'location':location,'origin':origin,'answer':state[location]['answer'],'stops':rows,**{k:float(v) for k,v in rule.model_dump().items()}})
    if refresh:
        selection=json.loads(job.customer_packing_package or '{}');selection['extra_stops']=state
        job.customer_packing_package=json.dumps(selection)
    return {'locations':locations}

@isolated_charge('Extra stops')
def add_charges(lead,job,db,plan=None,refresh=True):
    from models import LeadJobCharge
    data=option(lead,job,db,plan,refresh=refresh)
    total=Decimal(0)
    for group in data['locations'] if data else []:
        for i,row in enumerate(group['stops']):
            amount=Decimal(str(row['total'] or 0))
            name='Extra '+group['location']+' stop '+str(i+1)
            description=f"{row['address']}; {row['miles']} driving miles from {group['origin']}. {group['free_miles']:g} miles free; ${group['stop_fee']:.2f} per chargeable stop + ${group['per_mile']:.2f} per mile beyond the allowance."
            if row['total'] is None:
                description = error_description(ValueError(f"Driving distance unavailable for {row['address']}"))
            charge_id = 'extra-stop:' + base64.urlsafe_b64encode(UUID(row['id']).bytes).decode().rstrip('=')
            db.add(LeadJobCharge(id=charge_id,job_id=job.id,name=name,description=description,subtotal=amount,discount_amount=0,total_cost=amount,sort_order=2900+i))
            total+=amount
    return total

def sync_charges(lead,job,db,refresh=True):
    from models import LeadJobCharge,PublicMoveAccess
    # Resolve routes before updating any saved charge.
    if job.price is None:return
    data=option(lead,job,db,refresh=refresh)
    old=db.query(LeadJobCharge).filter(LeadJobCharge.job_id==job.id,LeadJobCharge.id.like('extra-stop:%')).all()
    previous=sum((row.total_cost for row in old),Decimal(0))
    from charge_updates import ChargeUpdates
    updates=ChargeUpdates(db,old)
    delta=add_charges(lead,job,updates,refresh=refresh)-previous
    updates.finish()
    job.price+=delta
    for access in db.query(PublicMoveAccess).filter_by(job_id=job.id).all():
        if access.published_price is not None:access.published_price+=delta
    from routes.leads import _refresh_lead_estimated_total
    _refresh_lead_estimated_total(lead.id,db)
