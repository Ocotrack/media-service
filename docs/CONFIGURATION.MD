# 📦 Microservicio de Medios - Meximova

Este microservicio se encarga de la gestión, procesamiento y almacenamiento de evidencias (fotos, videos y archivos) para la plataforma Meximova.

---

## 🚀 Detalles de Conexión

El servicio está detrás de un proxy inverso Apache que gestiona la terminación SSL y redirige el tráfico internamente.

| Parámetro | Valor |
|-----------|-------|
| **URL Base** | `https://media.meximova.com` |
| **Protocolo** | HTTPS (Obligatorio) |
| **Puerto Externo** | 443 |
| **Servidor de Entrada (Proxy)** | 192.168.1.116 (Apache) |
| **Servidor de Destino (Backend)** | 192.168.1.126 (FastAPI/Uvicorn en puerto 8002) |

---

## 🛠 Configuración del Cliente

> [!IMPORTANT]
> Para evitar errores de cURL timeout (error 28), especialmente al subir archivos desde el servidor principal hacia el subdominio de medios, es necesario seguir estas pautas:

### 1. Resolución de Nombres

Si el cliente está en el mismo servidor físico que el proxy, asegúrese de que el archivo `/etc/hosts` apunte localmente para evitar latencia de red:

```plaintext
127.0.0.1 media.meximova.com
```

### 2. Implementación en Laravel/PHP

Al realizar peticiones, se recomienda forzar la resolución a IPv4 y extender los tiempos de espera:

```php
$response = Http::timeout(120)
    ->withOptions([
        'force_ip_resolve' => 'v4',
    ])
    ->attach('file', $archivo, 'evidencia.jpg')
    ->withHeaders(['X-Api-Key' => env('MEDIA_SERVICE_API_KEY')])
    ->post('https://media.meximova.com/media');
```

---

## 📂 Endpoints Disponibles

### 1. Health Check

Verifica si el servicio y el proxy están respondiendo correctamente.

- **Método**: `GET`
- **Ruta**: `/health`
- **Respuesta Exitosa**: 
  ```json
  {
    "status": "ok"
  }
  ```

### 2. Subida de Evidencias

- **Método**: `POST`
- **Ruta**: `/media`
- **Formato**: `multipart/form-data`
- **Headers Requeridos**:
  - `X-Api-Key`: Clave de API del cliente
  - `X-Folder` (opcional): Carpeta de destino
- **Límite de Tamaño**: Sin límite estricto en el proxy (configurado con `LimitRequestBody 0`)

**Tipos de Archivo Soportados**:
- Imágenes: `image/*` (se comprime automáticamente a WebP/JPEG)
- Videos: `video/*` (se comprime automáticamente a MP4)
- Documentos: PDF, Excel (`.xlsx`, `.xls`)

### 3. Generar URL Firmada

- **Método**: `GET`
- **Ruta**: `/media/url`
- **Query Parameters**:
  - `path`: Ruta del archivo en el storage

### 4. Descargar Archivo

- **Método**: `GET`
- **Ruta**: `/media/download`
- **Query Parameters**:
  - `path`: Ruta del archivo en el storage

### 5. Eliminar Archivo

- **Método**: `DELETE`
- **Ruta**: `/media`
- **Query Parameters**:
  - `path`: Ruta del archivo en el storage

---

## ⚠️ Solución de Problemas Comunes

| Error | Causa Probable | Solución |
|-------|----------------|----------|
| **cURL error 28** | Timeout en el handshake SSL o DNS lento | Forzar IPv4 en el cliente y añadir el dominio al archivo `/etc/hosts` |
| **405 Method Not Allowed** | Se intentó un método (ej. HEAD) no permitido | Asegúrese de usar `GET` para salud y `POST` para subidas |
| **502 Bad Gateway** | El servicio en el .126 está caído | Revisar que Uvicorn esté corriendo en el puerto 8002 del servidor .126 |
| **SSL Certificate Error** | Intento de conexión por IP en lugar de dominio | Use siempre el dominio `https://media.meximova.com` |
| **401 Unauthorized** | API Key faltante o inválida | Verificar el header `X-Api-Key` |
| **403 Forbidden** | Intento de acceder a recursos de otro cliente | Verificar que la ruta pertenezca al cliente autenticado |

---

## 📝 Notas de Infraestructura

- **SSL**: Certificado Let's Encrypt (E7)
- **Handshake**: Soporta TLS v1.2 y v1.3
- **Buffer**: Configurado con `SSLRenegBufferSize 10MB` para soportar renegociación de certificados durante subidas largas
- **Proxy**: Apache2 en puerto 443 con `ProxyPass` hacia el backend FastAPI
- **Storage Backend**: MinIO (S3-compatible)

---

## 🔧 Variables de Entorno Requeridas

```env
# MinIO Configuration
MINIO_ENDPOINT=your-minio-endpoint
MINIO_ACCESS_KEY=your-access-key
MINIO_SECRET_KEY=your-secret-key
MINIO_BUCKET=media-bucket
MINIO_USE_SSL=true

# API Security
API_KEYS={"key1": "client1", "key2": "client2"}

# Media URLs
MEDIA_URL_TTL_SECONDS=3600
```

---

## 📊 Monitoreo

Para verificar el estado del servicio:

```bash
# Health check
curl https://media.meximova.com/health

# Verificar conectividad desde el servidor principal
curl -v https://media.meximova.com/health

# Con resolución forzada (desde servidor principal)
curl --resolve media.meximova.com:443:127.0.0.1 https://media.meximova.com/health
```