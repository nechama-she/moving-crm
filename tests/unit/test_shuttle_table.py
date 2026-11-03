import json
import sys
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from models import Base, PricingPlan, PricingService, PricingShuttle, PricingShuttleArea
from shuttle import (SHUTTLE_PREFIX, ShuttleCard, plan_shuttle_card, save_shuttle_card,
                     shuttle_service_row, migrate_shuttle_cards)

CONFIG = {'enabled': True, 'rate': '1.5', 'access_distance_ft': 100, 'minimum_cubic_feet': 400,
          'areas': [{'state': 'NY', 'zip_codes': ['100XX-104XX', '11201']}, {'state': 'DC', 'zip_codes': []}]}
SORTED = {**CONFIG, 'areas': [{'state': 'DC', 'zip_codes': []}, {'state': 'NY', 'zip_codes': ['100XX-104XX', '11201']}]}


def plan():
    return PricingPlan(id='plan', source_key='plan', company_name='Co', name='East', source_file='', source_sheet='')


def test_saved_card_reads_back_and_is_presented_as_the_same_service_row():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        book = plan()
        save_shuttle_card(book, ShuttleCard.model_validate(CONFIG))
        db.add(book)
        db.commit()
        db.expire_all()
        book = db.get(PricingPlan, 'plan')
        assert plan_shuttle_card(book) == ShuttleCard.model_validate(SORTED)
        row = shuttle_service_row(book)
        assert row['name'] == 'Delivery shuttle'
        assert json.loads(row['comments'][len(SHUTTLE_PREFIX):]) == SORTED
        assert row in book.to_dict()['services']
        # Re-saving keeps unchanged area rows, so the unique key never collides.
        kept = {area.id for area in book.shuttle.areas if area.state == 'DC'}
        save_shuttle_card(book, ShuttleCard.model_validate({**CONFIG, 'areas': [{'state': 'DC', 'zip_codes': []}]}))
        db.commit()
        assert {area.id for area in db.query(PricingShuttleArea)} == kept
        save_shuttle_card(book, None)
        db.commit()
        assert db.query(PricingShuttle).count() == 0 and db.query(PricingShuttleArea).count() == 0
    engine.dispose()


def test_migration_moves_the_first_card_and_deletes_the_json_rows_once():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    PricingShuttleArea.__table__.drop(engine)
    PricingShuttle.__table__.drop(engine)
    with Session(engine) as db:
        book = plan()
        book.services = [
            PricingService(id='card', name='Delivery shuttle', comments=SHUTTLE_PREFIX + json.dumps(CONFIG), sort_order=0),
            PricingService(id='copy', name='Delivery shuttle', comments=SHUTTLE_PREFIX + json.dumps({**CONFIG, 'enabled': False}), sort_order=1),
            PricingService(id='piano', name='Piano', rate_text='150', comments='', sort_order=2),
        ]
        db.add(book)
        db.commit()
    with engine.begin() as connection:
        assert migrate_shuttle_cards(connection) == 1
        assert migrate_shuttle_cards(connection) == 0
        assert [row[0] for row in connection.execute(text('SELECT id FROM pricing_services'))] == ['piano']
    with Session(engine) as db:
        card = plan_shuttle_card(db.get(PricingPlan, 'plan'))
        assert card == ShuttleCard.model_validate(SORTED) and card.rate == Decimal('1.5')
    engine.dispose()
