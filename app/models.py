from pydantic import BaseModel
from typing import Optional

class MediaItem(BaseModel):
    id: str
    filename: str
    content_type: str
    path: str
    client_id: str
    folder: str
