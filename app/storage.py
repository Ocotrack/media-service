import io
from urllib.parse import urlparse, urlunparse
from fastapi import HTTPException
from minio import Minio
from minio.error import S3Error
from .config import MINIO_ACCESS_KEY, MINIO_SECRET_KEY, MINIO_BUCKET, MEDIA_URL_EXPIRES

# --- Cliente interno (para operaciones reales: upload, download, delete) ---
minio_internal = Minio(
    endpoint="minio:9003",  # MinIO interno
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=False,  # cambiar si usas HTTPS interno
)

# --- Cliente para generar URLs firmadas públicas vía CDN ---
# La firma se genera para el host que verá el cliente: cdn.meximova.com
minio_signer = Minio(
    endpoint="cdn.meximova.com",  # host público que usará la URL
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=False,  # HTTP en CDN
)


def upload_bytes(path: str, data: bytes, content_type: str):
    try:
        minio_internal.put_object(
            bucket_name=MINIO_BUCKET,
            object_name=path,
            data=io.BytesIO(data),
            length=len(data),
            content_type=content_type,
        )
    except S3Error as e:
        raise HTTPException(status_code=500, detail=f"Upload to MinIO failed: {str(e)}") from e


def delete_object(path: str):
    try:
        minio_internal.remove_object(MINIO_BUCKET, path)
    except S3Error as e:
        raise HTTPException(status_code=500, detail=f"Delete from MinIO failed: {str(e)}") from e


def generate_signed_url(path: str) -> str:
    """
    Genera URL firmada apuntando al CDN público vía Proxy /media/
    """
    try:
        # NO añadir prefijos, usar exactamente el path en el bucket
        url = minio_signer.presigned_get_object(
            bucket_name=MINIO_BUCKET,
            object_name=path,
            expires=MEDIA_URL_EXPIRES,
        )
        # url ya tiene host firmado = cdn.meximova.com, devuelve tal cual
        return url
    except S3Error as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate signed URL (S3Error): {str(e)}"
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate signed URL: {type(e).__name__} - {str(e)}"
        ) from e


def get_object_stream(path: str):
    """
    Obtiene stream del objeto directamente desde MinIO interno
    """
    try:
        return minio_internal.get_object(MINIO_BUCKET, path)
    except S3Error:
        return None
