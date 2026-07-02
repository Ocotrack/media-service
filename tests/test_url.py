"""Tests for GET /media/url (presigned URL generation)."""

import pytest
from tests.conftest import VALID_HEADERS

# Path that belongs to the authenticated client (local_test)
OWNED_PATH = "local_test/uploads/some-uuid.webp"
# Path that belongs to a different client
FOREIGN_PATH = "other_client/uploads/some-uuid.webp"


@pytest.mark.asyncio
async def test_generate_url_returns_signed_url(client):
    response = await client.get(
        "/media/url",
        headers=VALID_HEADERS,
        params={"path": OWNED_PATH},
    )
    assert response.status_code == 200
    body = response.json()
    assert "url" in body
    assert body["url"].startswith("http")
    assert "expires_in" in body
    assert isinstance(body["expires_in"], int)


@pytest.mark.asyncio
async def test_generate_url_requires_path_param(client):
    response = await client.get("/media/url", headers=VALID_HEADERS)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_generate_url_for_foreign_path_returns_403(client):
    response = await client.get(
        "/media/url",
        headers=VALID_HEADERS,
        params={"path": FOREIGN_PATH},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_generate_url_without_auth_returns_401(client):
    response = await client.get(
        "/media/url", params={"path": OWNED_PATH}
    )
    assert response.status_code == 401
