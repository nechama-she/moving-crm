"""Book-scoped local rate settings and hourly estimates."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from auth import get_current_user, require_admin
from database import get_db
from models import AppSetting, User, Company
from local_pricing import LocalSettings, LocalCalculation, calculate_local
from routes.pricing import _plan_or_404

router = APIRouter(prefix='/api/pricing/local', tags=['Local pricing'])


def load_settings(plan, db):
    row = db.get(AppSetting, f'local_pricing:{plan.id}')
    if row:
        return LocalSettings.model_validate_json(row.value)
    if 'gorilla' in plan.company_name.lower() and plan.name.strip().lower() == 'east':
        return LocalSettings()
    return None


@router.get('/{plan_id}')
def get_settings(plan_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    plan = _plan_or_404(db, user, plan_id)
    company = db.get(Company, plan.company_id) if plan.company_id else None
    return {'settings': load_settings(plan, db), 'office_address': company.office_address if company else '', 'company_id': plan.company_id}


@router.put('/{plan_id}')
def save_settings(plan_id: str, body: LocalSettings, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    _plan_or_404(db, user, plan_id)
    key = f'local_pricing:{plan_id}'
    row = db.get(AppSetting, key)
    if row:
        row.value = body.model_dump_json()
    else:
        db.add(AppSetting(key=key, value=body.model_dump_json()))
    db.commit()
    return {'settings': body}


class BookCalculation(LocalCalculation):
    lead_id: str | None = None
    job_id: str | None = None
    pickup: str = Field(default='', max_length=1000)
    delivery: str = Field(default='', max_length=1000)


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
