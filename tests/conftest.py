import os

os.environ["S3_ENDPOINT"] = "https://example.invalid"
os.environ["S3_BUCKET"] = "test-bucket"
os.environ["S3_REGION"] = "us-east-1"
os.environ["S3_ACCESS_KEY_ID"] = "test-key"
os.environ["S3_SECRET_ACCESS_KEY"] = "test-secret"
os.environ["DATABASE_URL"] = "postgres://test@localhost:5432/test"

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.routers.db import get_conn

get_settings.cache_clear()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def mock_conn() -> AsyncIterator[AsyncMock]:
    conn = AsyncMock()

    async def fake_get_conn() -> AsyncIterator[AsyncMock]:
        yield conn

    app.dependency_overrides[get_conn] = fake_get_conn
    yield conn
    app.dependency_overrides.pop(get_conn, None)
