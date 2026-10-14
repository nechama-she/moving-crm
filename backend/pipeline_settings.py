"""One-time configuration promotion inside the existing deployment pipeline.

The dev deployment freezes a private snapshot per release ID. Production imports
it transactionally once; retries and later deployments preserve production edits.
"""
import hashlib
import json
import os
import re
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from settings_transfer import TABLES, apply_settings, export_settings, table, validate


def serialize(value):
    return json.dumps(value, sort_keys=True, default=lambda v: str(v) if isinstance(v, Decimal) else str(v)).encode('utf-8')


def read_release():
    release = json.loads((Path(__file__).resolve().parents[1] / 'settings-release.json').read_text(encoding='utf-8'))
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', release['release_id']):
        raise ValueError('Invalid settings release ID')
    return release


def decode_snapshot(body, release_id, account):
    snapshot = json.loads(body)
    if snapshot['release_id'] != release_id or snapshot['source_account'] != account:
        raise ValueError('Settings snapshot belongs to a different release or account')
    bundle = snapshot['bundle']
    if hashlib.sha256(serialize(bundle)).hexdigest() != snapshot['sha256']:
        raise ValueError('Settings snapshot checksum mismatch')
    validate(bundle)
    if not bundle['tables']['companies']:
        raise ValueError('Empty settings snapshot')
    return snapshot


def apply_once(connection, snapshot):
    release_id = snapshot['release_id']
    key = 'migration:settings-release:' + release_id
    settings = table('app_settings')
    existing = connection.execute(select(settings.c.value).where(settings.c.key == key)).scalar()
    if existing:
        if json.loads(existing)['sha256'] != snapshot['sha256']:
            raise ValueError('Previously imported release has a different checksum')
        return False
    apply_settings(connection, snapshot['bundle'])
    connection.execute(settings.insert().values(key=key, value=json.dumps({
        'sha256': snapshot['sha256'], 'source_revision': snapshot['source_revision']})))
    return True


def run(mode, engine, s3, account):
    release = read_release()
    if not release['enabled']:
        print('Settings promotion disabled')
        return
    environment = os.environ['ENVIRONMENT']
    expected = os.environ['SETTINGS_SOURCE_ACCOUNT_ID' if environment == 'dev' else 'SETTINGS_PRODUCTION_ACCOUNT_ID']
    if account != expected:
        raise ValueError('Settings promotion AWS account mismatch')
    release_id = release['release_id']
    source_account = os.environ['SETTINGS_SOURCE_ACCOUNT_ID']
    bucket = 'moving-crm-settings-dev-' + source_account
    key = 'releases/' + release_id + '.json'
    if mode == 'publish' and environment == 'dev':
        with engine.connect() as connection:
            connection.exec_driver_sql('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            bundle = export_settings(connection)
        snapshot = {'release_id': release_id, 'source_account': account,
                    # Deploy consumes BuildOutput; a resolved Git revision may
                    # not be supplied. It is audit metadata, not release identity.
                    'source_revision': os.environ.get('CODEBUILD_RESOLVED_SOURCE_VERSION') or None,
                    'source_build_id': os.environ.get('CODEBUILD_BUILD_ID') or None,
                    'bundle': bundle, 'sha256': hashlib.sha256(serialize(bundle)).hexdigest()}
        body = serialize(snapshot)
        decode_snapshot(body, release_id, account)
        from botocore.exceptions import ClientError
        try:
            s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType='application/json',
                          ServerSideEncryption='AES256', IfNoneMatch='*')
            print('Published private settings snapshot: ' + release_id)
        except ClientError as error:
            if error.response['Error']['Code'] != 'PreconditionFailed':
                raise
            # A release is frozen, even if dev settings change afterwards.
            decode_snapshot(s3.get_object(Bucket=bucket, Key=key)['Body'].read(), release_id, account)
            print('Settings snapshot already frozen: ' + release_id)
    elif mode in ('check', 'apply') and environment == 'prod':
        snapshot = decode_snapshot(s3.get_object(Bucket=bucket, Key=key)['Body'].read(), release_id, source_account)
        if mode == 'check':
            print('Settings snapshot verified: ' + release_id)
            print('Configuration rows: ' + json.dumps({name: len(rows) for name, rows in snapshot['bundle']['tables'].items()}))
            return
        with engine.begin() as connection:
            connection.exec_driver_sql("SET LOCAL lock_timeout = '10s'")
            connection.exec_driver_sql('LOCK TABLE ' + ', '.join((*TABLES, 'app_settings')) + ' IN SHARE ROW EXCLUSIVE MODE')
            applied = apply_once(connection, snapshot)
        print(('Imported settings release: ' if applied else 'Settings release already imported: ') + release_id)
    else:
        raise ValueError('Settings promotion mode does not match environment')


if __name__ == '__main__':
    import sys
    environment = os.environ['ENVIRONMENT']
    if environment not in ('dev', 'prod'):
        print('No settings promotion for ' + environment)
    else:
        import boto3
        from database import engine
        run(sys.argv[1], engine, boto3.client('s3'), boto3.client('sts').get_caller_identity()['Account'])
