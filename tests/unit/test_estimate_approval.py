"""A rep's approval is cleared by any saved change to what the estimate shows, and only by those."""
import json
from decimal import Decimal
from pathlib import Path
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
import estimate_approval  # noqa: F401  The approval hook.
from models import Base, Company, Lead, LeadContact, LeadJob, LeadJobCharge, LeadLiveSwitch, LeadPayment

CHANGES = {
    'price line': (lambda db: setattr(db.get(LeadJobCharge, 'c'), 'total_cost', Decimal('80')), True),
    'answer or discount': (lambda db: setattr(db.get(LeadJob, 'j'), 'customer_packing_package', '{"stairs": {"pickup": 2}}'), True),
    'customer notes': (lambda db: setattr(db.get(LeadJob, 'j'), 'customer_notes', 'new note'), True),
    'move date': (lambda db: setattr(db.get(LeadJob, 'j'), 'move_date', '2026-12-01'), True),
    'phone': (lambda db: setattr(db.get(Lead, 'l'), 'phone', '2405550199'), True),
    'extra phone': (lambda db: db.add(LeadContact(lead_id='l', kind='phone', value='3015550100', normalized='3015550100')), True),
    'inventory report': (lambda db: setattr(db.get(LeadLiveSwitch, 'l'), 'details', json.dumps({'last_spark_id': 'r2'})), True),
    'company phone': (lambda db: setattr(db.get(Company, 'co'), 'phone', '2025550000'), True),
    'payment': (lambda db: db.add(LeadPayment(lead_id='l', source='crm', amount=100)), False),
    'internal notes': (lambda db: setattr(db.get(LeadJob, 'j'), 'notes', 'gate code'), False),
    'foreman notes': (lambda db: setattr(db.get(LeadJob, 'j'), 'foreman_notes', 'bring dolly'), False),
    'crew': (lambda db: setattr(db.get(LeadJob, 'j'), 'crew_size', 3), False),
}


@pytest.mark.parametrize('name', CHANGES)
def test_only_changes_the_estimate_shows_clear_the_approval(name):
    change, clears = CHANGES[name]
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([Company(id='co', name='Co'), Lead(id='l', full_name='C', company_id='co', phone='2405550100'),
                    LeadJob(id='j', lead_id='l', job_order=1, company_id='co', customer_packing_package='{}', customer_notes=''),
                    LeadJobCharge(id='c', job_id='j', name='Stairs', subtotal=75, total_cost=75, source='crm'),
                    LeadLiveSwitch(lead_id='l', details=json.dumps({'last_spark_id': 'r1'}))])
        db.commit()
        db.get(LeadJob, 'j').estimate_approved_id = 'copy'
        db.commit()
        change(db)
        db.commit()
        db.expire_all()
        assert (db.get(LeadJob, 'j').estimate_approved_id is None) == clears
    engine.dispose()
