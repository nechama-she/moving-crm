"""Pricing books: an admin adds an empty one for a company, and deletes one with everything in it."""
import os
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT)]
os.environ.setdefault('JWT_SECRET', 'test-only-secret-with-at-least-32-characters')


def test_add_then_delete_a_pricing_book_with_its_rates():
    from models import Base, Company, PricingPlan, PricingRate
    from routes import pricing
    engine = create_engine('sqlite://')
    # As in the database: a book's rows are deleted with it.
    event.listen(engine, 'connect', lambda connection, _: connection.execute('PRAGMA foreign_keys=ON'))
    Base.metadata.create_all(engine)
    admin = SimpleNamespace(role='admin', id='admin')
    with Session(engine) as db:
        db.add(Company(id='gorilla', name='Gorilla Haulers'))
        db.add(PricingPlan(id='old', company_id='gorilla', company_name='Gorilla Haulers', name='OLD', source_key='import:old', sort_order=4))
        db.commit()
        row = pricing.create_pricing_plan(pricing.NewPricingPlan(company_id='gorilla', name='  MD, VA, DC '), admin, db)
        new = db.get(PricingPlan, row['id'])
        # Named for its area, after the company's other books, empty.
        assert (row['company_name'], row['name'], new.sort_order, new.rates) == ('Gorilla Haulers', 'MD, VA, DC', 5, [])
        with pytest.raises(HTTPException) as error:
            pricing.create_pricing_plan(pricing.NewPricingPlan(company_id='nobody', name='Area'), admin, db)
        assert error.value.status_code == 404
        db.add(PricingRate(plan_id='old', destination='TX', band_label='0-500'))
        db.commit()
        assert pricing.delete_pricing_plan('old', admin, db) == {'deleted': 'old'}
        db.expire_all()
        assert db.get(PricingPlan, 'old') is None and db.query(PricingRate).count() == 0
        assert db.get(PricingPlan, row['id']) is not None
    engine.dispose()


def test_master_book_is_a_copy_of_east_and_new_books_start_from_it():
    from sqlalchemy import text
    from models import Base, Company, PricingPlan, PricingRate, PricingRule, PricingElevator, PricingElevatorTier, PricingPickupArea, AppSetting
    from routes import pricing
    from pricing_books import copy_book
    engine = create_engine('sqlite://')
    event.listen(engine, 'connect', lambda connection, _: connection.execute('PRAGMA foreign_keys=ON'))
    Base.metadata.create_all(engine)
    admin = SimpleNamespace(role='admin', id='admin')

    def contents(db, plan_id):
        return (sorted(r.destination for r in db.query(PricingRate).filter_by(plan_id=plan_id)),
                sorted(r.title for r in db.query(PricingRule).filter_by(plan_id=plan_id)),
                sorted(float(t.fee) for t in db.query(PricingElevatorTier).filter_by(plan_id=plan_id)),
                sorted(a.state for a in db.query(PricingPickupArea).filter_by(plan_id=plan_id)),
                (db.get(AppSetting, f'local_pricing:{plan_id}') or SimpleNamespace(value=None)).value)
    with Session(engine) as db:
        db.add(Company(id='gorilla', name='Gorilla Haulers'))
        db.add(PricingPlan(id='east', company_id='gorilla', company_name='Gorilla Haulers', name='East', source_key='import:east',
                           fuel_percent=13, admin_fee=199, price_valid_days=10))
        db.flush()
        db.add_all([PricingRate(plan_id='east', destination='TX', band_label='0-500'), PricingRate(plan_id='east', destination='FL', band_label='0-500'),
                    PricingRule(plan_id='east', category='discount_percent', title='Military', description='10'),
                    PricingElevator(plan_id='east'), PricingPickupArea(plan_id='east', state='MD'),
                    AppSetting(key='local_pricing:east', value='{"hourly": 1}')])
        db.flush()
        db.add(PricingElevatorTier(plan_id='east', fee=75))
        db.commit()
        east = contents(db, 'east')
        # The default book: an exact copy of East, no company, inactive.
        db.add(PricingPlan(id='master', company_id=None, company_name='Master', name='Default', source_key='master', active=False))
        db.commit()
        with engine.begin() as connection:
            copy_book(connection, 'east', 'master', keep=())
        db.expire_all()
        master = db.get(PricingPlan, 'master')
        assert (float(master.fuel_percent), float(master.admin_fee), master.price_valid_days) == (13, 199, 10)
        assert contents(db, master.id) == east
        # A new book starts with the master's values, without its pickup areas.
        row = pricing.create_pricing_plan(pricing.NewPricingPlan(company_id='gorilla', name='South'), admin, db)
        assert contents(db, row['id']) == (east[0], east[1], east[2], [], east[4])
        assert float(db.get(PricingPlan, row['id']).admin_fee) == 199
        # Copying the master into an existing book replaces its values and keeps its pickup areas.
        db.add(PricingPlan(id='old', company_id='gorilla', company_name='Gorilla Haulers', name='OLD', source_key='import:old'))
        db.flush()
        db.add_all([PricingRate(plan_id='old', destination='NY', band_label='0-500'), PricingPickupArea(plan_id='old', state='VA')])
        db.commit()
        assert pricing.copy_master_into_plan('old', admin, db)['name'] == 'OLD'
        assert contents(db, 'old') == (east[0], east[1], east[2], ['VA'], east[4])
        with pytest.raises(HTTPException):
            pricing.copy_master_into_plan(master.id, admin, db)
        # A book's name and company are edited with its details; None leaves it with no company.
        details = dict(fuel_percent=13, admin_fee=199, price_valid_days=10)
        db.add(Company(id='movers', name='Movers 95'))
        db.commit()
        pricing.update_pricing_section('master', 'details', pricing.SectionUpdate(name=' Default ', company_id=None, **details), admin, db)
        assert (master.company_id, master.company_name, master.name) == (None, '', 'Default')
        pricing.update_pricing_section('old', 'details', pricing.SectionUpdate(name='OLD', company_id='movers', **details), admin, db)
        assert (db.get(PricingPlan, 'old').company_id, db.get(PricingPlan, 'old').company_name) == ('movers', 'Movers 95')
        with pytest.raises(HTTPException):
            pricing.update_pricing_section('old', 'details', pricing.SectionUpdate(name='OLD', company_id='nobody', **details), admin, db)
        # The source stays as it was; deleting a book takes its local pricing with it.
        assert contents(db, 'east') == east
        pricing.delete_pricing_plan('old', admin, db)
        assert db.get(AppSetting, 'local_pricing:old') is None
    engine.dispose()
