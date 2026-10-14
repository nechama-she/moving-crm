"""SQL expiration boundary checks for CodeBuild."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine, func
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from models import Base, MessageState
from ended_chat_retention import clear_existing_ended_states, visible_message_states


def test_sql_filters_expired_history_from_rows_and_counts_without_deleting():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    now = datetime.now(timezone.utc)
    with Session(engine) as db:
        for key, ended, ended_at in [
            ("expired", True, now - timedelta(days=2)),
            ("boundary", True, now - timedelta(hours=24)),
            ("recent", True, now - timedelta(hours=24) + timedelta(seconds=1)),
            ("unanswered", False, None),
            ("reopened", False, now - timedelta(days=2)),
        ]:
            db.add(MessageState(channel="sms", message_id=key, client_identifier="client",
                company_identifier="company", direction="inbound", occurred_at=now - timedelta(days=5),
                conversation_ended=ended, ended_at=ended_at))
        db.commit()
        visible = visible_message_states(now)
        assert {row.message_id for row in db.query(MessageState).filter(visible)} == {
            "recent", "unanswered", "reopened"}
        counts = dict(db.query(MessageState.conversation_ended, func.count()).filter(visible)
                      .group_by(MessageState.conversation_ended).all())
        assert counts == {False: 2, True: 1}
        assert db.query(MessageState).count() == 5
    engine.dispose()


def test_existing_ended_cleanup_runs_once_and_preserves_unanswered():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    now = datetime.now(timezone.utc)
    def row(key, ended):
        return dict(channel="sms", message_id=key, client_identifier="client",
                    company_identifier="company", direction="inbound", occurred_at=now,
                    conversation_ended=ended, ended_at=now if ended else None)
    with engine.begin() as connection:
        connection.execute(MessageState.__table__.insert(), [row("old-ended", True), row("active", False)])
        assert clear_existing_ended_states(connection) == 1
    with engine.begin() as connection:
        connection.execute(MessageState.__table__.insert(), row("new-ended", True))
        assert clear_existing_ended_states(connection) == 0
        remaining = connection.execute(MessageState.__table__.select()).mappings().all()
        assert {item["message_id"] for item in remaining} == {"active", "new-ended"}
    engine.dispose()
