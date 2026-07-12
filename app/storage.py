import io
import json
import logging

import boto3
import botocore
from botocore.config import Config
from fastapi import HTTPException

from .config import (
    AWS_ACCESS_KEY_ID,
    AWS_BUCKET_NAME,
    AWS_ENDPOINT_URL,
    AWS_REGION,
    AWS_SECRET_ACCESS_KEY,
    MEDIA_URL_TTL_SECONDS,
    PRESIGN_ENDPOINT_URL,
    UPLOAD_CACHE_CONTROL,
)

logger = logging.getLogger(__name__)

# ================== S3 Client Factory ==================

def _make_client(endpoint_url: str | None = None):
    """
    Build a boto3 S3 client for storage operations.
    endpoint_url overrides AWS_ENDPOINT_URL (used internally for MinIO/R2).
    """
    kwargs = dict(
        service_name="s3",
        region_name=AWS_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4"),
    )
    effective_url = endpoint_url or AWS_ENDPOINT_URL
    if effective_url:
        kwargs["endpoint_url"] = effective_url
    return boto3.client(**kwargs)


# Internal client: connects to the real S3/MinIO endpoint for storage operations.
s3_client = _make_client()

# Presign client: uses PRESIGN_ENDPOINT_URL (public-facing domain) so that
# generated URLs are valid for the browser to use directly.
# Singleton — avoids creating a new TCP connection on every presign request.
s3_presign_client = _make_client(endpoint_url=PRESIGN_ENDPOINT_URL)




def init_storage():
    """
    Ensure the target S3 bucket exists and apply a public read policy automatically.
    This makes the project plug-and-play without requiring users to manually configure MinIO.
    """
    try:
        # Check if bucket exists, create if it doesn't
        try:
            s3_client.head_bucket(Bucket=AWS_BUCKET_NAME)
            logger.info("Bucket '%s' already exists.", AWS_BUCKET_NAME)
        except botocore.exceptions.ClientError as e:
            if e.response['Error']['Code'] == '404':
                logger.info("Bucket '%s' not found. Creating it...", AWS_BUCKET_NAME)
                s3_client.create_bucket(Bucket=AWS_BUCKET_NAME)
            else:
                raise

        # Apply a hybrid public read policy: only files inside any /public/ folder are accessible
        # This keeps documents safe while allowing CDNs to cache public images.
        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": "*",
                    "Action": ["s3:GetObject"],
                    "Resource": [f"arn:aws:s3:::{AWS_BUCKET_NAME}/*/public/*"]
                }
            ]
        }
        s3_client.put_bucket_policy(
            Bucket=AWS_BUCKET_NAME,
            Policy=json.dumps(policy)
        )
        logger.info("Public read policy applied to bucket '%s'.", AWS_BUCKET_NAME)

    except Exception as e:
        logger.warning("Could not auto-configure bucket '%s': %s", AWS_BUCKET_NAME, e)


# ================== Storage Operations ==================

def upload_file(local_path: str, s3_key: str, content_type: str) -> None:
    """
    Upload a local file on disk to S3 using a streaming multipart upload.
    Operates on file paths to keep memory usage constant regardless of file size.
    Injects Cache-Control so the CDN (Cloudflare) caches the file efficiently.
    """
    try:
        s3_client.upload_file(
            Filename=local_path,
            Bucket=AWS_BUCKET_NAME,
            Key=s3_key,
            ExtraArgs={
                "ContentType": content_type,
                "CacheControl": UPLOAD_CACHE_CONTROL,
            },
        )
    except botocore.exceptions.ClientError as e:
        logger.error("S3 upload failed for key '%s': %s", s3_key, e)
        raise HTTPException(
            status_code=500, detail=f"Storage upload failed: {e.response['Error']['Code']}"
        ) from e


def upload_bytes(s3_key: str, data: bytes, content_type: str) -> None:
    """
    Upload raw bytes to S3. Used for small files (e.g. compressed images in memory).
    Injects Cache-Control so the CDN (Cloudflare) caches the file efficiently.
    """
    try:
        s3_client.put_object(
            Bucket=AWS_BUCKET_NAME,
            Key=s3_key,
            Body=io.BytesIO(data),
            ContentType=content_type,
            CacheControl=UPLOAD_CACHE_CONTROL,
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
    Uses the singleton s3_presign_client configured with AWS_PUBLIC_URL so the
    AWS V4 Signature is valid for the public-facing domain (no SignatureDoesNotMatch).
    """
    try:
        url: str = s3_presign_client.generate_presigned_url(
            ClientMethod="get_object",
            Params={"Bucket": AWS_BUCKET_NAME, "Key": s3_key},
            ExpiresIn=MEDIA_URL_TTL_SECONDS,
        )
        return url
    except botocore.exceptions.ClientError as e:
        logger.error("Presigned URL generation failed for key '%s': %s", s3_key, e)
        raise HTTPException(
            status_code=500, detail="Failed to generate signed URL"
        ) from e


def generate_public_url(s3_key: str) -> str:
    """
    Generate a clean, static, cacheable public URL without any AWS signatures.
    Requires the underlying S3 bucket (or prefix) to have a Public Read policy.
    """
    base_url = PRESIGN_ENDPOINT_URL.rstrip("/")
    return f"{base_url}/{AWS_BUCKET_NAME}/{s3_key}"


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
