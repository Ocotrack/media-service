[English](README.md) | [Español](README.es.md)

# Media service

Un microservicio self-hosted compatible con S3 para **subir, comprimir y administrar archivos multimedia** (imágenes, videos y documentos) — construido con FastAPI y Python 3.11.

[![Python](https://img.shields.io/badge/Python-3.11-blue?logo=python)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green?logo=fastapi)](https://fastapi.tiangolo.com)
[![Docker](https://img.shields.io/badge/Docker-ready-blue?logo=docker)](https://docker.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

---

## Características

- **Compresión Automática de Imágenes** — Convierte imágenes subidas a WebP (calidad y dimensión máxima configurables).
- **Procesamiento Asíncrono de Video** — Comprime videos a H.264 MP4 usando FFmpeg.
- **Callbacks por Webhook** — Notifica a tu backend vía HTTP POST cuando el procesamiento de video ha terminado.
- **Control de Concurrencia** — `asyncio.Semaphore` limita los trabajos de FFmpeg en paralelo para proteger los recursos del servidor.
- **Streaming a Disco** — Lee subidas en bloques de 1MB hacia el disco; el consumo de RAM se mantiene plano sin importar el tamaño del archivo.
- **Acceso Híbrido Público/Privado** — Aloja assets estáticos de CDN y documentos privados seguros en el mismo bucket usando prefijos de carpeta (ej. `X-Folder: public`).
- **Caché de Borde (CDN Edge Caching)** — Inyecta cabeceras `Cache-Control: immutable` automáticamente para aprovechar al máximo CDNs como Cloudflare.
- **Auto-Inicialización** — Plug-and-play: crea el bucket de S3 y aplica la política de seguridad híbrida automáticamente al iniciar.
- **Soporte Universal de S3** — Funciona con AWS S3, MinIO, Cloudflare R2, DigitalOcean Spaces y cualquier proveedor compatible con S3.
- **API Keys Multi-Tenant** — Autenticación simple mediante `X-Api-Key` con rutas de almacenamiento aisladas por cliente.
- **URLs Firmadas (Presigned URLs)** — Enlaces de acceso directo por tiempo limitado para archivos privados (TTL configurable).
- **Almacenamiento de Documentos** — Guarda PDFs, DOCX, XLSX, XML y otros tipos de documentos tal como están.

---

## Inicio Rápido (Docker Compose)

### 1. Clonar y configurar

```bash
git clone https://github.com/your-org/media-service.git
cd media-service
cp .env.example .env
```

Edita `.env` con tus credenciales. Para desarrollo local con el MinIO incluido:

```env
AWS_ACCESS_KEY_ID=admin
AWS_SECRET_ACCESS_KEY=password123
AWS_BUCKET_NAME=media
AWS_ENDPOINT_URL=http://minio:9000
API_KEYS=mysecretkey:my_app
```

### 2. Iniciar los servicios

```bash
docker compose up -d --build
```

La API estará disponible en `http://localhost:8002`.  
La consola de MinIO estará disponible en `http://localhost:9001`.

### 3. Verificar

```bash
curl http://localhost:8002/health
# {"status":"ok","max_concurrent_jobs":2}
```

---

## Configuración del proveedor S3

El servicio usa `boto3` y es compatible con cualquier proveedor de almacenamiento compatible con S3:

| Proveedor               | `AWS_ENDPOINT_URL`                              | Notas                    |
| ----------------------- | ----------------------------------------------- | ------------------------ |
| **AWS S3**              | _(dejar vacío)_                                 | Credenciales AWS estándar|
| **MinIO**               | `http://minio:9000`                             | Definido en red Docker   |
| **Cloudflare R2**       | `https://<ACCOUNT_ID>.r2.cloudflarestorage.com` | Usar tokens API de R2    |
| **DigitalOcean Spaces** | `https://<REGION>.digitaloceanspaces.com`       | Región en el endpoint    |

---

## Endpoints de la API

Todos los endpoints (excepto `/health`) requieren la cabecera `X-Api-Key`.

### `POST /media` — Subir un archivo

| Cabecera    | Requerido | Descripción                      |
| ----------- | -------- | -------------------------------- |
| `X-Api-Key` | ✅       | Tu clave de API                  |
| `X-Folder`  | ❌       | Subcarpeta de destino en storage |

| Parámetro Query | Requerido | Descripción                                            |
| ------------- | -------- | ------------------------------------------------------ |
| `webhook_url` | ❌       | URL para recibir callback cuando termine de procesar video |

**Respuesta de Imagen** (`200 OK`):

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

**Respuesta de Video** (`202 Accepted`):

```json
{
  "id": "uuid-v4",
  "status": "processing",
  "message": "Video accepted. It will be compressed and uploaded in the background.",
  "client_id": "my_app",
  "folder": "uploads"
}
```

**Payload del callback del Webhook** (enviado a `webhook_url` al terminar):

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

### `GET /media/presign` — Generar URL de acceso

```
GET /media/presign?path=my_app/uploads/uuid.webp&public=false
X-Api-Key: mysecretkey
```

| Parámetro Query | Requerido | Descripción |
| ----------- | -------- | ----------- |
| `path` | ✅ | Llave (ruta) del objeto S3 del archivo multimedia |
| `public` | ❌ | Define como `true` para retornar una URL estática, cacheable (sin firmas de AWS). Requiere que el archivo esté dentro de una carpeta `/public/`. Por defecto es `false` (retorna una URL firmada segura). |

**Respuesta Firmada (Privada)**:
```json
{
  "url": "https://media.yourdomain.com/my_app/uploads/uuid.webp?X-Amz-Signature=...",
  "type": "presigned",
  "expires_in": 3600
}
```

**Respuesta Pública (CDN)**:
```json
{
  "url": "https://cdn.yourdomain.com/my_app/public/uuid.webp",
  "type": "public",
  "expires_in": null
}
```

### `DELETE /media` — Eliminar un archivo

```
DELETE /media?path=my_app/uploads/uuid.webp
X-Api-Key: mysecretkey
```

### `GET /media/download` — Hacer streaming del archivo para descarga

```
GET /media/download?path=my_app/uploads/uuid.webp
X-Api-Key: mysecretkey
```

---

## Variables de entorno

| Variable                | Por Defecto                 | Descripción                                                   |
| ----------------------- | --------------------------- | ------------------------------------------------------------- |
| `AWS_ACCESS_KEY_ID`     | —                           | Clave de acceso a S3                                          |
| `AWS_SECRET_ACCESS_KEY` | —                           | Clave secreta de S3                                           |
| `AWS_BUCKET_NAME`       | `media`                     | Nombre del bucket S3 destino                                  |
| `AWS_REGION`            | `us-east-1`                 | Región del bucket S3                                          |
| `AWS_ENDPOINT_URL`      | _(vacío)_                   | Endpoint S3 personalizado (MinIO, R2, etc.)                   |
| `AWS_PUBLIC_URL`        | _(vacío)_                   | URL pública de CDN para reemplazar el endpoint interno en URLs firmadas |
| `API_KEYS`              | —                           | Pares separados por comas `key:client_id`                     |
| `IMAGE_MAX_DIMENSION`   | `1280`                      | Dimensión máxima de la imagen en píxeles antes de redimensionar |
| `IMAGE_QUALITY`         | `75`                        | Calidad de compresión WebP (1–100)                            |
| `ALLOWED_EXTENSIONS`    | `pdf,xlsx,xls,docx,txt,xml` | Extensiones de documentos permitidas                          |
| `MAX_CONCURRENT_JOBS`   | `2`                         | Máximo de procesos FFmpeg en paralelo                         |
| `MEDIA_URL_TTL_SECONDS` | `3600`                      | Tiempo de vida de la URL firmada en segundos                  |
| `UPLOAD_CACHE_CONTROL`  | `public, max-age=31536000, immutable` | Cabecera Cache-Control inyectada en la metadata del objeto S3 |
| `DOWNLOAD_CACHE_CONTROL`| `private, max-age=31536000, immutable`| Cabecera Cache-Control enviada en GET /media/download         |
| `DOWNLOAD_CONTENT_DISPOSITION` | `inline`               | Content-Disposition enviado en GET /media/download            |
| `PORT`                  | `8002`                      | Puerto del servicio                                           |

---

## Modelo de Seguridad

- Cada clave de API se mapea a un `client_id`.
- Todos los archivos subidos se almacenan bajo la ruta `{client_id}/{folder}/{uuid}.{ext}`.
- Todos los endpoints de lectura, borrado y generación de URL validan que la ruta solicitada comience con el prefijo `client_id` del solicitante — previniendo acceso entre clientes.

---

## Despliegue en Producción

### Proxy Inverso (recomendado)

Ejecuta el servicio detrás de un proxy inverso que maneje la terminación SSL. El servicio confía en las cabeceras `X-Forwarded-Proto` y `X-Forwarded-For` automáticamente.

**Nginx:**
```nginx
server {
    listen 443 ssl;
    server_name media.tudominio.com;

    location / {
        proxy_pass         http://localhost:8002;
        proxy_set_header   Host $host;
        proxy_set_header   X-Forwarded-For $remote_addr;
        proxy_set_header   X-Forwarded-Proto $scheme;
        client_max_body_size 0;  # sin límite de subida
    }
}
```

**Caddy:**
```
media.tudominio.com {
    reverse_proxy localhost:8002
}
```

**Traefik** — añade las etiquetas estándar al contenedor `media-service` en `docker-compose.yml`.

### URLs Públicas / CDN

Si quieres que las URLs firmadas apunten a un CDN o a un dominio público en lugar del endpoint S3 puro, configura:

```env
AWS_PUBLIC_URL=https://cdn.tudominio.com
```

El servicio reemplazará automáticamente el host de S3 interno en todas las URLs generadas.

### Auto-Inicialización de Infraestructura

El media-service es **Plug & Play**. Cuando la aplicación FastAPI inicia, se conecta a tu proveedor S3/MinIO y automáticamente:
1. Crea el bucket destino (ej. `media`) si no existe.
2. Inyecta una Política de Bucket híbrida JSON que permite **acceso público de lectura solo a los archivos ubicados dentro de cualquier carpeta `/public/`** (`arn:aws:s3:::media/*/public/*`).

Todas las demás rutas permanecen estrictamente privadas. Esto elimina la configuración manual y hace que el proyecto esté instantáneamente listo para escalar con CDN en producción.

---

## Ejecutar Pruebas

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

---

## Desarrollo Local (sin Docker)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env  # llena los valores
uvicorn app.main:app --reload --port 8002
```

Documentación interactiva de API: `http://localhost:8002/docs`

---

## Licencia

Licencia MIT — ver [LICENSE](./LICENSE).
