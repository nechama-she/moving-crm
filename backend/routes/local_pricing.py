"""Book-scoped local rate settings and hourly estimates."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from auth import get_current_user, require_admin
from database import get_db
from models import AppSetting, User
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
    return {'settings': load_settings(plan, db)}


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


@router.post('/{plan_id}/calculate')
def calculate(plan_id: str, body: LocalCalculation, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    plan = _plan_or_404(db, user, plan_id)
    settings = load_settings(plan, db)
    if settings is None:
        raise HTTPException(400, 'Set up Local pricing for this book first.')
    return calculate_local(settings, body)
