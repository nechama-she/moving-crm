"""Book-scoped local rate settings and hourly estimates."""
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from auth import get_current_user, require_admin
from database import get_db
from models import AppSetting, User, Company, LocalPricingRoute
from local_pricing import LocalSettings, LocalCalculation, calculate_local, parse_local_route_region
from routes.pricing import _plan_or_404

router = APIRouter(prefix='/api/pricing/local', tags=['Local pricing'])


def load_settings(plan, db):
    row = db.get(AppSetting, f'local_pricing:{plan.id}')
    if row:
        return LocalSettings.model_validate_json(row.value)
    if 'gorilla' in plan.company_name.lower() and plan.name.strip().lower() == 'east':
        return LocalSettings()
    return None


def load_routes(company_id: str, db: Session) -> list[LocalPricingRoute]:
    if not company_id:
        return []
    return (
        db.query(LocalPricingRoute)
        .filter(LocalPricingRoute.company_id == company_id)
        .order_by(LocalPricingRoute.sort_order, LocalPricingRoute.created_at)
        .all()
    )


class LocalRouteInput(BaseModel):
    pickup: str = Field(min_length=2, max_length=64)
    delivery: str = Field(min_length=2, max_length=64)


class LocalSettingsPayload(LocalSettings):
    routes: list[LocalRouteInput] = Field(default_factory=list, max_length=500)


def _plan_and_company(plan_id: str, user: User, db: Session):
    plan = _plan_or_404(db, user, plan_id)
    if not plan.company_id:
        raise HTTPException(400, 'Pricing book is missing company')
    return plan


def _route_or_404(route_id: str, company_id: str, db: Session) -> LocalPricingRoute:
    row = db.get(LocalPricingRoute, route_id)
    if not row or row.company_id != company_id:
        raise HTTPException(404, 'Route not found')
    return row


