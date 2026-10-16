"""Priority-zero Activity tasks, maintained on lead and communication events."""
from datetime import datetime, timezone

from sqlalchemy import text

from models import Lead, Task
from work_queue_rules import _digits, _epoch, _smartmoving_created_at, calculate_followup_rows


def utc(value):
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def install(connection):
    connection.execute(text('ALTER TABLE leads ADD COLUMN IF NOT EXISTS followup_priority_confirmed BOOLEAN NOT NULL DEFAULT FALSE'))
    for name, kind in [('due_at', 'TIMESTAMPTZ'), ('scheduled_start', 'TIMESTAMPTZ'),
                       ('automatic_key', 'VARCHAR(40)'), ('completed_at', 'TIMESTAMPTZ'),
                       ('completion_reason', 'VARCHAR(100)')]:
        connection.execute(text(f'ALTER TABLE tasks ADD COLUMN IF NOT EXISTS {name} {kind}'))
    connection.execute(text('ALTER TABLE tasks ALTER COLUMN created_by DROP NOT NULL'))
    connection.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS uq_tasks_followup ON tasks(lead_id, automatic_key)'))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_tasks_pending_followup ON tasks(due_at, lead_id) WHERE automatic_key IS NOT NULL AND status <> 'done'"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_leads_contact_phone ON leads ((right(regexp_replace(phone, '\\D', '', 'g'), 10)))"))


def eligible(lead):
    from routes.unanswered_messages import _is_us_client_phone
    return (lead.followup_priority_confirmed and lead.priority == 0
            and (lead.status or '').lower() in {'new', 'contacted', 'quoted', ''}
            and (not lead.company or (lead.company.name or '').lower() != 'mirit great american')
            and _is_us_client_phone(lead.phone))


def communication(channel, item):
    """Normalize only outbound, non-AI activity; shared by replay and events."""
    direction = str(item.get('direction') or '').strip().lower()
    role = str(item.get('role') or '').strip().lower()
    sender = str(item.get('sales_name') or item.get('company_name') or '').strip().lower()
    if role in {'ai', 'assistant', 'bot', 'user', 'client', 'customer'} or sender in {'ai', 'assistant', 'bot'}:
        return None
    if channel in {'calls', 'sms'}:
        if direction not in ({'outbound'} if channel == 'calls' else {'sent', 'outbound'}):
            return None
    elif direction not in {'sent', 'outbound'} and role not in {'agent', 'human', 'sales', 'sales_rep', 'admin', 'business', 'page'}:
        return None
    if direction in {'draft', 'inbound', 'received'} or _epoch(item.get('timestamp')) <= 0:
        return None
    if channel == 'calls':
        return item
    return {'channel': channel, 'occurred_at': datetime.fromtimestamp(_epoch(item.get('timestamp')), timezone.utc),
            'client': _digits(item.get('phone_number')) if channel == 'sms' else str(item.get('user_id') or ''),
            'destination': _digits(item.get('company_number')), 'number_id': str(item.get('number_id') or ''),
            'page_id': str(item.get('page_id') or '')}


def history(lead):
    """Explicit reconciliation reads only this client's partitions, never a table scan."""
    from boto3.dynamodb.conditions import Key
    from db import calls_table, sms_messages_table, conversations_table
    from libs.common.phone import phone_variants
    calls, messages = [], []
    sources = [(calls_table, 'calls', 'phone_number', value) for value in set(phone_variants(lead.phone or ''))]
    sources += [(sms_messages_table, 'sms', 'phone_number', value) for value in set(phone_variants(lead.phone or ''))]
    if lead.facebook_user_id:
        sources.append((conversations_table, 'messenger', 'user_id', lead.facebook_user_id))
    for table, channel, key, value in sources:
        args = {'KeyConditionExpression': Key(key).eq(value), 'ConsistentRead': True}
        while True:
            page = table.query(**args)
            for item in page.get('Items', []):
                event = communication(channel, item)
                if event:
                    (calls if channel == 'calls' else messages).append(event)
            if not page.get('LastEvaluatedKey'):
                break
            args['ExclusiveStartKey'] = page['LastEvaluatedKey']
    return calls, messages


def apply_progress(db, lead, tasks, calls, messages):
    created = _smartmoving_created_at(lead.created_time)
    if created is None:
        return False  # No guessed creation time for SmartMoving leads.
    # Include completions already saved by stream events racing a refresh.
    destination = _digits(lead.company.phone) if lead.company else ''
    destination = destination or (_digits(lead.assignee.phone) if lead.assignee else '')
    for task in tasks:
        if task.completed_at and task.completion_reason in {'Communication', 'Manually completed'}:
            if task.task_type == 'call':
                calls.append({'timestamp': utc(task.completed_at).timestamp(), 'phone_number': lead.phone, 'company_number': destination})
            else:
                messages.append({'channel': 'sms', 'occurred_at': utc(task.completed_at), 'client': _digits(lead.phone), 'destination': destination})
    row = calculate_followup_rows([(lead, created)], calls, messages, datetime.now(timezone.utc))[0]
    by_key = {task.automatic_key: task for task in tasks}
    changed = False
    for kind, attempts in [('call', row['attempts']), ('message', row['message_attempts'])]:
        for index, attempt in enumerate(attempts, 1):
            key = f'priority0:{kind}:{index}'
            task = by_key.get(key)
            if task and task.status == 'done' and task.completion_reason in {'Manually completed', 'Priority changed', 'Lead closed'}:
                continue
            if task is None:
                task = Task(lead_id=lead.id, automatic_key=key, task_type='call' if kind == 'call' else 'text',
                            title=attempt['label'], notes='', created_by=None)
                db.add(task)
            start = datetime.fromisoformat(attempt['scheduled_start'])
            end = datetime.fromisoformat(attempt['scheduled_end'])
            completed = datetime.fromisoformat(attempt['completed_at']) if attempt['completed_at'] else None
            missed = attempt['status'] == 'not_sent'
            values = dict(scheduled_start=start, due_at=end, due_date=end.date().isoformat(),
                          completed_at=completed, status='done' if completed or missed else 'open',
                          completion_reason='Communication' if completed else 'Superseded by later message' if missed else None)
            for name, value in values.items():
                previous = getattr(task, name)
                if isinstance(previous, datetime):
                    previous = utc(previous)
                if previous != value:
                    setattr(task, name, value)
                    changed = True
    return changed


