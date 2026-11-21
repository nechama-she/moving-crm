"""The fields a message template can show, written @Token: read from the database's own columns for the lead (and its
first job), its company and the rep it is assigned to, so a column added later is offered by itself. Columns that are
internal, private or another system's are never offered. A few fields are worked out rather than read as saved
(names, the route, the estimate total, an admin's phone and email): those are built in below."""
import re
from datetime import date, datetime
from decimal import Decimal

from models import Company, Lead, LeadJob, User

LEAD, COMPANY, REP = "Lead info", "Company info", "Rep info"

# Each source: its model, the group it is listed under, and the start of its tokens. The lead's first job is part of
# the lead's info; where both have a value, the job's is used.
SOURCES = [("leads", Lead, LEAD, ""), ("lead_jobs", LeadJob, LEAD, ""), ("companies", Company, COMPANY, "Company"),
           ("users", User, REP, "Rep")]

# Never offered, for any column now or added later: ids, secrets, timestamps, and other systems' data.
_BLOCKED_NAME = re.compile(r"(^id$|_id$|password|hash|token|secret|key|permission|_at$"
                           r"|^smartmoving|^samrtmoving|^facebook|^leadgen|^aircall|^granot)")
# Never offered: internal notes, saved working data and settings that are not for a customer to read.
BLOCKED = {
    "leads": {"assigned_to", "source", "inbox_url", "notes", "estimated_total", "third_party_payout_to",
              "third_party_payout_amount", "third_party_payout_paid", "status", "priority", "created_time"},
    "lead_jobs": {"pricing_move_type", "minimum_cuft", "job_order", "notes", "foreman_notes", "estimated_materials",
                  "customer_packing", "customer_packing_package", "price_refresh_error", "price", "out_of_area_meters",
                  "out_of_area_revision", "smartmoving_price", "stop_types"},
    "companies": {"color", "logo", "customer_questions", "valuation_per_lb", "timezone", "is_default_company"},
    "users": {"role", "must_change_password", "crm_managed_followups"},
}
_ACRONYMS = {"dot": "DOT", "mc": "MC", "url": "URL", "id": "ID"}


def _phone(value):
    """A US number as people write it, (202) 937-2625; anything else as saved."""
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}" if len(digits) == 10 else (value or "").strip()


def _date(value):
    """12/23/2026 from a saved date (a date, or text such as 2026-12-23); text that is not a date as saved."""
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.strftime("%m/%d/%Y")
    try:
        return date.fromisoformat((value or "").strip()[:10]).strftime("%m/%d/%Y")
    except ValueError:
        return (value or "").strip()


def _number(value, unit=""):
    """1,250 or 2,002.50 (with its unit, when it has one); blank when there is none."""
    if value is None or value == "":
        return ""
    number = float(value)
    text = f"{number:,.0f}" if number == int(number) else f"{number:,.2f}"
    return f"{text} {unit}" if unit else text


