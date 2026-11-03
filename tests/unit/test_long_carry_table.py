import json
import sys
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from models import Base, PricingPlan, PricingService, PricingLongCarry
from long_carry_pricing import (LONG_CARRY_PREFIX, LongCarryCard, plan_long_carry_card, save_long_carry_card,
                                long_carry_service_row, migrate_long_carry_cards)

CONFIG = {'enabled': True, 'increment_feet': 75, 'included_feet': 75, 'rate_per_cuft': '0.2',
          'minimum_cubic_feet': 375, 'pickup_discount_percent': '100', 'delivery_discount_percent': '0'}


def plan():
    return PricingPlan(id='plan', source_key='plan', company_name='Co', name='East', source_file='', source_sheet='')


def test_saved_card_reads_back_and_is_presented_as_the_same_service_row():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        book = plan()
        save_long_carry_card(book, LongCarryCard.model_validate(CONFIG))
        db.add(book)
        db.commit()
        db.expire_all()
        book = db.get(PricingPlan, 'plan')
        assert plan_long_carry_card(book) == LongCarryCard.model_validate(CONFIG)
        row = long_carry_service_row(book)
        assert row['name'] == 'Long carry pricing'
        assert json.loads(row['comments'][len(LONG_CARRY_PREFIX):]) == CONFIG
        assert row in book.to_dict()['services']
        save_long_carry_card(book, None)
        db.commit()
        assert db.query(PricingLongCarry).count() == 0
    engine.dispose()


def test_migration_moves_the_first_card_and_deletes_the_json_rows_once():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    PricingLongCarry.__table__.drop(engine)
    with Session(engine) as db:
        book = plan()
        book.services = [
            PricingService(id='card', name='Long carry pricing', comments=LONG_CARRY_PREFIX + json.dumps(CONFIG), sort_order=0),
            PricingService(id='copy', name='Long carry pricing', comments=LONG_CARRY_PREFIX + json.dumps({**CONFIG, 'enabled': False}), sort_order=1),
            PricingService(id='piano', name='Piano', rate_text='150', comments='', sort_order=2),
        ]
        db.add(book)
        db.commit()
    with engine.begin() as connection:
        assert migrate_long_carry_cards(connection) == 1
        assert migrate_long_carry_cards(connection) == 0
        assert [row[0] for row in connection.execute(text('SELECT id FROM pricing_services'))] == ['piano']
    with Session(engine) as db:
        card = plan_long_carry_card(db.get(PricingPlan, 'plan'))
        assert card.enabled is True and card.rate_per_cuft == Decimal('0.2') and card.minimum_cubic_feet == 375
    engine.dispose()
