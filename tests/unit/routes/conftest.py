"""Shared fixtures for backend API route tests."""

import sys
import os
import importlib.util
from unittest.mock import MagicMock

import pytest

BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "backend")
BACKEND_DIR = os.path.abspath(BACKEND_DIR)

# Mock db module before any route import
mock_db = MagicMock()
sys.modules["db"] = mock_db

# Mock config module
mock_config = MagicMock()
mock_config.get_config.return_value = {
    "AWS_REGION": "us-east-1",
    "CORS_ORIGINS": "http://localhost:5173",
    "DYNAMO_TABLE_NAME": "test-leads",
}
sys.modules["config"] = mock_config

# Ensure backend is on path (for transitive imports inside routes)
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def _load_module(name: str, rel_path: str):
    """Load a module from backend by file path, avoiding package shadowing."""
    full = os.path.join(BACKEND_DIR, rel_path)
    spec = importlib.util.spec_from_file_location(name, full)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# Pre-load route modules so tests can import them
_load_module("routes", os.path.join("routes", "__init__.py"))
_load_module("routes.meta", os.path.join("routes", "meta", "__init__.py"))
_messenger = _load_module("routes.meta.messenger", os.path.join("routes", "meta", "messenger.py"))
_instagram = _load_module("routes.meta.instagram", os.path.join("routes", "meta", "instagram.py"))
_sms = _load_module("routes.sms", os.path.join("routes", "sms.py"))

from fastapi.testclient import TestClient
from fastapi import FastAPI


@pytest.fixture
def mock_conversations_table():
    """Return the mocked conversations_table from the db module."""
    table = MagicMock()
    mock_db.conversations_table = table
    # Also patch the module-level reference in messenger and instagram
    _messenger.conversations_table = table
    _instagram.conversations_table = table
    return table


@pytest.fixture
def mock_sms_messages_table():
    """Return the mocked sms_messages_table from the db module."""
    table = MagicMock()
    mock_db.sms_messages_table = table
    _sms.sms_messages_table = table
    return table


@pytest.fixture
def messenger_client(mock_conversations_table):
    """TestClient wired to the messenger router."""
    app = FastAPI()
    app.include_router(_messenger.router)
    return TestClient(app)


@pytest.fixture
def instagram_client(mock_conversations_table):
    """TestClient wired to the instagram router."""
    app = FastAPI()
    app.include_router(_instagram.router)
    return TestClient(app)


@pytest.fixture
def sms_client(mock_sms_messages_table):
    """TestClient wired to the sms router."""
    app = FastAPI()
    app.include_router(_sms.router)
    return TestClient(app)
