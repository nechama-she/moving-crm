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
