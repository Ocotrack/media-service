import io
import logging
from fastapi import HTTPException
from minio import Minio
from minio.error import S3Error, BucketAlreadyOwnedByYou, BucketAlreadyExists
from .config import MINIO_ACCESS_KEY, MINIO_SECRET_KEY, MINIO_BUCKET

logger = logging.getLogger(__name__)

minio_client = Minio(
    endpoint="minio:9003",
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=False,
)

try:
    if not minio_client.bucket_exists(MINIO_BUCKET):
        minio_client.make_bucket(MINIO_BUCKET)
        logger.info("Bucket creado automáticamente: %s", MINIO_BUCKET)
except (S3Error, BucketAlreadyOwnedByYou, BucketAlreadyExists) as e:
    logger.warning("Error verificando/creando bucket '%s': %s", MINIO_BUCKET, e)


def upload_bytes(path: str, data: bytes, content_type: str):
    """
    Sube un objeto y lo hace público
    """
    try:
        minio_client.put_object(
            bucket_name=MINIO_BUCKET,
            object_name=path,
            data=io.BytesIO(data),
            length=len(data),
            content_type=content_type,
        )
        minio_client.set_object_acl(MINIO_BUCKET, path, "public-read")
    except S3Error as e:
        raise HTTPException(status_code=500, detail=f"Upload to MinIO failed: {str(e)}") from e


def delete_object(path: str):
    try:
        minio_client.remove_object(MINIO_BUCKET, path)
    except S3Error as e:
        raise HTTPException(status_code=500, detail=f"Delete from MinIO failed: {str(e)}") from e


def generate_public_url(path: str) -> str:
    """
    Devuelve la URL pública del objeto (para usar con tu CDN)
    """
    return f"http://cdn.meximova.com/media/{path}"


def get_object_stream(path: str):
    """
    Obtiene stream del objeto (opcional si quieres servir directamente)
    """
    try:
        return minio_client.get_object(MINIO_BUCKET, path)
    except S3Error:
        return None
