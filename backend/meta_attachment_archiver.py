"""Archive Messenger/Instagram attachments in the CRM attachment bucket."""

import logging
import mimetypes
import os
import re
from datetime import datetime, timezone
from pathlib import PurePosixPath
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

import boto3
from models import Lead, LeadAttachment, User


logger = logging.getLogger("moving-crm.meta-attachments")
MAX_ATTACHMENT_BYTES = 15 * 1024 * 1024


def _safe_name(value: str) -> str:
    return re.sub(r'[^A-Za-z0-9._ -]+', "_", (value or "").strip())[:180] or "attachment"


def _attachment_url(row: object) -> str:
    if not isinstance(row, dict):
        return ""
    payload = row.get("payload")
    if isinstance(payload, dict) and payload.get("url"):
        return str(payload["url"]).strip()
    return str(row.get("url") or "").strip()


def _attachment_type(row: object) -> str:
    if not isinstance(row, dict):
        return "file"
    payload = row.get("payload")
    return str(row.get("type") or (payload.get("type") if isinstance(payload, dict) else "") or "file").lower()


def _file_name(url: str, kind: str, message_id: str, index: int, content_type: str) -> str:
    candidate = unquote(PurePosixPath(urlparse(url).path).name)
    if candidate and "." in candidate:
        return _safe_name(candidate)
    extension = mimetypes.guess_extension((content_type or "").split(";", 1)[0].strip()) or ""
    if kind == "sticker" and not extension:
        extension = ".png"
    return _safe_name(f"{kind}-{message_id[:24]}-{index + 1}{extension}")


def archive_meta_attachments(
    db,
    lead_id: str | None,
    channel: str,
    message_id: str,
    attachments: object,
    occurred_at: datetime | None = None,
) -> int:
    """Copy exact message attachments to S3 once and register them on the lead."""
    if not lead_id or channel not in {"messenger", "instagram"} or not isinstance(attachments, list):
        return 0
    bucket = (os.getenv("ATTACHMENTS_BUCKET") or "").strip()
    if not bucket:
        logger.warning("Cannot archive Meta attachments: ATTACHMENTS_BUCKET is not configured")
        return 0

    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        return 0
    uploader_id = lead.assigned_to
    if not uploader_id:
        admin = db.query(User.id).filter(User.role == "admin").order_by(User.created_at.asc()).first()
        uploader_id = admin[0] if admin else None
    if not uploader_id:
        logger.warning("Cannot archive Meta attachments for lead %s: no attachment owner exists", lead_id)
        return 0

    stored = 0
    s3 = boto3.client("s3")
    for index, attachment in enumerate(attachments):
        try:
            url = _attachment_url(attachment)
            if not url.lower().startswith("https://"):
                continue
            source_id = f"{message_id}:{index}"
            exists = db.query(LeadAttachment.id).filter(
                LeadAttachment.lead_id == lead_id,
                LeadAttachment.external_source == "meta_s3",
                LeadAttachment.source_external_id == source_id,
            ).first()
            if exists:
                continue

            request = Request(url, headers={"User-Agent": "moving-crm-attachment-archiver/1.0"})
            with urlopen(request, timeout=15) as response:
                size_header = int(response.headers.get("content-length") or 0)
                if size_header > MAX_ATTACHMENT_BYTES:
                    raise ValueError(f"Meta attachment exceeds {MAX_ATTACHMENT_BYTES} bytes")
                chunks: list[bytes] = []
                size = 0
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_ATTACHMENT_BYTES:
                        raise ValueError(f"Meta attachment exceeds {MAX_ATTACHMENT_BYTES} bytes")
                    chunks.append(chunk)
                content = b"".join(chunks)
                content_type = (response.headers.get("content-type") or "application/octet-stream").split(";", 1)[0]

            kind = _attachment_type(attachment)
            name = _file_name(url, kind, message_id, index, content_type)
            object_key = f"leads/{lead_id}/jobs/lead/meta/{channel}/{message_id}/{index + 1}-{name}"
            s3.put_object(
                Bucket=bucket,
                Key=object_key,
                Body=content,
                ContentType=content_type,
                ServerSideEncryption="AES256",
                Metadata={"message-id": message_id[:200], "channel": channel},
            )
            db.add(LeadAttachment(
                lead_id=lead_id,
                file_name=name,
                content_type=content_type,
                file_size=len(content),
                file_blob=b"",
                external_url=f"s3://{bucket}/{object_key}",
                is_external_link=True,
                external_source="meta_s3",
                source_external_id=source_id,
                uploaded_by=uploader_id,
                created_at=occurred_at or datetime.now(timezone.utc),
            ))
            stored += 1
        except Exception:
            logger.exception("Failed archiving %s attachment %d for message %s", channel, index, message_id)
    return stored
