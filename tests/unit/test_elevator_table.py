import json
import sys
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from models import Base, PricingPlan, PricingService, PricingElevator, PricingElevatorTier
from elevator_pricing import (ELEVATOR_PREFIX, ElevatorCard, plan_elevator_card, save_elevator_card,
                              elevator_service_row, migrate_elevator_cards)

CONFIG = {'enabled': True, 'tiers': [{'up_to_cuft': 500, 'fee': '150'}, {'up_to_cuft': None, 'fee': '250.5'}],
          'pickup_discount_percent': '0', 'delivery_discount_percent': '10'}


def plan():
    return PricingPlan(id='plan', source_key='plan', company_name='Co', name='East', source_file='', source_sheet='')


def test_saved_card_reads_back_and_is_presented_as_the_same_service_row():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        book = plan()
        save_elevator_card(book, ElevatorCard.model_validate(CONFIG))
        db.add(book)
        db.commit()
        db.expire_all()
        book = db.get(PricingPlan, 'plan')
        assert plan_elevator_card(book) == ElevatorCard.model_validate(CONFIG)
        row = elevator_service_row(book)
        assert row['name'] == 'Elevator pricing'
        assert json.loads(row['comments'][len(ELEVATOR_PREFIX):]) == CONFIG
        assert row in book.to_dict()['services']
        # Re-saving with a changed fee keeps the tier rows and their unique key intact.
        kept = {tier.id for tier in book.elevator.tiers}
        save_elevator_card(book, ElevatorCard.model_validate({**CONFIG, 'tiers': [{'up_to_cuft': 500, 'fee': '175'}, {'up_to_cuft': None, 'fee': '250.5'}]}))
        db.commit()
        assert {tier.id for tier in db.query(PricingElevatorTier)} == kept
        save_elevator_card(book, None)
        db.commit()
        assert db.query(PricingElevator).count() == 0 and db.query(PricingElevatorTier).count() == 0
    engine.dispose()


def test_migration_moves_the_first_card_including_legacy_format_once():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    PricingElevatorTier.__table__.drop(engine)
    PricingElevator.__table__.drop(engine)
    legacy = {'enabled': True, 'threshold_cuft': 500, 'lower_fee': '150', 'upper_fee': '250'}
    with Session(engine) as db:
        book = plan()
        book.services = [
            PricingService(id='card', name='Elevator pricing', comments=ELEVATOR_PREFIX + json.dumps(legacy), sort_order=0),
            PricingService(id='copy', name='Elevator pricing', comments=ELEVATOR_PREFIX + json.dumps(CONFIG), sort_order=1),
            PricingService(id='piano', name='Piano', rate_text='150', comments='', sort_order=2),
        ]
        db.add(book)
        db.commit()
    with engine.begin() as connection:
        assert migrate_elevator_cards(connection) == 1
        assert migrate_elevator_cards(connection) == 0
        assert [row[0] for row in connection.execute(text('SELECT id FROM pricing_services'))] == ['piano']
    with Session(engine) as db:
        card = plan_elevator_card(db.get(PricingPlan, 'plan'))
        assert [(tier.up_to_cuft, tier.fee) for tier in card.tiers] == [(500, Decimal('150')), (None, Decimal('250'))]
    engine.dispose()
