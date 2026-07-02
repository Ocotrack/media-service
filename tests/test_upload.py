"""
Tests for POST /media (file upload endpoint).

Covers all supported file types:
  - Images:    JPEG, PNG, GIF, WebP, BMP, TIFF
  - Videos:    MP4, MOV, AVI, MKV, WebM
  - Documents: PDF, XLSX, XLS, DOCX, TXT, XML
  - Rejected:  EXE, ZIP, binary blobs
"""

import io
import pytest
from tests.conftest import VALID_HEADERS, make_image_bytes, make_text_bytes


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _upload(client, filename, content, content_type, folder=None, webhook_url=None):
    """Shorthand for a multipart POST /media request."""
    headers = {**VALID_HEADERS}
    if folder:
        headers["X-Folder"] = folder
    params = {}
    if webhook_url:
        params["webhook_url"] = webhook_url
    return client.post(
        "/media",
        headers=headers,
        params=params,
        files={"file": (filename, content, content_type)},
    )


# ─── Images ───────────────────────────────────────────────────────────────────

IMAGE_CASES = [
    ("photo.jpg",  "image/jpeg"),
    ("photo.jpeg", "image/jpeg"),
    ("image.png",  "image/png"),
    ("anim.gif",   "image/gif"),
    ("icon.webp",  "image/webp"),
    ("scan.bmp",   "image/bmp"),
    ("raw.tiff",   "image/tiff"),
]

@pytest.mark.asyncio
@pytest.mark.parametrize("filename,content_type", IMAGE_CASES)
async def test_upload_image_format(client, filename, content_type):
    response = await _upload(client, filename, make_image_bytes(), content_type)
    assert response.status_code == 200
    body = response.json()
    assert body["content_type"] == "image/webp", f"Expected webp for {filename}"
    assert body["path"].endswith(".webp")
    assert body["client_id"] == "local_test"
    assert "id" in body


@pytest.mark.asyncio
async def test_upload_image_with_folder(client):
    response = await _upload(
        client, "photo.jpg", make_image_bytes(), "image/jpeg", folder="receipts/2026"
    )
    assert response.status_code == 200
    body = response.json()
    assert "receipts/2026" in body["path"]
    assert body["folder"] == "receipts/2026"


@pytest.mark.asyncio
async def test_upload_image_without_folder_has_flat_path(client):
    response = await _upload(client, "img.jpg", make_image_bytes(), "image/jpeg")
    assert response.status_code == 200
    # Flat path: client_id/uuid.webp — exactly one slash
    assert response.json()["path"].count("/") == 1


# ─── Videos ───────────────────────────────────────────────────────────────────

VIDEO_CASES = [
    ("clip.mp4",  "video/mp4"),
    ("clip.mov",  "video/quicktime"),
    ("clip.avi",  "video/x-msvideo"),
    ("clip.mkv",  "video/x-matroska"),
    ("clip.webm", "video/webm"),
]

@pytest.mark.asyncio
@pytest.mark.parametrize("filename,content_type", VIDEO_CASES)
async def test_upload_video_returns_processing(client, filename, content_type):
    response = await _upload(client, filename, b"fake-video-bytes", content_type)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processing", f"Expected processing for {filename}"
    assert body["client_id"] == "local_test"
    assert "id" in body


@pytest.mark.asyncio
async def test_upload_video_with_webhook_url(client):
    response = await _upload(
        client,
        "video.mp4",
        b"fake-video",
        "video/mp4",
        webhook_url="http://mybackend.com/media-callback",
    )
    assert response.status_code == 200
    assert response.json()["status"] == "processing"


@pytest.mark.asyncio
async def test_upload_video_with_folder(client):
    response = await _upload(
        client, "video.mp4", b"fake-video", "video/mp4", folder="trips/driver-42"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["folder"] == "trips/driver-42"


# ─── Documents ────────────────────────────────────────────────────────────────

DOCUMENT_CASES = [
    ("report.pdf",  "application/pdf",                                                            ".pdf"),
    ("data.xlsx",   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",          ".xlsx"),
    ("legacy.xls",  "application/vnd.ms-excel",                                                   ".xls"),
    ("letter.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document",    ".docx"),
    ("notes.txt",   "text/plain",                                                                  ".txt"),
    ("feed.xml",    "application/xml",                                                             ".xml"),
    ("feed.xml",    "text/xml",                                                                    ".xml"),
]

@pytest.mark.asyncio
@pytest.mark.parametrize("filename,content_type,expected_ext", DOCUMENT_CASES)
async def test_upload_document_type(client, filename, content_type, expected_ext):
    response = await _upload(client, filename, b"document-content", content_type)
    assert response.status_code == 200, f"Failed for {filename} ({content_type})"
    body = response.json()
    assert body["path"].endswith(expected_ext), f"Expected {expected_ext} extension for {filename}"
    assert body["client_id"] == "local_test"


@pytest.mark.asyncio
async def test_upload_document_with_folder(client):
    response = await _upload(
        client, "invoice.pdf", b"%PDF-content", "application/pdf", folder="invoices/jan"
    )
    assert response.status_code == 200
    body = response.json()
    assert "invoices/jan" in body["path"]


# ─── Unsupported / rejected ───────────────────────────────────────────────────

REJECTED_CASES = [
    ("virus.exe",    b"MZ\x90\x00",  "application/x-msdownload"),
    ("archive.zip",  b"PK\x03\x04",  "application/zip"),
    ("shell.sh",     b"#!/bin/bash", "application/x-sh"),
    ("binary.bin",   b"\x00\x01\x02","application/octet-stream"),
    ("data.csv",     b"a,b,c",       "text/csv"),
]

@pytest.mark.asyncio
@pytest.mark.parametrize("filename,content,content_type", REJECTED_CASES)
async def test_upload_rejected_file_type_returns_415(client, filename, content, content_type):
    response = await _upload(client, filename, content, content_type)
    assert response.status_code == 415, f"Expected 415 for {filename}"


# ─── Validation ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_upload_without_file_returns_422(client):
    response = await client.post("/media", headers=VALID_HEADERS)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_upload_without_auth_returns_401(client):
    response = await client.post(
        "/media",
        files={"file": ("photo.jpg", make_image_bytes(), "image/jpeg")},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_folder_with_path_traversal_returns_400(client):
    response = await _upload(
        client, "img.jpg", make_image_bytes(), "image/jpeg", folder="../../etc/passwd"
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_folder_with_invalid_characters_returns_400(client):
    response = await _upload(
        client, "img.jpg", make_image_bytes(), "image/jpeg", folder="bad folder!"
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_folder_with_nested_path_is_valid(client):
    response = await _upload(
        client, "img.jpg", make_image_bytes(), "image/jpeg", folder="a/b/c"
    )
    assert response.status_code == 200
    assert "a/b/c" in response.json()["path"]
