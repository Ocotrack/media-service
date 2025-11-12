import os
from datetime import timedelta
from dotenv import load_dotenv
from redis import Redis
from minio import Minio

load_dotenv()

# ================== MinIO base creds ==================
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY")
MINIO_USE_SSL = os.getenv("MINIO_USE_SSL", "false").lower() == "true"
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "media")

if not MINIO_ACCESS_KEY or not MINIO_SECRET_KEY:
    raise RuntimeError("MinIO credentials are missing: set MINIO_ACCESS_KEY and MINIO_SECRET_KEY.")

# Fix region to avoid SDK calling '/?location'
MINIO_REGION = os.getenv("MINIO_REGION", "us-east-1")

# ---- Endpoints (new style preferred) ----
# Internal endpoint: used for actual I/O from containers (e.g., 'minio:9003')
MINIO_ENDPOINT_INTERNAL = os.getenv("MINIO_ENDPOINT_INTERNAL")
# Public endpoint: used only to sign URLs (e.g., 'casamagoswiss.ddns.net:9003')
MINIO_ENDPOINT_PUBLIC = os.getenv("MINIO_ENDPOINT_PUBLIC")

# ---- Legacy fallback (single endpoint) ----
LEGACY_MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT")

# Resolve endpoints
if not MINIO_ENDPOINT_INTERNAL:
    if LEGACY_MINIO_ENDPOINT:
        MINIO_ENDPOINT_INTERNAL = LEGACY_MINIO_ENDPOINT
    else:
        MINIO_ENDPOINT_INTERNAL = "minio:9003"  # safe default inside docker network

if not MINIO_ENDPOINT_PUBLIC:
    # If not provided, fall back to whatever we have internally (works on LAN)
    MINIO_ENDPOINT_PUBLIC = MINIO_ENDPOINT_INTERNAL

# ================== Redis ==================
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")

redis_client = Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    db=REDIS_DB,
    password=REDIS_PASSWORD or None,
    decode_responses=True,
)

# ================== API Keys ==================
RAW_API_KEYS = os.getenv("API_KEYS", "")
API_KEYS_MAP = {}
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

# ================== Signed URL TTL ==================
MEDIA_URL_TTL_SECONDS = int(os.getenv("MEDIA_URL_TTL_SECONDS", "300"))
MEDIA_URL_EXPIRES = timedelta(seconds=MEDIA_URL_TTL_SECONDS)

# ================== Job Queue ==================
MEDIA_JOBS_QUEUE_KEY = "media:jobs"

# ================== MinIO clients ==================
# Internal client: real I/O within Docker network
minio_internal = Minio(
    MINIO_ENDPOINT_INTERNAL,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=MINIO_USE_SSL,
    region=MINIO_REGION,
)

# Signer client: ONLY for presigned URLs (public host); fixed region prevents calls to '/?location'
minio_signer = Minio(
    MINIO_ENDPOINT_PUBLIC,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=MINIO_USE_SSL,
    region=MINIO_REGION,
)

# Ensure bucket exists using internal client
if not minio_internal.bucket_exists(MINIO_BUCKET):
    minio_internal.make_bucket(MINIO_BUCKET)
