# Configuración de Almacenamiento MinIO con CDN y URLs Firmadas

Este documento detalla la arquitectura y configuración necesaria para desplegar un sistema de almacenamiento de archivos robusto utilizando MinIO, expuesto a través de un CDN/Reverse Proxy, y asegurado mediante URLs firmadas.

## 1. Arquitectura del Sistema

El sistema se compone de tres capas principales:

1.  **Capa de Almacenamiento (MinIO Server)**:
    *   Responsable de guardar los objetos (imágenes, videos, documentos).
    *   No expuesto directamente a internet.
    *   Escucha en puertos internos (ej: 9003 API, 9004 Consola).

2.  **Capa de Acceso Público (CDN / Reverse Proxy)**:
    *   Servidor web (Nginx/Apache) que actúa como puerta de enlace.
    *   Maneja SSL/TLS (HTTPS).
    *   Redirige el tráfico autorizado al servidor MinIO.
    *   Dominio ejemplo: `cdn.meximova.com`.

3.  **Capa de Aplicación (Media Service)**:
    *   Microservicio que gestiona la lógica de negocio.
    *   Se conecta a MinIO internamente para subir/borrar archivos.
    *   Genera URLs firmadas usando el dominio público del CDN para que los clientes (App Móvil/Web) puedan descargar el contenido.


## 2. Configuración del Servidor MinIO

### Requisitos
*   Docker y Docker Compose instalados.
*   Volumen de datos persistente.

### Docker Compose (Ejemplo)

```yaml
services:
  minio:
    image: minio/minio:latest
    container_name: minio
    restart: unless-stopped
    command: server /data --address ":9003" --console-address ":9004"
    ports:
      - "9003:9003" # API S3 (Interno)
      - "9004:9004" # Consola Web (Interno)
    environment:
      MINIO_ROOT_USER: ${MINIO_ACCESS_KEY}
      MINIO_ROOT_PASSWORD: ${MINIO_SECRET_KEY}
      # Importante: No configurar MINIO_BROWSER_REDIRECT_URL si se usa proxy transparente
    volumes:
      - minio_data:/data

volumes:
  minio_data:
```

### Variables de Entorno (.env)
```bash
MINIO_ACCESS_KEY=admin_user
MINIO_SECRET_KEY=super_secure_password_123
```

---

## 3. Configuración del CDN / Reverse Proxy (Nginx)

Este servidor expone MinIO al mundo. Debe estar configurado para pasar las cabeceras correctamente, lo cual es crítico para que la validación de firma de AWS S3 funcione.

### Configuración Nginx (`/etc/nginx/sites-available/cdn.meximova.com`)

```nginx
server {
    listen 80;
    server_name cdn.meximova.com;

    # Redirección a HTTPS (Recomendado)
    # return 301 https://$host$request_uri;
    
    # Configuración para servir archivos
    location / {
        proxy_pass http://192.168.1.3:9003; # IP Privada del servidor MinIO
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Optimizaciones para archivos grandes
        proxy_buffering off;
        client_max_body_size 0;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
        
        # Ocultar cabeceras de MinIO (seguridad por oscuridad)
        proxy_hide_header x-amz-request-id;
        proxy_hide_header x-minio-deployment-id;
    }
}
```

> **Nota Crítica**: La directiva `proxy_set_header Host $http_host;` es fundamental. Si Nginx cambia el Host header, la firma generada por la aplicación no coincidirá con la que MinIO calcula, resultando en error `SignatureDoesNotMatch`.

---

## 4. Configuración del Servicio de Aplicación (Media Service)

El servicio debe tener **dos clientes MinIO configurados**:

1.  **Cliente Interno**: Para operaciones de administración (subir, borrar, verificar existencia). Se conecta directamente a la IP/DNS interno de Docker.
2.  **Cliente Público (Signer)**: Exclusivamente para generar URLs. Se configura con el dominio público.

### Variables de Entorno (.env)

