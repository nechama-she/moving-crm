"""One-time deploy import: open SmartMoving follow-ups assigned to one rep become CRM tasks.

The earlier report run saved, per lead, the rep's open follow-ups it found. This goes over only
the leads where it found some, fetches their follow-ups again (the report kept no follow-up ids),
and stores the open ones assigned to the rep with the same upsert as the lead refresh.
"""
import logging
import os
import sys
from pathlib import Path
from time import sleep

from sqlalchemy import text
from sqlalchemy.orm import Session

from models import AppSetting, Lead, User

REP_NAME = 'Eli Jones'
KEY = 'migration:smartmoving-open-followups:eli-jones:2026-10-28'
REPORT_PREFIX = 'report:smartmoving-followups-open:eli-jones:2026-10-28:lead:'
REQUEST_GAP_SECONDS = 2.1  # About 28 requests a minute, under SmartMoving's limit.
logger = logging.getLogger(__name__)


def run(engine):
    # Keep the shared client importable when invoked by `python migrate.py`.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    with Session(bind=engine) as db:
        if db.get(AppSetting, KEY):
            logger.info('SmartMoving open follow-up import already ran')
            return
        rep = db.query(User).filter(User.name.ilike(REP_NAME)).first()
        if not rep:
            logger.warning('SmartMoving open follow-up import: no CRM user named %s', REP_NAME)
            return
        rep_sm_id = (rep.smartmoving_rep_id or '').strip().lower()
        lead_ids = [
            key[len(REPORT_PREFIX):]
            for (key,) in db.query(AppSetting.key).filter(
                AppSetting.key.startswith(REPORT_PREFIX),
                AppSetting.value != '[]',
            )
        ]
        leads = db.query(Lead).filter(Lead.id.in_(lead_ids)).all() if lead_ids else []

        from config import get_config
        key = os.getenv('SMARTMOVING_API_KEY') or get_config().get('SMARTMOVING_API_KEY')
        if not key:
            logger.warning('SmartMoving open follow-up import skipped: SMARTMOVING_API_KEY is missing')
            return
        os.environ['SMARTMOVING_API_KEY'] = key
        from libs.smartmoving import client
        client.SMARTMOVING_API_KEY = key
        from libs.smartmoving.followup_tasks import UPSERT_TASK

        imported = failures = 0
        for lead in leads:
            sleep(REQUEST_GAP_SECONDS)
            response = client.get_followups(lead.smartmoving_id)
            if response.get('error') or not isinstance(response.get('data'), list):
                failures += 1
                logger.warning('SmartMoving open follow-up import could not load lead %s', lead.id)
                continue
            params = []
            for followup in response['data']:
                if not isinstance(followup, dict) or not followup.get('id'):
                    continue
                if followup.get('completed') or followup.get('completedAtUtc'):
                    continue
                if rep_sm_id and (followup.get('assignedToId') or '').strip().lower() != rep_sm_id:
                    continue
                params.append({
                    'smartmoving_id': lead.smartmoving_id,
                    'note_id': str(followup['id']),
                    'followup_type': followup.get('type'),
                    'title': followup.get('title') or 'Follow-up',
                    'assigned_to_id': followup.get('assignedToId'),
                    'due_date_time_iso': followup.get('dueDateTime'),
                    'notes': followup.get('notes') or '',
                    'completed': False,
                    'completed_at': None,
                    'created_at': None,
                })
            try:
                for values in params:
                    db.execute(text(UPSERT_TASK), values)
                db.commit()
            except Exception:
                db.rollback()
                failures += 1
                logger.exception('SmartMoving open follow-up import failed for lead %s', lead.id)
                continue
            imported += len(params)

        logger.info('SmartMoving open follow-up import for %s: %s tasks from %s leads, %s failed',
                    rep.name, imported, len(leads), failures)
        # Reruns are safe: the upsert updates tasks in place, so failed leads retry on the next deploy.
        if not failures:
            db.add(AppSetting(key=KEY, value='complete'))
            db.commit()
