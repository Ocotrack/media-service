"""Tests for DELETE /media."""

import pytest
from unittest.mock import patch
from tests.conftest import VALID_HEADERS

OWNED_PATH = "local_test/uploads/some-uuid.webp"
FOREIGN_PATH = "other_client/secret/file.pdf"


@pytest.mark.asyncio
async def test_delete_owned_file_returns_200(client):
    response = await client.delete(
        "/media",
        headers=VALID_HEADERS,
        params={"path": OWNED_PATH},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["detail"] == "Media deleted successfully"
    assert body["path"] == OWNED_PATH


@pytest.mark.asyncio
async def test_delete_foreign_path_returns_403(client):
    response = await client.delete(
        "/media",
        headers=VALID_HEADERS,
        params={"path": FOREIGN_PATH},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_delete_without_path_returns_422(client):
    response = await client.delete(
        "/media",
        headers=VALID_HEADERS,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_delete_without_auth_returns_401(client):
    response = await client.delete(
        "/media",
        params={"path": OWNED_PATH},
    )
    assert response.status_code == 401
