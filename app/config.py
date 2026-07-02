import os
import logging
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# ================== S3 / boto3 ==================
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_ENDPOINT_URL = os.getenv("AWS_ENDPOINT_URL")# Optional: for MinIO / R2
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
AWS_BUCKET_NAME = os.getenv("AWS_BUCKET_NAME", "media")
AWS_PUBLIC_URL = os.getenv("AWS_PUBLIC_URL", "")# Optional: for CDN / public endpoint URL generation

if not AWS_ACCESS_KEY_ID or not AWS_SECRET_ACCESS_KEY:
    logger.warning(
        "AWS_ACCESS_KEY_ID or AWS_SECRET_ACCESS_KEY are not set. "
        "Storage operations will fail."
    )

# ================== API Keys ==================
# Format: "key1:client_a,key2:client_b"
RAW_API_KEYS = os.getenv("API_KEYS", "")
API_KEYS_MAP: dict[str, str] = {}

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
    logger.warning(
        "No API keys configured. Set API_KEYS=key1:client_a,key2:client_b in .env."
    )

# ================== Signed URL TTL ==================
MEDIA_URL_TTL_SECONDS = int(os.getenv("MEDIA_URL_TTL_SECONDS", "3600"))

# ================== Concurrency ==================
# Max parallel FFmpeg compression jobs.
# Default is 2 for small servers. Increase for dedicated media servers.
MAX_CONCURRENT_JOBS = int(os.getenv("MAX_CONCURRENT_JOBS", "2"))

# ================== Media Processing ==================
# Image compression: max side in pixels before resizing
IMAGE_MAX_DIMENSION = int(os.getenv("IMAGE_MAX_DIMENSION", "1280"))
# Image compression quality (1-100), lower = smaller file
IMAGE_QUALITY = int(os.getenv("IMAGE_QUALITY", "75"))

# ================== Allowed Document Extensions ==================
# Comma-separated list of allowed non-image/video extensions
_raw_extensions = os.getenv("ALLOWED_EXTENSIONS", "pdf,xlsx,xls,docx,txt,xml")
ALLOWED_EXTENSIONS: set[str] = {
    ext.strip().lower().lstrip(".")
    for ext in _raw_extensions.split(",")
    if ext.strip()
}
