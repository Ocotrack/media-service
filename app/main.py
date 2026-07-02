import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager
from typing import Optional

import httpx
from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import StreamingResponse
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from .compression import compress_image, compress_video_async
from .config import (
    ALLOWED_EXTENSIONS,
    API_KEYS_MAP,
    MAX_CONCURRENT_JOBS,
    MEDIA_URL_TTL_SECONDS,
)
from .models import MediaItem, ProcessingResponse, WebhookPayload
from .storage import (
    delete_file,
    generate_presigned_url,
    get_object_stream,
    upload_bytes,
    upload_file,
)

logger = logging.getLogger(__name__)

# ============================================================
# Concurrency Semaphore (lives for the application lifetime)
# ============================================================
# Controls the max number of parallel FFmpeg processes.
# Set MAX_CONCURRENT_JOBS in .env (default: 2).
video_semaphore: asyncio.Semaphore


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize shared application resources on startup."""
    global video_semaphore
    video_semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)
    logger.info(
        "Media Service started. Max concurrent video jobs: %d", MAX_CONCURRENT_JOBS
    )
    yield
    logger.info("Media Service shutting down.")


# ============================================================
# Application
# ============================================================

app = FastAPI(
    title="Media Service",
    description=(
        "A self-hosted, S3-compatible microservice for uploading, compressing, "
        "and managing media files (images, videos, and documents). "
        "Supports AWS S3, MinIO, Cloudflare R2, and any S3-compatible provider."
    ),
    version="2.0.0",
    lifespan=lifespan,
)

# Trust reverse-proxy headers (X-Forwarded-For, X-Forwarded-Proto)
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")


# ============================================================
# Constants
# ============================================================
CHUNK_SIZE = 1024 * 1024  # 1 MB read chunks for streaming uploads to disk


# ============================================================
# Health Check
# ============================================================

@app.get("/health", tags=["System"])
async def health():
    """Liveness check. Returns 200 OK if the service is running."""
    return {"status": "ok", "max_concurrent_jobs": MAX_CONCURRENT_JOBS}


# ============================================================
# Dependency Helpers
# ============================================================

def sanitize_folder(folder: str) -> str:
    folder = folder.strip().strip("/")
    if not folder:
        return ""
    if ".." in folder:
        raise HTTPException(status_code=400, detail="Invalid folder: '..' is not allowed")
    allowed_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_/")
    if any(ch not in allowed_chars for ch in folder):
        raise HTTPException(status_code=400, detail="Folder contains invalid characters")
    return folder


async def get_folder(
    x_folder: Optional[str] = Header(None, alias="X-Folder"),
) -> str:
    return sanitize_folder(x_folder) if x_folder else ""


async def get_client_id(
    x_api_key: Optional[str] = Header(None, alias="X-Api-Key"),
) -> str:
    if not x_api_key:
        raise HTTPException(status_code=401, detail="X-Api-Key header is required")
    client_id = API_KEYS_MAP.get(x_api_key)
    if not client_id:
        raise HTTPException(status_code=403, detail="Invalid or unauthorized API Key")
    return client_id


def build_s3_key(client_id: str, folder: str, media_id: str, ext: str) -> str:
    """Construct the S3 object key: {client_id}/{folder?}/{media_id}.{ext}"""
    parts = [client_id]
    if folder:
        parts.append(folder)
    parts.append(f"{media_id}.{ext}")
    return "/".join(parts)


def validate_path_ownership(path: str, client_id: str) -> None:
    """
    Ensure a given S3 path starts with the authenticated client's ID prefix.
    Prevents clients from accessing or mutating each other's data.
    """
    parts = path.split("/")
    if not parts or parts[0] != client_id:
        raise HTTPException(
            status_code=403, detail="You are not authorized to access this resource"
        )


# ============================================================
# Disk Streaming Helper
# ============================================================

async def stream_upload_to_disk(file: UploadFile, dest_path: str) -> None:
    """
    Read an UploadFile in 1MB chunks and write it directly to dest_path on disk.
    This keeps RAM usage constant regardless of the uploaded file size.
    """
    with open(dest_path, "wb") as out:
        while True:
            chunk = await file.read(CHUNK_SIZE)
            if not chunk:
                break
            out.write(chunk)


# ============================================================
# Background Task: Video Processing
# ============================================================

async def _process_video_background(
    tmp_raw_path: str,
    s3_key: str,
    media_id: str,
    client_id: str,
    folder: str,
    webhook_url: Optional[str],
):
    """
    Background task for video processing:
      1. Acquire the concurrency semaphore (throttles parallel FFmpeg jobs).
      2. Compress video with FFmpeg (async subprocess, non-blocking).
      3. Upload compressed file to S3.
      4. Clean up all temporary disk files.
      5. Dispatch HTTP webhook callback (if webhook_url is provided).
    """
    tmp_compressed_path = f"{tmp_raw_path}.mp4"
    status = "failed"
    error_message: Optional[str] = None
    final_url: Optional[str] = None

    try:
        async with video_semaphore:
            logger.info("[video] Acquired semaphore for %s", media_id)
            await compress_video_async(tmp_raw_path, tmp_compressed_path)

        upload_file(tmp_compressed_path, s3_key, "video/mp4")
        final_url = generate_presigned_url(s3_key)
        status = "ready"
        logger.info("[video] Successfully processed and uploaded %s -> %s", media_id, s3_key)

    except Exception as exc:
        error_message = str(exc)
        logger.error("[video] Processing failed for %s: %s", media_id, exc)

    finally:
        # Always clean up temp files regardless of success or failure
        for path in (tmp_raw_path, tmp_compressed_path):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError as e:
                logger.warning("[video] Could not remove temp file %s: %s", path, e)

    # Dispatch webhook notification
    if webhook_url:
        payload = WebhookPayload(
            id=media_id,
            status=status,
            path=s3_key if status == "ready" else None,
            url=final_url,
            error=error_message,
            client_id=client_id,
            folder=folder,
        )
        await _dispatch_webhook(webhook_url, payload)


async def _dispatch_webhook(webhook_url: str, payload: WebhookPayload) -> None:
    """Send the processing result as a POST request to the client's webhook URL."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                webhook_url,
                json=payload.model_dump(),
                headers={"Content-Type": "application/json"},
            )
            logger.info(
                "[webhook] Dispatched to %s — HTTP %d", webhook_url, response.status_code
            )
    except httpx.RequestError as e:
        logger.error("[webhook] Failed to deliver to %s: %s", webhook_url, e)


