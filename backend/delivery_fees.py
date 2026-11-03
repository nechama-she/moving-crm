"""Pricing-book delivery fees based on Google driving-route mileage."""
import hashlib
import json
import os
import re
from decimal import Decimal, ROUND_HALF_UP
import httpx
from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator
from shuttle import ShuttleArea, area_matches, zip_bounds
from zip_state import delivery_location

DELIVERY_FEE_PREFIX = '__delivery_mileage__:'
ORIGIN_FEE_PREFIX = '__origin_mileage__:'


class DeliveryFeeRule(ShuttleArea):
    origin_zip: str
    rate_per_mile: Decimal = Field(ge=0, max_digits=10, decimal_places=2)

    @field_validator('origin_zip')
    @classmethod
    def valid_origin(cls, value):
        value = value.strip()
        if not re.fullmatch(r'\d{5}', value):
            raise ValueError('Enter a five-digit starting ZIP code')
        return value


class DeliveryFeeCard(BaseModel):
    enabled: bool = False
    rules: list[DeliveryFeeRule] = Field(default_factory=list, max_length=200)


FEE_KINDS = {ORIGIN_FEE_PREFIX: 'origin', DELIVERY_FEE_PREFIX: 'delivery'}


def delivery_fee_card(plan, prefix=DELIVERY_FEE_PREFIX):
    """The plan's origin or destination fees, read from the pricing_mileage_fee tables."""
    row = next((fee for fee in plan.mileage_fees if fee.kind == FEE_KINDS[prefix]), None)
    if row is None:
        return None
    return DeliveryFeeCard(enabled=row.enabled, rules=[
        DeliveryFeeRule(state=rule.state, zip_codes=sorted(zip_row.zip_code for zip_row in rule.zips),
                        origin_zip=rule.origin_zip, rate_per_mile=rule.rate_per_mile)
        for rule in sorted(row.rules, key=lambda rule: rule.position)])


def fee_service_row(plan, prefix):
    """The card as the pricing API presents it: a service row holding its settings."""
    card = delivery_fee_card(plan, prefix)
    if card is None:
        return None
    config = {'enabled': card.enabled, 'rules': [
        {'state': rule.state, 'zip_codes': rule.zip_codes, 'origin_zip': rule.origin_zip,
         'rate_per_mile': format(rule.rate_per_mile.normalize(), 'f')} for rule in card.rules]}
    kind = FEE_KINDS[prefix]
    return {'id': f'{kind}-fees:{plan.id}', 'name': 'Origin fees' if kind == 'origin' else 'Destination fees',
            'rate_text': '', 'comments': prefix + json.dumps(config), 'sort_order': -1}


def save_fee_card(plan, prefix, card):
    """Replace the plan's origin or destination fees; None removes them."""
    from models import PricingMileageFee, PricingMileageFeeRule, PricingMileageFeeZip
    kind = FEE_KINDS[prefix]
    row = next((fee for fee in plan.mileage_fees if fee.kind == kind), None)
    if card is None:
        if row is not None:
            plan.mileage_fees.remove(row)
        return
    if row is None:
        row = PricingMileageFee(kind=kind)
        plan.mileage_fees.append(row)
    row.enabled = card.enabled
    # Rules are kept by position and ZIP rows by value, so no primary key is reused mid-save.
    existing = {rule.position: rule for rule in row.rules}
    row.rules[:] = [existing.get(position) or PricingMileageFeeRule(kind=kind, position=position)
                    for position in range(len(card.rules))]
    for saved, rule in zip(row.rules, card.rules):
        saved.state, saved.origin_zip, saved.rate_per_mile = rule.state, rule.origin_zip, rule.rate_per_mile
        saved.zips[:] = [zip_row for zip_row in saved.zips if zip_row.zip_code in rule.zip_codes]
        kept = {zip_row.zip_code for zip_row in saved.zips}
        saved.zips.extend(PricingMileageFeeZip(kind=kind, position=saved.position, zip_code=zip_code)
                          for zip_code in rule.zip_codes if zip_code not in kept)


def migrate_fee_cards(connection):
    """Move each plan's origin and destination fee cards from pricing_services JSON rows into tables, once."""
    from sqlalchemy import inspect, text
    from models import PricingMileageFee, PricingMileageFeeRule, PricingMileageFeeZip
    if inspect(connection).has_table(PricingMileageFee.__tablename__):
        return 0
    for model in (PricingMileageFee, PricingMileageFeeRule, PricingMileageFeeZip):
        model.__table__.create(connection)
    moved = set()
    for prefix, kind in FEE_KINDS.items():
        rows = connection.execute(text(
            "SELECT id, plan_id, comments FROM pricing_services WHERE comments LIKE :prefix ORDER BY plan_id, sort_order"),
            {'prefix': prefix + '%'}).all()
        for service_id, plan_id, comments in rows:
            # Pricing used the first card of a plan; any later copies were never read.
            if (plan_id, kind) not in moved:
                card = DeliveryFeeCard.model_validate_json(comments[len(prefix):])
                connection.execute(PricingMileageFee.__table__.insert().values(plan_id=plan_id, kind=kind, enabled=card.enabled))
                for position, rule in enumerate(card.rules):
                    connection.execute(PricingMileageFeeRule.__table__.insert().values(
                        plan_id=plan_id, kind=kind, position=position, state=rule.state,
                        origin_zip=rule.origin_zip, rate_per_mile=rule.rate_per_mile))
                    for zip_code in rule.zip_codes:
                        connection.execute(PricingMileageFeeZip.__table__.insert().values(
                            plan_id=plan_id, kind=kind, position=position, zip_code=zip_code))
                moved.add((plan_id, kind))
            connection.execute(text('DELETE FROM pricing_services WHERE id = :id'), {'id': service_id})
    return len(moved)


