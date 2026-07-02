from pydantic import BaseModel
from typing import Optional


class MediaItem(BaseModel):
    """Represents a successfully stored media object."""
    id: str
    filename: Optional[str] = None
    content_type: str
    path: str
    client_id: str
    folder: str


class ProcessingResponse(BaseModel):
    """Returned for asynchronous video uploads (HTTP 202)."""
    id: str
    status: str = "processing"
    message: str = "Video is being compressed and uploaded in the background."
    filename: Optional[str] = None
    client_id: str
    folder: str


class WebhookPayload(BaseModel):
    """Payload sent to the client's webhook_url upon task completion."""
    id: str
    status: str          # "ready" | "failed"
    path: Optional[str] = None
    url: Optional[str] = None
    error: Optional[str] = None
    client_id: str
    folder: str
