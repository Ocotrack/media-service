import json
from typing import Optional, Dict
from .config import redis_client, MEDIA_JOBS_QUEUE_KEY

def enqueue_job(job: Dict):
    """
    Push a job to the Redis queue.
    Job example:
    {
      "media_id": "...",
      "original_path": "...",
      "final_path": "...",
      "content_type": "image/..." or "video/..."
    }
    """
    redis_client.rpush(MEDIA_JOBS_QUEUE_KEY, json.dumps(job))

def dequeue_job(block: bool = True, timeout: int = 5) -> Optional[Dict]:
    """
    Pop a job from the Redis queue.
    """
    if block:
        item = redis_client.blpop(MEDIA_JOBS_QUEUE_KEY, timeout=timeout)
        if not item:
            return None
        _, data = item
    else:
        data = redis_client.lpop(MEDIA_JOBS_QUEUE_KEY)
        if not data:
            return None

    try:
        return json.loads(data)
    except json.JSONDecodeError:
        return None