```bash
# Credenciales (Mismas que en MinIO Server)
MINIO_ACCESS_KEY=admin_user
MINIO_SECRET_KEY=super_secure_password_123
MINIO_BUCKET=media

# Endpoint Interno (Red Docker o IP Privada)
# Usado para uploads y checks de existencia
MINIO_ENDPOINT_INTERNAL=minio:9003

# Endpoint Público (CDN)
# Usado SOLO para firmar URLs
CDN_HOST=cdn.meximova.com:80  # Incluir puerto si no es estándar
MINIO_USE_SSL=false           # True si el CDN tiene HTTPS
```

### Implementación en Código (Python/FastAPI)

```python
import os
from minio import Minio

# 1. Cliente Interno
minio_internal = Minio(
    endpoint=os.getenv("MINIO_ENDPOINT_INTERNAL", "minio:9003"),
    access_key=os.getenv("MINIO_ACCESS_KEY"),
    secret_key=os.getenv("MINIO_SECRET_KEY"),
    secure=False # Generalmente False dentro de la red privada
)

# 2. Cliente Público (Signer)
minio_signer = Minio(
    endpoint=os.getenv("CDN_HOST", "cdn.meximova.com"),
    access_key=os.getenv("MINIO_ACCESS_KEY"),
    secret_key=os.getenv("MINIO_SECRET_KEY"),
    secure=os.getenv("MINIO_USE_SSL") == "true"
)

def generate_signed_url(path):
    # Usamos el cliente signer. NO verifica conexión, solo calcula firma.
    return minio_signer.presigned_get_object(
        bucket_name="media",
        object_name=path,
        expires=timedelta(minutes=5)
    )

def upload_file(path, data):
    # Usamos el cliente interno. SÍ requiere conexión.
    minio_internal.put_object(...)
```

---

## 5. Checklist de Verificación y Troubleshooting

Si algo falla, sigue estos pasos en orden:

### A. Conectividad Interna
Desde el contenedor de `media-service`, verifica que puedes ver a MinIO:
```bash
# Dentro del contenedor
curl -v http://minio:9003/minio/health/live
```
*   **Éxito**: Respuesta 200 OK.
*   **Fallo**: Revisa redes de Docker y nombres de servicio en `docker-compose.yml`.

### B. Conectividad Pública (CDN)
Desde tu máquina local o navegador:
```bash
curl -v http://cdn.meximova.com/minio/health/live
```
*   **Éxito**: Respuesta 200 OK.
*   **Fallo**: Revisa configuración de Nginx, DNS y Firewall (puerto 80/443 abierto).

### C. Validación de Firmas
Si obtienes `SignatureDoesNotMatch` o `403 Forbidden` al acceder a una URL firmada:
1.  Verifica que `CDN_HOST` en la app coincida exactamente con el dominio del navegador.
2.  Verifica que Nginx esté pasando el header `Host` (`proxy_set_header Host $http_host;`).
3.  Asegúrate de que la hora del servidor MinIO y la del servidor de Aplicación estén sincronizadas (NTP).

### D. Errores de Conexión al Generar URL
Si la aplicación lanza error 500 al llamar a `generate_signed_url`:
*   **Causa**: El cliente MinIO está intentando conectarse al CDN para validar el bucket y falla (por firewall o DNS interno).
*   **Solución**: Asegúrate de que el código **NO** llame a `bucket_exists` usando el cliente `minio_signer`. Solo usa `presigned_get_object`.

---

## 6. Resiliencia y Mantenimiento

*   **Cambio de Dominio**: Solo necesitas actualizar la variable `CDN_HOST` en el `media-service` y la configuración `server_name` en Nginx. No requiere reiniciar MinIO.
*   **Rotación de Claves**: Si cambias las claves en MinIO, debes actualizarlas en `media-service` inmediatamente. Las URLs generadas anteriormente dejarán de funcionar.
*   **Backup**: Respalda regularmente el volumen `minio_data`.
