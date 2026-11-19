"""The out-of-area fee: a pickup more than the book's miles from the company office pays the book's fee."""
import os
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT)]
os.environ.setdefault('JWT_SECRET', 'test-only-secret-with-at-least-32-characters')

OFFICE = '1 Office St, Washington, DC 20001'
PICKUP = '9 Far Rd, Pittsburgh, PA 15201'


def book(miles=100, fee=Decimal('750'), office=OFFICE):
    return SimpleNamespace(out_of_area_miles=miles, out_of_area_fee=fee, company=SimpleNamespace(office_address=office))


def measured(miles):
    from delivery_fees import route_revision
    return route_revision(OFFICE, PICKUP), round(miles * 1609.344)


def test_fee_over_the_miles_only():
    from delivery_fees import out_of_area_fee
    assert out_of_area_fee(book(), PICKUP, *measured(250))['amount'] == Decimal('750')
    assert out_of_area_fee(book(), PICKUP, *measured(100)) is None
    assert out_of_area_fee(book(), PICKUP, *measured(40)) is None


def test_book_without_the_fee_has_none():
    from delivery_fees import out_of_area_fee, out_of_area_office
    for plan in (book(miles=None), book(fee=None), book(miles=None, fee=None)):
        assert out_of_area_fee(plan, PICKUP, *measured(250)) is None
        assert out_of_area_office(plan) == ''


def test_unmeasured_or_moved_pickup_waits_for_the_browser():
    from fastapi import HTTPException
    from delivery_fees import out_of_area_fee
    with pytest.raises(HTTPException) as unmeasured:
        out_of_area_fee(book(), PICKUP)
    assert unmeasured.value.status_code == 409
    # Measured for another address: measured again.
    with pytest.raises(HTTPException):
        out_of_area_fee(book(), '5 Other Ave, Erie, PA 16501', *measured(250))
    with pytest.raises(HTTPException) as no_office:
        out_of_area_fee(book(office=''), PICKUP, *measured(250))
    assert 'office address' in no_office.value.detail


def test_browser_measures_the_office_to_pickup_route(monkeypatch):
    import routes.pricing as pricing
    from delivery_fees import browser_fee_routes, route_revision
    job = SimpleNamespace(pickup_zip=PICKUP, delivery_zip='', customer_packing_package='{}',
                          out_of_area_meters=None, out_of_area_revision=None)
    plan = book()
    plan.mileage_fees = []
    monkeypatch.setattr(pricing, 'infer_job_move_type', lambda lead, job, db: ('Long Distance', plan))
    [route] = browser_fee_routes(None, job, None)
    assert route == {'kind': 'area', 'origin': OFFICE, 'destination': PICKUP,
                     'revision': route_revision(OFFICE, PICKUP), 'meters': None}
    job.out_of_area_revision, job.out_of_area_meters = route['revision'], 402336
    assert browser_fee_routes(None, job, None)[0]['meters'] == 402336
    # Local moves and books without the fee measure nothing.
    monkeypatch.setattr(pricing, 'infer_job_move_type', lambda lead, job, db: ('Local', plan))
    assert browser_fee_routes(None, job, None) == []
    plan.out_of_area_fee = None
    monkeypatch.setattr(pricing, 'infer_job_move_type', lambda lead, job, db: ('Long Distance', plan))
    assert browser_fee_routes(None, job, None) == []


def test_saved_as_numbers_and_priced(monkeypatch):
    import importlib.util
    import json
    from unittest.mock import MagicMock, patch
    from fastapi import HTTPException
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    import models
    import delivery_fees as fees
    backend = ROOT / 'backend'
    mocks = {name: MagicMock() for name in ['auth', 'database', 'routes.leads']}
    mocks['auth'].get_current_user = lambda: None
    mocks['auth'].require_admin = lambda: None
    mocks['database'].get_db = lambda: None
    spec = importlib.util.spec_from_file_location('out_of_area_pricing_test', backend / 'routes/pricing.py')
    api = importlib.util.module_from_spec(spec)
    mocks['out_of_area_pricing_test'] = api
    with patch.dict(sys.modules, mocks):
        spec.loader.exec_module(api)
        engine = create_engine('sqlite://')
        models.Base.metadata.create_all(engine)
        with Session(engine) as db:
            db.add(models.Company(id='co', name='Test', office_address=OFFICE))
            lead = models.Lead(id='lead', full_name='Test', company_id='co', volume='24')
            delivery = {'revision': fees.route_revision('20815', '05401'), 'meters': 160934}
            job = models.LeadJob(id='job', lead_id='lead', company_id='co', pickup_zip=PICKUP, delivery_zip='05401',
                                 customer_packing_package=json.dumps({'delivery_route': delivery}))
            plan = models.PricingPlan(id='plan', source_key='plan', company_id='co', company_name='Test', name='East',
                                      pickup_rows=[models.PricingPickupArea(state='PA')], active=True)
            fees.save_fee_card(plan, fees.DELIVERY_FEE_PREFIX, fees.DeliveryFeeCard(enabled=True, rules=[
                {'state': 'VT', 'zip_codes': [], 'origin_zip': '20815', 'rate_per_mile': '5'}]))
            plan.rates = [models.PricingRate(destination='VT', band_label='286+', cubic_feet_min=286, rate=5, minimum_price=1500)]
            db.add_all([lead, job, plan]); db.commit()
            monkeypatch.setattr(api, '_plan_or_404', lambda *args: plan)
            details = dict(name='East', fuel_percent=None, admin_fee=None, price_valid_days=7)
            # Saved as plain numbers; both or neither.
            with pytest.raises(HTTPException):
                api.update_pricing_section('plan', 'details', api.SectionUpdate(**details, out_of_area_miles=100), None, db)
            api.update_pricing_section('plan', 'details', api.SectionUpdate(**details, out_of_area_miles=100, out_of_area_fee=Decimal('750')), None, db)
            db.expire_all()
            plan = db.get(models.PricingPlan, 'plan')
            assert (plan.out_of_area_miles, plan.out_of_area_fee) == (100, Decimal('750.00'))
            # Details saved without the fields keep them.
            api.update_pricing_section('plan', 'details', api.SectionUpdate(**details), None, db)
            assert plan.out_of_area_fee == Decimal('750.00')
            # Measured 250 miles away by the browser: the fee is on the price.
            job.out_of_area_revision, job.out_of_area_meters = measured(250)
            db.commit()
            assert api.calculate_and_save_lead_job_price(lead, job, db) == 2750
            db.commit()
            assert db.query(models.LeadJobCharge).filter_by(name='Out-of-area fee').one().total_cost == 750
            # Measured again at 50 miles: the fee comes off.
            job.out_of_area_revision, job.out_of_area_meters = measured(50)
            monkeypatch.setattr(api, 'infer_job_move_type', lambda *args: ('long distance', plan))
            api.sync_out_of_area_fee(lead, job, db)
            db.commit()
            assert job.price == 2000
            assert db.query(models.LeadJobCharge).filter_by(name='Out-of-area fee').count() == 0
            # Turned off on the book: no fee and nothing to measure. The job priced with it keeps it for its valid days,
            # so the edit is saved as a new version, and the job's version keeps its fee.
            saved = api.update_pricing_section('plan', 'details', api.SectionUpdate(**details, out_of_area_miles=None, out_of_area_fee=None), None, db)
            assert saved['id'] != 'plan' and (saved['out_of_area_miles'], saved['out_of_area_fee']) == (None, None)
            assert (plan.out_of_area_miles, plan.out_of_area_fee) == (100, Decimal('750.00'))
        engine.dispose()