def _format(column, value):
    """A column's value as a customer reads it, by its kind."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (datetime, date)):
        return _date(value)
    if isinstance(value, (int, float, Decimal)):
        return _number(value)
    text = str(value).strip()
    if "phone" in column:
        return _phone(text)
    if column.endswith("date"):
        return _date(text)
    return text


def _words(column):
    return [_ACRONYMS.get(word, word) for word in column.split("_") if word]


def _label(column):
    words = _words(column)
    first = words[0] if words[0].isupper() else words[0].capitalize()
    return " ".join([first, *words[1:]])


def _token(prefix, column):
    return prefix + "".join(word if word.isupper() else word.capitalize() for word in _words(column))


class _Move:
    """What the fields are filled from: the lead, its first job and route, its company, its rep, and the customer's
    links (customer_links)."""
    def __init__(self, lead, job, route, company, rep, links=None):
        self.lead, self.job, self.company, self.rep = lead, job, company, rep
        self.links = links or {}
        self.pickup, self.stops, self.delivery = route
        self.names = (lead.full_name or "").split()
        self.rep_names = ((rep.name or "") if rep else "").split()
        # An admin works from the company's own phone and email; a rep has their own.
        self.admin_rep = bool(rep and rep.role == "admin")

    def first(self, column):
        """The job's value where it has one, otherwise the lead's."""
        job_value = getattr(self.job, column, None) if self.job else None
        return job_value if job_value not in (None, "") else getattr(self.lead, column, None)


def _total(move):
    total = (move.lead.estimated_total_data() or {}).get("finalTotal")
    return f"${total:,.2f}" if total else ""


def _job_number(move):
    from models import job_number
    return job_number(move.lead, move.job) if move.job else (move.lead.number or "")


# Built in: (token, label, group, the columns it stands for, its value).
BUILT_IN = [
    ("FirstName", "First name", LEAD, {("leads", "full_name")}, lambda m: m.names[0] if m.names else ""),
    ("LastName", "Last name", LEAD, set(), lambda m: " ".join(m.names[1:])),
    ("FullName", "Full name", LEAD, set(), lambda m: " ".join(m.names)),
    ("LeadPhone", "Phone", LEAD, {("leads", "phone")}, lambda m: _phone(m.lead.phone)),
    ("LeadEmail", "Email", LEAD, {("leads", "email")}, lambda m: (m.lead.email or "").strip()),
    ("MoveDate", "Move date", LEAD, {("leads", "move_date"), ("lead_jobs", "move_date")}, lambda m: _date(m.first("move_date"))),
    ("BookedDate", "Booked date", LEAD, {("leads", "booked_move_date"), ("lead_jobs", "booked_move_date")},
     lambda m: _date(m.first("booked_move_date"))),
    ("MoveType", "Move type", LEAD, {("leads", "move_type")}, lambda m: _move_type(m.lead.move_type)),
    ("Volume", "Volume (cu ft)", LEAD, {("leads", "volume")}, lambda m: _number(m.lead.volume, "cu ft")),
    ("Weight", "Weight (lb)", LEAD, {("leads", "weight")}, lambda m: _number(m.lead.weight, "lb")),
    ("Pickup", "Pickup address", LEAD, {("leads", "pickup_zip"), ("lead_jobs", "pickup_zip")}, lambda m: m.pickup or ""),
    ("Stops", "Stops", LEAD, set(), lambda m: "; ".join(address for address in m.stops if address)),
    ("Delivery", "Delivery address", LEAD, {("leads", "delivery_zip"), ("lead_jobs", "delivery_zip")}, lambda m: m.delivery or ""),
    ("JobNumber", "Job number", LEAD, {("leads", "number")}, _job_number),
    ("EstimateTotal", "Estimate total", LEAD, set(), _total),
    ("CustomerLink", "Customer page link", LEAD, set(), lambda m: m.links.get("customer", "")),
    ("ParticipantLink", "Video call link (LiveSwitch)", LEAD, set(), lambda m: m.links.get("participant", "")),
    ("CompanyEmail", "Email", COMPANY, {("companies", "sender_email")},
     lambda m: (m.company.sender_email or "") if m.company else ""),
    ("RepFirstName", "First name", REP, {("users", "name")}, lambda m: m.rep_names[0] if m.rep_names else ""),
    ("RepName", "Full name", REP, set(), lambda m: " ".join(m.rep_names)),
    ("RepPhone", "Phone", REP, {("users", "phone")},
     lambda m: (_phone(m.company.phone) if m.company else "") if m.admin_rep else (_phone(m.rep.phone) if m.rep else "")),
    ("RepEmail", "Email", REP, {("users", "email")},
     lambda m: ((m.company.sender_email or "") if m.company else "") if m.admin_rep else ((m.rep.email or "") if m.rep else "")),
]


def _move_type(value):
    from move_types import normalize_move_type
    return normalize_move_type(value)


def _columns():
    """The columns offered as they are: (token, label, group, table, column), each token once (the lead's first)."""
    claimed = set().union(*(columns for _, _, _, columns, _ in BUILT_IN))
    taken = {token for token, *_ in BUILT_IN}
    found = []
    for table, model, group, prefix in SOURCES:
        for column in model.__table__.columns:
            name = column.name
            if (table, name) in claimed or name in BLOCKED.get(table, ()) or _BLOCKED_NAME.search(name):
                continue
            token = _token(prefix, name)
            if token in taken:
                continue
            taken.add(token)
            found.append((token, _label(name), group, table, name))
    return found


def fields():
    """Every field a template can show, by group: Lead info, Company info, Rep info."""
    order = {LEAD: 0, COMPANY: 1, REP: 2}
    built_in = [(token, label, group) for token, label, group, _, _ in BUILT_IN]
    columns = [(token, label, group) for token, label, group, _, _ in _columns()]
    # The lead's built-in fields lead its group; a company's and rep's follow their columns (Name first).
    listed = [field for field in built_in if field[2] == LEAD] + columns + [field for field in built_in if field[2] != LEAD]
    return sorted(listed, key=lambda field: order[field[2]])


def enabled_tokens(db):
    """The fields the @ list offers. A switch saved in message_template_fields decides; with none saved, a built-in
    field is on (it is added on purpose) and a column is off (one added later waits to be turned on)."""
    from models import MessageTemplateField
    saved = dict(db.query(MessageTemplateField.token, MessageTemplateField.enabled).all())
    built_in = {token for token, *_ in BUILT_IN}
    return {token for token, _, _ in fields() if saved.get(token, token in built_in)}


def offered(db):
    """The fields turned on for the @ list."""
    enabled = enabled_tokens(db)
    return [field for field in fields() if field[0] in enabled]


def customer_page_link(db, lead):
    """The lead's customer page link, made when the lead has none yet (as the Estimate button makes it); empty while it
    does not open (revoked or expired), without a job, or without a customer website. Does not commit."""
    from fastapi import HTTPException
    from routes.public_moves import lead_customer_page, public_url
    access = lead_customer_page(db, lead)
    if access is None or access.revoked or access.expires_at <= datetime.utcnow():
        return ""
    try:
        return public_url(access)
    except HTTPException:  # The customer website is not configured: no link rather than a broken one.
        return ""


def customer_links(db, lead, customer_page=True):
    """The links a customer may be sent: their customer page (customer_page_link; left out when customer_page is
    False, so none is made for a text that does not use it), and their LiveSwitch video call link, as the CRM sends it.
    The rep's and host's links are never offered."""
    import json
    from models import LeadLiveSwitch
    links = {}
    if customer_page and (link := customer_page_link(db, lead)):
        links["customer"] = link
    conversation = db.get(LeadLiveSwitch, lead.id)
    if conversation is not None:
        try:
            links["participant"] = str(json.loads(conversation.details or "{}").get("participantJoinUrl") or "").strip()
        except ValueError:
            pass
    return links


def values(lead, job, route, company, rep, links=None):
    """Each field's value for this lead, ready to read."""
    move = _Move(lead, job, route, company, rep, links)
    filled = {token: value(move) for token, _, _, _, value in BUILT_IN}
    rows = {"leads": lead, "companies": company, "users": rep}
    for token, _, _, table, column in _columns():
        if table in ("leads", "lead_jobs"):
            filled[token] = _format(column, move.first(column))
        else:
            row = rows[table]
            filled[token] = _format(column, getattr(row, column, None)) if row is not None else ""
    return filled