@router.get('/{plan_id}')
def get_settings(plan_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    plan = _plan_or_404(db, user, plan_id)
    company = db.get(Company, plan.company_id) if plan.company_id else None
    return {
        'settings': load_settings(plan, db),
        'routes': [{'id': row.id, 'pickup': row.pickup, 'delivery': row.delivery} for row in load_routes(plan.company_id, db)],
        'office_address': company.office_address if company else '',
        'company_id': plan.company_id,
    }


@router.put('/{plan_id}')
def save_settings(plan_id: str, body: LocalSettingsPayload, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    plan = _plan_and_company(plan_id, user, db)
    key = f'local_pricing:{plan_id}'
    settings = LocalSettings.model_validate(body.model_dump())
    row = db.get(AppSetting, key)
    if row:
        row.value = settings.model_dump_json()
    else:
        db.add(AppSetting(key=key, value=settings.model_dump_json()))

    db.query(LocalPricingRoute).filter(LocalPricingRoute.company_id == plan.company_id).delete()
    for index, route in enumerate(body.routes):
        # Validate route strings but store them as-is (trimmed).
        parse_local_route_region(route.pickup)
        parse_local_route_region(route.delivery)
        db.add(LocalPricingRoute(
            id=str(uuid4()),
            company_id=plan.company_id,
            pickup=route.pickup.strip(),
            delivery=route.delivery.strip(),
            sort_order=index,
        ))

    db.commit()
    return {
        'settings': settings,
        'routes': [{'pickup': row.pickup, 'delivery': row.delivery} for row in load_routes(plan.company_id, db)],
    }


class BookCalculation(LocalCalculation):
    lead_id: str | None = None
    job_id: str | None = None
    pickup: str = Field(default='', max_length=1000)
    delivery: str = Field(default='', max_length=1000)


@router.get('/{plan_id}/routes')
def list_routes(plan_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    plan = _plan_and_company(plan_id, user, db)
    return {'routes': [row.to_dict() for row in load_routes(plan.company_id, db)]}


@router.post('/{plan_id}/routes')
def create_route(plan_id: str, body: LocalRouteInput, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    plan = _plan_and_company(plan_id, user, db)
    pickup = body.pickup.strip()
    delivery = body.delivery.strip()
    parse_local_route_region(pickup)
    parse_local_route_region(delivery)
    exists = db.query(LocalPricingRoute).filter(
        LocalPricingRoute.company_id == plan.company_id,
        LocalPricingRoute.pickup == pickup,
        LocalPricingRoute.delivery == delivery,
    ).first()
    if exists:
        raise HTTPException(409, 'Route already exists')
    next_sort = db.query(func.max(LocalPricingRoute.sort_order)).filter(LocalPricingRoute.company_id == plan.company_id).scalar()
    row = LocalPricingRoute(
        id=str(uuid4()),
        company_id=plan.company_id,
        pickup=pickup,
        delivery=delivery,
        sort_order=int(next_sort or -1) + 1,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {'route': row.to_dict(), 'routes': [entry.to_dict() for entry in load_routes(plan.company_id, db)]}


@router.put('/{plan_id}/routes/{route_id}')
def update_route(plan_id: str, route_id: str, body: LocalRouteInput, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    plan = _plan_and_company(plan_id, user, db)
    row = _route_or_404(route_id, plan.company_id, db)
    pickup = body.pickup.strip()
    delivery = body.delivery.strip()
    parse_local_route_region(pickup)
    parse_local_route_region(delivery)
    duplicate = db.query(LocalPricingRoute).filter(
        LocalPricingRoute.company_id == plan.company_id,
        LocalPricingRoute.pickup == pickup,
        LocalPricingRoute.delivery == delivery,
        LocalPricingRoute.id != route_id,
    ).first()
    if duplicate:
        raise HTTPException(409, 'Route already exists')
    row.pickup = pickup
    row.delivery = delivery
    db.commit()
    db.refresh(row)
    return {'route': row.to_dict(), 'routes': [entry.to_dict() for entry in load_routes(plan.company_id, db)]}


@router.delete('/{plan_id}/routes/{route_id}')
def delete_route(plan_id: str, route_id: str, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    plan = _plan_and_company(plan_id, user, db)
    row = _route_or_404(route_id, plan.company_id, db)
    db.delete(row)
    db.flush()
    rows = load_routes(plan.company_id, db)
    for index, item in enumerate(rows):
        item.sort_order = index
    db.commit()
    return {'ok': True, 'routes': [entry.to_dict() for entry in rows]}


def book_travel(plan, db, pickup, delivery):
    from travel_routes import estimate_travel
    company = db.get(Company, plan.company_id) if plan.company_id else None
    if not company or not (company.office_address or '').strip():
        raise HTTPException(400, 'Add the company office address in Company Management before calculating travel.')
    return estimate_travel(company.office_address, pickup, delivery)


def calculate_book_price(plan, body, db, pickup, delivery):
    """Single complete local quote path for the calculator and report automation."""
    settings = load_settings(plan, db)
    if settings is None:
        raise HTTPException(400, 'Set up Local pricing for this book first.')
    travel = book_travel(plan, db, pickup, delivery)
    values = body.model_dump(include=set(LocalCalculation.model_fields))
    values.update(office_to_pickup_miles=travel['office_to_pickup_miles'],
                  delivery_to_office_miles=travel['delivery_to_office_miles'])
    quote = calculate_local(settings, LocalCalculation.model_validate(values))
    if not quote['travel_complete']:
        raise HTTPException(422, 'Both travel distances are required before pricing this move.')
    return quote


@router.post('/{plan_id}/calculate')
def calculate(plan_id: str, body: BookCalculation, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    plan = _plan_or_404(db, user, plan_id)
    pickup, delivery = calculation_addresses(plan, body, user, db)
    return calculate_book_price(plan, body, db, pickup, delivery)


class TravelRequest(BaseModel):
    lead_id: str | None = None
    job_id: str | None = None
    pickup: str = Field(default='', max_length=1000)
    delivery: str = Field(default='', max_length=1000)


def calculation_addresses(plan, body, user, db):
    from routes.leads import _get_job_or_404
    if body.lead_id or body.job_id:
        if not body.lead_id or not body.job_id:
            raise HTTPException(400, 'Both lead and job are required')
        job = _get_job_or_404(body.lead_id, body.job_id, user, db)
        if job.company_id != plan.company_id:
            raise HTTPException(400, 'Select a pricing book for this job company')
        return job.pickup_zip, job.delivery_zip
    return body.pickup, body.delivery


@router.post('/{plan_id}/travel')
def travel_times(plan_id: str, body: TravelRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    plan = _plan_or_404(db, user, plan_id)
    pickup, delivery = calculation_addresses(plan, body, user, db)
    return book_travel(plan, db, pickup, delivery)
