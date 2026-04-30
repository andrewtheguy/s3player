import os

os.environ["S3_ENDPOINT"] = "https://example.invalid"
os.environ["S3_BUCKET"] = "test-bucket"
os.environ["S3_REGION"] = "us-east-1"
os.environ["S3_ACCESS_KEY_ID"] = "test-key"
os.environ["S3_SECRET_ACCESS_KEY"] = "test-secret"

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app

get_settings.cache_clear()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
