import json
import sys
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from models import Base, PricingPlan, PricingService, PricingExtraStops
from extra_stops import (EXTRA_STOPS_PREFIX, ExtraStopsCard, plan_stops_card, save_stops_card,
                         stops_service_row, migrate_stops_cards)

CONFIG = {'enabled': True, 'pickup': {'free_miles': '10', 'stop_fee': '50', 'per_mile': '5'},
          'delivery': {'free_miles': '0', 'stop_fee': '75.5', 'per_mile': '4.25'}}


def plan():
    return PricingPlan(id='plan', source_key='plan', company_name='Co', name='East', source_file='', source_sheet='')


def test_saved_card_reads_back_and_is_presented_as_the_same_service_row():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        book = plan()
        save_stops_card(book, ExtraStopsCard.model_validate(CONFIG))
        db.add(book)
        db.commit()
        db.expire_all()
        book = db.get(PricingPlan, 'plan')
        assert plan_stops_card(book) == ExtraStopsCard.model_validate(CONFIG)
        row = stops_service_row(book)
        assert row['name'] == 'Additional stops'
        assert json.loads(row['comments'][len(EXTRA_STOPS_PREFIX):]) == CONFIG
        assert row in book.to_dict()['services']
        save_stops_card(book, None)
        db.commit()
        assert db.query(PricingExtraStops).count() == 0
    engine.dispose()


def test_migration_moves_the_first_card_and_deletes_the_json_rows_once():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    PricingExtraStops.__table__.drop(engine)
    with Session(engine) as db:
        book = plan()
        book.services = [
            PricingService(id='card', name='Additional stops', comments=EXTRA_STOPS_PREFIX + json.dumps(CONFIG), sort_order=0),
            PricingService(id='copy', name='Additional stops', comments=EXTRA_STOPS_PREFIX + json.dumps({**CONFIG, 'enabled': False}), sort_order=1),
            PricingService(id='piano', name='Piano', rate_text='150', comments='', sort_order=2),
        ]
        db.add(book)
        db.commit()
    with engine.begin() as connection:
        assert migrate_stops_cards(connection) == 1
        assert migrate_stops_cards(connection) == 0
        assert [row[0] for row in connection.execute(text('SELECT id FROM pricing_services'))] == ['piano']
    with Session(engine) as db:
        card = plan_stops_card(db.get(PricingPlan, 'plan'))
        assert card.enabled is True and card.delivery.stop_fee == Decimal('75.5')
    engine.dispose()
