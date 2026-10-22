import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from test_public_moves import portal


@pytest.mark.parametrize('ready,locked,expected', [(False, False, 1), (True, False, 0), (False, True, 0)])
def test_view_refreshes_stale_price_but_preserves_locked_price(portal, monkeypatch, ready, locked, expected):
    from unittest.mock import Mock
    from models import LeadJob, LeadLiveSwitch
    import price_validity
    mod, db, lead, access = portal
    job = db.get(LeadJob, access.job_id)
    job.price = 100
    job.price_refresh_error = None
    job.customer_packing_package = '{}'
    saved = db.query(LeadLiveSwitch).filter_by(lead_id=lead.id).first()
    if saved is None:
        saved = LeadLiveSwitch(lead_id=lead.id)
        db.add(saved)
    saved.details = json.dumps({'last_spark_status': 'completed', 'spark_pricing_ready': ready})
    db.commit()
    calculate = Mock()
    monkeypatch.setattr(mod, 'recalculate_current_price', calculate)
    monkeypatch.setattr(price_validity, 'price_is_locked', lambda *args: locked)
    monkeypatch.setattr(price_validity, 'refresh_expired_price', Mock())
    mod.refresh_estimate_for_view(access, db)
    assert calculate.call_count == expected


def test_signature_preserves_reviewed_version_and_cannot_be_overwritten(portal, monkeypatch):
    import estimate_pdf
    from models import EstimateSignature
    mod, db, lead, access = portal
    data = {'estimate': {'price': 100, 'charges': []}, 'name': 'Jane',
            'documents': [{'title': 'Terms', 'body_html': '<p>Original wording</p>', 'revision': 1}]}
    monkeypatch.setattr(mod, '_estimate_document', lambda *args: (data, []))
    monkeypatch.setattr(estimate_pdf, 'build_estimate_pdf', lambda snapshot, rows: json.dumps(snapshot).encode())
    version = mod.prepare_estimate_signature(access, db)['id']
    data['estimate']['price'] = 999
    data['documents'][0]['body_html'] = '<p>Later wording</p>'
    body = mod.EstimateSigningInput(name='Jane', consent=True, strokes=[[(.1, .2), (.3, .4)]])
    mod.sign_estimate(version, body, access, db)
    record = db.get(EstimateSignature, version)
    saved_pdf = record.pdf
    assert json.loads(saved_pdf)['estimate']['price'] == 100
    assert json.loads(saved_pdf)['documents'][0]['body_html'] == '<p>Original wording</p>'
    assert json.loads(saved_pdf)['signature']['name'] == 'Jane'
    mod.sign_estimate(version, body.model_copy(update={'name': 'Changed'}), access, db)
    assert record.pdf == saved_pdf
    assert record.signer_name == 'Jane'
    assert mod.list_estimate_signatures(access, db)['items'][0]['id'] == version
    for other in [SimpleNamespace(lead_id='another', job_id=access.job_id),
                  SimpleNamespace(lead_id=access.lead_id, job_id='another')]:
        with pytest.raises(HTTPException) as error:
            mod.signature_pdf(version, other, db)
        assert error.value.status_code == 404


@pytest.mark.parametrize('strokes', [[], [[]], [[(.1, .1)]], [[(.1, .1), (.1, .1)]],
                                    [[(-1, 0), (1, 1)]], [[(float('nan'), 0), (1, 1)]]])
def test_signature_rejects_blank_or_invalid_drawing(portal, strokes):
    mod, *_ = portal
    with pytest.raises(ValidationError):
        mod.EstimateSigningInput(name='Jane', consent=True, strokes=strokes)


def test_pending_estimate_cannot_be_prepared_for_signing(portal, monkeypatch):
    mod, db, _, access = portal
    monkeypatch.setattr(mod, '_estimate_document', lambda *args: ({'estimate': {'charges': [{'pending': True}]}}, []))
    with pytest.raises(HTTPException) as error:
        mod.prepare_estimate_signature(access, db)
    assert error.value.status_code == 409

