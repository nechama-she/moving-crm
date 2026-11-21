"""A lead without a SmartMoving id is a standalone CRM lead: assigning it a rep is not a SmartMoving failure, and the
rep stays. The reps a lead list filters by are the people leads are assigned to, admins included."""
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT)]
os.environ.setdefault('JWT_SECRET', 'test-only-secret-with-at-least-32-characters')


@pytest.mark.parametrize('module', ['routes.leads', 'routes.assignment'])
def test_assigning_a_standalone_lead_needs_no_smartmoving(module, monkeypatch):
    import importlib
    sync = importlib.import_module(module)
    calls = []
    monkeypatch.setattr(sync, 'update_opportunity_salesperson', lambda *args: calls.append(args) or {'ok': False})
    rep = SimpleNamespace(id='eli', smartmoving_rep_id=None)
    result = sync._sync_assignment_to_smartmoving(SimpleNamespace(id='lead', smartmoving_id=None), rep)
    assert result['ok'] is True and result['skipped'] == 'standalone_lead'
    assert calls == []  # SmartMoving is never contacted.
    # A SmartMoving lead still syncs, and still reports a failed sync.
    failed = sync._sync_assignment_to_smartmoving(SimpleNamespace(id='lead', smartmoving_id='sm-1'),
                                                  SimpleNamespace(id='eli', smartmoving_rep_id='rep-1'))
    assert failed['ok'] is False and calls == [('sm-1', 'rep-1')]


def test_the_reps_filter_lists_admins_who_take_leads():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from models import Base, Company, User, UserCompany
    from routes.users import list_my_reps
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([Company(id='gorilla', name='Gorilla Haulers'), Company(id='other', name='Other')])
        db.flush()
        users = [('me', 'Admin', 'admin'), ('eli', 'Eli Jones', 'admin'), ('devin', 'Devin K', 'sales_rep'),
                 ('far', 'Far Rep', 'sales_rep'), ('disp', 'Dispatcher', 'dispatch')]
        db.add_all([User(id=i, name=n, email=f'{i}@example.com', password_hash='x', role=r) for i, n, r in users])
        db.flush()
        db.add_all([UserCompany(user_id='me', company_id='gorilla'), UserCompany(user_id='eli', company_id='gorilla'),
                    UserCompany(user_id='devin', company_id='gorilla'), UserCompany(user_id='far', company_id='other'),
                    UserCompany(user_id='disp', company_id='gorilla')])
        db.commit()
        names = [row['name'] for row in list_my_reps(db.get(User, 'me'), db)]
        assert names == ['Admin', 'Devin K', 'Eli Jones']
    engine.dispose()
