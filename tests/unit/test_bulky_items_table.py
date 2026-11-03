import json
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from models import Base, PricingPlan, PricingService, PricingBulkyItem
from bulky_items import BULKY_ITEM_MARKER, BULKY_ITEM_PREFIX, bulky_service_rows, save_bulky_items, migrate_bulky_items


def plan():
    return PricingPlan(id='plan', source_key='plan', company_name='Co', name='East', source_file='', source_sheet='')


def row(name, handling='', packing='', crating='', id=None):
    prices = {'handling': handling, 'packing': packing, 'crating': crating}
    return SimpleNamespace(id=id, name=name, rate_text=handling, comments=BULKY_ITEM_PREFIX + json.dumps(prices))


def test_items_save_keep_their_ids_and_are_presented_as_the_same_service_rows():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        book = plan()
        book.services = [PricingService(id='piano-service', name='Piano tuning', rate_text='100', comments='', sort_order=0)]
        save_bulky_items(book, [row('Piano Upright', '625', '500', '1500'), row('Pool Table Large', '1250')], first_sort_order=1)
        db.add(book)
        db.commit()
        db.expire_all()
        book = db.get(PricingPlan, 'plan')
        rows = bulky_service_rows(book)
        assert [(r['name'], r['rate_text'], json.loads(r['comments'][len(BULKY_ITEM_PREFIX):])) for r in rows] == [
            ('Piano Upright', '625', {'handling': '625', 'packing': '500', 'crating': '1500'}),
            ('Pool Table Large', '1250', {'handling': '1250', 'packing': '', 'crating': ''})]
        assert [r['name'] for r in book.to_dict()['services']] == ['Piano tuning', 'Piano Upright', 'Pool Table Large']
        piano = rows[0]['id']
        save_bulky_items(book, [row('Piano Upright', '700', id=piano)], first_sort_order=1)
        db.commit()
        assert [(item.id, item.handling, item.packing) for item in db.query(PricingBulkyItem)] == [(piano, Decimal('700'), None)]
        with pytest.raises(HTTPException):
            save_bulky_items(book, [row('Safe', '625', id='unknown')])
        with pytest.raises(HTTPException):
            save_bulky_items(book, [row('Safe', 'call us')])
    engine.dispose()


def test_migration_moves_items_with_their_ids_once():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    PricingBulkyItem.__table__.drop(engine)
    with Session(engine) as db:
        book = plan()
        book.services = [
            PricingService(id='piano', name='Piano Upright', rate_text='625',
                           comments=BULKY_ITEM_PREFIX + json.dumps({'handling': '625', 'packing': '500', 'crating': '1500'}), sort_order=3),
            PricingService(id='safe', name='Safe Small', rate_text='$625', comments=BULKY_ITEM_MARKER, sort_order=4),
            PricingService(id='tuning', name='Piano tuning', rate_text='100', comments='', sort_order=5),
        ]
        db.add(book)
        db.commit()
    with engine.begin() as connection:
        assert migrate_bulky_items(connection) == 2
        assert migrate_bulky_items(connection) == 0
        assert [r[0] for r in connection.execute(text('SELECT id FROM pricing_services'))] == ['tuning']
    with Session(engine) as db:
        items = db.query(PricingBulkyItem).order_by(PricingBulkyItem.sort_order).all()
        assert [(i.id, i.name, i.handling, i.packing, i.crating, i.sort_order) for i in items] == [
            ('piano', 'Piano Upright', Decimal('625'), Decimal('500'), Decimal('1500'), 3),
            ('safe', 'Safe Small', Decimal('625'), None, None, 4)]
    engine.dispose()
