from sqlalchemy.orm import Session

from models import CommunicationAssociation


def digits(value: object) -> str:
    normalized = "".join(character for character in str(value or "") if character.isdigit())
    return normalized[-10:] if len(normalized) >= 10 else normalized


def normalized_key(channel: object, client_identifier: object, company_identifier: object) -> tuple[str, str, str]:
    normalized_channel = str(channel or "").strip().lower()
    if normalized_channel in {"sms", "calls", "call", "phone"}:
        return "phone", digits(client_identifier), digits(company_identifier)
    if normalized_channel not in {"messenger", "instagram"}:
        return "", "", ""
    return normalized_channel, str(client_identifier or "").strip(), str(company_identifier or "").strip()


def find_association(db: Session, channel: object, client_identifier: object, company_identifier: object) -> CommunicationAssociation | None:
    key = normalized_key(channel, client_identifier, company_identifier)
    if not all(key):
        return None
    return db.query(CommunicationAssociation).filter(
        CommunicationAssociation.channel == key[0],
        CommunicationAssociation.client_identifier == key[1],
        CommunicationAssociation.company_identifier == key[2],
    ).first()
