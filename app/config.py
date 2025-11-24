# app/config.py
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
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "minio:9003")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "my-bucket")
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() in ("1", "true", "yes")

# --- Validaciones básicas (sin llamadas de red) ---
if not MINIO_ACCESS_KEY or not MINIO_SECRET_KEY:
    logger.warning("MINIO_ACCESS_KEY o MINIO_SECRET_KEY no están definidos. "
                   "Si vas a usar MinIO, configúralos en el entorno.")

# --- Cliente MinIO (no ejecutar operaciones aquí) ---
minio_internal = Minio(
    endpoint=MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=MINIO_SECURE
)

# Signer client: para URLs pre-firmadas (mismo que internal en esta configuración)
minio_signer = minio_internal


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

# ================== Job Queue ==================
MEDIA_JOBS_QUEUE_KEY = "media:jobs"


# --- utilidades ---
def _try_bucket_exists_positional(client, bucket_name):
    """Intento directo con la firma posicional."""
    return client.bucket_exists(bucket_name)

def _try_bucket_exists_kw(client, bucket_name):
    """Intento con keyword (bucket_name=...), por si la firma difiere."""
    return client.bucket_exists(bucket_name=bucket_name)

def _try_list_buckets(client, bucket_name):
    """Fallback: listar buckets y comparar por nombre (no ideal pero funciona)."""
    buckets = client.list_buckets()
    return any(b.name == bucket_name for b in buckets)

def ensure_bucket_exists(client, bucket_name, create_if_missing=True):
    """
    Asegura que exista el bucket.
    - NO debe llamarse durante la importación del módulo.
    - Llamar desde el evento de startup o desde el entrypoint.
    Devuelve True si existe o fue creado, False si no existe (y create_if_missing=False).
    Lanza excepción si hay un error irreparable.
    """
    if not bucket_name:
        raise ValueError("bucket_name vacío")

    # Intentos ordenados con manejo de TypeError específico
    try:
        try:
            exists = _try_bucket_exists_positional(client, bucket_name)
            logger.debug("bucket_exists (positional) OK -> %s", exists)
        except TypeError as te_pos:
            # firma inesperada; intenta con keyword
            logger.debug("bucket_exists posicional falló: %s", te_pos)
            try:
                exists = _try_bucket_exists_kw(client, bucket_name)
                logger.debug("bucket_exists (keyword) OK -> %s", exists)
            except TypeError as te_kw:
                logger.debug("bucket_exists keyword falló: %s", te_kw)
                # fallback a listar buckets
                exists = _try_list_buckets(client, bucket_name)
                logger.debug("list_buckets fallback -> %s", exists)
    except S3Error as s3e:
        # errores del cliente S3/MinIO (credenciales, conexión, etc.)
        logger.exception("S3Error verificando bucket: %s", s3e)
        raise
    except Exception as e:
        logger.exception("Error inesperado verificando bucket: %s", e)
        raise

    if exists:
        return True

    # Si no existe y está permitido, intentar crear el bucket
    if not create_if_missing:
        return False

    try:
        client.make_bucket(bucket_name)
        logger.info("Bucket creado exitosamente: %s", bucket_name)
        return True
    except S3Error as s3e:
        logger.exception("S3Error creando bucket '%s': %s", bucket_name, s3e)
        raise
    except Exception as e:
        logger.exception("Error creando bucket '%s': %s", bucket_name, e)
        raise
