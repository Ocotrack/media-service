import io
import uuid
import os
from typing import Optional, Tuple, Dict

from fastapi import FastAPI, UploadFile, File, HTTPException, Header, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from minio import Minio
from minio.error import S3Error
from PIL import Image
from dotenv import load_dotenv
from redis import Redis

# Cargar variables de entorno
load_dotenv()

# ========== Configuración MinIO ==========
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY")
MINIO_USE_SSL = os.getenv("MINIO_USE_SSL", "false").lower() == "true"
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "media")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL")

# ========== Configuración Redis ==========
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")

redis_client = Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    db=REDIS_DB,
    password=REDIS_PASSWORD if REDIS_PASSWORD else None,
    decode_responses=True,  # trabajamos con strings
)

# ========== Configuración API Keys ==========
# Formato en .env:
# API_KEYS=meximova-web:SUPER_KEY_WEB,meximova-doubts:SUPER_KEY_DOUBTS
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
    print("WARNING: No API keys configured. Configure API_KEYS in .env for production.")

# ========== Cliente MinIO ==========
minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=MINIO_USE_SSL,
)

# Crear bucket si no existe
if not minio_client.bucket_exists(MINIO_BUCKET):
    minio_client.make_bucket(MINIO_BUCKET)

# ========== FastAPI ==========
app = FastAPI(
    title="Media Storage Service",
    description=(
        "Microservice for managing media files.\n"
        "- Authentication via API Key (X-Api-Key) per project.\n"
        "- User association through X-User-Id.\n"
        "- Logical folder using X-Folder."
    ),
    version="1.0.0",
)

# ========== Modelos ==========
class MediaItem(BaseModel):
    id: str
    filename: str
    content_type: str
    url: str
    user_id: str
    client_id: str       # proyecto origen (ej: meximova-web)
    folder: str          # carpeta lógica (ej: evidences, doubts, etc.)


# ========== Helpers Redis ==========
def redis_key(media_id: str) -> str:
    return f"media:{media_id}"


def save_media(item: MediaItem) -> None:
    redis_client.set(redis_key(item.id), item.json())


def get_media_item(media_id: str) -> Optional[MediaItem]:
    data = redis_client.get(redis_key(media_id))
    if not data:
        return None
    return MediaItem.parse_raw(data)


def delete_media_item(media_id: str) -> None:
    redis_client.delete(redis_key(media_id))


# ========== Helpers Path / Folder ==========

def sanitize_folder(folder: str) -> str:
    """
        Cleans the folder name to avoid unusual paths.
        Allows letters, numbers, dashes, underscores, and simple slashes.
    """
    folder = folder.strip().strip("/")
    if not folder:
        return ""

    if ".." in folder:
        raise HTTPException(status_code=400, detail="Carpeta inválida")

    allowed_chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_/"

    if any(ch not in allowed_chars for ch in folder):
        raise HTTPException(status_code=400, detail="Carpeta contiene caracteres inválidos")

    return folder


async def get_folder(x_folder: Optional[str] = Header(None, alias="X-Folder")) -> str:
    """
    Reads the logical folder from X-Folder.
    Examples:
    - X-Folder: evidences
    - X-Folder: evidences/load-123
    It will be used as part of the path in MinIO: client_id/folder/user_id/media_id.webp
    If not provided, no extra folder will be added.
    """
    if not x_folder:
        return ""
    return sanitize_folder(x_folder)


def build_object_name(client_id: str, folder: str, user_id: str, media_id: str) -> str:
    """
    Builds the final path in MinIO following this structure:
    client_id/[folder]/user_id/media_id.webp
    """
    if folder:
        return f"{client_id}/{folder}/{user_id}/{media_id}.webp"
    return f"{client_id}/{user_id}/{media_id}.webp"


# ========== Dependencias de seguridad ==========

async def get_client_id(x_api_key: Optional[str] = Header(None, alias="X-Api-Key")) -> str:
    if not x_api_key:
        raise HTTPException(status_code=401, detail="X-Api-Key is required")

    client_id = API_KEYS_MAP.get(x_api_key)
    if not client_id:
        raise HTTPException(status_code=403, detail="Invalid or unauthorized API Key")
    return client_id


async def get_current_user(x_user_id: Optional[str] = Header(None, alias="X-User-Id")) -> str:
    if not x_user_id:
        raise HTTPException(status_code=401, detail="X-User-Id is required")
    return x_user_id


# ========== Utilidades de compresión y MinIO ==========

async def compress_image(file: UploadFile) -> Tuple[bytes, str]:
    """
    compresses images by converting them to WEBP (quality=80).
    """
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
        raise HTTPException(
            status_code=400,
            detail=f"Could not process the image: {str(e)}"
        )