def sync(db, lead, priority, *, reconcile=False):
    """Caller supplies priority read from SmartMoving, never the model's default zero."""
    db.query(Lead.id).filter_by(id=lead.id).with_for_update().one()
    lead.followup_priority_confirmed = priority is not None
    if priority is not None:
        lead.priority = priority
    existing = db.query(Task).filter(Task.lead_id == lead.id, Task.automatic_key.isnot(None)).all()
    if not eligible(lead):
        if priority is not None and (priority != 0 or (lead.status or '').lower() not in {'new', 'contacted', 'quoted', ''}):
            for task in existing:
                if task.status != 'done':
                    task.status = 'done'
                    task.completed_at = datetime.now(timezone.utc)
                    task.completion_reason = 'Priority changed' if priority != 0 else 'Lead closed'
        return
    calls, messages = history(lead) if reconcile or not existing else ([], [])
    # Event deliveries use the same lead lock. Refresh tasks after reconciliation.
    tasks = db.query(Task).filter(Task.lead_id == lead.id, Task.automatic_key.isnot(None)).populate_existing().all()
    apply_progress(db, lead, tasks, calls, messages)


def sync_saved_lead(lead_id):
    """Creation/update hook; a provider failure does not prevent saving the lead."""
    import logging
    from database import SessionLocal
    from libs.smartmoving.client import check_opportunity_exists
    from routes.leads import _parse_smartmoving_priority, _map_smartmoving_status
    try:
        with SessionLocal() as db:
            lead = db.get(Lead, lead_id)
            if not lead or not lead.smartmoving_id:
                return
            result = check_opportunity_exists(lead.smartmoving_id)
            if not result.get('ok') or not result.get('exists'):
                lead.followup_priority_confirmed = False
                db.commit()
                raise ValueError('SmartMoving priority could not be confirmed')
            if result.get('created_at_utc'):
                lead.created_time = result['created_at_utc']
            status = _map_smartmoving_status(result.get('status'))
            if status:
                lead.status = status
            sync(db, lead, _parse_smartmoving_priority(result.get('lead_status')))
            db.commit()
            from realtime import publish_realtime_event
            publish_realtime_event({'type': 'followup_tasks_changed', 'lead_id': lead_id})
    except Exception:
        logging.getLogger('moving-crm').exception('Could not synchronize follow-up tasks for lead %s', lead_id)


def record_contact(db, lead, channel, item):
    event = communication(channel, item)
    if not event or not eligible(lead):
        return False
    tasks = db.query(Task).filter(Task.lead_id == lead.id, Task.automatic_key.isnot(None)).all()
    if not tasks:
        return False
    return apply_progress(db, lead, tasks, [event] if channel == 'calls' else [], [] if channel == 'calls' else [event])


def lead_row(lead, tasks, now):
    """Serialize saved tasks; no communication queries or schedule reconstruction."""
    attempts, messages = [], []
    for task in sorted(tasks, key=lambda task: task.automatic_key):
        completed = utc(task.completed_at).isoformat() if task.completed_at else ''
        start, end = utc(task.scheduled_start), utc(task.due_at)
        status = ('completed' if completed else 'not_sent') if task.status == 'done' else 'overdue' if end < now else 'open' if start <= now else 'upcoming'
        call = task.task_type == 'call'
        entry = {'number': int(task.automatic_key.rsplit(':', 1)[1]), 'kind': 'call' if call else 'message',
                 'label': task.title, 'period': task.title.split()[0].lower() if call else 'message',
                 'scheduled_start': start.isoformat(), 'scheduled_end': end.isoformat(), 'completed_at': completed, 'status': status}
        (attempts if call else messages).append(entry)
    return {'lead_id': lead.id, 'client': lead.full_name or lead.phone, 'client_phone': lead.phone,
            'rep': lead.assignee.name if lead.assignee else '', 'company': lead.company.name if lead.company else '',
            'status': lead.status, 'priority': lead.priority, 'created_at': _smartmoving_created_at(lead.created_time).isoformat(),
            'smartmoving_created_time': lead.created_time, 'created_time_source': 'smartmoving',
            'attempts': attempts, 'message_attempts': messages,
            'timeline': sorted([item for item in attempts + messages if item['status'] != 'not_sent'], key=lambda item: item['scheduled_end']),
            'completed_count': sum(bool(item['completed_at']) for item in attempts),
            'completed_message_count': sum(bool(item['completed_at']) for item in messages),
            'overdue_count': sum(item['status'] == 'overdue' for item in attempts),
            'overdue_message_count': sum(item['status'] == 'overdue' for item in messages)}
