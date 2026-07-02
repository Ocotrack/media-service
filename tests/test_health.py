"""Tests for GET /health"""

import pytest
from tests.conftest import VALID_HEADERS


@pytest.mark.asyncio
async def test_health_returns_ok(client):
    response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "max_concurrent_jobs" in body


@pytest.mark.asyncio
async def test_health_does_not_require_auth(client):
    """Health endpoint must be publicly accessible (no API key needed)."""
    response = await client.get("/health")
    assert response.status_code == 200
