"""The work queue's Customer Page and Customer Chat cards: one row per lead that only moves forward (opened, verified,
chat), cleared by the rep's text or call, or Ignore."""
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from boto3.dynamodb.types import TypeSerializer

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT)]
os.environ.setdefault('JWT_SECRET', 'test-only-secret-with-at-least-32-characters')


@pytest.fixture
def db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from models import Base, Lead, LeadJob, PublicMoveAccess
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Lead(id='lead', full_name='Dana Customer', phone='(240) 555-0188', number='48213075526'))
        session.flush()
        session.add(LeadJob(id='job', lead_id='lead', job_order=1))
        session.flush()
        session.add(PublicMoveAccess(id='access', lead_id='lead', job_id='job', key_hash='k', request_hash='r', token_hash='t',
                                     expires_at=datetime(2030, 1, 1)))
        session.commit()
        yield session
    engine.dispose()


@pytest.fixture
def access(db):
    from models import PublicMoveAccess
    return db.get(PublicMoveAccess, 'access')


def states(db):
    from customer_page_states import items
    return [(row['lead_id'], row['state']) for row in items(db)]


def test_each_step_replaces_the_one_before_and_never_goes_back(db, access):
    from customer_page_states import OPENED, VERIFIED, advance, advance_to_chat
    assert advance(db, access, OPENED) is True
    assert states(db) == [('lead', 'opened')]
    assert advance(db, access, VERIFIED) is True
    assert states(db) == [('lead', 'verified')]
    # Opening the page again after verifying keeps Verified.
    assert advance(db, access, OPENED) is False
    assert states(db) == [('lead', 'verified')]
    assert advance_to_chat(db, 'access', datetime.now(timezone.utc)) == 'lead'
    assert states(db) == [('lead', 'chat')]
    assert advance(db, access, VERIFIED) is False
    assert states(db) == [('lead', 'chat')]


def test_a_row_shows_the_lead_its_job_and_the_step(db, access):
    from customer_page_states import OPENED, advance, items
    advance(db, access, OPENED)
    row = items(db)[0]
    assert {key: row[key] for key in ('client', 'phone', 'job_number', 'rep', 'state')} == {
        'client': 'Dana Customer', 'phone': '(240) 555-0188', 'job_number': '48213075526-1', 'rep': 'Unassigned', 'state': 'opened'}


def test_clearing_removes_the_row_and_says_which_lead(db, access):
    from customer_page_states import CHAT, advance, clear, cleared_event
    from models import CustomerPageState
    advance(db, access, CHAT)
    assert clear(db, CustomerPageState.lead_id == 'lead') == ['lead']
    assert states(db) == []
    assert cleared_event(db) == {'type': 'customer_page_state_changed', 'row': None, 'lead_ids': ['lead']}
    assert cleared_event(db) is None


def conversation(item):
    return {'eventName': 'INSERT', 'eventSourceARN': 'arn:aws:dynamodb:us-east-1:1:table/conversations/stream/2026',
            'dynamodb': {'NewImage': {key: TypeSerializer().serialize(value) for key, value in item.items()}, 'SequenceNumber': '1'}}


def chat_message(user_id='cp-access', role='user'):
    return conversation({'user_id': user_id, 'message_id': 'm-1', 'timestamp': 1795000000000, 'text': 'Hi',
                         'platform': 'customer_page_bot', 'page_id': 'Gorilla Haulers', 'role': role, 'record_type': 'message'})


def test_the_customers_chat_message_moves_the_row_to_chat(db, access):
    import message_stream_handler
    from customer_page_states import VERIFIED, advance
    advance(db, access, VERIFIED)
    event = message_stream_handler._customer_page_chat(db, chat_message())
    assert states(db) == [('lead', 'chat')]
    assert event['type'] == 'customer_page_state_changed' and event['row']['state'] == 'chat'
    # A later message changes nothing.
    assert message_stream_handler._customer_page_chat(db, chat_message()) is None


def test_a_chat_on_an_unknown_page_adds_no_row(db):
    import message_stream_handler
    assert message_stream_handler._customer_page_chat(db, chat_message('cp-missing')) is None
    assert states(db) == []


@pytest.mark.parametrize('user_id,role', [('cp-rep-access', 'user'), ('cp-access', 'assistant')])
def test_the_reps_chat_and_the_bots_replies_add_no_row(db, user_id, role):
    import message_stream_handler
    assert message_stream_handler._customer_page_chat(db, chat_message(user_id, role)) is False
    assert states(db) == []


def test_other_conversations_are_not_customer_page_chats(db):
    import message_stream_handler
    record = conversation({'user_id': 'cp-access', 'message_id': 'm-1', 'timestamp': 1795000000000, 'platform': 'messenger',
                           'page_id': 'p', 'role': 'user', 'record_type': 'message'})
    assert message_stream_handler._customer_page_chat(db, record) is False


def test_asking_for_a_code_comes_between_opened_and_verified(db, access):
    from customer_page_states import CHAT, OPENED, VERIFIED, advance, items, request_code
    assert advance(db, access, OPENED) is True
    assert request_code(db, access, 'sms') is True
    row = items(db)[0]
    assert (row['state'], row['code_channel']) == ('code_requested', 'sms')
    # Opening the page again keeps it; asking again changes nothing.
    assert advance(db, access, OPENED) is False and request_code(db, access, 'email') is False
    assert items(db)[0]['state'] == 'code_requested'
    assert advance(db, access, VERIFIED) is True
    assert (items(db)[0]['state'], items(db)[0]['code_channel']) == ('verified', '')
    assert request_code(db, access, 'email') is False  # Never back from a later step.
    assert advance(db, access, CHAT) is True and items(db)[0]['state'] == 'chat'


def test_asking_for_a_code_with_no_row_yet_adds_it(db, access):
    from customer_page_states import items, request_code
    assert request_code(db, access, 'email') is True
    assert (items(db)[0]['state'], items(db)[0]['code_channel']) == ('code_requested', 'email')
