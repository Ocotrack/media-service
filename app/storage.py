import io
from datetime import timedelta
from fastapi import HTTPException
from minio import Minio
from minio.error import S3Error
import os

# ---------------- Configuración ----------------
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "minio:9003")   # interno, para subir/leer
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "media")
MEDIA_URL_TTL_SECONDS = int(os.getenv("MEDIA_URL_TTL_SECONDS", "300"))
MEDIA_URL_EXPIRES = timedelta(seconds=MEDIA_URL_TTL_SECONDS)
CDN_HOST = os.getenv("CDN_HOST", "cdn.meximova.com")  # host público para firmar URLs
USE_HTTPS = os.getenv("CDN_USE_HTTPS", "false").lower() in ("1", "true", "yes")

# ---------------- Clientes MinIO ----------------
# Cliente interno para subir/eliminar/leer objetos
minio_internal = Minio(
    endpoint=MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=False  # Usa False porque Docker interno
)

# Cliente público para firmar URLs (con host real)
minio_signer = Minio(
    endpoint=CDN_HOST,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=USE_HTTPS
)

# ---------------- Funciones ----------------
def upload_bytes(path: str, data: bytes, content_type: str):
    """Sube un archivo a MinIO (interno)"""
    try:
        minio_internal.put_object(
            bucket_name=MINIO_BUCKET,
            object_name=path,
            data=io.BytesIO(data),
            length=len(data),
            content_type=content_type
        )
    except S3Error as e:
        raise HTTPException(status_code=500, detail=f"Upload to MinIO failed: {str(e)}") from e

def delete_object(path: str):
    """Elimina un archivo de MinIO (interno)"""
    try:
        minio_internal.remove_object(MINIO_BUCKET, path)
    except S3Error as e:
        raise HTTPException(status_code=500, detail=f"Delete from MinIO failed: {str(e)}") from e

def generate_signed_url(path: str) -> str:
    """
    Genera URL firmada para acceder desde el CDN.
    NO reemplaza host, ya que la firma depende del host.
    """
    try:
        url = minio_signer.presigned_get_object(
            bucket_name=MINIO_BUCKET,
            object_name=path,
            expires=MEDIA_URL_EXPIRES  # timedelta
        )
        return url
    except S3Error as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate signed URL: {str(e)}") from e

def get_object_stream(path: str):
    """Obtiene un stream del objeto desde MinIO interno"""
    try:
        return minio_internal.get_object(MINIO_BUCKET, path)
    except S3Error:
        return None
