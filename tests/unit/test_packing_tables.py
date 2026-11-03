import json
import sys
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from models import Base, PricingPlan, PricingService, PricingPacking, PricingMaterial
from long_distance_packing import (PACKING_CARD_PREFIX, PackingCard, plan_packing_card, save_packing_card,
                                   packing_service_row, migrate_packing_cards)

CONFIG = {'full': '1.5', 'partial': '1', 'unpacking': None,
          'items': [{'id': 'tv', 'name': 'TV 70"', 'labor_price': '65', 'material_price': '20'}],
          'materials': [
              {'id': 'book', 'name': 'Book Box: 2 CU', 'material_price': '10', 'packing_price': '6', 'unpacking_price': '0'},
              {'id': 'queen', 'name': 'Mattress Bag (Queen)', 'material_price': '26', 'packing_price': '12', 'unpacking_price': '0',
               'capacity_unit': 'mattress_size', 'mattress_size': 'queen'},
              {'id': 'tv-box', 'name': 'TV Box up to 59 inches', 'material_price': '32', 'packing_price': '20', 'unpacking_price': '0',
               'capacity': '59', 'capacity_unit': 'inches'}]}


def plan():
    return PricingPlan(id='plan', source_key='plan', company_name='Co', name='East', source_file='', source_sheet='')


def stored_without_legacy():
    return PackingCard.model_validate({**CONFIG, 'items': []})


def test_migration_keeps_materials_and_ids_and_drops_the_legacy_list():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    PricingMaterial.__table__.drop(engine)
    PricingPacking.__table__.drop(engine)
    with Session(engine) as db:
        book = plan()
        book.services = [
            PricingService(id='card', name='Long-distance packing', comments=PACKING_CARD_PREFIX + json.dumps(CONFIG), sort_order=0),
            PricingService(id='piano', name='Piano', rate_text='150', comments='', sort_order=1)]
        db.add(book)
        db.commit()
    with engine.begin() as connection:
        assert migrate_packing_cards(connection) == 1
        assert migrate_packing_cards(connection) == 0
        assert [r[0] for r in connection.execute(text('SELECT id FROM pricing_services'))] == ['piano']
    with Session(engine) as db:
        book = db.get(PricingPlan, 'plan')
        card = plan_packing_card(book)
        # Every derived value (default box size, matching rules) is identical to reading the old JSON.
        assert card.model_dump() == stored_without_legacy().model_dump()
        assert [m.id for m in card.materials] == ['book', 'queen', 'tv-box']
        assert card.materials[0].box_capacity_cuft == Decimal('2')
        row = packing_service_row(book)
        # The page gets the same shape back, and saving it again changes nothing.
        resaved = PackingCard.model_validate_json(row['comments'][len(PACKING_CARD_PREFIX):])
        assert resaved.model_dump() == card.model_dump()
    engine.dispose()


def test_saving_materials_keeps_ids_and_removing_the_card_removes_its_rows():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        book = plan()
        save_packing_card(book, stored_without_legacy())
        db.add(book)
        db.commit()
        card = plan_packing_card(book)
        save_packing_card(book, PackingCard.model_construct(full=Decimal('2'), partial=card.partial, unpacking=None,
                                                            items=[], materials=card.materials[1:]))
        db.commit()
        db.expire_all()
        book = db.get(PricingPlan, 'plan')
        assert plan_packing_card(book).full == Decimal('2')
        assert [m.material_id for m in db.query(PricingMaterial).order_by(PricingMaterial.sort_order)] == ['queen', 'tv-box']
        save_packing_card(book, None)
        db.commit()
        assert db.query(PricingPacking).count() == 0 and db.query(PricingMaterial).count() == 0
    engine.dispose()
