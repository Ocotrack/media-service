import io
from fastapi import HTTPException
from minio.error import S3Error
from .config import minio_internal, minio_signer, MINIO_BUCKET, MEDIA_URL_EXPIRES, CDN_HOST

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
    try:
        expires_seconds = int(MEDIA_URL_EXPIRES.total_seconds())

        url = minio_signer.presigned_get_object(
            bucket_name=MINIO_BUCKET,
            object_name=path,
            expires=expires_seconds
        )

        url = url.replace(minio_signer._endpoint_url, f"http://{CDN_HOST}")
        return url
    except S3Error as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate signed URL: {str(e)}") from e

def get_object_stream(path: str):
    try:
        return minio_internal.get_object(MINIO_BUCKET, path)
    except S3Error:
        return None
