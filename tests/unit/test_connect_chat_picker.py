import ast
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

BACKEND = Path(__file__).resolve().parents[2] / 'backend'
sys.path.insert(0, str(BACKEND))
from models import Base, Company, Lead, CommunicationAssociation


def test_picker_searches_message_text_and_excludes_other_platforms_companies_and_links():
    tree = ast.parse((BACKEND / 'routes/communication_associations.py').read_text())
    node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'unconnected_meta')
    node.decorator_list = []
    node.args.defaults = []
    for arg in node.args.args: arg.annotation = None
    namespace = dict(Company=Company, Lead=Lead, CommunicationAssociation=CommunicationAssociation)
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<picker>', 'exec'), namespace)
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        company = Company(id='company', name='Test', facebook_page_id='page')
        db.add(company)
        lead = Lead(id='target', full_name='Target', company_id='company')
        db.add_all([lead, Lead(id='linked', full_name='Linked', company_id='company', facebook_user_id='legacy')])
        db.add(CommunicationAssociation(channel='messenger', client_identifier='connected', company_identifier='page', lead_id='linked', company_id='company', created_by='admin'))
        db.commit()
        rows = [dict(user_id=client, page_id=page, platform=platform, timestamp=stamp, text=text)
            for client, page, platform, stamp, text in [
                ('old', 'page', 'messenger', 10, 'looking for boxes'),
                ('new', 'page', 'messenger', 20, 'need boxes'),
                ('ig', 'page', 'instagram', 30, 'boxes'),
                ('wrong-page', 'other', 'messenger', 40, 'boxes'),
                ('legacy', 'page', 'messenger', 50, 'boxes'),
                ('connected', 'page', 'messenger', 60, 'boxes'),
                ('unmatched', 'page', 'messenger', 70, 'chairs'),
            ]]
        chats = SimpleNamespace(_query_meta_page=lambda start, limit: (rows, {'next': 1}),
            _decode_cursor=lambda value: (None, None), _encode_cursor=lambda *args: 'next-page', _timestamp=float)
        with patch.dict(sys.modules, {'routes.leads': SimpleNamespace(_get_visible_lead_or_404=lambda *args: lead), 'routes.chats': chats}):
            result = namespace['unconnected_meta']('target', 'messenger', 'BOXES', '', SimpleNamespace(id='admin'), db)
        assert [row['client_identifier'] for row in result['items']] == ['new', 'old']
        assert result['next_cursor'] == 'next-page'
        assert result['has_more'] is True
    engine.dispose()


# Load the route logic without initializing database credentials or AWS clients.
def connection_functions():
    from datetime import datetime, timezone
    from fastapi import HTTPException
    from sqlalchemy.dialects.postgresql import insert
    from communication_associations import normalized_key
    namespace = dict(Company=Company, Lead=Lead, CommunicationAssociation=CommunicationAssociation,
                     datetime=datetime, timezone=timezone, HTTPException=HTTPException,
                     insert=insert, normalized_key=normalized_key,
                     _destination_scope=lambda db, channel, page: ({'company'}, set(), 'Test'))
    tree = ast.parse((BACKEND / 'routes/communication_associations.py').read_text())
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in ('connect', 'disconnect', 'lead_meta_links'):
            node.decorator_list = []
            node.args.defaults = []
            node.returns = None
            for arg in node.args.args:
                arg.annotation = None
            exec(compile(ast.Module(body=[node], type_ignores=[]), '<connection>', 'exec'), namespace)
    return namespace


def test_connect_persists_link_rejects_reassignment_and_disconnects():
    from datetime import datetime, timezone
    import pytest
    from fastapi import HTTPException
    from models import MessageState
    functions = connection_functions()
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        lead = Lead(id='target', full_name='Target', company_id='company')
        db.add_all([Company(id='company', name='Test', facebook_page_id='page'), lead,
                    Lead(id='other', full_name='Other', company_id='company')])
        state = MessageState(channel='messenger', message_id='message', client_identifier='client',
                             company_identifier='page', direction='inbound', occurred_at=datetime.now(timezone.utc))
        db.add(state)
        db.commit()
        body = SimpleNamespace(channel='messenger', client_identifier='client', company_identifier='page',
                               lead_id='target', only_if_unconnected=True)
        admin = SimpleNamespace(id='admin')
        assert functions['connect'](body, admin, db)['ok']
        db.refresh(state)
        assert state.lead_id == 'target'
        body.lead_id = 'other'
        with pytest.raises(HTTPException) as error:
            functions['connect'](body, admin, db)
        assert error.value.status_code == 409
        assert db.query(CommunicationAssociation).one().lead_id == 'target'
        body.lead_id = 'target'
        with patch.dict(sys.modules, {'routes.leads': SimpleNamespace(_get_visible_lead_or_404=lambda *args: lead)}):
            assert functions['lead_meta_links']('target', admin, db)['items'] == [
                dict(channel='messenger', client_identifier='client', company_identifier='page')]
            assert functions['disconnect'](body, admin, db)['ok']
        db.refresh(state)
        assert state.lead_id is None
        assert db.query(CommunicationAssociation).count() == 0
    engine.dispose()


def test_connect_rejects_wrong_company_and_legacy_link():
    import pytest
    from fastapi import HTTPException
    functions = connection_functions()
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([Company(id='company', name='Test', facebook_page_id='page'),
                    Company(id='outside', name='Outside', facebook_page_id='other-page'),
                    Lead(id='target', full_name='Target', company_id='company'),
                    Lead(id='legacy', full_name='Legacy', company_id='company', facebook_user_id='client'),
                    Lead(id='wrong', full_name='Wrong', company_id='outside')])
        db.commit()
        body = SimpleNamespace(channel='messenger', client_identifier='client', company_identifier='page',
                               lead_id='wrong', only_if_unconnected=True)
        with pytest.raises(HTTPException) as error:
            functions['connect'](body, SimpleNamespace(id='admin'), db)
        assert error.value.status_code == 400
        body.lead_id = 'target'
        with pytest.raises(HTTPException) as error:
            functions['connect'](body, SimpleNamespace(id='admin'), db)
        assert error.value.status_code == 409
        assert db.query(CommunicationAssociation).count() == 0
    engine.dispose()