def upload_to_minio(object_name: str, data: bytes, content_type: str):
    try:
        minio_client.put_object(
            bucket_name=MINIO_BUCKET,
            object_name=object_name,
            data=io.BytesIO(data),
            length=len(data),
            content_type=content_type,
        )
    except S3Error as e:
        raise HTTPException(
            status_code=500,
            detail="Error uploading to MinIO"
        ) from e


def delete_from_minio(object_name: str):
    try:
        minio_client.remove_object(MINIO_BUCKET, object_name)
    except S3Error as e:
        raise HTTPException(
            status_code=500,
            detail="Error deleting in MinIO"
        ) from e


# ========== Endpoints ==========

@app.post(
    "/media",
    response_model=MediaItem,
    summary="Upload media with compression",
    tags=["Media"],
)
async def upload_media(
    file: UploadFile = File(...),
    client_id: str = Depends(get_client_id),
    user_id: str = Depends(get_current_user),
    folder: str = Depends(get_folder),
):
    """
    Uploads an image, compresses it (WEBP), and stores it in MinIO.
    Security:
    - X-Api-Key: identifies the project (client_id).
    - X-User-Id: user already authenticated by your system.
    Organization:
    - X-Folder (optional): additional logical folder, e.g., evidences, evidences/load-123
    Final path: client_id/folder/user_id/media_id.webp
    """
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(
            status_code=400,
            detail="Por ahora solo se permiten archivos de tipo imagen."
        )

    compressed_bytes, new_content_type = await compress_image(file)

    media_id = str(uuid.uuid4())
    object_name = build_object_name(client_id, folder, user_id, media_id)

    upload_to_minio(object_name, compressed_bytes, new_content_type)

    url = f"{PUBLIC_BASE_URL}/{object_name}"

    item = MediaItem(
        id=media_id,
        filename=file.filename,
        content_type=new_content_type,
        url=url,
        user_id=user_id,
        client_id=client_id,
        folder=folder,
    )

    save_media(item)

    return item


@app.get(
    "/media/{media_id}",
    response_model=MediaItem,
    summary="Get media metadata",
    tags=["Media"],
)
async def get_media(
    media_id: str,
    client_id: str = Depends(get_client_id),
    user_id: str = Depends(get_current_user),
):
    """
    Returns the media metadata.
    - Validates that the media belongs to the same client_id (API Key).
    - Validates that it belongs to the same user_id.
    """
    item = get_media_item(media_id)
    if not item:
        raise HTTPException(status_code=404, detail="Media not found")

    if item.client_id != client_id:
        raise HTTPException(status_code=403, detail="Not authorized for this media (client_id)")

    if item.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not authorized for this media (user_id)")

    return item


@app.delete(
    "/media/{media_id}",
    summary="Delete media",
    tags=["Media"],
)
async def delete_media(
    media_id: str,
    client_id: str = Depends(get_client_id),
    user_id: str = Depends(get_current_user),
):
    """
    Deletes the media (MinIO + metadata in Redis).
    Only allowed for the same client_id and user_id.
    """
    item = get_media_item(media_id)
    if not item:
        raise HTTPException(status_code=404, detail="Media not found")

    if item.client_id != client_id or item.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this media")

    object_name = build_object_name(item.client_id, item.folder, item.user_id, item.id)
    delete_from_minio(object_name)
    delete_media_item(media_id)

    return JSONResponse({"detail": "Deleted successfully"})


@app.put(
    "/media/{media_id}",
    response_model=MediaItem,
    summary="Update media (replace file)",
    tags=["Media"],
)
async def update_media(
    media_id: str,
    file: UploadFile = File(...),
    client_id: str = Depends(get_client_id),
    user_id: str = Depends(get_current_user),
):
    """
    Replaces the file.
    Only allowed for the same project (X-Api-Key) and the same user (X-User-Id).
    Uses the originally stored folder.
    """
    item = get_media_item(media_id)
    if not item:
        raise HTTPException(status_code=404, detail="Media not found")

    if item.client_id != client_id or item.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not authorized to update this media")

    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(
            status_code=400,
            detail="Only image files are allowed for now."
        )

    old_object_name = build_object_name(item.client_id, item.folder, item.user_id, item.id)
    delete_from_minio(old_object_name)

    compressed_bytes, new_content_type = await compress_image(file)
    new_object_name = build_object_name(item.client_id, item.folder, item.user_id, item.id)
    upload_to_minio(new_object_name, compressed_bytes, new_content_type)

    url = f"{PUBLIC_BASE_URL}/{new_object_name}"

    updated = MediaItem(
        id=item.id,
        filename=file.filename,
        content_type=new_content_type,
        url=url,
        user_id=user_id,
        client_id=client_id,
        folder=item.folder,
    )

    save_media(updated)

    return updated
