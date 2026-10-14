"""Startup automation contract, executed by CodeBuild with mocked AWS clients."""
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from start_work_queue import start


def clients():
    lam, events = Mock(), Mock()
    mappings = [{"UUID": name, "State": "Disabled", "EventSourceArn": f"arn:aws:dynamodb:us-east-1:123:table/{name}/stream/test"}
                for name in ("calls", "sms_messages", "conversations")]
    lam.get_paginator.return_value.paginate.return_value = [{"EventSourceMappings": mappings}]
    lam.get_event_source_mapping.return_value = {"State": "Enabled"}
    lam.invoke.return_value = {"StatusCode": 202}
    return lam, events


def test_starts_streams_listener_and_worker_without_recurring_schedule():
    lam, events = clients()
    start(lam, events, "dev")
    assert lam.update_event_source_mapping.call_count == 3
    events.update_service.assert_called_once_with(cluster="moving-crm-work-queue-dev",
        service="moving-crm-work-queue-dev", desiredCount=1, forceNewDeployment=True)
    events.enable_rule.assert_not_called()
    assert lam.invoke.call_args.kwargs["InvocationType"] == "Event"
    assert lam.invoke.call_args.kwargs["FunctionName"] == "moving-crm-work-queue-worker-dev"


def test_incomplete_sources_fail_deployment_without_starting_worker():
    lam, events = clients()
    lam.get_paginator.return_value.paginate.return_value = [{"EventSourceMappings": []}]
    with pytest.raises(RuntimeError, match="three configured"):
        start(lam, events, "dev")
    events.enable_rule.assert_not_called()
    lam.invoke.assert_not_called()


def test_listener_start_failure_does_not_acknowledge_startup():
    lam, events = clients()
    events.update_service.side_effect = RuntimeError("listener unavailable")
    with pytest.raises(RuntimeError, match="listener unavailable"):
        start(lam, events, "dev")
    events.enable_rule.assert_not_called()


def test_startup_does_not_poll_mapping_state():
    lam, events = clients()
    lam.get_event_source_mapping.return_value = {"State": "Enabling"}
    start(lam, events, "dev")
    lam.get_event_source_mapping.assert_not_called()
    events.enable_rule.assert_not_called()
