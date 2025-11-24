import io
import uuid
import os
from typing import Optional

from fastapi import FastAPI, UploadFile, File, HTTPException, Header, Depends, Query
from fastapi.responses import StreamingResponse

from .config import API_KEYS_MAP, MEDIA_URL_TTL_SECONDS
from .models import (
    MediaItem,
    save_media,
    get_media_by_path,
    delete_media_item,
)
from .storage import (
    upload_bytes,
    delete_object,
    generate_signed_url,
    get_object_stream,
)
from .compression import compress_image_aggressive
from .queue import enqueue_job

app = FastAPI(
    title="Media Storage Service",
    description=(
        "Module of Meximova Transportes for managing media files.\n"
        "- Allows uploading, updating, deleting, and downloading media.\n"
        "- Protected by project-based API Key.\n"
        "- Each request requires a user identifier (X-User-Id)."
    ),
    version="1.0.0",
)

# ========== Helpers ==========

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

async def get_client_id(x_api_key: Optional[str] = Header(None, alias="X-Api-Key")) -> str:
    if not x_api_key:
        raise HTTPException(status_code=401, detail="X-Api-Key required")
    client_id = API_KEYS_MAP.get(x_api_key)
    if not client_id:
        raise HTTPException(status_code=403, detail="Invalid or unauthorized API Key")
    return client_id

async def get_current_user(x_user_id: Optional[str] = Header(None, alias="X-User-Id")) -> Optional[str]:
    return x_user_id

def build_base_path(client_id: str, folder: str, user_id: Optional[str], media_id: str) -> str:
    parts = [client_id]
    if folder:
        parts.append(folder)
    if user_id:
        parts.append(user_id)
    parts.append(media_id)
    return "/".join(parts)

# ========== Endpoints ==========

@app.post("/media", response_model=MediaItem, summary="Upload media")
async def upload_media(
    file: UploadFile = File(...),
    client_id: str = Depends(get_client_id),
    user_id: Optional[str] = Depends(get_current_user),
    folder: str = Depends(get_folder),
):
    """
    Upload media:
    - Small images: compressed inline → WEBP.
    - Large images & all videos: uploaded quickly and processed async via queue.
    """
    content_type = file.content_type or ""
    media_id = str(uuid.uuid4())
    base_path = build_base_path(client_id, folder, user_id, media_id)

    # Images
    if content_type.startswith("image/"):
        raw = await file.read()
        # Threshold: inline if <= 3MB, else async
        if len(raw) <= 3 * 1024 * 1024:
            compressed, new_type, ext = compress_image_aggressive(raw)
            final_path = f"{base_path}.{ext}"
            upload_bytes(final_path, compressed, new_type)

            item = MediaItem(
                id=media_id,
                filename=file.filename,
                content_type=new_type,
                path=final_path,
                user_id=user_id,
                client_id=client_id,
                folder=folder,
                status="ready",
            )
            save_media(item)
            return item
        else:
            original_path = f"{base_path}.original"
            upload_bytes(original_path, raw, content_type)

            final_path = f"{base_path}.webp"
            item = MediaItem(
                id=media_id,
                filename=file.filename,
                content_type="image/webp",
                path=final_path,
                user_id=user_id,
                client_id=client_id,
                folder=folder,
                status="processing",
                original_path=original_path,
            )
            save_media(item)

            enqueue_job(
                {
                    "media_id": media_id,
                    "original_path": original_path,
                    "final_path": final_path,
                    "content_type": content_type,
                    "type": "image",
                }
            )
            return item

    if content_type.startswith("video/"):
        raw = await file.read()
        original_ext = os.path.splitext(file.filename or "")[1] or ".source"
        original_path = f"{base_path}{original_ext}"
        upload_bytes(original_path, raw, content_type)

        final_path = f"{base_path}.mp4"
        item = MediaItem(
            id=media_id,
            filename=file.filename,
            content_type="video/mp4",
            path=final_path,
            user_id=user_id,
            client_id=client_id,
            folder=folder,
            status="processing",
            original_path=original_path,
        )
        save_media(item)

        enqueue_job(
            {
                "media_id": media_id,
                "original_path": original_path,
                "final_path": final_path,
                "content_type": content_type,
                "type": "video",
            }
        )
        return item

    raise HTTPException(status_code=400, detail="Only image/* or video/* files are allowed")


