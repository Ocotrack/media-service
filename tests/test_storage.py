"""Tests for the storage helper functions (S3 operations and URL generation)."""

import pytest
from unittest.mock import MagicMock, patch
import urllib.parse


def test_generate_presigned_url_without_public_url():
    """Verify that the presigned URL uses the default internal endpoint when AWS_PUBLIC_URL is not set."""
    with (
        patch("app.storage.AWS_PUBLIC_URL", None),
        patch("boto3.client") as mock_boto,
    ):
        mock_client_instance = MagicMock()
        mock_client_instance.generate_presigned_url.return_value = "http://minio:9000/media/file.webp?Signature=123"
        mock_boto.return_value = mock_client_instance

        from app.storage import generate_presigned_url
        url = generate_presigned_url("local_test/file.webp")

        assert url == "http://minio:9000/media/file.webp?Signature=123"
        mock_client_instance.generate_presigned_url.assert_called_once()
        
        # Ensure it was initialized with the default endpoint
        kwargs = mock_boto.call_args[1]
        # In our test environment, AWS_ENDPOINT_URL is http://localhost:9000
        assert kwargs["endpoint_url"] == "http://localhost:9000"


def test_generate_presigned_url_with_https_public_url():
    """Verify that generate_presigned_url instantiates boto3 with the public HTTPS CDN domain."""
    with (
        patch("app.storage.AWS_PUBLIC_URL", "https://cdn.mydomain.com"),
        patch("boto3.client") as mock_boto,
    ):
        mock_client_instance = MagicMock()
        mock_client_instance.generate_presigned_url.return_value = "https://cdn.mydomain.com/media/file.webp?Signature=123"
        mock_boto.return_value = mock_client_instance

        from app.storage import generate_presigned_url
        url = generate_presigned_url("local_test/file.webp")

        parsed = urllib.parse.urlparse(url)
        assert parsed.scheme == "https"
        assert parsed.netloc == "cdn.mydomain.com"
        assert parsed.path == "/media/file.webp"
        
        # Crucial check: ensure the boto3 client itself was instantiated with the public URL
        kwargs = mock_boto.call_args[1]
        assert kwargs["endpoint_url"] == "https://cdn.mydomain.com"


def test_generate_presigned_url_with_custom_port_public_url():
    """Verify boto3 client instantiation with a custom port public URL."""
    with (
        patch("app.storage.AWS_PUBLIC_URL", "https://media.company.org:8443"),
        patch("boto3.client") as mock_boto,
    ):
        mock_client_instance = MagicMock()
        mock_client_instance.generate_presigned_url.return_value = "https://media.company.org:8443/media/file.webp?Signature=123"
        mock_boto.return_value = mock_client_instance

        from app.storage import generate_presigned_url
        url = generate_presigned_url("local_test/file.webp")

        parsed = urllib.parse.urlparse(url)
        assert parsed.scheme == "https"
        assert parsed.netloc == "media.company.org:8443"
        
        kwargs = mock_boto.call_args[1]
        assert kwargs["endpoint_url"] == "https://media.company.org:8443"
