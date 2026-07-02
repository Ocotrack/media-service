"""Tests for the storage helper functions (S3 operations and URL generation)."""

import pytest
from unittest.mock import MagicMock, patch
import urllib.parse


def test_generate_presigned_url_without_public_url():
    """Verify that the presigned URL remains unchanged when AWS_PUBLIC_URL is not set."""
    # We patch the config variables inside app.storage
    with (
        patch("app.storage.AWS_PUBLIC_URL", None),
        patch("app.storage.s3_client") as mock_s3,
    ):
        mock_s3.generate_presigned_url.return_value = "http://minio:9000/media/file.webp?Signature=123"

        from app.storage import generate_presigned_url
        url = generate_presigned_url("local_test/file.webp")

        assert url == "http://minio:9000/media/file.webp?Signature=123"
        mock_s3.generate_presigned_url.assert_called_once()


def test_generate_presigned_url_with_https_public_url():
    """Verify that generate_presigned_url swaps the S3 host for the public HTTPS CDN domain."""
    with (
        patch("app.storage.AWS_PUBLIC_URL", "https://cdn.mydomain.com"),
        patch("app.storage.s3_client") as mock_s3,
    ):
        # boto3 generates URL pointing to internal or local MinIO host
        mock_s3.generate_presigned_url.return_value = "http://minio:9000/media/file.webp?Signature=123"

        from app.storage import generate_presigned_url
        url = generate_presigned_url("local_test/file.webp")

        # The protocol must be https, and netloc must be the cdn host
        parsed = urllib.parse.urlparse(url)
        assert parsed.scheme == "https"
        assert parsed.netloc == "cdn.mydomain.com"
        assert parsed.path == "/media/file.webp"
        assert "Signature=123" in parsed.query


def test_generate_presigned_url_with_custom_port_public_url():
    """Verify swapping when the public URL has a custom port."""
    with (
        patch("app.storage.AWS_PUBLIC_URL", "https://media.company.org:8443"),
        patch("app.storage.s3_client") as mock_s3,
    ):
        mock_s3.generate_presigned_url.return_value = "http://localhost:9000/media/file.webp?Signature=123"

        from app.storage import generate_presigned_url
        url = generate_presigned_url("local_test/file.webp")

        parsed = urllib.parse.urlparse(url)
        assert parsed.scheme == "https"
        assert parsed.netloc == "media.company.org:8443"
        assert parsed.path == "/media/file.webp"
