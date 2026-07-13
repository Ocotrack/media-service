"""Tests for the storage helper functions (S3 operations and URL generation)."""

import pytest
from unittest.mock import MagicMock, patch
import urllib.parse


def test_make_client_with_custom_endpoint():
    """Verify that _make_client correctly uses the provided endpoint_url override."""
    from app.storage import _make_client
    
    # Passing a custom endpoint should override the default (AWS_ENDPOINT_URL)
    client = _make_client(endpoint_url="https://custom.endpoint.com")
    assert client.meta.endpoint_url == "https://custom.endpoint.com"


def test_generate_public_url_uses_presign_endpoint():
    """Verify that generate_public_url builds URLs using PRESIGN_ENDPOINT_URL."""
    with patch("app.storage.PRESIGN_ENDPOINT_URL", "https://cdn.mydomain.com"):
        from app.storage import generate_public_url
        url = generate_public_url("local_test/file.webp")
        assert url == "https://cdn.mydomain.com/media/local_test/file.webp"


def test_generate_presigned_url_delegates_to_presign_client():
    """Verify that generate_presigned_url delegates to the s3_presign_client singleton."""
    with patch("app.storage.s3_presign_client") as mock_client:
        mock_client.generate_presigned_url.return_value = "https://cdn.mydomain.com/media/file.webp?Signature=123"
        
        from app.storage import generate_presigned_url
        url = generate_presigned_url("local_test/file.webp")
        
        assert url == "https://cdn.mydomain.com/media/file.webp?Signature=123"
        mock_client.generate_presigned_url.assert_called_once_with(
            ClientMethod="get_object",
            Params={"Bucket": "media", "Key": "local_test/file.webp"},
            ExpiresIn=3600
        )
