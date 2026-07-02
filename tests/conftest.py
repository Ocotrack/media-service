"""
Shared fixtures for the media-service test suite.

All S3 and FFmpeg calls are mocked so tests run instantly
without any infrastructure (no MinIO, no FFmpeg binary needed).
"""

import asyncio
import io
import os
import sys
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Set env vars before any app import so boto3 client creation does not fail.
os.environ["AWS_ACCESS_KEY_ID"] = "test-key"
os.environ["AWS_SECRET_ACCESS_KEY"] = "test-secret"
os.environ["AWS_BUCKET_NAME"] = "media"
os.environ["AWS_ENDPOINT_URL"] = "http://localhost:9000"
os.environ["AWS_REGION"] = "us-east-1"
os.environ["API_KEYS"] = "testkey:local_test"

STORAGE_MODULE = "app.storage"
COMPRESSION_MODULE = "app.compression"

# The API key used in all authenticated test requests
TEST_API_KEY = "testkey"
TEST_CLIENT_ID = "local_test"
VALID_HEADERS = {"X-Api-Key": TEST_API_KEY}


# --- Minimal fake file helpers ---

def make_image_bytes() -> bytes:
    """Return a minimal valid 1x1 white JPEG."""
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (1, 1), color=(255, 255, 255)).save(buf, format="JPEG")
    return buf.getvalue()


def make_text_bytes() -> bytes:
    return b"hello world"


# --- App client fixture ---

@pytest_asyncio.fixture
async def client():
    """
    Async HTTP client wired directly to the FastAPI app via ASGI transport.
    - All S3 calls are replaced with no-op mocks.
    - FFmpeg compression is replaced with an async no-op.
    - API_KEYS_MAP is patched directly so auth works regardless of .env on disk.
    """
    # Clear cached app modules so each fixture gets a clean import
    for mod in list(sys.modules.keys()):
        if mod.startswith("app"):
            del sys.modules[mod]

    with (
        patch(f"{STORAGE_MODULE}.s3_client"),
        patch(f"{STORAGE_MODULE}.upload_bytes"),
        patch(f"{STORAGE_MODULE}.upload_file"),
        patch(f"{STORAGE_MODULE}.delete_file"),
        patch(
            f"{STORAGE_MODULE}.generate_presigned_url",
            return_value="http://localhost:9000/media/signed-url?token=abc",
        ),
        patch(
            f"{STORAGE_MODULE}.get_object_stream",
            return_value=io.BytesIO(b"binary-content"),
        ),
        patch(
            f"{COMPRESSION_MODULE}.compress_image",
            return_value=(b"compressed-webp", "image/webp", "webp"),
        ),
        patch(
            f"{COMPRESSION_MODULE}.compress_video_async",
            new=AsyncMock(),
        ),
        # Patch the map directly so .env on disk cannot interfere
        patch("app.config.API_KEYS_MAP", {TEST_API_KEY: TEST_CLIENT_ID}),
    ):
        from app.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            yield ac
