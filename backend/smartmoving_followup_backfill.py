"""One-time remote refresh and task import, resumable per lead."""
import json
import logging
import os
import re
from pathlib import Path
import sys

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from models import AppSetting, Lead

KEY = 'migration:smartmoving-followup-import-v1'
LOCK = 73910251
logger = logging.getLogger(__name__)
# Same status codes as the normal SmartMoving lead refresh.
STATUSES = {0: 'new', 1: 'contacted', 3: 'quoted', 4: 'booked',
            10: 'completed', 11: 'completed', 20: 'cancelled', 30: 'lost', 50: 'lost'}


def refresh_one(db, lead, check, import_tasks):
    result = check(lead.smartmoving_id)
    if not result.get('ok'):
        raise ValueError('SmartMoving lead refresh failed')
    if result.get('exists') is False:
        return 'not_found'
    try:
        status = STATUSES[int(result['status'])]
    except (KeyError, TypeError, ValueError):
        raise ValueError('SmartMoving returned an unknown lead status')
    raw = result.get('lead_status')
    if raw is None or raw == '':
        priority = 0  # CRM priority is NOT NULL; unset remote priority imports no tasks.
    else:
        match = re.fullmatch(r'(?:Priority\s*)?(\d+)', str(raw).strip(), re.IGNORECASE)
        if not match:
            raise ValueError('SmartMoving returned an invalid priority')
        priority = int(match[1])
    lead.status = status
    lead.priority = priority
    db.flush()
    count = import_tasks(db, lead, commit=False) if priority else 0
    return f'imported:{count}' if priority else 'skipped_priority_zero'


def run(engine):
    # Keep the shared client importable when invoked by `python migrate.py`.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    with engine.connect() as connection:
        acquired = connection.execute(text('SELECT pg_try_advisory_lock(:key)'), {'key': LOCK}).scalar()
        connection.commit()
        if not acquired:
            raise RuntimeError('SmartMoving follow-up migration is already running')
        try:
            with Session(bind=connection) as db:
                marker = db.get(AppSetting, KEY)
                if marker and marker.value == 'complete':
                    logger.info('SmartMoving follow-up import already complete')
                    return
                manifest = db.get(AppSetting, KEY + ':leads')
                if manifest is None:
                    ids = list(db.scalars(select(Lead.id).where(Lead.smartmoving_id.isnot(None), Lead.smartmoving_id != '').order_by(Lead.id)))
                    manifest = AppSetting(key=KEY + ':leads', value=json.dumps(ids))
                    db.add(manifest)
                    db.commit()
                ids = json.loads(manifest.value)
                from config import get_config
                key = os.getenv('SMARTMOVING_API_KEY') or get_config().get('SMARTMOVING_API_KEY')
                if ids and not key:
                    raise RuntimeError('SMARTMOVING_API_KEY is required for the one-time follow-up import')
                if key:
                    os.environ['SMARTMOVING_API_KEY'] = key
                from libs.smartmoving import client
                client.SMARTMOVING_API_KEY = key or ''
                from smartmoving_followup_sync import sync
                failures = 0
                for index, lead_id in enumerate(ids, 1):
                    progress_key = KEY + ':' + lead_id
                    if db.get(AppSetting, progress_key):
                        continue
                    try:
                        lead = db.get(Lead, lead_id)
                        with client.bulk_requests():
                            outcome = refresh_one(db, lead, client.check_opportunity_exists, sync) if lead and lead.smartmoving_id else 'no_longer_available'
                        db.add(AppSetting(key=progress_key, value=outcome))
                        db.commit()
                        logger.info('SmartMoving migration %s/%s lead=%s %s', index, len(ids), lead_id, outcome)
                    except Exception as exc:
                        db.rollback()
                        failures += 1
                        # Do not log remote payloads, credentials, or SQL parameters.
                        logger.error('SmartMoving migration failed for lead=%s (%s); will retry', lead_id, type(exc).__name__)
                if failures:
                    raise RuntimeError(f'{failures} SmartMoving lead imports failed; successful leads are saved. Rerun to retry.')
                db.merge(AppSetting(key=KEY, value='complete'))
                db.commit()
                logger.info('One-time SmartMoving follow-up import complete: %s leads', len(ids))
        finally:
            connection.rollback()
            connection.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': LOCK})
            connection.commit()
