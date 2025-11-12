import io
import uuid
import os
from datetime import timedelta
from typing import Optional, Tuple, Dict

from fastapi import FastAPI, UploadFile, File, HTTPException, Header, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from minio import Minio
from minio.error import S3Error
from PIL import Image
from dotenv import load_dotenv
from redis import Redis

load_dotenv()

# ===== MinIO =====
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY")
MINIO_USE_SSL = os.getenv("MINIO_USE_SSL", "false").lower() == "true"
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "media")

if not MINIO_ENDPOINT or not MINIO_ACCESS_KEY or not MINIO_SECRET_KEY:
    raise RuntimeError("MinIO configuration is incomplete. Check MINIO_* environment variables.")

PUBLIC_MINIO_ENDPOINT = os.getenv("PUBLIC_MINIO_ENDPOINT")

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")

redis_client = Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    db=REDIS_DB,
    password=REDIS_PASSWORD if REDIS_PASSWORD else None,
    decode_responses=True,
)

RAW_API_KEYS = os.getenv("API_KEYS", "")
API_KEYS_MAP: Dict[str, str] = {}

if RAW_API_KEYS:
    for pair in RAW_API_KEYS.split(","):
        pair = pair.strip()
        if not pair:
            continue
        try:
            client_id, key = pair.split(":", 1)
            client_id = client_id.strip()
            key = key.strip()
            if client_id and key:
                API_KEYS_MAP[key] = client_id
        except ValueError:
            continue

if not API_KEYS_MAP:
    print("WARNING: No API keys configured. Set API_KEYS in .env for production.")

MEDIA_URL_TTL_SECONDS = int(os.getenv("MEDIA_URL_TTL_SECONDS", "300"))

minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=MINIO_USE_SSL,
)

if not minio_client.bucket_exists(MINIO_BUCKET):
    minio_client.make_bucket(MINIO_BUCKET)

# ================== FastAPI ==================
app = FastAPI(
    title="Media Storage Service",
    description=(
        "Microservice to handle compressed media.\n"
        "- Protected via API Key (X-Api-Key).\n"
        "- Each request must include X-User-Id.\n"
        "- Generates signed, publicly accessible URLs.\n"
        "- Includes endpoints to upload, update, delete, and download media."
    ),
    version="1.1.0",
)

# ================== Models ==================
class MediaItem(BaseModel):
    id: str
    filename: str
    content_type: str
    path: str
    user_id: str
    client_id: str
    folder: str


def redis_key(media_id: str) -> str:
    return f"media:{media_id}"


def media_path_key(path: str) -> str:
    return f"media_path:{path}"


def save_media(item: MediaItem) -> None:
    redis_client.set(redis_key(item.id), item.json())
    redis_client.set(media_path_key(item.path), item.id)


def get_media_item(media_id: str) -> Optional[MediaItem]:
    data = redis_client.get(redis_key(media_id))
    if not data:
        return None
    return MediaItem.parse_raw(data)


def get_media_by_path(path: str) -> Optional[MediaItem]:
    media_id = redis_client.get(media_path_key(path))
    if not media_id:
        return None
    return get_media_item(media_id)


def delete_media_item(item: MediaItem) -> None:
    redis_client.delete(redis_key(item.id))
    redis_client.delete(media_path_key(item.path))


def sanitize_folder(folder: str) -> str:
    folder = folder.strip().strip("/")
    if not folder:
        return ""
    if ".." in folder:
        raise HTTPException(status_code=400, detail="Invalid folder name")
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_/"
    if any(ch not in allowed for ch in folder):
        raise HTTPException(status_code=400, detail="Invalid characters in folder")
    return folder


async def get_folder(x_folder: Optional[str] = Header(None, alias="X-Folder")) -> str:
    if not x_folder:
        return ""
    return sanitize_folder(x_folder)


def build_object_path(client_id: str, folder: str, user_id: str, media_id: str) -> str:
    if folder:
        return f"{client_id}/{folder}/{user_id}/{media_id}.webp"
    return f"{client_id}/{user_id}/{media_id}.webp"


async def get_client_id(x_api_key: Optional[str] = Header(None, alias="X-Api-Key")) -> str:
    if not x_api_key:
        raise HTTPException(status_code=401, detail="X-Api-Key required")
    client_id = API_KEYS_MAP.get(x_api_key)
    if not client_id:
        raise HTTPException(status_code=403, detail="Invalid or unauthorized API Key")
    return client_id


async def get_current_user(x_user_id: Optional[str] = Header(None, alias="X-User-Id")) -> str:
    if not x_user_id:
        raise HTTPException(status_code=401, detail="X-User-Id required")
    return x_user_id


async def compress_image(file: UploadFile) -> Tuple[bytes, str]:
    """Compress uploaded image to WEBP format."""
    try:
        raw = await file.read()
        image = Image.open(io.BytesIO(raw))
        if image.mode in ("RGBA", "P"):
            image = image.convert("RGB")
        buf = io.BytesIO()
        image.save(buf, format="WEBP", quality=80, method=6)
        buf.seek(0)
        return buf.read(), "image/webp"
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Image processing failed: {str(e)}")


