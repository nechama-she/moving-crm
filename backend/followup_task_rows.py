"""Read-only task presentation for the follow-up calendar."""
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo
from followup_tasks import lead_row, utc, followup_created_at
from work_queue_rules import CALL_PERIODS


def calendar_lead_row(lead, tasks, now):
    if lead.priority == 0:
        # Preserve the original priority-zero payload and full six/three schedule.
        return lead_row(lead, tasks, now)
    created, source = followup_created_at(lead)
    try:
        tz = ZoneInfo(lead.company.timezone if lead.company else 'America/New_York')
    except (ValueError, TypeError):
        tz = ZoneInfo('America/New_York')
    entries = []
    for task in tasks:
        end = utc(task.due_at) if task.due_at else datetime.combine(datetime.fromisoformat(task.due_date).date(), time.max, tz) if task.due_date else None
        start = utc(task.scheduled_start) if task.scheduled_start else end
        period_start, period_end = start, end
        if end and task.due_at:
            local_due = end.astimezone(tz)
            for _, start_hour, end_hour in CALL_PERIODS:
                if start_hour <= local_due.hour < end_hour:
                    period_start = local_due.replace(hour=start_hour, minute=0, second=0, microsecond=0)
                    period_end = local_due.replace(hour=end_hour, minute=0, second=0, microsecond=0)
                    break
        status = 'completed' if task.status == 'done' else 'overdue' if end and end < now else 'open' if start and start <= now else 'upcoming'
        if task.status != 'done' and period_start and period_end:
            status = 'open' if period_start <= now < period_end else 'overdue' if period_end <= now else 'upcoming'
        entries.append(dict(number=None, kind='call' if task.task_type == 'call' else 'message',
            label=task.title, notes=task.notes or '', task_type=task.task_type, period='', status=status,
            scheduled_start=start.isoformat() if start else '', scheduled_end=end.isoformat() if end else '',
            completed_at=utc(task.completed_at).isoformat() if task.completed_at else ''))
    entries.sort(key=lambda entry: entry['scheduled_end'])
    calls = [entry for entry in entries if entry['kind'] == 'call']
    others = [entry for entry in entries if entry['kind'] != 'call']
    return dict(lead_id=lead.id, client=lead.full_name or lead.phone, client_phone=lead.phone,
        rep=lead.assignee.name if lead.assignee else '', company=lead.company.name if lead.company else '',
        status=lead.status, priority=lead.priority, created_at=created.isoformat(),
        smartmoving_created_time=lead.created_time, created_time_source=source,
        attempts=calls, message_attempts=others, timeline=entries,
        completed_count=sum(e['status'] == 'completed' for e in calls),
        completed_message_count=sum(e['status'] == 'completed' for e in others),
        overdue_count=sum(e['status'] == 'overdue' for e in calls),
        overdue_message_count=sum(e['status'] == 'overdue' for e in others))
