import hashlib
import io
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
import pipeline_settings as pipeline
from models import Base, Company, AppSetting
from settings_transfer import export_settings


@pytest.fixture
def promotion():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(Company.__table__.insert().values(id='company', name='Moving Co', phone='old'))
        bundle = export_settings(connection)
    bundle['tables']['companies'][0]['phone'] = 'imported'
    snapshot = {'release_id': 'test', 'source_account': '123', 'source_revision': 'commit',
                'bundle': bundle, 'sha256': hashlib.sha256(pipeline.serialize(bundle)).hexdigest()}
    yield engine, snapshot
    engine.dispose()


def test_retry_preserves_later_production_changes(promotion):
    engine, snapshot = promotion
    with engine.begin() as connection:
        assert pipeline.apply_once(connection, snapshot)
    with engine.begin() as connection:
        connection.execute(Company.__table__.update().values(phone='edited in prod'))
    with engine.begin() as connection:
        assert not pipeline.apply_once(connection, snapshot)
        assert connection.execute(select(Company.phone)).scalar() == 'edited in prod'


def test_changed_release_is_rejected(promotion):
    engine, snapshot = promotion
    with engine.begin() as connection:
        pipeline.apply_once(connection, snapshot)
    snapshot['sha256'] = 'different'
    with engine.begin() as connection, pytest.raises(ValueError, match='different checksum'):
        pipeline.apply_once(connection, snapshot)


def test_failed_import_does_not_mark_release_complete(promotion):
    engine, snapshot = promotion
    snapshot['bundle']['tables']['app_settings'].append({'key': 'local_pricing:missing', 'value': '{}'})
    with pytest.raises(KeyError):
        with engine.begin() as connection:
            pipeline.apply_once(connection, snapshot)
    with engine.connect() as connection:
        assert connection.execute(select(AppSetting.key)).first() is None
        assert connection.execute(select(Company.phone)).scalar() == 'old'


def test_snapshot_integrity_and_identity(promotion):
    _, snapshot = promotion
    assert pipeline.decode_snapshot(pipeline.serialize(snapshot), 'test', '123') == snapshot
    with pytest.raises(ValueError, match='different release'):
        pipeline.decode_snapshot(pipeline.serialize(snapshot), 'other', '123')
    snapshot['bundle']['tables']['companies'][0]['phone'] = 'tampered'
    with pytest.raises(ValueError, match='checksum'):
        pipeline.decode_snapshot(pipeline.serialize(snapshot), 'test', '123')


def test_preflight_does_not_connect_to_database(monkeypatch, promotion):
    _, snapshot = promotion
    monkeypatch.setenv('ENVIRONMENT', 'prod')
    monkeypatch.setenv('SETTINGS_SOURCE_ACCOUNT_ID', '123')
    monkeypatch.setenv('SETTINGS_PRODUCTION_ACCOUNT_ID', '456')
    monkeypatch.setattr(pipeline, 'read_release', lambda: {'enabled': True, 'release_id': 'test'})

    class S3:
        def get_object(self, **kwargs):
            assert kwargs == {'Bucket': 'moving-crm-settings-dev-123', 'Key': 'releases/test.json'}
            return {'Body': io.BytesIO(pipeline.serialize(snapshot))}

    pipeline.run('check', None, S3(), '456')
    with pytest.raises(ValueError, match='account mismatch'):
        pipeline.run('check', None, S3(), 'wrong-account')


def test_dev_publish_preserves_frozen_release(monkeypatch, promotion):
    from botocore.exceptions import ClientError
    _, snapshot = promotion
    monkeypatch.setenv('ENVIRONMENT', 'dev')
    monkeypatch.setenv('SETTINGS_SOURCE_ACCOUNT_ID', '123')
    monkeypatch.setenv('CODEBUILD_RESOLVED_SOURCE_VERSION', 'new-commit')
    monkeypatch.setattr(pipeline, 'read_release', lambda: {'enabled': True, 'release_id': 'test'})

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def exec_driver_sql(self, sql):
            assert sql.endswith('READ ONLY')

    class Engine:
        def connect(self):
            return Connection()

    class S3:
        def put_object(self, **kwargs):
            assert kwargs['IfNoneMatch'] == '*'
            assert kwargs['ServerSideEncryption'] == 'AES256'
            pipeline.decode_snapshot(kwargs['Body'], 'test', '123')
            raise ClientError({'Error': {'Code': 'PreconditionFailed'}}, 'PutObject')

        def get_object(self, **kwargs):
            return {'Body': io.BytesIO(pipeline.serialize(snapshot))}

    monkeypatch.setattr(pipeline, 'export_settings', lambda connection: snapshot['bundle'])
    pipeline.run('publish', Engine(), S3(), '123')