def upload_to_minio(path: str, data: bytes, content_type: str):
    """Upload object to MinIO."""
    try:
        minio_client.put_object(
            bucket_name=MINIO_BUCKET,
            object_name=path,
            data=io.BytesIO(data),
            length=len(data),
            content_type=content_type,
        )
    except S3Error as e:
        raise HTTPException(status_code=500, detail=f"Upload to MinIO failed: {str(e)}") from e


def delete_from_minio(path: str):
    """Delete object from MinIO."""
    try:
        minio_client.remove_object(MINIO_BUCKET, path)
    except S3Error as e:
        raise HTTPException(status_code=500, detail=f"Delete from MinIO failed: {str(e)}") from e


def generate_signed_url(path: str) -> str:
    """
    Generate a signed MinIO URL.
    The signature is based on MINIO_ENDPOINT (must be the correct public host).
    """
    try:
        return minio_client.presigned_get_object(
            bucket_name=MINIO_BUCKET,
            object_name=path,
            expires=timedelta(seconds=MEDIA_URL_TTL_SECONDS),
        )
    except S3Error as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate signed URL: {str(e)}") from e


# ================== Endpoints ==================

#  Create media 
@app.post("/media", response_model=MediaItem, summary="Upload media (returns internal path)")
async def upload_media(
    file: UploadFile = File(...),
    client_id: str = Depends(get_client_id),
    user_id: str = Depends(get_current_user),
    folder: str = Depends(get_folder),
):
    """Upload and compress an image"""
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Only image files allowed")

    compressed, new_type = await compress_image(file)
    media_id = str(uuid.uuid4())
    path = build_object_path(client_id, folder, user_id, media_id)

    upload_to_minio(path, compressed, new_type)

    item = MediaItem(
        id=media_id,
        filename=file.filename,
        content_type=new_type,
        path=path,
        user_id=user_id,
        client_id=client_id,
        folder=folder,
    )
    save_media(item)
    return item


#  Get signed URL 
@app.get("/media/url", summary="Generate signed URL for media access")
async def generate_media_url(
    path: str = Query(...),
    client_id: str = Depends(get_client_id),
    user_id: str = Depends(get_current_user),
):
    """Generate a signed URL to access a private object in MinIO."""
    item = get_media_by_path(path)
    if not item:
        raise HTTPException(status_code=404, detail="Media not found")

    if item.client_id != client_id or item.user_id != user_id:
        raise HTTPException(status_code=403, detail="Unauthorized for this path")

    signed_url = generate_signed_url(path)
    return {"url": signed_url, "expires_in": MEDIA_URL_TTL_SECONDS}


# ---- Update media ----
@app.put("/media", response_model=MediaItem, summary="Update existing media by path")
async def update_media(
    path: str = Query(..., description="Internal path returned when uploading (MediaItem.path)"),
    file: UploadFile = File(...),
    client_id: str = Depends(get_client_id),
    user_id: str = Depends(get_current_user),
):
    """Replace an existing image in MinIO, preserving the same internal path."""
    item = get_media_by_path(path)
    if not item:
        raise HTTPException(status_code=404, detail="Media not found")

    if item.client_id != client_id or item.user_id != user_id:
        raise HTTPException(status_code=403, detail="Unauthorized for this path")

    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Only image files allowed")

    compressed, new_type = await compress_image(file)

    upload_to_minio(path, compressed, new_type)

    item.filename = file.filename
    item.content_type = new_type
    save_media(item)

    return item


#  Delete media 
@app.delete("/media", summary="Delete media by path")
async def delete_media(
    path: str = Query(..., description="Internal path returned when uploading (MediaItem.path)"),
    client_id: str = Depends(get_client_id),
    user_id: str = Depends(get_current_user),
):
    """Delete a media file from MinIO and remove its metadata from Redis."""
    item = get_media_by_path(path)
    if not item:
        raise HTTPException(status_code=404, detail="Media not found")

    if item.client_id != client_id or item.user_id != user_id:
        raise HTTPException(status_code=403, detail="Unauthorized for this path")

    delete_from_minio(path)
    delete_media_item(item)

    return {"detail": "Media deleted successfully"}


#  Download media 
@app.get("/media/download", summary="Download media content (stream)")
async def download_media(
    path: str = Query(..., description="Internal path returned when uploading (MediaItem.path)"),
    client_id: str = Depends(get_client_id),
    user_id: str = Depends(get_current_user),
):
    """Download a media file directly as a streaming response."""
    item = get_media_by_path(path)
    if not item:
        raise HTTPException(status_code=404, detail="Media not found")

    if item.client_id != client_id or item.user_id != user_id:
        raise HTTPException(status_code=403, detail="Unauthorized for this path")

    try:
        obj = minio_client.get_object(MINIO_BUCKET, path)
    except S3Error:
        raise HTTPException(status_code=404, detail="Media not found in storage")

    return StreamingResponse(
        obj,
        media_type=item.content_type or "application/octet-stream",
        headers={
            "Content-Disposition": f'inline; filename="{item.filename}"'
        },
    )
