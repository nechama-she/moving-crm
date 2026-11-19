import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
import models
from price_validity import refresh_expired_price


@pytest.fixture
def quote(monkeypatch):
    engine = create_engine('sqlite://')
    models.Base.metadata.create_all(engine)
    now = datetime(2026, 10, 10, 12)
    with Session(engine) as db:
        lead = models.Lead(id='lead', full_name='Customer', status='quoted')
        job = models.LeadJob(id='job', lead_id='lead', price=100, price_calculated_at=now-timedelta(days=8),
                            customer_packing='{"item":"packing"}', customer_packing_package='{"mode":"none"}',
                            estimated_materials='[{"name":"Sofa"}]')
        charge = models.LeadJobCharge(id='charge', job_id='job', name='Transportation', subtotal=100,total_cost=100)
        plan = models.PricingPlan(id='plan',name='Book',company_name='Company',source_key='test')
        db.add_all([lead,job,charge,plan]);db.commit()
        def calculate(lead,job,db):
            job.price = 200
            charge.subtotal = charge.total_cost = 200
            return 200
        pricing = SimpleNamespace(infer_job_move_type=MagicMock(return_value=('Long Distance',plan)),
                                  calculate_and_save_lead_job_price=MagicMock(side_effect=calculate))
        monkeypatch.setitem(sys.modules,'routes.pricing',pricing)
        yield db,lead,job,plan,pricing,now
    engine.dispose()


def test_zero_placeholder_price_does_not_refresh_or_lock(quote, monkeypatch):
    db, lead, job, plan, pricing, now = quote
    job.price = 0
    job.price_calculated_at = None
    db.commit()
    # Load attributes before spying on explicit row-lock refreshes.
    assert job.price == 0
    refresh = MagicMock(side_effect=AssertionError('Empty move must not lock for pricing'))
    monkeypatch.setattr(db, 'refresh', refresh)
    assert not refresh_expired_price(lead, job, db, now)
    refresh.assert_not_called()
    pricing.calculate_and_save_lead_job_price.assert_not_called()


def test_default_seven_days_refreshes_once_and_preserves_answers(quote):
    db,lead,job,plan,pricing,now = quote
    assert plan.price_valid_days == 7
    before = job.customer_packing,job.customer_packing_package,job.estimated_materials
    assert refresh_expired_price(lead,job,db,now)
    assert job.price == 200
    assert job.price_calculated_at == now
    assert not refresh_expired_price(lead,job,db,now+timedelta(days=6))
    pricing.calculate_and_save_lead_job_price.assert_called_once()
    assert (job.customer_packing,job.customer_packing_package,job.estimated_materials) == before
    assert db.query(models.LeadJobCharge).one().id == 'charge'


def test_fresh_price_does_not_take_write_locks(quote, monkeypatch):
    db, lead, job, plan, pricing, now = quote
    job.price_calculated_at = now - timedelta(hours=1)
    db.commit()
    assert job.price == 100
    refresh = MagicMock(side_effect=AssertionError('Fresh quote must not lock'))
    monkeypatch.setattr(db, 'refresh', refresh)
    assert not refresh_expired_price(lead, job, db, now)
    refresh.assert_not_called()
    pricing.calculate_and_save_lead_job_price.assert_not_called()


def test_custom_validity_and_exact_expiry_boundary(quote):
    db,lead,job,plan,pricing,now = quote
    plan.price_valid_days = 14
    db.commit()
    assert not refresh_expired_price(lead,job,db,now)
    assert refresh_expired_price(lead,job,db,now+timedelta(days=6))


@pytest.mark.parametrize('status', ['booked','scheduled','completed'])
def test_booked_prices_are_never_refreshed(quote,status):
    db,lead,job,plan,pricing,now = quote
    lead.status = status
    db.commit()
    assert not refresh_expired_price(lead,job,db,now)
    assert job.price == 100
    pricing.calculate_and_save_lead_job_price.assert_not_called()


@pytest.mark.parametrize('status', ['confirmed','lost','cancelled','quoted'])
def test_other_statuses_do_not_lock_the_price(status):
    from types import SimpleNamespace
    from price_validity import price_is_locked
    assert not price_is_locked(SimpleNamespace(status=status, booked_move_date=None), SimpleNamespace(booked_move_date=None))


