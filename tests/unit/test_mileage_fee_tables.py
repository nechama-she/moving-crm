import json
import sys
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from models import Base, PricingPlan, PricingService, PricingMileageFee, PricingMileageFeeRule, PricingMileageFeeZip
from delivery_fees import (ORIGIN_FEE_PREFIX, DELIVERY_FEE_PREFIX, DeliveryFeeCard, delivery_fee_card, save_fee_card,
                           fee_service_row, migrate_fee_cards)

CONFIG = {'enabled': True, 'rules': [
    {'state': 'VT', 'zip_codes': [], 'origin_zip': '20815', 'rate_per_mile': '5'},
    {'state': 'VT', 'zip_codes': ['05401', '050XX-051XX'], 'origin_zip': '20815', 'rate_per_mile': '7.5'}]}
SORTED = {**CONFIG, 'rules': [CONFIG['rules'][0], {**CONFIG['rules'][1], 'zip_codes': ['050XX-051XX', '05401']}]}


def plan():
    return PricingPlan(id='plan', source_key='plan', company_name='Co', name='East', source_file='', source_sheet='')


def test_both_kinds_save_read_back_and_are_presented_as_service_rows():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        book = plan()
        save_fee_card(book, ORIGIN_FEE_PREFIX, DeliveryFeeCard.model_validate(CONFIG))
        save_fee_card(book, DELIVERY_FEE_PREFIX, DeliveryFeeCard.model_validate({**CONFIG, 'enabled': False}))
        db.add(book)
        db.commit()
        db.expire_all()
        book = db.get(PricingPlan, 'plan')
        assert delivery_fee_card(book, ORIGIN_FEE_PREFIX) == DeliveryFeeCard.model_validate(SORTED)
        assert delivery_fee_card(book, DELIVERY_FEE_PREFIX).enabled is False
        origin = fee_service_row(book, ORIGIN_FEE_PREFIX)
        assert origin['name'] == 'Origin fees'
        assert json.loads(origin['comments'][len(ORIGIN_FEE_PREFIX):]) == SORTED
        assert fee_service_row(book, DELIVERY_FEE_PREFIX)['name'] == 'Destination fees'
        assert origin in book.to_dict()['services']
        # Fewer rules and ZIP codes on a later save; removing a card removes its rows.
        save_fee_card(book, ORIGIN_FEE_PREFIX, DeliveryFeeCard.model_validate({**CONFIG, 'rules': [
            {**CONFIG['rules'][0], 'zip_codes': ['05401']}]}))
        db.commit()
        assert db.query(PricingMileageFeeRule).filter_by(kind='origin').count() == 1
        assert [row.zip_code for row in db.query(PricingMileageFeeZip).filter_by(kind='origin')] == ['05401']
        save_fee_card(book, DELIVERY_FEE_PREFIX, None)
        db.commit()
        assert [row.kind for row in db.query(PricingMileageFee)] == ['origin']
        assert db.query(PricingMileageFeeZip).filter_by(kind='delivery').count() == 0
    engine.dispose()


def test_migration_moves_both_kinds_once():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    for model in (PricingMileageFeeZip, PricingMileageFeeRule, PricingMileageFee):
        model.__table__.drop(engine)
    with Session(engine) as db:
        book = plan()
        book.services = [
            PricingService(id='origin', name='Origin fees', comments=ORIGIN_FEE_PREFIX + json.dumps(CONFIG), sort_order=0),
            PricingService(id='delivery', name='Destination fees', comments=DELIVERY_FEE_PREFIX + json.dumps(CONFIG), sort_order=1),
            PricingService(id='piano', name='Piano', rate_text='150', comments='', sort_order=2),
        ]
        db.add(book)
        db.commit()
    with engine.begin() as connection:
        assert migrate_fee_cards(connection) == 2
        assert migrate_fee_cards(connection) == 0
        assert [row[0] for row in connection.execute(text('SELECT id FROM pricing_services'))] == ['piano']
    with Session(engine) as db:
        book = db.get(PricingPlan, 'plan')
        for prefix in (ORIGIN_FEE_PREFIX, DELIVERY_FEE_PREFIX):
            assert delivery_fee_card(book, prefix) == DeliveryFeeCard.model_validate(SORTED)
    engine.dispose()
