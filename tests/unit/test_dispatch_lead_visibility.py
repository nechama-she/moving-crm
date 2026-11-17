"""A lead on a user's dispatch calendar opens for them: the lead page follows the calendar's rule."""
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT)]
os.environ.setdefault('JWT_SECRET', 'test-only-secret-with-at-least-32-characters')


@pytest.fixture
def db():
    """The estimate-approval hook is not what these tests check (and imports modules other tests replace): off here."""
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import Session
    from models import Base, Company, Lead, LeadJob, User, UserCompany
    import estimate_approval
    hook = estimate_approval._clear_changed_approvals
    hooked = event.contains(Session, 'before_flush', hook)
    if hooked:
        event.remove(Session, 'before_flush', hook)
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([Company(id='haulers', name='Gorilla Haulers'), Company(id='rapid', name='Gorilla (Rapid Jobs)')])
        session.add(User(id='alonzo', name='Alonzo', email='alonzo@example.com', password_hash='x', role='dispatch'))
        session.add(UserCompany(user_id='alonzo', company_id='rapid'))
        session.flush()
        # Contract company Gorilla Haulers; subcontractor Gorilla (Rapid Jobs).
        session.add(Lead(id='subcontracted', full_name='Gabrielle Taylor', company_id='haulers', status='booked'))
        session.add(Lead(id='not-booked', full_name='Pat Quote', company_id='haulers', status='quoted'))
        session.add(Lead(id='other', full_name='Other Customer', company_id='haulers', status='booked'))
        session.flush()
        session.add_all([LeadJob(id='j1', lead_id='subcontracted', job_order=1, company_id='haulers', dispatch_company_id='rapid'),
                         LeadJob(id='j2', lead_id='not-booked', job_order=1, company_id='haulers', dispatch_company_id='rapid'),
                         LeadJob(id='j3', lead_id='other', job_order=1, company_id='haulers')])
        session.commit()
        yield session
    engine.dispose()
    if hooked:
        event.listen(Session, 'before_flush', hook)


def visible_lead(monkeypatch):
    """The lead page's check, from the real leads module and what it imports: tests elsewhere leave fakes of them behind.
    They are put back after the test."""
    for name in list(sys.modules):
        if name in ('database', 'routes.leads', 'libs') or name.startswith('libs.'):
            monkeypatch.delitem(sys.modules, name)
    import importlib
    return importlib.import_module('routes.leads')._get_visible_lead_or_404


def test_dispatch_opens_what_its_calendar_shows(db, monkeypatch):
    from fastapi import HTTPException
    _get_visible_lead_or_404 = visible_lead(monkeypatch)
    alonzo = SimpleNamespace(id='alonzo', role='dispatch')
    assert _get_visible_lead_or_404('subcontracted', alonzo, db).id == 'subcontracted'
    # Not on the calendar: a status it does not show, or no job subcontracted to his companies.
    for lead_id in ('not-booked', 'other'):
        with pytest.raises(HTTPException):
            _get_visible_lead_or_404(lead_id, alonzo, db)


def test_other_roles_keep_the_company_rule(db, monkeypatch):
    from fastapi import HTTPException
    _get_visible_lead_or_404 = visible_lead(monkeypatch)
    with pytest.raises(HTTPException):
        _get_visible_lead_or_404('subcontracted', SimpleNamespace(id='alonzo', role='sales_rep'), db)
