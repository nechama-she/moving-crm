"""Event/deadline contracts, run by CodeBuild without production connections."""
import sys
import asyncio
import socket
import threading
from io import BytesIO
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
import work_queue_worker as worker


@pytest.fixture
def scheduling(monkeypatch):
    client = Mock()
    client.exceptions.ResourceNotFoundException = type("Missing", (Exception,), {})
    client.exceptions.ConflictException = type("Conflict", (Exception,), {})
    monkeypatch.setattr(worker.boto3, "client", lambda name: client)
    monkeypatch.setattr(worker, "checkpoint", lambda db, key: {"name": "queue-previous"})
    save = Mock()
    monkeypatch.setattr(worker, "save_checkpoint", save)
    for key, value in {"WORK_QUEUE_DEADLINE_NAME": "queue", "WORK_QUEUE_FUNCTION_ARN": "worker",
                       "WORK_QUEUE_SCHEDULER_ROLE_ARN": "role"}.items():
        monkeypatch.setenv(key, value)
    return Mock(), client, save


def test_deadline_is_once_and_never_earlier_than_due(scheduling):
    db, client, save = scheduling
    due = datetime.now(timezone.utc) + timedelta(hours=2, microseconds=123)
    db.query.return_value.scalar.return_value = due
    worker.schedule_deadline(db)
    args = client.create_schedule.call_args.kwargs
    assert args["ScheduleExpression"].startswith("at(")
    scheduled = datetime.fromisoformat(args["ScheduleExpression"][3:-1]).replace(tzinfo=timezone.utc)
    assert due < scheduled <= due + timedelta(seconds=1)
    assert args["ActionAfterCompletion"] == "DELETE"
    assert args["Name"] != "queue-previous"
    client.delete_schedule.assert_called_once_with(Name="queue-previous")
    db.commit.assert_called_once()


def test_idle_queue_has_no_schedule(scheduling):
    db, client, save = scheduling
    db.query.return_value.scalar.return_value = None
    worker.schedule_deadline(db)
    client.create_schedule.assert_not_called()
    client.delete_schedule.assert_called_once_with(Name="queue-previous")
    save.assert_called_once_with(db, "deadline", {})


def test_schedule_failure_is_not_acknowledged(scheduling):
    db, client, save = scheduling
    db.query.return_value.scalar.return_value = datetime.now(timezone.utc) + timedelta(hours=1)
    client.create_schedule.side_effect = RuntimeError("AWS unavailable")
    with pytest.raises(RuntimeError, match="AWS unavailable"):
        worker.schedule_deadline(db)
    save.assert_not_called()
    client.delete_schedule.assert_not_called()


def test_unchanged_deadline_makes_no_scheduler_requests(scheduling, monkeypatch):
    db, client, save = scheduling
    due = datetime.now(timezone.utc) + timedelta(hours=2)
    db.query.return_value.scalar.return_value = due
    name = f"queue-{int((due.replace(microsecond=0) + timedelta(seconds=1)).timestamp())}"
    monkeypatch.setattr(worker, "checkpoint", lambda db, key: {"name": name})
    worker.schedule_deadline(db)
    client.create_schedule.assert_not_called()
    client.update_schedule.assert_not_called()
    client.delete_schedule.assert_not_called()
    save.assert_not_called()


def test_unaccepted_event_raises_for_retry(monkeypatch):
    client = Mock()
    client.invoke.return_value = {"StatusCode": 500}
    monkeypatch.setattr(worker.boto3, "client", lambda name: client)
    with pytest.raises(RuntimeError, match="not accepted"):
        worker.invoke_event("worker", {"source": "continuation"})


@pytest.mark.parametrize("source", [None, "deadline", "continuation"])
def test_async_continuation_uses_database_event_not_lambda_recursion(source, monkeypatch):
    db = Mock()
    invoke = Mock()
    monkeypatch.setattr(worker, "invoke_event", invoke)
    worker.request_continuation(db, source)
    assert "pg_notify('work_queue_changed', '')" in str(db.execute.call_args.args[0])
    db.commit.assert_called_once()
    invoke.assert_not_called()


def test_listener_continuation_needs_no_additional_event():
    db = Mock()
    worker.request_continuation(db, "listener")
    db.execute.assert_not_called()
    db.commit.assert_not_called()


def test_listener_wakes_on_socket_events_and_recovers_on_start(monkeypatch):
    import work_queue_listener as listener

    async def scenario():
        reader, writer = socket.socketpair()
        connection = Mock()
        connection.cursor.return_value.__enter__ = Mock(return_value=Mock())
        connection.cursor.return_value.__exit__ = Mock(return_value=False)
        connection.fileno.return_value = reader.fileno()
        connection.notifies = []
        received = asyncio.Event()
        finish_worker = threading.Event()

        def receive():
            if reader.recv(4096) == b"x":
                raise RuntimeError("disconnected")
            connection.notifies.append(object())
            received.set()

        connection.poll.side_effect = receive
        monkeypatch.setattr(listener.psycopg2, "connect", lambda **kwargs: connection)
        secret = Mock()
        secret.get_secret_value.return_value = {"SecretString": '{"username":"test","password":"test"}'}
        invoked = asyncio.Queue()
        loop = asyncio.get_running_loop()
        client = Mock()

        def invoke(**kwargs):
            loop.call_soon_threadsafe(invoked.put_nowait, kwargs)
            assert kwargs["InvocationType"] == "RequestResponse"
            if client.invoke.call_count == 1:
                assert finish_worker.wait(timeout=3)
            return {"StatusCode": 200, "Payload": BytesIO(b'{}')}

        client.invoke.side_effect = invoke
        monkeypatch.setattr(listener.boto3, "client", lambda name, **kwargs: secret if name == "secretsmanager" else client)
        for name in ("DB_SECRET_ARN", "DB_HOST", "DB_NAME", "WORK_QUEUE_FUNCTION_NAME"):
            monkeypatch.setenv(name, "test")
        task = asyncio.create_task(listener.listen())
        try:
            await asyncio.wait_for(invoked.get(), timeout=2)
            connection.poll.assert_not_called()
            writer.send(b"n" * 100)
            await asyncio.wait_for(received.wait(), timeout=2)
            assert client.invoke.call_count == 1
            finish_worker.set()
            await asyncio.wait_for(invoked.get(), timeout=2)
            assert client.invoke.call_count == 2
            writer.send(b"x")
            with pytest.raises(RuntimeError, match="disconnected"):
                await asyncio.wait_for(task, timeout=2)
            connection.close.assert_called_once()
        finally:
            finish_worker.set()
            task.cancel()
            reader.close()
            writer.close()

    asyncio.run(scenario())
