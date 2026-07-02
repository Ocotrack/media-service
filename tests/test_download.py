"""Tests for GET /media/download (streaming download)."""

import pytest
from unittest.mock import patch
from tests.conftest import VALID_HEADERS

OWNED_PATH = "local_test/uploads/some-uuid.webp"
FOREIGN_PATH = "other_client/secret/file.pdf"


@pytest.mark.asyncio
async def test_download_returns_binary_content(client):
    response = await client.get(
        "/media/download",
        headers=VALID_HEADERS,
        params={"path": OWNED_PATH},
    )
    assert response.status_code == 200
    assert response.content == b"binary-content"
    assert response.headers["content-disposition"] == 'attachment; filename="some-uuid.webp"'


@pytest.mark.asyncio
async def test_download_foreign_path_returns_403(client):
    response = await client.get(
        "/media/download",
        headers=VALID_HEADERS,
        params={"path": FOREIGN_PATH},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_download_not_found_returns_404(client):
    with patch("app.main.get_object_stream", return_value=None):
        response = await client.get(
            "/media/download",
            headers=VALID_HEADERS,
            params={"path": OWNED_PATH},
        )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_download_without_path_returns_422(client):
    response = await client.get("/media/download", headers=VALID_HEADERS)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_download_without_auth_returns_401(client):
    response = await client.get(
        "/media/download", params={"path": OWNED_PATH}
    )
    assert response.status_code == 401
