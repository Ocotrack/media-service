import io
import logging
import boto3
import botocore
from botocore.config import Config
from fastapi import HTTPException

from .config import (
    AWS_ACCESS_KEY_ID,
    AWS_SECRET_ACCESS_KEY,
    AWS_ENDPOINT_URL,
    AWS_REGION,
    AWS_BUCKET_NAME,
    MEDIA_URL_TTL_SECONDS,
    AWS_PUBLIC_URL,
)

logger = logging.getLogger(__name__)

# ================== S3 Client Factory ==================

def _make_client():
    """
    Build a boto3 S3 client compatible with AWS S3, MinIO, Cloudflare R2,
    DigitalOcean Spaces, and any S3-compatible provider.
    Simply set AWS_ENDPOINT_URL for non-AWS providers.
    """
    kwargs = dict(
        service_name="s3",
        region_name=AWS_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4"),
    )
    if AWS_ENDPOINT_URL:
        kwargs["endpoint_url"] = AWS_ENDPOINT_URL
    return boto3.client(**kwargs)


s3_client = _make_client()


# ================== Storage Operations ==================

def upload_file(local_path: str, s3_key: str, content_type: str) -> None:
    """
    Upload a local file on disk to S3 using a streaming multipart upload.
    Operates on file paths to keep memory usage constant regardless of file size.
    """
    try:
        s3_client.upload_file(
            Filename=local_path,
            Bucket=AWS_BUCKET_NAME,
            Key=s3_key,
            ExtraArgs={"ContentType": content_type},
        )
    except botocore.exceptions.ClientError as e:
        logger.error("S3 upload failed for key '%s': %s", s3_key, e)
        raise HTTPException(
            status_code=500, detail=f"Storage upload failed: {e.response['Error']['Code']}"
        ) from e


def upload_bytes(s3_key: str, data: bytes, content_type: str) -> None:
    """
    Upload raw bytes to S3. Used for small files (e.g. compressed images in memory).
    """
    try:
        s3_client.put_object(
            Bucket=AWS_BUCKET_NAME,
            Key=s3_key,
            Body=io.BytesIO(data),
            ContentType=content_type,
        )
    except botocore.exceptions.ClientError as e:
        logger.error("S3 put_object failed for key '%s': %s", s3_key, e)
        raise HTTPException(
            status_code=500, detail=f"Storage upload failed: {e.response['Error']['Code']}"
        ) from e


def delete_file(s3_key: str) -> None:
    """
    Delete an object from S3. Silently ignores if the object does not exist.
    """
    try:
        s3_client.delete_object(Bucket=AWS_BUCKET_NAME, Key=s3_key)
    except botocore.exceptions.ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("NoSuchKey", "404"):
            return
        logger.error("S3 delete failed for key '%s': %s", s3_key, e)
        raise HTTPException(
            status_code=500, detail=f"Storage delete failed: {code}"
        ) from e


def generate_presigned_url(s3_key: str) -> str:
    """
    Generate a time-limited presigned URL for direct file access.
    If AWS_PUBLIC_URL is set, the URL host is replaced with the public CDN endpoint.
    """
    try:
        url: str = s3_client.generate_presigned_url(
            ClientMethod="get_object",
            Params={"Bucket": AWS_BUCKET_NAME, "Key": s3_key},
            ExpiresIn=MEDIA_URL_TTL_SECONDS,
        )
        if AWS_PUBLIC_URL:
            # Swap internal endpoint host with the public-facing CDN host
            import urllib.parse
            parsed = urllib.parse.urlparse(url)
            public_parsed = urllib.parse.urlparse(AWS_PUBLIC_URL)
            url = url.replace(
                f"{parsed.scheme}://{parsed.netloc}",
                f"{public_parsed.scheme}://{public_parsed.netloc}",
            )
        return url
    except botocore.exceptions.ClientError as e:
        logger.error("Presigned URL generation failed for key '%s': %s", s3_key, e)
        raise HTTPException(
            status_code=500, detail="Failed to generate signed URL"
        ) from e


def get_object_stream(s3_key: str):
    """
    Stream an S3 object for direct HTTP response. Returns None if not found.
    """
    try:
        response = s3_client.get_object(Bucket=AWS_BUCKET_NAME, Key=s3_key)
        return response["Body"]
    except botocore.exceptions.ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("NoSuchKey", "404"):
            return None
        logger.error("S3 get_object failed for key '%s': %s", s3_key, e)
        raise HTTPException(
            status_code=500, detail=f"Storage read failed: {code}"
        ) from e
