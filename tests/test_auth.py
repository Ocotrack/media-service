"""Tests for API key authentication across all protected endpoints."""

import pytest


@pytest.mark.asyncio
async def test_missing_api_key_returns_401(client):
    response = await client.post("/media")
    assert response.status_code == 401
    assert "X-Api-Key" in response.json()["detail"]


@pytest.mark.asyncio
async def test_invalid_api_key_returns_403(client):
    response = await client.get(
        "/media/url",
        headers={"X-Api-Key": "invalid-key"},
        params={"path": "local_test/file.webp"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_invalid_key_on_delete_returns_403(client):
    response = await client.delete(
        "/media",
        headers={"X-Api-Key": "bad-key"},
        params={"path": "local_test/file.webp"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_invalid_key_on_download_returns_403(client):
    response = await client.get(
        "/media/download",
        headers={"X-Api-Key": "bad-key"},
        params={"path": "local_test/file.webp"},
    )
    assert response.status_code == 403
