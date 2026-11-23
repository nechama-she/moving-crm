"""Each user's order of the Sales Work Queue cards: saved as one row per card, read back with the queue counts."""
import os
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT)]
os.environ.setdefault('JWT_SECRET', 'test-only-secret-with-at-least-32-characters')


@pytest.fixture
def db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from models import Base, User
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([User(id='rep-1', name='Eli', email='eli@example.com', role='admin', password_hash='x'),
                         User(id='rep-2', name='Bushra', email='bushra@example.com', role='admin', password_hash='x')])
        session.commit()
        yield session
    engine.dispose()


def test_each_user_keeps_their_own_card_order(db):
    from models import User, WorkQueueCardOrder
    from routes.unanswered_messages import CardOrderRequest, queue_summary, save_card_order
    eli, bushra = db.get(User, 'rep-1'), db.get(User, 'rep-2')
    save_card_order(CardOrderRequest(cards=['followups', 'messages']), eli, db)
    save_card_order(CardOrderRequest(cards=['calls', 'followups', 'messages']), eli, db)  # Replaces the last one.
    assert queue_summary(eli, db)['card_order'] == ['calls', 'followups', 'messages']
    assert queue_summary(bushra, db)['card_order'] == []
    assert db.query(WorkQueueCardOrder).count() == 3


@pytest.mark.parametrize('cards', [['messages', 'messages'], ['no-such-card']])
def test_only_known_cards_once_each(db, cards):
    from models import User
    from routes.unanswered_messages import CardOrderRequest, save_card_order
    with pytest.raises(HTTPException) as error:
        save_card_order(CardOrderRequest(cards=cards), db.get(User, 'rep-1'), db)
    assert error.value.status_code == 400
