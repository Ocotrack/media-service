from pydantic import BaseModel
from typing import Optional
from .config import redis_client

class MediaItem(BaseModel):
    id: str
    filename: str
    content_type: str
    path: str
    user_id: Optional[str] = None
    client_id: str
    folder: str
    status: str = "ready"
    original_path: Optional[str] = None  

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
    if item.original_path:
        redis_client.delete(media_path_key(item.original_path))
