# Media service

A self-hosted, S3-compatible microservice for **uploading, compressing, and managing media files** (images, videos, and documents) — built with FastAPI and Python 3.11.

[![Python](https://img.shields.io/badge/Python-3.11-blue?logo=python)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green?logo=fastapi)](https://fastapi.tiangolo.com)
[![Docker](https://img.shields.io/badge/Docker-ready-blue?logo=docker)](https://docker.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

---

## Features

- **Automatic Image Compression** — Converts uploaded images to WebP (configurable quality and max dimension)
- **Async Video Processing** — Compresses videos to H.264 MP4 via FFmpeg
- **Webhook Callbacks** — Notifies your backend via HTTP POST when video processing is complete
- **Concurrency Control** — `asyncio.Semaphore` limits parallel FFmpeg jobs to protect server resources
- **Disk Streaming** — Reads uploads in 1MB chunks to disk; RAM stays flat regardless of file size
- **Hybrid Public/Private Access** — Host static CDN assets and secure private documents in the same bucket using folder prefixes (e.g. `X-Folder: public`).
- **CDN Edge Caching** — Injects `Cache-Control: immutable` headers automatically to perfectly leverage CDNs like Cloudflare.
- **Auto-Initialization** — Plug-and-play: creates the S3 bucket and applies the hybrid security policy automatically on startup.
- **Universal S3 Support** — Works with AWS S3, MinIO, Cloudflare R2, DigitalOcean Spaces, and any S3-compatible provider.
- **Multi-Tenant API Keys** — Simple `X-Api-Key` authentication with client-isolated storage paths.
- **Presigned URLs** — Time-limited direct access links for private files (TTL configurable).
- **Document Storage** — Stores PDFs, DOCX, XLSX, XML, and other document types as-is.

---

## Quick start (Docker Compose)

### 1. Clone and configure

```bash
git clone https://github.com/your-org/media-service.git
cd media-service
cp .env.example .env
```

Edit `.env` with your credentials. For local development with the bundled MinIO:

```env
AWS_ACCESS_KEY_ID=admin
AWS_SECRET_ACCESS_KEY=password123
AWS_BUCKET_NAME=media
AWS_ENDPOINT_URL=http://minio:9000
API_KEYS=mysecretkey:my_app
```

### 2. Start the services

```bash
docker compose up -d --build
```

The API will be available at `http://localhost:8002`.  
The MinIO console will be available at `http://localhost:9001`.

### 3. Verify

```bash
curl http://localhost:8002/health
# {"status":"ok","max_concurrent_jobs":2}
```

---

## S3 provider configuration

The service uses `boto3` and is compatible with any S3-compatible storage provider:

| Provider                | `AWS_ENDPOINT_URL`                              | Notes                    |
| ----------------------- | ----------------------------------------------- | ------------------------ |
| **AWS S3**              | _(leave empty)_                                 | Standard AWS credentials |
| **MinIO**               | `http://minio:9000`                             | Set in Docker network    |
| **Cloudflare R2**       | `https://<ACCOUNT_ID>.r2.cloudflarestorage.com` | Use R2 API tokens        |
| **DigitalOcean Spaces** | `https://<REGION>.digitaloceanspaces.com`       | Region in endpoint       |

---

## API endpoints

All endpoints (except `/health`) require the `X-Api-Key` header.

### `POST /media` — Upload a file

| Header      | Required | Description                      |
| ----------- | -------- | -------------------------------- |
| `X-Api-Key` | ✅       | Your API key                     |
| `X-Folder`  | ❌       | Destination subfolder in storage |

| Query Param   | Required | Description                                            |
| ------------- | -------- | ------------------------------------------------------ |
| `webhook_url` | ❌       | URL to receive callback when video processing finishes |

**Image response** (`200 OK`):

```json
{
  "id": "uuid-v4",
  "filename": "photo.jpg",
  "content_type": "image/webp",
  "path": "my_app/uploads/uuid.webp",
  "client_id": "my_app",
  "folder": "uploads"
}
```

**Video response** (`202 Accepted`):

```json
{
  "id": "uuid-v4",
  "status": "processing",
  "message": "Video accepted. It will be compressed and uploaded in the background.",
  "client_id": "my_app",
  "folder": "uploads"
}
```

**Webhook callback payload** (sent to `webhook_url` on completion):

```json
{
  "id": "uuid-v4",
  "status": "ready",
  "path": "my_app/uploads/uuid.mp4",
  "url": "https://cdn.yourdomain.com/my_app/uploads/uuid.mp4?X-Amz-...",
  "error": null,
  "client_id": "my_app",
  "folder": "uploads"
}
```

### `GET /media/url` — Generate access URL

```
GET /media/url?path=my_app/uploads/uuid.webp&public=false
X-Api-Key: mysecretkey
```

| Query Param | Required | Description |
| ----------- | -------- | ----------- |
| `path` | ✅ | S3 object key (path) of the media file |
| `public` | ❌ | Set to `true` to return a static, cacheable URL (without AWS signatures). Requires the file to be inside a `/public/` folder. Default is `false` (returns a secure presigned URL). |

**Presigned (Private) Response**:
```json
{
  "url": "https://media.yourdomain.com/my_app/uploads/uuid.webp?X-Amz-Signature=...",
  "type": "presigned",
  "expires_in": 3600
}
```

**Public (CDN) Response**:
```json
{
  "url": "https://cdn.yourdomain.com/my_app/public/uuid.webp",
  "type": "public",
  "expires_in": null
}
```

### `DELETE /media` — Delete a file

```
DELETE /media?path=my_app/uploads/uuid.webp
X-Api-Key: mysecretkey
```

### `GET /media/download` — Stream file for download

```
GET /media/download?path=my_app/uploads/uuid.webp
X-Api-Key: mysecretkey
```

---

## Environment variables

| Variable                | Default                     | Description                                                   |
| ----------------------- | --------------------------- | ------------------------------------------------------------- |
| `AWS_ACCESS_KEY_ID`     | —                           | S3 access key                                                 |
| `AWS_SECRET_ACCESS_KEY` | —                           | S3 secret key                                                 |
| `AWS_BUCKET_NAME`       | `media`                     | Target S3 bucket name                                         |
| `AWS_REGION`            | `us-east-1`                 | S3 bucket region                                              |
| `AWS_ENDPOINT_URL`      | _(empty)_                   | Custom S3 endpoint (MinIO, R2, etc.)                          |
| `AWS_PUBLIC_URL`        | _(empty)_                   | Public CDN URL to replace internal endpoint in presigned URLs |
| `API_KEYS`              | —                           | Comma-separated `key:client_id` pairs                         |
| `IMAGE_MAX_DIMENSION`   | `1280`                      | Max image side in pixels before resizing                      |
| `IMAGE_QUALITY`         | `75`                        | WebP compression quality (1–100)                              |
| `ALLOWED_EXTENSIONS`    | `pdf,xlsx,xls,docx,txt,xml` | Allowed document extensions                                   |
| `MAX_CONCURRENT_JOBS`   | `2`                         | Max parallel FFmpeg processes                                 |
| `MEDIA_URL_TTL_SECONDS` | `3600`                      | Presigned URL lifetime in seconds                             |
| `PORT`                  | `8002`                      | Service port                                                  |

---

## Security model

- Each API key maps to a `client_id`.
- All uploaded files are stored under the path `{client_id}/{folder}/{uuid}.{ext}`.
- All read, delete, and URL-generation endpoints validate that the requested path starts with the caller's `client_id` prefix — preventing cross-client access.

---

## Production deployment

### Reverse proxy (recommended)

Run the service behind a reverse proxy that handles SSL termination. The service trusts `X-Forwarded-Proto` and `X-Forwarded-For` headers automatically.

**Nginx:**
```nginx
server {
    listen 443 ssl;
    server_name media.yourdomain.com;

    location / {
        proxy_pass         http://localhost:8002;
        proxy_set_header   Host $host;
        proxy_set_header   X-Forwarded-For $remote_addr;
        proxy_set_header   X-Forwarded-Proto $scheme;
        client_max_body_size 0;  # no upload size limit
    }
}
```

**Caddy:**
```
media.yourdomain.com {
    reverse_proxy localhost:8002
}
```

**Traefik** — add standard labels to the `media-service` container in `docker-compose.yml`.

### CDN / public URLs

If you want presigned URLs to point to a CDN or a public domain instead of the raw S3 endpoint, set:

```env
AWS_PUBLIC_URL=https://cdn.yourdomain.com
```

The service will automatically replace the internal S3 host in all generated URLs.

### Infrastructure Auto-Initialization

The media-service is **Plug & Play**. When the FastAPI application starts, it connects to your S3/MinIO provider and automatically:
1. Creates the target bucket (e.g., `media`) if it does not exist.
2. Injects a hybrid JSON Bucket Policy that allows **public read access only to files located inside any `/public/` folder** (`arn:aws:s3:::media/*/public/*`).

All other paths remain strictly private. This eliminates manual configuration and makes the project instantly ready for production CDN scaling.

---

## Running tests

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

---

## Local development (without Docker)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env  # fill in values
uvicorn app.main:app --reload --port 8002
```

Interactive API docs: `http://localhost:8002/docs`

---

## License

MIT License — see [LICENSE](./LICENSE).
