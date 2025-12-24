import io
import uuid
import os
from typing import Optional

from fastapi import FastAPI, UploadFile, File, HTTPException, Header, Depends, Query, Request
from fastapi.responses import StreamingResponse

# Importante: Middleware para manejar headers de proxy (HTTPS)
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from .config import API_KEYS_MAP, MEDIA_URL_TTL_SECONDS
from .models import MediaItem
from .storage import (
    upload_bytes,
    delete_object,
    generate_signed_url,
    get_object_stream,
)
from .compression import compress_image_aggressive, compress_video_ffmpeg

app = FastAPI(
    title="Media Storage Service",
    description=(
        "Module of Meximova Transportes for managing media files.\n"
        "- Allows uploading, updating, deleting, and downloading media.\n"
        "- Protected by project-based API Key.\n"
        "- Stateless: No database, relies on file path checks."
    ),
    version="2.0.0",
)

# Trust Proxy Headers (for SSL termination)
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

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

def build_base_path(client_id: str, folder: str, media_id: str) -> str:
    parts = [client_id]
    if folder:
        parts.append(folder)
    parts.append(media_id)
    return "/".join(parts)

def validate_path_ownership(path: str, client_id: str):
    """
    Ensure the path belongs to the client_id.
    Path format expected: {client_id}/...
    """
    parts = path.split("/")
    if not parts or parts[0] != client_id:
        raise HTTPException(status_code=403, detail="Unauthorized for this path")

# ========== Endpoints ==========

@app.post("/media", response_model=MediaItem, summary="Upload media")
async def upload_media(
    file: UploadFile = File(...),
    client_id: str = Depends(get_client_id),
    folder: str = Depends(get_folder),
):
    content_type = file.content_type or ""
    media_id = str(uuid.uuid4())
    base_path = build_base_path(client_id, folder, media_id)

    # Image Processing (Sync)
    if content_type.startswith("image/"):
        raw = await file.read()
        # Compress
        compressed, new_type, ext = compress_image_aggressive(raw)
        final_path = f"{base_path}.{ext}"
        upload_bytes(final_path, compressed, new_type)

        return MediaItem(
            id=media_id,
            filename=file.filename,
            content_type=new_type,
            path=final_path,
            client_id=client_id,
            folder=folder,
        )

    # Video Processing (Sync - Warning: Heavy operation)
    if content_type.startswith("video/"):
        import tempfile
        
        original_ext = os.path.splitext(file.filename or "")[1] or ".source"
        
        # Save uploaded file to temp
        with tempfile.NamedTemporaryFile(delete=False, suffix=original_ext) as tmp_in:
            tmp_in.write(await file.read())
            tmp_in_path = tmp_in.name
            
        tmp_out_path = f"{tmp_in_path}.mp4"
        
        try:
            # Compress using existing helper
            out_path, new_type = compress_video_ffmpeg(tmp_in_path, tmp_out_path)
            
            with open(out_path, "rb") as f:
                compressed_data = f.read()
                
            final_path = f"{base_path}.mp4"
            upload_bytes(final_path, compressed_data, new_type)
            
            return MediaItem(
                id=media_id,
                filename=file.filename,
                content_type=new_type,
                path=final_path,
                client_id=client_id,
                folder=folder,
            )
        finally:
            # Cleanup temp files
            if os.path.exists(tmp_in_path):
                os.remove(tmp_in_path)
            if os.path.exists(tmp_out_path):
                os.remove(tmp_out_path)

    # Documents (PDF, Excel, etc)
    allowed_docs = [
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel"
    ]
    if content_type in allowed_docs:
        raw = await file.read()
        original_ext = os.path.splitext(file.filename or "")[1] or ".file"
        final_path = f"{base_path}{original_ext}"
        upload_bytes(final_path, raw, content_type)

        return MediaItem(
            id=media_id,
            filename=file.filename,
            content_type=content_type,
            path=final_path,
            client_id=client_id,
            folder=folder,
        )

    raise HTTPException(status_code=400, detail="Only image/*, video/*, PDF, or Excel files are allowed")


@app.get("/media/url", summary="Generate signed URL for media access")
async def generate_media_url(
    path: str = Query(...),
    client_id: str = Depends(get_client_id),
):
    validate_path_ownership(path, client_id)
    
    # We don't check existence strictly to be faster/simpler, 
    # OR we can assume if client has path, it exists.
    # If strictly needed, we could head_object, but signed url generation doesn't require it.
    
    url = generate_signed_url(path)
    return {"url": url, "expires_in": MEDIA_URL_TTL_SECONDS}


@app.put("/media", response_model=MediaItem, summary="Update existing media by path")
async def update_media(
    path: str = Query(...),
    file: UploadFile = File(...),
    client_id: str = Depends(get_client_id),
):
    validate_path_ownership(path, client_id)
    
    # Extract folder/media_id from path if possible, but simplest is to overwrite
    # logic here is tricky without DB. We assume replacing content at 'path' or similar.
    # To keep consistency with "stateless", we essentially re-upload to a NEW path 
    # or the SAME path if extension matches.
    # Ideally, we should generate a NEW unique ID/path to avoid cache issues, 
    # but the user might want to keep the same reference?
    # Let's generate a NEW path and return it, as that's safer for "Update" (essentially Replace).
    
    # However, 'path' is the key. 
    # If we want to replace the content OF the path, we must ensure extension matches or similar.
    
    # SIMPLIFIED STRATEGY: Treat update as "Upload new, Delete old" 
    # BUT since we're stateless, we just Upload New and return it. 
    # The client can delete the old one if they want.
    # OR if the client insists on "same path", we overwrite.
    
    # Let's overwrite IF extension allows, otherwise new path.
    
    # Re-using upload logic mostly
    content_type = file.content_type or ""
    # We try to preserve the base path structure
    base_path_without_ext = path.rsplit(".", 1)[0]
    
    # Images
    if content_type.startswith("image/"):
        raw = await file.read()
        compressed, new_type, ext = compress_image_aggressive(raw)
        final_path = f"{base_path_without_ext}.{ext}"
        
        # If final_path differs from input path (e.g. png -> webp), we should probably delete the old one
        if final_path != path:
            delete_object(path)
            
        upload_bytes(final_path, compressed, new_type)
        
        return MediaItem(
            id="unknown", # We don't parse ID from path easily without regex, keeping it simple
            filename=file.filename,
            content_type=new_type,
            path=final_path,
            client_id=client_id,
            folder="", # Unknown without parsing
        )

    # ... For brevity and statelessness, "Update" is complex. 
    # Let's implement a simple "Overwrite" logic that might change extension.
    
    raise HTTPException(status_code=501, detail="Update not fully implemented in stateless mode yet. Use Upload + Delete.")


@app.delete("/media", summary="Delete media by path")
async def delete_media(
    path: str = Query(...),
    client_id: str = Depends(get_client_id),
):
    validate_path_ownership(path, client_id)
    delete_object(path)
    return {"detail": "Media deleted successfully"}


@app.get("/media/download", summary="Download media content (stream)")
async def download_media(
    path: str = Query(...),
    client_id: str = Depends(get_client_id),
):
    validate_path_ownership(path, client_id)

    obj = get_object_stream(path)
    if not obj:
        raise HTTPException(status_code=404, detail="Media not found in storage")

    # MinIO stream response has headers
    # We try to guess media type or default
    media_type = "application/octet-stream" 
    
    return StreamingResponse(
        obj,
        media_type=media_type,
        headers={"Content-Disposition": f'inline; filename="{os.path.basename(path)}"'},
    )
