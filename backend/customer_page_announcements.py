"""The one place customer page saves are announced: the move's other open pages (the customer's other browsers, the
rep's page) update and show what changed, and saves listed in Customer Activity tell the CRM's work queue."""
import re

from starlette.concurrency import run_in_threadpool

# Customer page requests that send something but save nothing another open copy of the page shows.
CUSTOMER_PAGE_READS = {'realtime-token', 'send-code', 'verify', 'address-search', 'address-resolve', 'inventory.pdf',
                       'mileage', 'availability', 'question-images', 'prepare-upload'}

# What a save did, for the other open pages' notice (the page words it). A save not listed updates them without one.
CHANGES = [
    (re.compile(r'estimate-signatures/[^/]+/sign'), 'estimate_signed'),
    (re.compile(r'estimate-signatures/[^/]+/resign'), 'estimate_signature_cancelled'),
    (re.compile(r'estimate-signatures/[^/]+/approve'), 'estimate_approved'),
    (re.compile(r'bill-of-lading/[0-9]+/[^/]+/sign'), 'bill_of_lading_signed'),
    (re.compile(r'inventory/actions'), 'inventory_updated'),
    (re.compile(r'item-answer'), 'item_questions_answered'),
    (re.compile(r'reports/[^/]+/select'), 'inventory_report_chosen'),
    (re.compile(r'generate-inventory-report|recalculate-price|calculate-price'), 'estimate_updated'),
    (re.compile(r'packing'), 'packing_changed'),
    (re.compile(r'details'), 'details_updated'),
    (re.compile(r'customer-discount'), 'discount_chosen'),
    (re.compile(r'rep-discounts'), 'discounts_changed'),
    (re.compile(r'files|finish-upload'), 'files_uploaded'),
    (re.compile(r'files/[^/]+'), 'file_deleted'),
    (re.compile(r'walkthrough'), 'walkthrough_requested'),
    (re.compile(r'reschedule'), 'reschedule_requested'),
]

# Saves shown in the work queue's Customer Activity: signing the estimate or a Bill of Lading spot, and cancelling an
# estimate signature.
CUSTOMER_ACTIVITY = {'estimate_signed', 'estimate_signature_cancelled', 'bill_of_lading_signed'}


def _move_of(access_id, link):
    """The move's lead, whether the save came from the rep's page (its link is the rep's), and who made it by name: the
    customer, or the rep the lead is assigned to (blank when the lead has none)."""
    import hmac
    from database import SessionLocal
    from models import Lead, PublicMoveAccess, User
    from routes.public_moves import rep_link_token
    db = SessionLocal()
    try:
        access = db.get(PublicMoveAccess, access_id)
        if not access:
            return None, False, ''
        by_rep = bool(link) and hmac.compare_digest(link, rep_link_token(access))
        lead = db.get(Lead, access.lead_id)
        rep = db.get(User, lead.assigned_to) if by_rep and lead and lead.assigned_to else None
        name = (rep.name if rep else '') if by_rep else (lead.full_name if lead else '')
        return access.lead_id, by_rep, (name or '').strip()
    finally:
        db.close()


def _announce(access_id, path, link, origin):
    from realtime import publish_move_change, publish_realtime_event
    lead_id, by_rep, name = _move_of(access_id, link)
    if not lead_id:
        return
    change = next((kind for pattern, kind in CHANGES if pattern.fullmatch(path)), '')
    publish_move_change(lead_id, origin, change, 'team' if by_rep else 'customer', name)
    if change in CUSTOMER_ACTIVITY:
        publish_realtime_event({'type': 'customer_activity', 'lead_id': lead_id})


async def announce_customer_page_changes(request, call_next):
    response = await call_next(request)
    match = re.fullmatch(r'/api/public-moves/([0-9a-f-]{36})/(.+)', request.url.path)
    if (match and request.method in {'POST', 'PUT', 'PATCH', 'DELETE'} and response.status_code < 300
            and match.group(2) not in CUSTOMER_PAGE_READS):
        await run_in_threadpool(_announce, match.group(1), match.group(2), request.headers.get('x-public-link', ''),
                                request.headers.get('x-page-id', '')[:64])
    return response
