import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest

@pytest.mark.parametrize('page,expected',[(None,False),(('page-1',),True)])
def test_lead_response_includes_page_existence(page,expected):
    source=Path(__file__).resolve().parents[2]/'backend/routes/leads.py'
    node=next(n for n in ast.parse(source.read_text(encoding='utf-8')).body if getattr(n,'name','')=='get_lead')
    node.decorator_list=[];node.args.defaults=[];node.returns=None
    for arg in node.args.args:arg.annotation=None
    lead=SimpleNamespace(id='lead-1',facebook_user_id=None,source='',to_dict=lambda:{'id':'lead-1'})
    db=MagicMock();db.query.return_value.filter.return_value.first.return_value=page
    scope={'_get_visible_lead_or_404':lambda *args:lead,'PublicMoveAccess':SimpleNamespace(id='id',lead_id='lead_id')}
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),'exec'),scope)
    result=scope['get_lead']('lead-1',SimpleNamespace(role='foreman'),db)
    assert result['has_customer_page'] is expected
    db.query.assert_called_once()
