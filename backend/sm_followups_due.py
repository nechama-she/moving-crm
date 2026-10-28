"""One-time deploy report: all open SmartMoving follow-ups assigned to one rep.

SmartMoving only returns follow-ups per opportunity, so this checks the rep's CRM leads
with a priority above 0 (except 6) and a service date of DAY or later, and writes the list to the deploy log.
Changes no CRM data; it only stores its own progress in app_settings.
"""
import json
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path
from time import monotonic, sleep
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from models import AppSetting, Lead, LeadJob, User

REP_NAME = 'Eli Jones'
DAY = date(2026, 10, 28)
KEY = 'report:smartmoving-followups-open:eli-jones:2026-10-28'
EASTERN = ZoneInfo('America/New_York')
BUDGET_SECONDS = 100 * 60  # The deploy project times out at 120 minutes.
REQUEST_GAP_SECONDS = 2.1
logger = logging.getLogger(__name__)


def parse_service_date(value):
    text = (value or '').strip()
    for fmt in ('%Y-%m-%d', '%m/%d/%Y'):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


def parse_due(value):
    text = (value or '').strip()
    if not text:
        return None
    parsed = datetime.fromisoformat(text.replace('Z', '+00:00'))
    # Values without an offset are already in the company's local (Eastern) time.
    return parsed.astimezone(EASTERN) if parsed.tzinfo else parsed.replace(tzinfo=EASTERN)


def run(engine):
    # Keep the shared client importable when invoked by `python migrate.py`.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    with Session(bind=engine) as db:
        if db.get(AppSetting, KEY):
            logger.info('SmartMoving follow-up report already ran')
            return
        rep = db.query(User).filter(User.name.ilike(REP_NAME)).first()
        if not rep:
            logger.warning('SmartMoving follow-up report: no CRM user named %s', REP_NAME)
            return
        rep_sm_id = (rep.smartmoving_rep_id or '').strip().lower()
        all_leads = (
            db.query(Lead)
            .filter(
                Lead.assigned_to == rep.id,
                Lead.smartmoving_id.isnot(None),
                Lead.smartmoving_id != '',
                Lead.priority > 0,  # Leaves out priority 0 and no priority.
                Lead.priority != 6,
            )
            .all()
        )
        job_dates = {}
        for lead_id, move_date in db.query(LeadJob.lead_id, LeadJob.move_date).filter(LeadJob.lead_id.in_([lead.id for lead in all_leads])):
            job_dates.setdefault(lead_id, []).append(move_date)
        # Service date today or later on the lead or any of its jobs.
        leads = [
            lead for lead in all_leads
            if any((parsed := parse_service_date(value)) and parsed >= DAY for value in [lead.move_date, *job_dates.get(lead.id, [])])
        ]

        from config import get_config
        key = os.getenv('SMARTMOVING_API_KEY') or get_config().get('SMARTMOVING_API_KEY')
        if not key:
            logger.warning('SmartMoving follow-up report skipped: SMARTMOVING_API_KEY is missing')
            return
        os.environ['SMARTMOVING_API_KEY'] = key
        from libs.smartmoving import client
        client.SMARTMOVING_API_KEY = key

        # About 28 requests a minute stays under SmartMoving's limit without 429 waits, and the
        # time budget keeps the deploy inside its timeout. Each lead's result is
        # saved, so the next deploy continues where this one stopped.
        deadline = monotonic() + BUDGET_SECONDS
        checked = failures = 0
        for lead in leads:
            progress_key = f'{KEY}:lead:{lead.id}'
            if db.get(AppSetting, progress_key):
                continue
            if monotonic() >= deadline:
                break
            sleep(REQUEST_GAP_SECONDS)
            response = client.get_followups(lead.smartmoving_id)
            if response.get('error'):
                failures += 1
                continue
            found = []
            for followup in response.get('data') or []:
                if followup.get('completed') or followup.get('completedAtUtc'):
                    continue
                if rep_sm_id and (followup.get('assignedToId') or '').strip().lower() != rep_sm_id:
                    continue
                found.append({'due': followup.get('dueDateTime') or '', 'title': followup.get('title') or 'Follow-up'})
            db.add(AppSetting(key=progress_key, value=json.dumps(found)))
            db.commit()
            checked += 1

        done = {lead.id for lead in leads if db.get(AppSetting, f'{KEY}:lead:{lead.id}')}
        logger.info('SmartMoving follow-up report for %s: checked %s leads this deploy, %s of %s done, %s failed '
                    '(%s prioritized leads, %s with a service date on or after %s)',
                    rep.name, checked, len(done), len(leads), failures, len(all_leads), len(leads), DAY.isoformat())
        if len(done) < len(leads):
            logger.info('SmartMoving follow-up report will continue on the next deploy')
            return

        rows = []
        for lead in leads:
            for item in json.loads(db.get(AppSetting, f'{KEY}:lead:{lead.id}').value):
                try:
                    due = parse_due(item['due'])
                except ValueError:
                    due = None
                rows.append((due, lead, item['title']))
        rows.sort(key=lambda row: (row[0] is None, row[0] or datetime.min.replace(tzinfo=EASTERN)))
        logger.info('SmartMoving follow-ups for %s: %s open', rep.name, len(rows))
        for due, lead, title in rows:
            logger.info('  %s | %s | %s | opportunity %s', due.strftime('%m/%d/%Y %I:%M %p') if due else 'no due date',
                        lead.full_name, title, lead.smartmoving_id)
        db.add(AppSetting(key=KEY, value='complete'))
        db.commit()
