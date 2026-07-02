"""Tests for the video processing background task and webhook notification flow."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.models import WebhookPayload


@pytest.mark.asyncio
async def test_dispatch_webhook_sends_post_request(client):
    """Verify that _dispatch_webhook correctly sends a POST request with the JSON payload."""
    from app.main import _dispatch_webhook
    from app.models import WebhookPayload

    payload = WebhookPayload(
        id="test-media-id",
        status="ready",
        path="client_test/folder/test-media-id.mp4",
        url="http://localhost:9000/signed-url",
        error=None,
        client_id="client_test",
        folder="folder",
    )
    webhook_url = "http://mybackend.local/callback"

    # Mock the AsyncClient.post method
    mock_response = MagicMock()
    mock_response.status_code = 200

    # We patch httpx.AsyncClient.post
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response

        await _dispatch_webhook(webhook_url, payload)

        mock_post.assert_called_once_with(
            webhook_url,
            json=payload.model_dump(),
            headers={"Content-Type": "application/json"},
        )


@pytest.mark.asyncio
async def test_process_video_background_success(client):
    """Verify _process_video_background flow on successful video compression and upload."""
    import app.main
    from app.main import _process_video_background
    from app.models import WebhookPayload

    media_id = "test-media-id"
    client_id = "client_test"
    folder = "folder"
    s3_key = f"{client_id}/{folder}/{media_id}.mp4"
    webhook_url = "http://mybackend.local/callback"
    tmp_raw_path = f"/tmp/{media_id}.mp4"

    # Mock the semaphore directly by setting it as an attribute
    app.main.video_semaphore = AsyncMock()

    with (
        patch("app.main.compress_video_async", new_callable=AsyncMock) as mock_compress,
        patch("app.main.upload_file") as mock_upload,
        patch("app.main.generate_presigned_url", return_value="http://localhost:9000/signed-url") as mock_presign,
        patch("app.main._dispatch_webhook", new_callable=AsyncMock) as mock_dispatch,
        patch("os.path.exists", return_value=True),
        patch("os.remove") as mock_remove,
    ):
        await _process_video_background(
            tmp_raw_path=tmp_raw_path,
            s3_key=s3_key,
            media_id=media_id,
            client_id=client_id,
            folder=folder,
            webhook_url=webhook_url,
        )

        # Assertions
        mock_compress.assert_called_once_with(tmp_raw_path, f"{tmp_raw_path}.mp4")
        mock_upload.assert_called_once_with(f"{tmp_raw_path}.mp4", s3_key, "video/mp4")
        mock_presign.assert_called_once_with(s3_key)
        
        # Check webhook callback payload
        mock_dispatch.assert_called_once()
        called_url, called_payload = mock_dispatch.call_args[0]
        assert called_url == webhook_url
        assert isinstance(called_payload, WebhookPayload)
        assert called_payload.id == media_id
        assert called_payload.status == "ready"
        assert called_payload.path == s3_key
        assert called_payload.url == "http://localhost:9000/signed-url"
        assert called_payload.error is None

        # Verify cleanup of temporary files
        assert mock_remove.call_count == 2


@pytest.mark.asyncio
async def test_process_video_background_failure(client):
    """Verify _process_video_background flow when compression raises an exception."""
    import app.main
    from app.main import _process_video_background
    from app.models import WebhookPayload

    media_id = "test-media-id"
    client_id = "client_test"
    folder = "folder"
    s3_key = f"{client_id}/{folder}/{media_id}.mp4"
    webhook_url = "http://mybackend.local/callback"
    tmp_raw_path = f"/tmp/{media_id}.mp4"

    # Mock the semaphore directly by setting it as an attribute
    app.main.video_semaphore = AsyncMock()

    # Make compression fail
    mock_compress = AsyncMock(side_effect=Exception("FFmpeg failed to encode audio"))

    with (
        patch("app.main.compress_video_async", mock_compress),
        patch("app.main.upload_file") as mock_upload,
        patch("app.main.generate_presigned_url") as mock_presign,
        patch("app.main._dispatch_webhook", new_callable=AsyncMock) as mock_dispatch,
        patch("os.path.exists", return_value=True),
        patch("os.remove") as mock_remove,
    ):
        await _process_video_background(
            tmp_raw_path=tmp_raw_path,
            s3_key=s3_key,
            media_id=media_id,
            client_id=client_id,
            folder=folder,
            webhook_url=webhook_url,
        )

        # Assertions
        mock_upload.assert_not_called()
        mock_presign.assert_not_called()
        
        # Check failure webhook callback payload
        mock_dispatch.assert_called_once()
        called_url, called_payload = mock_dispatch.call_args[0]
        assert called_url == webhook_url
        assert isinstance(called_payload, WebhookPayload)
        assert called_payload.id == media_id
        assert called_payload.status == "failed"
        assert called_payload.path is None
        assert called_payload.url is None
        assert "FFmpeg failed to encode audio" in called_payload.error

        # Temp files should still be removed
        assert mock_remove.call_count == 2
