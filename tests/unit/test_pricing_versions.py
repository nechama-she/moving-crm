"""A job keeps the pricing book it was priced with, every rate and fee of it: for the book's valid days, and forever
once its estimate is signed. Saving a book that jobs keep leaves them that version and saves the edit as a new one."""
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT)]
os.environ.setdefault('JWT_SECRET', 'test-only-secret-with-at-least-32-characters')


@pytest.fixture
def db(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    import estimate_approval
    from sqlalchemy import event
    from models import (Base, Company, Lead, LeadJob, PricingPickupArea, PricingPlan, PricingRate, PricingService)
    hook = estimate_approval._clear_changed_approvals
    hooked = event.contains(Session, 'before_flush', hook)
    if hooked:
        event.remove(Session, 'before_flush', hook)
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([Company(id='movers', name='Movers 95'), Company(id='other', name='Other Movers')])
        session.flush()
        session.add(PricingPlan(id='east', company_id='movers', company_name='Movers 95', name='East', source_key='east',
                                fuel_percent=13, price_valid_days=7))
        session.add(PricingPlan(id='other-book', company_id='other', company_name='Other Movers', name='Other', source_key='other',
                                fuel_percent=20, price_valid_days=7))
        session.flush()
        for plan_id in ('east', 'other-book'):
            session.add_all([PricingPickupArea(id=f'{plan_id}-va', plan_id=plan_id, state='VA'),
                             PricingRate(id=f'{plan_id}-fl', plan_id=plan_id, destination='Florida', band_label='All', rate=4.25),
                             PricingRate(id=f'{plan_id}-tn', plan_id=plan_id, destination='Tennessee', band_label='All', rate=4.25)])
        session.add(PricingService(id='shuttle', plan_id='east', name='Shuttle', rate_text='400'))
        session.add(Lead(id='lead', full_name='Pat', company_id='movers', move_type='Long Distance'))
        session.flush()
        session.add(LeadJob(id='job', lead_id='lead', job_order=1, company_id='movers',
                            pickup_zip='Norfolk, VA 23505', delivery_zip='Miami, FL 33101'))
        session.commit()
        yield session
    engine.dispose()
    if hooked:
        event.listen(Session, 'before_flush', hook)


def book(db, job):
    """The book the job is priced with now."""
    from models import Lead
    from routes.pricing import infer_job_move_type
    db.info.pop('request_cache', None)
    return infer_job_move_type(db.get(Lead, job.lead_id), job, db)[1]


def edit_fuel(db, plan_id, fuel):
    """A save on the Pricing page: into the book to edit."""
    from models import PricingPlan
    from pricing_books import book_to_edit
    plan = book_to_edit(db, db.get(PricingPlan, plan_id))
    plan.fuel_percent = fuel
    db.commit()
    return plan


def sign(db, when=datetime(2026, 11, 1)):
    from models import EstimateSignature
    db.add(EstimateSignature(lead_id='lead', job_id='job', snapshot='{}', pdf=b'%PDF', signed_at=when))
    db.commit()


def test_a_book_no_job_keeps_is_edited_as_it_is(db):
    from models import LeadJob, PricingPlan
    job = db.get(LeadJob, 'job')
    assert book(db, job).id == 'east'
    job.pricing_plan_at = datetime.utcnow() - timedelta(days=30)  # Priced long ago and not signed: nothing keeps it.
    db.commit()
    assert edit_fuel(db, 'east', 15).id == 'east'
    assert db.get(PricingPlan, 'east').retired_at is None


def test_a_signed_job_keeps_its_book_and_the_edit_is_a_new_version(db):
    from models import LeadJob, PricingPlan, PricingRate, PricingService
    job = db.get(LeadJob, 'job')
    assert book(db, job).id == 'east'
    sign(db)
    version = edit_fuel(db, 'east', 20)
    assert version.id != 'east'
    old = db.get(PricingPlan, 'east')
    # The earlier version is untouched, retired, and points at its replacement; the new one took its name.
    assert float(old.fuel_percent) == 13 and old.retired_at and old.replaced_by_id == version.id
    assert version.source_key == 'east' and old.source_key == f'east@east'
    # Its rows keep their ids in the new version: what jobs saved by them still finds them.
    assert db.get(PricingService, ('shuttle', version.id)) and db.get(PricingRate, ('east-fl', version.id))
    # The signed job keeps the earlier version, even after a change to the move that still fits it.
    job.delivery_zip = 'Nashville, TN 37201'
    db.commit()
    assert book(db, job).id == 'east'
    # A new quote takes the current version.
    from models import Lead
    db.add(Lead(id='lead2', full_name='New', company_id='movers', move_type='Long Distance'))
    db.flush()
    other = LeadJob(id='job2', lead_id='lead2', job_order=1, company_id='movers', pickup_zip='Norfolk, VA 23505', delivery_zip='Miami, FL 33101')
    db.add(other)
    db.commit()
    assert book(db, other).id == version.id
    # A save through the earlier version's id goes on from the current version (which the new quote now keeps, so it
    # too becomes a version); the earlier one never changes.
    newest = edit_fuel(db, 'east', 22)
    assert db.get(PricingPlan, version.id).replaced_by_id == newest.id
    assert float(db.get(PricingPlan, 'east').fuel_percent) == 13 and book(db, job).id == 'east'


def test_an_unsigned_job_keeps_its_book_for_its_valid_days_only(db):
    from models import LeadJob
    job = db.get(LeadJob, 'job')
    assert book(db, job).id == 'east'
    version = edit_fuel(db, 'east', 20)
    assert version.id != 'east'  # Priced just now: the job keeps the book for 7 days.
    job.delivery_zip = 'Tampa, FL 33601'
    db.commit()
    assert book(db, job).id == 'east'
    job.pricing_plan_at = datetime.utcnow() - timedelta(days=8)
    job.delivery_zip = 'Orlando, FL 32801'
    db.commit()
    assert book(db, job).id == version.id  # Past its days: the current book.


def test_a_kept_book_that_no_longer_fits_gives_way_to_the_current_match(db):
    from models import LeadJob, PricingRate
    job = db.get(LeadJob, 'job')
    assert book(db, job).id == 'east'
    sign(db)
    version = edit_fuel(db, 'east', 20)
    # The current version also delivers to Georgia; the earlier one does not.
    db.add(PricingRate(id='ga', plan_id=version.id, destination='Georgia', band_label='All', rate=4.75))
    db.commit()
    job.delivery_zip = 'Atlanta, GA 30301'
    db.commit()
    assert book(db, job).id == version.id
    # Another company never gets this company's book.
    job.company_id = 'other'
    db.get(LeadJob, 'job').lead.company_id = 'other'
    db.commit()
    assert book(db, job).id == 'other-book'


def test_deleting_a_book_a_job_keeps_retires_it(db):
    from models import LeadJob, PricingPlan
    job = db.get(LeadJob, 'job')
    assert book(db, job).id == 'east'
    sign(db)
    from pricing_books import kept_by_jobs
    assert kept_by_jobs(db, db.get(PricingPlan, 'east'))


def test_an_earlier_version_is_dropped_when_its_days_end_even_with_nothing_else_changed(db):
    """The match is reused while nothing it depends on changes; an earlier version still leaves once the job's days end."""
    from models import LeadJob
    job = db.get(LeadJob, 'job')
    assert book(db, job).id == 'east'
    version = edit_fuel(db, 'east', 20)
    assert book(db, job).id == 'east'  # Kept, and the match saved with the books as they are now.
    job.pricing_plan_at = datetime.utcnow() - timedelta(days=8)
    db.commit()
    assert book(db, job).id == version.id
