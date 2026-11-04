"""A rep's approval holds for the exact estimate copy approved. Any saved change to what the estimate
shows clears it, from any route or worker, so the customer signs only what the rep approved."""
import json

from sqlalchemy import event, inspect, or_, select, update
from sqlalchemy.orm import Session

# Job columns that record how the page was worked out, not what the estimate shows.
_JOB_BOOKKEEPING = {'pricing_match_key', 'pricing_plan_id', 'pricing_move_type',
                    'price_refresh_attempted_at', 'price_refresh_error', 'price_calculated_at', 'updated_at',
                    'estimate_approved_id', 'estimate_approved_at',
                    'crew_size', 'trucks', 'start_time', 'estimated_hours', 'travel_hours'}
_LEAD_SHOWN = {'full_name', 'phone', 'email', 'volume', 'weight', 'move_type', 'estimated_total', 'company_id'}
_ACCESS_SHOWN = {'published_price', 'published_cuft'}
_COMPANY_SHOWN = {'name', 'phone', 'office_address', 'logo', 'color', 'dot_number'}
# The conversation record's parts the estimate shows: the inventory and the answers about it.
_CONVERSATION_SHOWN = ('spark_inventory_snapshot', 'question_original_rows', 'report_question_answers',
                       'question_excluded_items', 'manual_rooms', 'last_spark_id', 'spark_pricing_ready')


def _changed(session, row, only=None, ignore=()):
    if row in session.new or row in session.deleted:
        return True
    state = inspect(row)
    for attr in state.mapper.column_attrs:
        if (only is not None and attr.key not in only) or attr.key in ignore:
            continue
        history = state.attrs[attr.key].history
        if history.added and (not history.deleted or history.added[0] != history.deleted[0]):
            return True
    return False


def _conversation_changed(session, row):
    if row in session.new or row in session.deleted:
        return True
    history = inspect(row).attrs['details'].history
    if not history.added:
        return False
    if not history.deleted:
        return True  # The previous value was not loaded; count it as changed.
    try:
        old, new = json.loads(history.deleted[0] or '{}'), json.loads(history.added[0] or '{}')
    except ValueError:
        return True
    return any(old.get(key) != new.get(key) for key in _CONVERSATION_SHOWN)


@event.listens_for(Session, 'before_flush')
def _clear_changed_approvals(session, context, instances):
    from models import (Company, CompanyDocument, InventoryEditItem, InventoryEditRoom, Lead, LeadContact, LeadJob, LeadJobCharge,
                        LeadLiveSwitch, PublicMoveAccess, AppSetting)
    from routes.leads import JOB_DELIVERIES_SETTING_PREFIX, JOB_PICKUPS_SETTING_PREFIX, JOB_STOPS_SETTING_PREFIX
    jobs, leads, companies = set(), set(), set()
    for row in (*session.new, *session.dirty, *session.deleted):
        if isinstance(row, LeadJob):
            if _changed(session, row, ignore=_JOB_BOOKKEEPING):
                jobs.add(row.id)
        elif isinstance(row, (LeadJobCharge, InventoryEditItem, InventoryEditRoom)):
            jobs.add(row.job_id)
        elif isinstance(row, PublicMoveAccess):
            if _changed(session, row, only=_ACCESS_SHOWN):
                jobs.add(row.job_id)
        elif isinstance(row, Lead):
            if _changed(session, row, only=_LEAD_SHOWN):
                leads.add(row.id)
        elif isinstance(row, LeadContact):
            leads.add(row.lead_id)
        elif isinstance(row, LeadLiveSwitch):
            if _conversation_changed(session, row):
                leads.add(row.lead_id)
        elif isinstance(row, AppSetting):
            for prefix in (JOB_STOPS_SETTING_PREFIX, JOB_PICKUPS_SETTING_PREFIX, JOB_DELIVERIES_SETTING_PREFIX):
                if (row.key or '').startswith(prefix):
                    jobs.add(row.key[len(prefix):])
        elif isinstance(row, Company):
            if _changed(session, row, only=_COMPANY_SHOWN):
                companies.add(row.id)
        elif isinstance(row, CompanyDocument):
            companies.add(row.company_id)
    jobs.discard(None)
    if not (jobs or leads or companies):
        return
    # Jobs already loaded in this request are cleared in place, with no query.
    loaded = [row for row in session.identity_map.values() if isinstance(row, LeadJob)]
    for row in loaded:
        if (row.id in jobs or row.lead_id in leads) and row.estimate_approved_id:
            row.estimate_approved_id = row.estimate_approved_at = None
    # Jobs not loaded (a change made from another screen) are cleared with one update, where an approval exists.
    conditions = []
    if jobs - {row.id for row in loaded}:
        conditions.append(LeadJob.id.in_(jobs - {row.id for row in loaded}))
    if leads - {row.lead_id for row in loaded}:
        conditions.append(LeadJob.lead_id.in_(leads - {row.lead_id for row in loaded}))
    if companies:
        conditions.append(LeadJob.company_id.in_(companies))
        conditions.append(LeadJob.lead_id.in_(select(Lead.id).where(Lead.company_id.in_(companies))))
    if conditions:
        session.execute(update(LeadJob).where(or_(*conditions), LeadJob.estimate_approved_id.isnot(None))
                        .values(estimate_approved_id=None, estimate_approved_at=None).execution_options(synchronize_session=False))
