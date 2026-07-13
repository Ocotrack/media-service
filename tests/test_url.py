"""Tests for GET /media/url (presigned URL generation)."""

import pytest
from tests.conftest import VALID_HEADERS

# Path that belongs to the authenticated client (local_test)
OWNED_PATH = "local_test/uploads/some-uuid.webp"
# Path that belongs to a different client
FOREIGN_PATH = "other_client/uploads/some-uuid.webp"


@pytest.mark.asyncio
async def test_generate_url_returns_signed_url(client):
    response = await client.get("/media/presign?path=local_test/my-image.jpg", headers=VALID_HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert "url" in data
    assert "signed-url" in data["url"]
    assert data["type"] == "presigned"
    assert data["expires_in"] == 3600

@pytest.mark.asyncio
async def test_generate_url_returns_public_url(client):
    response = await client.get("/media/presign?path=local_test/public-image.jpg&public=true", headers=VALID_HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert "url" in data
    assert "public-url" in data["url"]
    assert data["type"] == "public"
    assert data["expires_in"] is None


@pytest.mark.asyncio
async def test_generate_url_requires_path_param(client):
    response = await client.get("/media/presign", headers=VALID_HEADERS)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_generate_url_for_foreign_path_returns_403(client):
    response = await client.get(
        "/media/presign",
        headers=VALID_HEADERS,
        params={"path": FOREIGN_PATH},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_generate_url_without_auth_returns_401(client):
    response = await client.get(
        "/media/presign", params={"path": OWNED_PATH}
    )
    assert response.status_code == 401
