"""Small, testable security primitives for the customer move portal."""
import hashlib
import hmac
import os
import re


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def secret_digest(value):
    return hmac.new(os.environ['JWT_SECRET'].encode(), value.encode(), hashlib.sha256).hexdigest()


def link_token(access_id):
    # Reproducible for idempotent intake responses, but unguessable without the
    # server secret. Only its hash is persisted in the access record.
    return secret_digest('public-move-link:' + access_id)


def contact_fingerprint(lead):
    return secret_digest(f'contact:{lead.phone or ""}:{lead.email or ""}')


def normalize_phone(value):
    digits = re.sub(r'\D', '', value or '')
    if len(digits) == 10:
        digits = '1' + digits
    if not 11 <= len(digits) <= 15:
        raise ValueError('Provide a valid phone number including its country code')
    return '+' + digits


def file_type(data):
    if data.startswith(b'\xff\xd8\xff'): return 'image/jpeg'
    if data.startswith(b'\x89PNG\r\n\x1a\n'): return 'image/png'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP': return 'image/webp'
    if data.startswith(b'%PDF-'): return 'application/pdf'
    if data[4:8] == b'ftyp': return 'video/quicktime' if data[8:12] == b'qt  ' else 'video/mp4'
    return None
