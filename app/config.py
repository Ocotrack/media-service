import os
import logging
from datetime import timedelta
from dotenv import load_dotenv
from redis import Redis
from minio import Minio
from minio.error import S3Error

load_dotenv()
logger = logging.getLogger(__name__)

# --- Configuración desde entorno ---
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "minio:9003")  # servicio interno Docker
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "media")
MINIO_SECURE = os.getenv("MINIO_USE_SSL", "false").lower() in ("1", "true", "yes")

# Host público para reemplazar en la URL firmada
CDN_HOST = os.getenv("CDN_HOST", "cdn.meximova.com")

# --- Validaciones básicas ---
if not MINIO_ACCESS_KEY or not MINIO_SECRET_KEY:
    logger.warning("MINIO_ACCESS_KEY o MINIO_SECRET_KEY no están definidos.")

# --- Cliente MinIO para operaciones ---
minio_internal = Minio(
    endpoint=MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=MINIO_SECURE
)

# Cliente para firmar URLs (usa endpoint interno)
minio_signer = Minio(
    endpoint=MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=MINIO_SECURE
)

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
    logger.warning("No API keys configured. Set API_KEYS in .env for production.")

# ================== Signed URL TTL ==================
MEDIA_URL_TTL_SECONDS = int(os.getenv("MEDIA_URL_TTL_SECONDS", "300"))
MEDIA_URL_EXPIRES = timedelta(seconds=MEDIA_URL_TTL_SECONDS)
