"""Exercise dispatch routes with real SQL queries, without external integrations."""
import ast
from datetime import date, datetime
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from fastapi import Depends, HTTPException, Query
from sqlalchemy import create_engine, func
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from models import Base, Company, Lead, LeadJob, User
from company_colors import resolve_company_color


@pytest.fixture
def dispatch_routes():
    source = Path(__file__).resolve().parents[2] / 'backend/routes/leads.py'
    names = {'get_dispatch_calendar', 'search_dispatch_jobs', '_parse_move_month'}
    nodes = [node for node in ast.parse(source.read_text(encoding='utf-8')).body
             if isinstance(node, ast.FunctionDef) and node.name in names]
    for node in nodes:
        node.decorator_list = []
    scope = dict(globals(), get_current_user=lambda: None, get_db=lambda: None,
                 _get_user_company_ids=lambda user, db: user.company_ids,
                 _effective_job_date=lambda job: date.fromisoformat(job.move_date),
                 _deserialize_estimated_total=lambda value: None,
                 _deserialize_payments=lambda value: [],
                 DISPATCH_STATUSES={'booked', 'scheduled', 'completed'})
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), scope)
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([
            Company(id='gorilla', name='Gorilla', color='#112233'),
            Company(id='rapid', name='Gorilla Rapid', color='#445566'),
            Lead(id='lead', company_id='gorilla', full_name='Calendar Customer', status='booked'),
            LeadJob(id='assigned-job', lead_id='lead', company_id='gorilla',
                    dispatch_company_id='rapid', job_order=1, move_date='2026-10-02'),
            LeadJob(id='fallback-job', lead_id='lead', company_id='gorilla',
                    job_order=2, move_date='2026-10-02'),
        ])
        db.commit()
        yield scope, db
    engine.dispose()


@pytest.mark.parametrize('endpoint', ['calendar', 'search', 'exact'])
@pytest.mark.parametrize('company', ['gorilla', 'rapid'])
def test_dispatch_company_controls_visibility_and_labels(dispatch_routes, endpoint, company):
    scope, db = dispatch_routes
    user = SimpleNamespace(role='dispatch', id='dispatcher', company_ids=[company])
    if endpoint == 'calendar':
        result = scope['get_dispatch_calendar'](company_id='', move_month='2026-10', user=user, db=db)
    else:
        result = scope['search_dispatch_jobs'](
            query='assigned-job' if endpoint == 'exact' else 'Calendar Customer',
            limit=10, user=user, db=db)
    expected = [] if endpoint == 'exact' and company == 'gorilla' else [
        'assigned-job' if company == 'rapid' else 'fallback-job']
    assert [item['id'] for item in result['items']] == expected
    for item in result['items']:
        assert item['company_id'] == company
        assert item['company_name'] == ('Gorilla Rapid' if company == 'rapid' else 'Gorilla')
        assert item['company_color'] == ('#445566' if company == 'rapid' else '#112233')


def test_selected_calendar_and_cleared_assignment(dispatch_routes):
    scope, db = dispatch_routes
    user = SimpleNamespace(role='admin', id='admin', company_ids=['gorilla', 'rapid'])
    def calendar(company):
        return scope['get_dispatch_calendar'](company_id=company, move_month='2026-10', user=user, db=db)['items']
    assert [item['id'] for item in calendar('rapid')] == ['assigned-job']
    assert len(calendar('')) == 2
    db.get(LeadJob, 'assigned-job').dispatch_company_id = None
    db.commit()
    assert calendar('rapid') == []
    assert {item['id'] for item in calendar('gorilla')} == {'assigned-job', 'fallback-job'}


def test_foreman_restriction_still_applies(dispatch_routes):
    scope, db = dispatch_routes
    user = SimpleNamespace(role='foreman', id='other-foreman', company_ids=['rapid'])
    assert scope['get_dispatch_calendar'](company_id='', move_month='2026-10', user=user, db=db)['items'] == []
    for query in ['assigned-job', 'Calendar Customer']:
        assert scope['search_dispatch_jobs'](query=query, limit=10, user=user, db=db)['items'] == []
