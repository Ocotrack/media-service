import io
from fastapi import HTTPException
from urllib.parse import urlparse, urlunparse
from minio.error import S3Error
from .config import minio_internal, MINIO_BUCKET, MEDIA_URL_EXPIRES


def upload_bytes(path: str, data: bytes, content_type: str):
    """
    Sube un archivo a MinIO interno.
    """
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
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error during upload: {type(e).__name__} - {str(e)}") from e


def delete_object(path: str):
    """
    Elimina un objeto de MinIO interno.
    """
    try:
        minio_internal.remove_object(MINIO_BUCKET, path)
    except S3Error as e:
        raise HTTPException(status_code=500, detail=f"Delete from MinIO failed: {str(e)}") from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error during delete: {type(e).__name__} - {str(e)}") from e


def generate_signed_url(path: str) -> str:
    """
    Genera una URL firmada que apunta al CDN público (Apache reverse proxy).
    """
    try:
        # URL firmada usando MinIO interno
        url = minio_internal.presigned_get_object(
            bucket_name=MINIO_BUCKET,
            object_name=path,
            expires=MEDIA_URL_EXPIRES,
        )

        # Reescribir host y path para el proxy Apache
        parsed = urlparse(url)
        parsed = parsed._replace(
            scheme="http",               # protocolo del proxy
            netloc="cdn.meximova.com",   # host público
            path=f"/media/{path}"        # coincide con ProxyPass /media/
        )
        return urlunparse(parsed)

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate signed URL: {type(e).__name__} - {str(e)}"
        )


def get_object_stream(path: str):
    """
    Devuelve un objeto abierto (stream) desde MinIO interno.
    Retorna None si no existe.
    """
    try:
        return minio_internal.get_object(MINIO_BUCKET, path)
    except S3Error:
        return None
    except Exception:
        return None