def matching_rule(card, address):
    if not card or not card.enabled:
        return None
    state, zip_code = delivery_location(address)
    matches = [rule for rule in card.rules if area_matches([rule], state, zip_code)]
    # Narrower ZIP coverage wins; stable card order breaks equal-specificity ties.
    def width(rule):
        return min((high-low for low, high in map(zip_bounds, rule.zip_codes)
                    if zip_code and low <= int(zip_code) <= high), default=100000)
    return min(matches, key=width) if matches else None


def driving_meters(origin_zip, destination):
    from config import get_config
    key = str(get_config().get('GOOGLE_MAPS_SERVER_KEY') or os.getenv('GOOGLE_MAPS_SERVER_KEY', '')).strip()
    if not key:
        raise HTTPException(503, 'Google Maps routing is not configured. The mileage fee could not be calculated.')
    try:
        response = httpx.post('https://routes.googleapis.com/directions/v2:computeRoutes',
            headers={'X-Goog-Api-Key': key, 'X-Goog-FieldMask': 'routes.distanceMeters'},
            json={'origin': {'address': f'{origin_zip}, USA'},
                  'destination': {'address': destination + ', USA'},
                  'travelMode': 'DRIVE', 'routingPreference': 'TRAFFIC_UNAWARE',
                  'computeAlternativeRoutes': False}, timeout=10)
        response.raise_for_status()
        routes = response.json().get('routes') or []
        if not routes:
            raise HTTPException(422, 'Google Maps could not find a driving route. Check the customer address.')
        meters = routes[0].get('distanceMeters')
        if type(meters) is not int or meters < 0:
            raise ValueError('Invalid route distance')
        return meters
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        raise HTTPException(502, 'Google Maps could not calculate the mileage fee. Please retry; no approximate mileage was used.') from None


def route_revision(origin_zip, address):
    return hashlib.sha256(json.dumps([origin_zip, address.strip().lower(), 'DRIVE']).encode()).hexdigest()


def browser_fee_routes(lead, job, db):
    from routes.pricing import infer_job_move_type
    move_type, plan = infer_job_move_type(lead, job, db)
    if not plan or (move_type or '').lower() == 'local':
        return []
    selection = json.loads(job.customer_packing_package or '{}')
    routes = []
    for kind, address, prefix in [('origin', job.pickup_zip or '', ORIGIN_FEE_PREFIX),
                                  ('delivery', job.delivery_zip or '', DELIVERY_FEE_PREFIX)]:
        rule = matching_rule(delivery_fee_card(plan, prefix), address)
        if not rule:
            continue
        revision = route_revision(rule.origin_zip, address)
        saved = selection.get(kind + '_route') or {}
        meters = saved.get('meters') if saved.get('revision') == revision else None
        routes.append({'kind': kind, 'origin': rule.origin_zip, 'destination': address,
                       'revision': revision, 'meters': meters if type(meters) is int and meters >= 0 else None})
    return routes


def delivery_fee(plan, address, saved=None, *, prefix=DELIVERY_FEE_PREFIX, endpoint="delivery"):
    rule = matching_rule(delivery_fee_card(plan, prefix), address)
    if not rule:
        return None
    revision = route_revision(rule.origin_zip, address)
    # Reuse this estimate's route basis until either endpoint changes. No polling.
    saved = saved or {}
    meters = saved.get('meters') if saved.get('revision') == revision else None
    if type(meters) is not int or meters < 0:
        meters = driving_meters(rule.origin_zip, address)
    miles = (Decimal(meters) / Decimal('1609.344')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    amount = (miles * rule.rate_per_mile).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return {'revision': revision, 'meters': meters, 'miles': str(miles), 'origin_zip': rule.origin_zip,
            'amount': amount, 'description': f'{miles:,.2f} driving miles from ZIP {rule.origin_zip} to {endpoint} at ${rule.rate_per_mile:,.2f} / mile (Google Maps)'}


def origin_fee_card(plan):
    return delivery_fee_card(plan, ORIGIN_FEE_PREFIX)


def origin_fee(plan, address, saved=None):
    return delivery_fee(plan, address, saved, prefix=ORIGIN_FEE_PREFIX, endpoint="pickup")
