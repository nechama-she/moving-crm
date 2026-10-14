import ast
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from models import Base, Company, Lead, LeadJob, User
from company_dispatch import (
    validate_dispatches_for, resolve_company_dispatch,
    smartmoving_dispatch_company, apply_job_dispatch,
)


@pytest.fixture
def db():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([
            Company(id='gorilla', name='Gorilla'),
            Company(id='rapid', name='Gorilla Rapid', samrtmoving_branch_id='branch-rapid',
                    dispatches_for_company_id='gorilla'),
            Company(id='other', name='Other'),
            Lead(id='lead', full_name='Customer', company_id='gorilla'),
            LeadJob(id='job', lead_id='lead', company_id='gorilla', job_order=1,
                    smartmoving_job_id='sm-job'),
        ])
        session.commit()
        yield session
    engine.dispose()


@pytest.mark.parametrize('branch', [
    {'id': 'branch-rapid', 'name': 'Renamed externally'},
    {'name': '  gOrIlLa rApId  '},
])
def test_incoming_branch_resolves_contract_and_dispatch(db, branch):
    incoming = smartmoving_dispatch_company(db, {'branch': branch})
    contract, dispatch = resolve_company_dispatch(db, incoming)
    assert (contract.id, dispatch) == ('gorilla', 'rapid')


def test_unmapped_branch_does_not_change_company(db):
    assert smartmoving_dispatch_company(db, {'branch': {'name': 'Other'}}) is None
    assert smartmoving_dispatch_company(db, {}) is None
    company = db.get(Company, 'other')
    assert resolve_company_dispatch(db, company) == (company, None)


@pytest.mark.parametrize(('company_id', 'target'), [
    ('rapid', 'rapid'), ('other', 'missing'), ('other', 'rapid'), ('gorilla', 'other'),
])
def test_invalid_mapping_rejected(db, company_id, target):
    with pytest.raises(HTTPException):
        validate_dispatches_for(db, target, company_id)


def test_mapping_can_be_set_or_cleared(db):
    assert validate_dispatches_for(db, ' gorilla ', 'rapid') == 'gorilla'
    assert validate_dispatches_for(db, '', 'rapid') is None
    assert db.get(Company, 'rapid').to_dict()['dispatches_for_company_id'] == 'gorilla'


def test_ambiguous_branch_id_rejected(db):
    db.get(Company, 'other').samrtmoving_branch_id = 'branch-rapid'
    with pytest.raises(HTTPException):
        smartmoving_dispatch_company(db, {'branch': {'id': 'branch-rapid'}})


@pytest.fixture
def update_route():
    source = Path(__file__).resolve().parents[2] / 'backend/routes/leads.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    node = next(n for n in tree.body if getattr(n, 'name', '') == '_apply_lead_update')
    # Exercise the real update function with SQL; isolate unrelated outbound services.
    scope = dict(globals(), LeadUpdate=object,
                 logger=logging.getLogger('test'),
                 _ensure_not_dispatch_write=lambda user: None,
                 _get_user_company_ids=lambda user, db: user.company_ids,
                 _get_or_create_primary_lead_job=lambda lead, db: db.get(LeadJob, 'job'),
                 _next_lead_job_order=lambda lead_id, db: (db.query(func.max(LeadJob.job_order)).filter(LeadJob.lead_id == lead_id).scalar() or 0) + 1,
                 _read_job_route=lambda db, job: ('', [], ''),
                 _sync_smartmoving_job_details=lambda lead, db: None)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), scope)
    fields = next(n for n in tree.body if getattr(n, 'name', '') == 'LeadUpdate')
    defaults = {n.target.id: None for n in fields.body if isinstance(n, ast.AnnAssign)}
    return scope['_apply_lead_update'], defaults


@pytest.mark.parametrize('mode', ['name', 'id', 'refresh'])
@pytest.mark.parametrize('existing_dispatch', [None, 'other'])
def test_sync_keeps_contract_and_manual_dispatch_and_maps_new_jobs(db, update_route, mode, existing_dispatch):
    update, defaults = update_route
    db.get(LeadJob, 'job').dispatch_company_id = existing_dispatch
    job_patch = lambda job_id: SimpleNamespace(dict=lambda **kwargs: {'smartmoving_job_id': job_id})
    body = SimpleNamespace(**dict(defaults, jobs=[job_patch('sm-job'), job_patch('sm-new')]))
    kwargs = {}
    if mode == 'refresh':
        kwargs['incoming_smartmoving_company'] = db.get(Company, 'rapid')
    elif mode == 'name':
        body.company_name = 'Gorilla Rapid'
    else:
        body.company_id = 'rapid'
    user = SimpleNamespace(role='admin', company_ids=['gorilla', 'rapid', 'other'])
    for _ in range(2):
        update('lead', body, user, db, **kwargs)
        assert db.get(Lead, 'lead').company_id == 'gorilla'
        jobs = db.query(LeadJob).order_by(LeadJob.job_order).all()
        assert len(jobs) == 2
        assert all(job.company_id == 'gorilla' for job in jobs)
        assert jobs[0].dispatch_company_id == (existing_dispatch or 'rapid')
        assert jobs[1].dispatch_company_id == 'rapid'


def test_sync_cannot_route_to_inaccessible_contract_company(db, update_route):
    update, defaults = update_route
    db.get(Lead, 'lead').company_id = 'rapid'
    user = SimpleNamespace(role='admin', company_ids=['rapid'])
    body = SimpleNamespace(**dict(defaults, company_name='Gorilla Rapid'))
    with pytest.raises(HTTPException) as error:
        update('lead', body, user, db)
    assert error.value.status_code == 403
