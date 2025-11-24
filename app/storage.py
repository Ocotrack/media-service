# app/storage.py
import io
import logging
from datetime import timedelta
from typing import Optional

from fastapi import HTTPException
from minio.error import S3Error

from .config import minio_internal, minio_signer, MINIO_BUCKET, MEDIA_URL_EXPIRES

logger = logging.getLogger(__name__)


def upload_bytes(path: str, data: bytes, content_type: str):
    """
    Sube bytes a MinIO usando el cliente interno.
    Lanza HTTPException(500) en caso de fallo.
    """
    try:
        # Asegurarnos de pasar un stream con la longitud correcta
        stream = io.BytesIO(data)
        stream.seek(0)
        minio_internal.put_object(
            bucket_name=MINIO_BUCKET,
            object_name=path,
            data=stream,
            length=len(data),
            content_type=content_type,
        )
        logger.debug("Uploaded object to %s/%s (bytes=%d)", MINIO_BUCKET, path, len(data))
    except S3Error as e:
        logger.exception("MinIO S3Error uploading %s: %s", path, e)
        raise HTTPException(status_code=500, detail=f"Upload to MinIO failed: {str(e)}") from e
    except Exception as e:
        logger.exception("Unexpected error uploading %s: %s", path, e)
        raise HTTPException(status_code=500, detail=f"Upload to MinIO failed: {type(e).__name__} - {str(e)}") from e


def delete_object(path: str):
    """
    Elimina un objeto del bucket. Lanza HTTPException(500) en caso de fallo.
    """
    try:
        minio_internal.remove_object(MINIO_BUCKET, path)
        logger.debug("Removed object %s/%s", MINIO_BUCKET, path)
    except S3Error as e:
        logger.exception("MinIO S3Error deleting %s: %s", path, e)
        raise HTTPException(status_code=500, detail=f"Delete from MinIO failed: {str(e)}") from e
    except Exception as e:
        logger.exception("Unexpected error deleting %s: %s", path, e)
        raise HTTPException(status_code=500, detail=f"Delete from MinIO failed: {type(e).__name__} - {str(e)}") from e


def generate_signed_url(path: str) -> str:
    """
    Genera una URL firmada para lectura pública usando el cliente signer.
    Acepta MEDIA_URL_EXPIRES como int (segundos) o datetime.timedelta.
    """
    try:
        expires = MEDIA_URL_EXPIRES

        # Aceptamos int (segundos) o timedelta; también toleramos string numérica.
        if isinstance(expires, int):
            expires_td = timedelta(seconds=expires)
        elif isinstance(expires, timedelta):
            expires_td = expires
        else:
            # intentar convertir string a int
            try:
                expires_int = int(expires)
                expires_td = timedelta(seconds=expires_int)
            except Exception:
                # fallback por si la librería acepta int: convertir a timedelta por seguridad
                logger.warning("MEDIA_URL_EXPIRES tiene tipo inesperado (%s). Usando 300s por defecto.", type(expires))
                expires_td = timedelta(seconds=300)

        logger.debug("Generating presigned URL for %s/%s expires=%s", MINIO_BUCKET, path, expires_td)
        url = minio_signer.presigned_get_object(
            bucket_name=MINIO_BUCKET,
            object_name=path,
            expires=expires_td,
        )
        logger.debug("Presigned URL generated for %s (len=%d)", path, len(url) if url else 0)
        return url

    except S3Error as e:
        logger.exception("MinIO S3Error generating signed URL for %s: %s", path, e)
        raise HTTPException(status_code=500, detail=f"Failed to generate signed URL (S3Error): {str(e)}") from e
    except Exception as e:
        logger.exception("Unexpected error generating signed URL for %s: %s", path, e)
        raise HTTPException(status_code=500, detail=f"Failed to generate signed URL: {type(e).__name__} - {str(e)}") from e


def get_object_stream(path: str):
    """
    Retorna el stream del objeto (file-like) o None si no existe / no puede recuperarse.
    El llamador decide mapear esto a 404.
    """
    try:
        obj = minio_internal.get_object(MINIO_BUCKET, path)
        logger.debug("Obtained object stream for %s/%s", MINIO_BUCKET, path)
        return obj
    except S3Error as e:
        logger.debug("MinIO S3Error getting object %s: %s", path, e)
        return None
    except Exception as e:
        logger.exception("Unexpected error getting object %s: %s", path, e)
        return None