# ============================================================
# Endpoints
# ============================================================

@app.post(
    "/media",
    summary="Upload a media file",
    description=(
        "Upload an image, video, or document. "
        "Images are compressed synchronously to WebP. "
        "Videos are compressed asynchronously (HTTP 202 is returned immediately). "
        "Optionally provide a `webhook_url` to receive a callback when video processing completes."
    ),
    tags=["Media"],
    responses={
        200: {"description": "File uploaded and processed successfully (images/documents)"},
        202: {"description": "Video accepted; processing in background"},
    },
)
async def upload_media(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    client_id: str = Depends(get_client_id),
    folder: str = Depends(get_folder),
    webhook_url: Optional[str] = Query(
        default=None,
        description="Optional URL to receive a POST callback when video processing finishes.",
    ),
):
    content_type = (file.content_type or "").lower()
    original_filename = file.filename or "upload"
    original_ext = os.path.splitext(original_filename)[1].lower().lstrip(".")
    media_id = str(uuid.uuid4())

    # ---- Image: process synchronously in memory ----
    if content_type.startswith("image/"):
        raw = await file.read()
        compressed, final_type, ext = compress_image(raw)
        s3_key = build_s3_key(client_id, folder, media_id, ext)
        upload_bytes(s3_key, compressed, final_type)

        return MediaItem(
            id=media_id,
            filename=original_filename,
            content_type=final_type,
            path=s3_key,
            client_id=client_id,
            folder=folder,
        )

    # ---- Video: stream to disk, process asynchronously ----
    if content_type.startswith("video/"):
        tmp_raw_path = f"/tmp/{media_id}.{original_ext or 'raw'}"
        s3_key = build_s3_key(client_id, folder, media_id, "mp4")

        await stream_upload_to_disk(file, tmp_raw_path)

        background_tasks.add_task(
            _process_video_background,
            tmp_raw_path=tmp_raw_path,
            s3_key=s3_key,
            media_id=media_id,
            client_id=client_id,
            folder=folder,
            webhook_url=webhook_url,
        )

        return ProcessingResponse(
            id=media_id,
            status="processing",
            message="Video accepted. It will be compressed and uploaded in the background.",
            filename=original_filename,
            client_id=client_id,
            folder=folder,
        )

    # ---- Documents: store as-is (configurable extensions) ----
    is_allowed_doc = (
        content_type
        in {
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.ms-excel",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/xml",
            "text/xml",
            "text/plain",
        }
        or original_ext in ALLOWED_EXTENSIONS
    )

    if is_allowed_doc:
        ext = original_ext or "bin"
        s3_key = build_s3_key(client_id, folder, media_id, ext)
        tmp_path = f"/tmp/{media_id}.{ext}"

        try:
            await stream_upload_to_disk(file, tmp_path)
            upload_file(tmp_path, s3_key, content_type or "application/octet-stream")
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

        return MediaItem(
            id=media_id,
            filename=original_filename,
            content_type=content_type or "application/octet-stream",
            path=s3_key,
            client_id=client_id,
            folder=folder,
        )

    raise HTTPException(
        status_code=415,
        detail=(
            f"Unsupported media type '{content_type}' or extension '.{original_ext}'. "
            f"Accepted: image/*, video/*, and extensions: {', '.join(sorted(ALLOWED_EXTENSIONS))}."
        ),
    )


@app.get(
    "/media/url",
    summary="Generate a presigned URL for private file access",
    tags=["Media"],
)
async def generate_media_url(
    path: str = Query(..., description="S3 object key (path) of the media file"),
    client_id: str = Depends(get_client_id),
):
    """
    Generate a time-limited presigned URL for direct access to a private file.
    TTL is controlled by MEDIA_URL_TTL_SECONDS (.env).
    """
    validate_path_ownership(path, client_id)
    url = generate_presigned_url(path)
    return {"url": url, "expires_in": MEDIA_URL_TTL_SECONDS}


@app.delete(
    "/media",
    summary="Delete a media file",
    tags=["Media"],
)
async def delete_media(
    path: str = Query(..., description="S3 object key (path) of the file to delete"),
    client_id: str = Depends(get_client_id),
):
    """Permanently delete a media file from storage."""
    validate_path_ownership(path, client_id)
    delete_file(path)
    return {"detail": "Media deleted successfully", "path": path}


@app.get(
    "/media/download",
    summary="Stream a media file for direct download",
    tags=["Media"],
)
async def download_media(
    path: str = Query(..., description="S3 object key (path) of the file to download"),
    client_id: str = Depends(get_client_id),
):
    """
    Stream file content directly from S3 as an HTTP response.
    Useful for serving private files without exposing storage credentials.
    """
    validate_path_ownership(path, client_id)

    stream = get_object_stream(path)
    if stream is None:
        raise HTTPException(status_code=404, detail="File not found in storage")

    filename = os.path.basename(path)
    return StreamingResponse(
        stream,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