def test_signature_records_report_and_appears_on_that_report_row(portal, monkeypatch):
    import estimate_pdf
    from datetime import datetime
    from models import EstimateSignature
    from estimate_signature_history import attach_signatures, signed_estimates
    mod, db, lead, access = portal
    data = {'estimate': {'price': 100, 'charges': []}, 'spark': {'id': 'report-2', 'status': 'completed'}}
    monkeypatch.setattr(mod, '_estimate_document', lambda *args: (data, []))
    monkeypatch.setattr(estimate_pdf, 'build_estimate_pdf', lambda snapshot, rows: b'pdf')
    version = mod.prepare_estimate_signature(access, db)['id']
    assert db.get(EstimateSignature, version).report_id == 'report-2'
    # Unsigned versions are not listed.
    assert signed_estimates(db, lead.id) == []
    mod.sign_estimate(version, mod.EstimateSigningInput(name='Jane', consent=True, strokes=[[(.1, .2), (.3, .4)]]), access, db)
    # A signature saved before report_id existed is matched through its snapshot.
    legacy = EstimateSignature(id='legacy', lead_id=lead.id, job_id=access.job_id, pdf=b'old', signer_name='Jane',
                               snapshot=json.dumps({'data': {'spark': {'id': 'report-1'}}, 'rows': []}),
                               signed_at=datetime(2026, 1, 1))
    unreadable = EstimateSignature(id='unreadable', lead_id=lead.id, job_id=access.job_id, pdf=b'old', signer_name='Jane',
                                   snapshot='not json', signed_at=datetime(2025, 1, 1))
    db.add_all([legacy, unreadable]); db.commit()
    signatures = signed_estimates(db, lead.id, access.job_id)
    assert [(row['id'], row['report_id']) for row in signatures] == [(version, 'report-2'), ('legacy', 'report-1'), ('unreadable', None)]
    assert signed_estimates(db, lead.id, 'another-job') == []
    reports = attach_signatures([{'id': 'report-2'}, {'id': 'report-1'}, {'id': 'report-0'}], signatures)
    assert [row['id'] for row in reports[0]['signatures']] == [version]
    assert reports[1]['signatures'] == [{'id': 'legacy', 'name': 'Jane', 'signed_at': '2026-01-01T00:00:00Z'}]
    assert reports[2]['signatures'] == []
    assert mod.list_estimate_signatures(access, db)['items'][0]['report_id'] == 'report-2'

def test_staff_report_history_lists_signatures_and_serves_only_signed_pdfs(portal):
    import ast
    from datetime import datetime
    from pathlib import Path
    from unittest.mock import MagicMock
    from fastapi import Response
    from models import EstimateSignature, LeadLiveSwitch
    from spark_history import report_history
    from estimate_signature_history import attach_signatures, signed_estimates
    _, db, lead, access = portal
    source = Path(__file__).resolve().parents[2] / 'backend/routes/liveswitch.py'
    names = {'get_report_history', 'get_signed_estimate_pdf'}
    functions = [n for n in ast.parse(source.read_text(encoding='utf-8')).body if isinstance(n, ast.FunctionDef) and n.name in names]
    for node in functions:
        node.decorator_list = []
        node.returns = None
        node.args.defaults = []
        for arg in node.args.args:
            arg.annotation = None
    visible = MagicMock(return_value=lead)
    scope = {'json': json, 'HTTPException': HTTPException, 'Response': Response, 'LeadLiveSwitch': LeadLiveSwitch,
             '_get_visible_lead_or_404': visible, 'report_history': report_history,
             'attach_signatures': attach_signatures, 'signed_estimates': signed_estimates}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), 'exec'), scope)
    db.add(LeadLiveSwitch(lead_id=lead.id, details=json.dumps({'last_spark_id': 'report-1', 'last_spark_status': 'completed', 'last_spark_at': 1})))
    db.add_all([EstimateSignature(id='signed', lead_id=lead.id, job_id=access.job_id, report_id='report-1', pdf=b'signed-pdf',
                                  snapshot='{}', signer_name='Jane', signed_at=datetime(2026, 10, 21)),
                EstimateSignature(id='draft', lead_id=lead.id, job_id=access.job_id, report_id='report-1', pdf=b'draft', snapshot='{}')])
    db.commit()
    reports = scope['get_report_history'](lead.id, None, db)['reports']
    assert [row['id'] for row in reports[0]['signatures']] == ['signed']
    assert scope['get_signed_estimate_pdf'](lead.id, 'signed', None, db).body == b'signed-pdf'
    for signature_id in ['draft', 'missing']:
        with pytest.raises(HTTPException) as error:
            scope['get_signed_estimate_pdf'](lead.id, signature_id, None, db)
        assert error.value.status_code == 404
    visible.side_effect = HTTPException(404, 'Lead not found')
    with pytest.raises(HTTPException):
        scope['get_signed_estimate_pdf'](lead.id, 'signed', None, db)

