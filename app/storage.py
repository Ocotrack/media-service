import io
from fastapi import HTTPException
from minio.error import S3Error
from .config import minio_internal, minio_public, MINIO_BUCKET, MEDIA_URL_EXPIRES

def upload_bytes(path: str, data: bytes, content_type: str):
    """Sube bytes a MinIO usando el endpoint interno."""
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
    """Elimina un objeto de MinIO."""
    try:
        minio_internal.remove_object(MINIO_BUCKET, path)
    except S3Error as e:
        raise HTTPException(status_code=500, detail=f"Delete from MinIO failed: {str(e)}") from e

def generate_signed_url(path: str) -> str:
    """Genera URL firmada directamente con el CDN público."""
    try:
        url = minio_public.presigned_get_object(
            bucket_name=MINIO_BUCKET,
            object_name=path,
            expires=MEDIA_URL_EXPIRES
        )
        return url
    except S3Error as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate signed URL: {str(e)}") from e

def get_object_stream(path: str):
    """Obtiene el objeto de MinIO como stream usando endpoint interno."""
    try:
        return minio_internal.get_object(MINIO_BUCKET, path)
    except S3Error:
        return None
