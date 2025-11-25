import io
from fastapi import HTTPException
from minio import Minio
from minio.error import S3Error
from datetime import timedelta
from .config import MINIO_ACCESS_KEY, MINIO_SECRET_KEY, MINIO_BUCKET, MEDIA_URL_EXPIRES, CDN_HOST

# Cliente MinIO para firmar URLs públicas
minio_public_signer = Minio(
    endpoint=CDN_HOST,  # Usa el host público aquí
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=False  # Cambia a True si tu CDN usa HTTPS
)

def upload_bytes(path: str, data: bytes, content_type: str):
    from .config import minio_internal
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
    from .config import minio_internal
    try:
        minio_internal.remove_object(MINIO_BUCKET, path)
    except S3Error as e:
        raise HTTPException(status_code=500, detail=f"Delete from MinIO failed: {str(e)}") from e

def generate_signed_url(path: str) -> str:
    """
    Genera URL firmada válida usando el host público.
    NO reemplaces el host después de firmar.
    """
    try:
        url = minio_public_signer.presigned_get_object(
            bucket_name=MINIO_BUCKET,
            object_name=path,
            expires=MEDIA_URL_EXPIRES  # timedelta
        )
        return url

    except S3Error as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate signed URL: {str(e)}") from e
