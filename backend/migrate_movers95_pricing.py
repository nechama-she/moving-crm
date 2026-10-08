"""One-time copy of Gorilla Haulers East into Movers 95 (dry-run by default)."""
import argparse
import json
from uuid import uuid4

from sqlalchemy import func
from models import AppSetting, Company, LocalPricingRoute, PricingPlan


PICKUP_STATES = ['MD', 'VA', 'DC', 'DE', 'PA']
MARKER = 'migration:movers95-gorilla-east-v1'


def copy_pricing(db):
    """Caller owns the transaction; update the existing Movers 95 book once."""
    if db.get(AppSetting, MARKER):
        return {'status': 'already applied'}
    source_company = db.query(Company).filter(func.lower(func.trim(Company.name)) == 'gorilla haulers').one_or_none()
    target_company = db.query(Company).filter(func.lower(func.trim(Company.name)) == 'movers 95').with_for_update().one_or_none()
    if source_company is None or target_company is None:
        return {'status': 'skipped: companies not present'}
    if db.get(AppSetting, MARKER):
        return {'status': 'already applied'}
    source = db.query(PricingPlan).filter(
        PricingPlan.company_id == source_company.id,
        func.lower(func.trim(PricingPlan.name)) == 'east').with_for_update().one()
    targets = db.query(PricingPlan).filter_by(company_id=target_company.id).with_for_update().all()
    if len(targets) > 1:
        raise ValueError('Movers 95 has multiple pricing books; cannot choose a destination safely.')
    excluded = {'id', 'company_id', 'company_name', 'source_key', 'name', 'pickup_regions', 'created_at', 'updated_at'}
    values = {column.name: getattr(source, column.name) for column in PricingPlan.__table__.columns
              if column.name not in excluded}
    target = targets[0] if targets else PricingPlan(id=str(uuid4()), company_id=target_company.id,
        company_name=target_company.name, source_key=MARKER)
    for key, value in values.items():
        setattr(target, key, value)
    target.name = 'MD, VA, DC, DE, PA'
    target.pickup_regions = json.dumps([{'state': state, 'zip_codes': []} for state in PICKUP_STATES])
    db.add(target)
    counts = {}
    for relation in ('rules', 'rates', 'services'):
        copied = []
        for row in getattr(source, relation):
            fields = {column.name: getattr(row, column.name) for column in row.__table__.columns
                      if column.name not in {'id', 'plan_id'}}
            copied.append(type(row)(**fields, id=str(uuid4())))
        setattr(target, relation, copied)
        counts[relation] = len(copied)

    # East has effective local defaults even when no settings row was saved.
    from local_pricing import LocalSettings
    local = db.get(AppSetting, f'local_pricing:{source.id}')
    local_key = f'local_pricing:{target.id}'
    target_local = db.get(AppSetting, local_key) or AppSetting(key=local_key)
    target_local.value = local.value if local else LocalSettings().model_dump_json()
    db.add(target_local)
    db.query(LocalPricingRoute).filter_by(company_id=target_company.id).delete(synchronize_session=False)
    db.flush()
    routes = db.query(LocalPricingRoute).filter_by(company_id=source_company.id).all()
    for route in routes:
        db.add(LocalPricingRoute(company_id=target_company.id, pickup=route.pickup,
            delivery=route.delivery, sort_order=route.sort_order))
    result = dict(status='copied', source_plan_id=source.id, target_plan_id=target.id,
        pickup_states=PICKUP_STATES, local_routes=len(routes), **counts)
    db.add(AppSetting(key=MARKER, value=json.dumps(result)))
    db.flush()
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Commit the copy; otherwise roll it back.')
    args = parser.parse_args()
    from database import SessionLocal
    with SessionLocal() as db:
        result = copy_pricing(db)
        if args.apply:
            db.commit()
        else:
            db.rollback()
        print(json.dumps({'committed': args.apply, **result}, indent=2))
