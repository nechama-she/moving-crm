import ast
import sys
from pathlib import Path
from types import SimpleNamespace as Row

import pytest
from fastapi import Depends, HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

BACKEND = Path(__file__).resolve().parents[2] / 'backend'
sys.path.insert(0, str(BACKEND))
from pricing_row_updates import prepare_row_updates
from local_pricing import LocalSettings
import models


def test_reorder_and_rename_use_existing_ids():
    a, b = Row(id='a', title='A', description='A'), Row(id='b', title='B', description='B')
    rows = [Row(id='b', title='Renamed', description='New'), Row(id='a', title='A', description='New')]
    assert [match for match, _ in prepare_row_updates([a,b], rows, ('title',), ('description',))] == [b,a]


@pytest.mark.parametrize('rows', [
    [Row(id='unknown', title='A', description='New')],
    [Row(id='a', title='A', description='New'), Row(id='a', title='A', description='New')],
    [Row(id='a', title='A', description='')],
])
def test_invalid_ids_and_blank_existing_rows_cannot_recreate(rows):
    original = Row(id='a', title='A', description='Old')
    with pytest.raises(HTTPException):
        prepare_row_updates([original], rows, ('title',), ('description',))
    assert original.description == 'Old'


def test_new_row_has_no_existing_match():
    assert prepare_row_updates([], [Row(id=None,title='New',description='New')], ('title',), ('description',))[0][0] is None


def test_local_settings_update_never_touches_company_routes():
    source = BACKEND / 'routes/local_pricing.py'
    node = next(n for n in ast.parse(source.read_text()).body if getattr(n,'name','') == 'save_settings')
    node.decorator_list = []
    plan = Row(id='plan', company_id='company')
    scope = dict(LocalSettingsPayload=LocalSettings, User=models.User, Session=Session,
                 Depends=Depends, require_admin=lambda:None, get_db=lambda:None,
                 _plan_and_company=lambda *args:plan, LocalSettings=LocalSettings, AppSetting=models.AppSetting,
                 load_routes=lambda company_id,db:db.query(models.LocalPricingRoute).filter_by(company_id=company_id).all())
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),'exec'),scope)
    engine = create_engine('sqlite://')
    models.Base.metadata.create_all(engine)
    with Session(engine) as db:
        route = models.LocalPricingRoute(id='route',company_id='company',pickup='MD',delivery='VA')
        db.add_all([route,models.AppSetting(key='local_pricing:plan',value=LocalSettings().model_dump_json())])
        db.commit()
        statements=[]
        event.listen(engine,'before_cursor_execute',lambda conn,cursor,sql,params,context,many:statements.append(sql))
        for rate in (0, 80):
            result = scope['save_settings']('plan',LocalSettings(full_pack_hourly=rate),Row(),db)
            assert db.get(models.LocalPricingRoute,'route') is route
            assert result['routes'][0]['id'] == 'route'
        assert not any(sql.lstrip().upper().startswith(('DELETE ', 'INSERT ')) for sql in statements)
    engine.dispose()
