"""Pure scheduling rules used when communication events update Activity tasks."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

CALL_PERIODS = (("morning", 8, 12), ("afternoon", 12, 17), ("evening", 17, 20))


def _digits(value: object) -> str:
    digits = "".join(character for character in str(value or "") if character.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits


def _epoch(value: object) -> float:
    try:
        number = float(value or 0)
        return number / 1000 if number >= 1_000_000_000_000 else number
    except (TypeError, ValueError):
        return 0


def _smartmoving_created_at(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if text.replace(".", "", 1).isdigit():
            return datetime.fromtimestamp(_epoch(text), tz=timezone.utc)
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None


def _period_on(day, name: str, tz: ZoneInfo) -> tuple[datetime, datetime, str]:
    _, start_hour, end_hour = next(period for period in CALL_PERIODS if period[0] == name)
    return (
        datetime(day.year, day.month, day.day, start_hour, tzinfo=tz),
        datetime(day.year, day.month, day.day, end_hour, tzinfo=tz),
        name,
    )


def _next_period(after: datetime, tz: ZoneInfo) -> tuple[datetime, datetime, str]:
    local = after.astimezone(tz)
    for name, start_hour, end_hour in CALL_PERIODS:
        end = datetime(local.year, local.month, local.day, end_hour, tzinfo=tz)
        if local < end:
            start = datetime(local.year, local.month, local.day, start_hour, tzinfo=tz)
            return max(start, local), end, name
    return _period_on(local.date() + timedelta(days=1), "morning", tz)


def _priority_zero_schedule(created_at: datetime, timezone_name: str) -> list[tuple[datetime, datetime, str]]:
    try:
        tz = ZoneInfo(timezone_name or "America/New_York")
    except Exception:
        tz = ZoneInfo("America/New_York")
    slots: list[tuple[datetime, datetime, str]] = []
    cursor = created_at.astimezone(tz)
    for _ in range(3):
        slot = _next_period(cursor, tz)
        slots.append(slot)
        cursor = slot[1]

    third_day = slots[-1][0].date()
    third_name = slots[-1][2]
    if third_name == "morning":
        phase_two = [_period_on(third_day, "afternoon", tz), _period_on(third_day, "evening", tz)]
    elif third_name == "afternoon":
        phase_two = [_period_on(third_day, "evening", tz), _period_on(third_day + timedelta(days=1), "morning", tz)]
    else:
        phase_two = [_period_on(third_day + timedelta(days=1), "morning", tz), _period_on(third_day + timedelta(days=1), "afternoon", tz)]
    slots.extend(phase_two)
    slots.append(_period_on(phase_two[-1][0].date() + timedelta(days=1), "morning", tz))
    return slots


def _call_period_key(call_at: datetime, timezone_name: str) -> tuple[str, str] | None:
    """Count calls from 8 AM to 9 PM, keeping the scheduled deadlines unchanged."""
    try:
        tz = ZoneInfo(timezone_name or "America/New_York")
    except Exception:
        tz = ZoneInfo("America/New_York")
    local = call_at.astimezone(tz)
    for name, start_hour, end_hour in CALL_PERIODS:
        # Late evening calls still complete the evening task until 9 PM.
        # Keep them in one period so repeated calls cannot finish extra tasks.
        counting_end = 21 if name == "evening" else end_hour
        if start_hour <= local.hour < counting_end:
            return local.date().isoformat(), name
    return None


def _required_message_attempts(
    created_at: datetime,
    timezone_name: str,
    message_times: list[datetime],
    now: datetime,
) -> list[dict]:
    try:
        tz = ZoneInfo(timezone_name or "America/New_York")
    except Exception:
        tz = ZoneInfo("America/New_York")
    created_local = created_at.astimezone(tz)
    local_messages = [value.astimezone(tz) for value in message_times if value >= created_at]
    definitions = (("Welcome message", 0), ("Day 2 message", 1), ("Day 3 message", 2))
    attempts = []
    for label, day_offset in definitions:
        day = created_local.date() + timedelta(days=day_offset)
        scheduled_start = created_local if day_offset == 0 else datetime(day.year, day.month, day.day, 8, tzinfo=tz)
        scheduled_end = datetime(day.year, day.month, day.day, 20, tzinfo=tz)
        completed = next((value for value in local_messages if value.date() == day), None)
        if completed:
            status = "completed"
        elif any(value > scheduled_end for value in local_messages):
            # A later outbound message makes an older missed message impossible
            # to recover. Preserve it as not sent for progress/audit purposes,
            # but do not leave it in the actionable overdue queue.
            status = "not_sent"
        elif now > scheduled_end.astimezone(timezone.utc):
            status = "overdue"
        elif now >= scheduled_start.astimezone(timezone.utc):
            status = "open"
        else:
            status = "upcoming"
        attempts.append({
            "kind": "message",
            "label": label,
            "period": "message",
            "scheduled_start": scheduled_start.isoformat(),
            "scheduled_end": scheduled_end.isoformat(),
            "completed_at": completed.isoformat() if completed else "",
            "status": status,
        })
    return attempts


def calculate_followup_rows(leads_with_created_at, calls, messages, now):
    calls_by_pair: dict[tuple[str, str], list[datetime]] = {}
    for call in calls:
        call_at = datetime.fromtimestamp(_epoch(call.get("timestamp")), tz=timezone.utc)
        key = (_digits(call.get("phone_number")), _digits(call.get("company_number")))
        calls_by_pair.setdefault(key, []).append(call_at)
    for values in calls_by_pair.values():
        values.sort()
    sms_by_phone_destination: dict[tuple[str, str], list[datetime]] = {}
    sms_by_phone_number_id: dict[tuple[str, str], list[datetime]] = {}
    meta_by_user_page: dict[tuple[str, str], list[datetime]] = {}
    for message in messages:
        occurred_at = message["occurred_at"]
        if message["channel"] == "sms":
            if message.get("destination"):
                sms_by_phone_destination.setdefault((message["client"], message["destination"]), []).append(occurred_at)
            if message.get("number_id"):
                sms_by_phone_number_id.setdefault((message["client"], message["number_id"]), []).append(occurred_at)
        elif message.get("client") and message.get("page_id"):
            meta_by_user_page.setdefault((message["client"], message["page_id"]), []).append(occurred_at)

    rows = []
    for lead, created_at in leads_with_created_at:
        client_phone = _digits(lead.phone)
        timezone_name = lead.company.timezone if lead.company else "America/New_York"
        destinations = {_digits(lead.company.phone) if lead.company else "", _digits(lead.assignee.phone) if lead.assignee else ""}
        destinations.discard("")
        matching_calls = sorted(
            call_at
            for destination in destinations
            for call_at in calls_by_pair.get((client_phone, destination), [])
            if call_at >= created_at
        )
        # A required morning/afternoon/evening period can be completed only once.
        # Extra calls in that same local period neither complete another slot nor
        # carry forward as a delayed completion.
        seen_call_periods: set[tuple[str, str]] = set()
        lead_calls = []
        for call_at in matching_calls:
            period_key = _call_period_key(call_at, timezone_name)
            if period_key is None or period_key in seen_call_periods:
                continue
            seen_call_periods.add(period_key)
            lead_calls.append(call_at)
        slots = _priority_zero_schedule(created_at, timezone_name)
        try:
            lead_tz = ZoneInfo(timezone_name or "America/New_York")
        except Exception:
            lead_tz = ZoneInfo("America/New_York")
        call_index = 0
        attempts = []
        slot_index = 0
        while slot_index < len(slots) and len(attempts) < 6:
            start, end, period = slots[slot_index]
            start_utc, end_utc = start.astimezone(timezone.utc), end.astimezone(timezone.utc)
            while call_index < len(lead_calls) and lead_calls[call_index] < start_utc:
                call_index += 1
            completed_at = lead_calls[call_index] if call_index < len(lead_calls) else None
            if completed_at:
                call_index += 1
                status = "on_time" if completed_at <= end_utc else "delayed"
                if status == "delayed":
                    completed_local = completed_at.astimezone(lead_tz)
                    completed_period_end = completed_local
                    for _, period_start_hour, period_end_hour in CALL_PERIODS:
                        if period_start_hour <= completed_local.hour < period_end_hour:
                            completed_period_end = datetime(
                                completed_local.year,
                                completed_local.month,
                                completed_local.day,
                                period_end_hour,
                                tzinfo=lead_tz,
                            )
                            break
                    next_available = completed_period_end
                    for future_index in range(slot_index + 1, len(slots)):
                        future_start, future_end, _ = slots[future_index]
                        if future_start < next_available:
                            replacement = _next_period(next_available, lead_tz)
                            slots[future_index] = replacement
                            next_available = replacement[1]
                        else:
                            next_available = future_end
            elif now > end_utc:
                status = "overdue"
            elif now >= start_utc:
                status = "open"
            else:
                status = "upcoming"
            attempts.append({
                "number": len(attempts) + 1,
                "kind": "call",
                "label": f"{period.capitalize()} call",
                "period": period,
                "scheduled_start": start.isoformat(),
                "scheduled_end": end.isoformat(),
                "completed_at": completed_at.isoformat() if completed_at else "",
                "status": status,
            })
            slot_index += 1
        message_times: set[datetime] = set()
        company_number_id = str(lead.company.aircall_number_id or "").strip() if lead.company else ""
        rep_number_id = str(lead.assignee.aircall_number_id or "").strip() if lead.assignee else ""
        for destination in destinations:
            message_times.update(sms_by_phone_destination.get((client_phone, destination), []))
        for number_id in {company_number_id, rep_number_id} - {""}:
            message_times.update(sms_by_phone_number_id.get((client_phone, number_id), []))
        facebook_user_id = str(lead.facebook_user_id or "").strip()
        facebook_page_id = str(lead.company.facebook_page_id or "").strip() if lead.company else ""
        if facebook_user_id and facebook_page_id:
            message_times.update(meta_by_user_page.get((facebook_user_id, facebook_page_id), []))
        message_attempts = _required_message_attempts(created_at, timezone_name, sorted(message_times), now)
        timeline = [*attempts, *(attempt for attempt in message_attempts if attempt["status"] != "not_sent")]
        # The UI presents each requirement by its deadline, so order the
        # checklist by that same deadline. Completion time must not move it.
        timeline.sort(key=lambda item: (item["scheduled_end"], 0 if item["kind"] == "call" else 1))
        overdue_count = sum(1 for attempt in attempts if attempt["status"] == "overdue")
        rows.append({
            "lead_id": lead.id,
            "client": lead.full_name or lead.phone or "Unknown client",
            "client_phone": lead.phone or "",
            "rep": lead.assignee.name if lead.assignee else "",
            "company": lead.company.name if lead.company else "",
            "status": lead.status or "",
            "priority": lead.priority,
            "created_at": created_at.isoformat(),
            "smartmoving_created_time": lead.created_time,
            "created_time_source": "smartmoving" if _smartmoving_created_at(lead.created_time) else "crm",
            "attempts": attempts,
            "message_attempts": message_attempts,
            "timeline": timeline,
            "completed_count": sum(1 for attempt in attempts if attempt["completed_at"]),
            "completed_message_count": sum(1 for attempt in message_attempts if attempt["completed_at"]),
            "overdue_message_count": sum(1 for attempt in message_attempts if attempt["status"] == "overdue"),
            "overdue_count": overdue_count,
        })
    return rows


def _is_us_client_phone(value):
    """Include the 50 states and D.C., excluding territories and toll-free numbers."""
    import phonenumbers
    try:
        number = phonenumbers.parse(str(value or ""), "US")
    except phonenumbers.NumberParseException:
        return False
    return (
        phonenumbers.is_valid_number(number)
        and phonenumbers.region_code_for_number(number) == "US"
        and phonenumbers.number_type(number) in (
            phonenumbers.PhoneNumberType.FIXED_LINE,
            phonenumbers.PhoneNumberType.MOBILE,
            phonenumbers.PhoneNumberType.FIXED_LINE_OR_MOBILE,
        )
    )