def test_booking_date_also_locks_price(quote):
    db,lead,job,plan,pricing,now = quote
    job.booked_move_date = now.date()
    db.commit()
    assert not refresh_expired_price(lead,job,db,now)
    pricing.calculate_and_save_lead_job_price.assert_not_called()


def test_failed_refresh_rolls_back_and_does_not_extend_validity(quote):
    db,lead,job,plan,pricing,now = quote
    previous = job.price_calculated_at
    def fail(*args):
        job.price = 999
        db.query(models.LeadJobCharge).one().total_cost = 999
        db.flush()
        raise ValueError('Unavailable rate')
    pricing.calculate_and_save_lead_job_price.side_effect = fail
    assert not refresh_expired_price(lead,job,db,now)
    assert job.price == 100
    assert db.query(models.LeadJobCharge).one().total_cost == 100
    assert job.price_calculated_at == previous
    assert job.price_refresh_error
    assert not refresh_expired_price(lead,job,db,now+timedelta(seconds=30))
    pricing.calculate_and_save_lead_job_price.assert_called_once()


def test_pricing_book_lookup_failure_keeps_previous_estimate(quote):
    db,lead,job,plan,pricing,now = quote
    pricing.infer_job_move_type.side_effect = ValueError('Address lookup unavailable')
    assert not refresh_expired_price(lead,job,db,now)
    assert job.price == 100
    assert job.price_refresh_error
    pricing.calculate_and_save_lead_job_price.assert_not_called()


def test_legacy_quote_uses_charge_timestamp_not_recent_note_edit(quote):
    db,lead,job,plan,pricing,now = quote
    job.price_calculated_at = None
    job.notes = 'Updated today'
    db.query(models.LeadJobCharge).one().updated_at = now-timedelta(days=8)
    db.commit()
    assert refresh_expired_price(lead,job,db,now)


@pytest.mark.parametrize('status', ['new', 'quoted', 'confirmed', 'lost', 'cancelled'])
def test_a_signed_estimate_locks_the_price_whatever_the_status(quote, status):
    """A signed estimate is a contract: its price never changes, not even when it expires."""
    from price_validity import price_is_locked
    db, lead, job, plan, pricing, now = quote
    lead.status = status
    db.add(models.EstimateSignature(lead_id='lead', job_id='job', snapshot='{}', pdf=b'%PDF', signed_at=now - timedelta(days=9)))
    db.commit()
    assert price_is_locked(lead, job)
    assert not refresh_expired_price(lead, job, db, now)
    assert job.price == 100
    pricing.calculate_and_save_lead_job_price.assert_not_called()


def test_a_removed_signature_unlocks_the_price(quote):
    from price_validity import price_is_locked
    db, lead, job, plan, pricing, now = quote
    db.add(models.EstimateSignature(lead_id='lead', job_id='job', snapshot='{}', pdf=b'%PDF', signed_at=None))
    db.commit()
    assert not price_is_locked(lead, job)
    assert refresh_expired_price(lead, job, db, now)


@pytest.mark.parametrize('locked_by', ['signature', 'booked'])
def test_customer_answers_are_refused_while_the_price_is_locked(locked_by):
    """Every customer page answer reprices the estimate: with the price locked it is refused and nothing is saved."""
    from types import SimpleNamespace as Access
    from fastapi import HTTPException
    from routes.public_moves import CustomerPackingChange, CustomerPackingPatch, _save_packing_change
    engine = create_engine('sqlite://')
    models.Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(models.Lead(id='lead', full_name='Customer', status='booked' if locked_by == 'booked' else 'quoted'))
        db.flush()
        db.add(models.LeadJob(id='job', lead_id='lead', price=100, customer_packing_package='{"mode":"none"}'))
        db.flush()
        if locked_by == 'signature':
            db.add(models.EstimateSignature(lead_id='lead', job_id='job', snapshot='{}', pdf=b'%PDF', signed_at=datetime(2026, 11, 1)))
        db.commit()
        with pytest.raises(HTTPException) as refused:
            _save_packing_change(CustomerPackingPatch(change=CustomerPackingChange(kind='mode', mode='full')),
                                 Access(lead_id='lead', job_id='job'), db)
        assert refused.value.status_code == 409
        db.expire_all()
        assert db.get(models.LeadJob, 'job').customer_packing_package == '{"mode":"none"}'
    engine.dispose()
