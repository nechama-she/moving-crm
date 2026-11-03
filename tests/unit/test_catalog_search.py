import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from models import Base, InventoryCatalogItem
from manual_inventory import search_catalog, catalog


def item(id, name, description='', active=True, deleted=False):
    return InventoryCatalogItem(id=id, name=name, description=description, cuft=10, weight=70, active=active, deleted=deleted)


def test_search_returns_only_matching_active_items_and_items_by_id():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([item('tv1', 'TV Flat Screen - 33 - 59'), item('tv2', 'TV Flat Screen - 60 - 79'),
                    item('stand', 'TV Stand'), item('old', 'TV Flat Screen old', active=False),
                    item('gone', 'TV Flat Screen gone', deleted=True), item('pct', '100% Cotton Rug'),
                    item('chair', 'Accent Chair', 'flat seat')]
                   + [item(f'box{n}', f'Book Box {n}') for n in range(60)])
        db.commit()
        assert [row['id'] for row in search_catalog(db, None, 'flat tv')] == ['tv1', 'tv2']
        assert [row['id'] for row in search_catalog(db, None, 'flat')] == ['chair', 'tv1', 'tv2']
        assert [row['id'] for row in search_catalog(db, None, '100%')] == ['pct']
        assert len(search_catalog(db, None, 'book')) == 50
        assert search_catalog(db, None, '   ') == []
        assert {row['id'] for row in search_catalog(db, None, ids=['stand', 'tv2', 'gone'])} == {'stand', 'tv2'}
        # Opening the window loads no catalog items beyond the sets' components.
        assert catalog(db)['items'] == []
    engine.dispose()