@app.get("/media/url", summary="Generate signed URL for media access")
async def generate_media_url(
    path: str = Query(...),
    client_id: str = Depends(get_client_id),
    user_id: Optional[str] = Depends(get_current_user),
):
    """
    Return signed URL only if media is ready.
    If still processing, return 409 so the mobile app can retry later.
    """
    item = get_media_by_path(path)
    if not item:
        raise HTTPException(status_code=404, detail="Media not found")

    if item.client_id != client_id or item.user_id != user_id:
        raise HTTPException(status_code=403, detail="Unauthorized for this path")

    if item.status != "ready":
        raise HTTPException(status_code=409, detail="Media is still processing")

    url = generate_signed_url(item.path)
    return {"url": url, "expires_in": MEDIA_URL_TTL_SECONDS}


@app.put("/media", response_model=MediaItem, summary="Update existing media by path")
async def update_media(
    path: str = Query(..., description="Internal path previously returned (MediaItem.path)"),
    file: UploadFile = File(...),
    client_id: str = Depends(get_client_id),
    user_id: Optional[str] = Depends(get_current_user),
):
    """
    Replace existing media (image/video). Uses same async/sync strategy as upload.
    """
    item = get_media_by_path(path)
    if not item:
        raise HTTPException(status_code=404, detail="Media not found")

    if item.client_id != client_id or item.user_id != user_id:
        raise HTTPException(status_code=403, detail="Unauthorized for this path")

    content_type = file.content_type or ""

    base_path = path.rsplit(".", 1)[0]

    if content_type.startswith("image/"):
        raw = await file.read()
        if len(raw) <= 3 * 1024 * 1024:
            compressed, new_type, ext = compress_image_aggressive(raw)
            final_path = f"{base_path}.{ext}"
            upload_bytes(final_path, compressed, new_type)

            item.filename = file.filename
            item.content_type = new_type
            item.path = final_path
            item.status = "ready"
            item.original_path = None
            save_media(item)
            return item
        else:
            original_path = f"{base_path}.original"
            upload_bytes(original_path, raw, content_type)

            final_path = f"{base_path}.webp"
            item.filename = file.filename
            item.content_type = "image/webp"
            item.path = final_path
            item.status = "processing"
            item.original_path = original_path
            save_media(item)

            enqueue_job(
                {
                    "media_id": item.id,
                    "original_path": original_path,
                    "final_path": final_path,
                    "content_type": content_type,
                    "type": "image",
                }
            )
            return item

    if content_type.startswith("video/"):
        raw = await file.read()
        original_ext = os.path.splitext(file.filename or "")[1] or ".source"
        original_path = f"{base_path}{original_ext}"
        upload_bytes(original_path, raw, content_type)

        final_path = f"{base_path}.mp4"
        item.filename = file.filename
        item.content_type = "video/mp4"
        item.path = final_path
        item.status = "processing"
        item.original_path = original_path
        save_media(item)

        enqueue_job(
            {
                "media_id": item.id,
                "original_path": original_path,
                "final_path": final_path,
                "content_type": content_type,
                "type": "video",
            }
        )
        return item

    raise HTTPException(status_code=400, detail="Only image/* or video/* files are allowed")


@app.delete("/media", summary="Delete media by path")
async def delete_media(
    path: str = Query(..., description="Internal path previously returned (MediaItem.path)"),
    client_id: str = Depends(get_client_id),
    user_id: Optional[str] = Depends(get_current_user),
):
    """Delete media object and its metadata."""
    item = get_media_by_path(path)
    if not item:
        raise HTTPException(status_code=404, detail="Media not found")

    if item.client_id != client_id or item.user_id != user_id:
        raise HTTPException(status_code=403, detail="Unauthorized for this path")

    delete_object(item.path)

    if item.original_path:
        delete_object(item.original_path)

    delete_media_item(item)
    return {"detail": "Media deleted successfully"}


@app.get("/media/download", summary="Download media content (stream)")
async def download_media(
    path: str = Query(..., description="Internal path previously returned (MediaItem.path)"),
    client_id: str = Depends(get_client_id),
    user_id: Optional[str] = Depends(get_current_user),
):
    """Stream media if it's ready."""
    item = get_media_by_path(path)
    if not item:
        raise HTTPException(status_code=404, detail="Media not found")

    if item.client_id != client_id or item.user_id != user_id:
        raise HTTPException(status_code=403, detail="Unauthorized for this path")

    if item.status != "ready":
        raise HTTPException(status_code=409, detail="Media is still processing")

    obj = get_object_stream(item.path)
    if not obj:
        raise HTTPException(status_code=404, detail="Media not found in storage")

    return StreamingResponse(
        obj,
        media_type=item.content_type or "application/octet-stream",
        headers={
            "Content-Disposition": f'inline; filename="{item.filename}"'
        },
    )
