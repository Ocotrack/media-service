# Configuración de Almacenamiento MinIO con Apache2 y CDN

Este documento detalla la arquitectura y configuración específica para el proyecto `media-service`, utilizando MinIO como almacenamiento y **Apache2** como Reverse Proxy/CDN para la entrega de contenido público mediante URLs firmadas.

## 1. Arquitectura del Proyecto

*   **MinIO (Docker)**:
    *   Contenedor: `minio`
    *   Puerto API Interno: `9003` (Mapeado en `docker-compose.yml`)
    *   Puerto Consola: `9004`
    *   Volumen: `minio_data`
*   **Media Service (App)**:
    *   Genera URLs firmadas apuntando a `cdn.meximova.com`.
    *   Usa cliente interno (`minio:9003`) para subir archivos.
    *   Usa cliente público (`cdn.meximova.com`) **solo** para firmar URLs.
*   **CDN / Proxy (Apache2)**:
    *   Servidor que recibe el tráfico de internet (`cdn.meximova.com`).
    *   Redirige las peticiones al puerto `9003` del servidor donde corre Docker.

---

## 2. Configuración de Apache2 (Reverse Proxy)

Esta configuración debe aplicarse en el servidor que atiende el dominio `cdn.meximova.com`. Es fundamental activar los módulos de proxy.

### Habilitar módulos necesarios
```bash
sudo a2enmod proxy
sudo a2enmod proxy_http
sudo a2enmod headers
sudo a2enmod rewrite
sudo systemctl restart apache2
```

### Archivo de VirtualHost (`/etc/apache2/sites-available/cdn.meximova.com.conf`)

```apache
<VirtualHost *:80>
    ServerName cdn.meximova.com
    ServerAdmin admin@meximova.com

    # Logs
    ErrorLog ${APACHE_LOG_DIR}/cdn_minio_error.log
    CustomLog ${APACHE_LOG_DIR}/cdn_minio_access.log combined

    # ==================================================================
    # Configuración Crítica para MinIO y URLs Firmadas
    # ==================================================================
    
    # 1. Preservar el Host original
    # Esto es OBLIGATORIO. Si Apache cambia el host a 'localhost' o IP,
    # la firma de AWS S3 fallará (SignatureDoesNotMatch).
    ProxyPreserveHost On

    # 2. No decodificar URLs
    # Evita que Apache modifique caracteres especiales en la firma
    AllowEncodedSlashes On

    # 3. Configuración del Proxy
    # Redirige todo el tráfico al puerto API de MinIO (9003)
    # Asumiendo que MinIO corre en el mismo servidor (localhost) o IP interna.
    ProxyPass / http://127.0.0.1:9003/ nocanon
    ProxyPassReverse / http://127.0.0.1:9003/

    # 4. Ajustes de Headers (Opcional pero recomendado)
    # Ocultar headers internos de MinIO por seguridad
    Header unset Server
    Header unset X-Minio-Deployment-Id
    Header unset X-Amz-Request-Id

    # 5. Configuración para archivos grandes (si aplica)
    # Desactivar buffering para streaming directo
    # ProxyIOBufferSize 65536
</VirtualHost>
```

> **Nota sobre SSL**: Si usas HTTPS (recomendado), la configuración es idéntica dentro del bloque `<VirtualHost *:443>`, añadiendo las directivas `SSLEngine` y certificados.

---

## 3. Configuración del Proyecto (`media-service`)

Asegúrate de que las variables de entorno en `.env` coincidan con esta arquitectura.

### Archivo `.env`

```bash
# --- MinIO Credenciales ---
MINIO_ACCESS_KEY=admin
MINIO_SECRET_KEY=Casamago1.
MINIO_BUCKET=media

# --- Configuración de Red ---

# 1. Endpoint Interno (Docker)
# Usado por la app para subir/borrar archivos.
# Debe ser el nombre del servicio en docker-compose y el puerto interno.
MINIO_ENDPOINT_INTERNAL=minio:9003

# 2. Endpoint Público (CDN)
# Usado EXCLUSIVAMENTE para generar la firma de la URL.
# Debe coincidir con el ServerName de Apache.
# Si Apache escucha en puerto 80, poner solo el dominio o dominio:80.
CDN_HOST=cdn.meximova.com:80

# SSL
# Poner 'true' solo si Apache tiene HTTPS configurado.
MINIO_USE_SSL=false
```

### Archivo `docker-compose.yml`

Es vital que el puerto `9003` esté expuesto en el host para que Apache pueda conectarse a él.

```yaml
services:
  minio:
    command: server /data --address ":9003" --console-address ":9004"
    ports:
      - "9003:9003" # API S3 (Apache se conecta aquí)
      - "9004:9004" # Consola Web
    # ... resto de la configuración
```

---

## 4. Solución de Problemas Comunes

### Error `SignatureDoesNotMatch`
*   **Síntoma**: La URL se genera bien, pero al abrirla en el navegador da error XML `SignatureDoesNotMatch`.
*   **Causa**: Apache no está enviando el header `Host` original a MinIO.
*   **Solución**: Verifica que `ProxyPreserveHost On` esté activo en la config de Apache.

### Error `Connection refused` (500 Internal Server Error)
*   **Síntoma**: La app falla al intentar generar la URL.
*   **Causa**: La app está intentando conectarse al CDN para validar el bucket y falla (bloqueo de red o DNS).
*   **Solución**: La app debe usar `minio_internal` para validar buckets y `minio_public` **solo** para firmar (sin conexión). El código ya fue ajustado para esto en `app/storage.py`.

### Error 502 Bad Gateway (Apache)
*   **Síntoma**: Al acceder a `cdn.meximova.com`, Apache devuelve 502.
*   **Causa**: Apache no puede conectar con MinIO en `127.0.0.1:9003`.
*   **Solución**: Verifica que el contenedor de MinIO esté corriendo (`docker ps`) y que el puerto `9003` esté correctamente mapeado.

---

## 5. Mantenimiento

*   **Rotación de Claves**: Si cambias `MINIO_ACCESS_KEY` o `SECRET` en MinIO, debes actualizarlas en el `.env` del `media-service` y reiniciar el contenedor. Apache no necesita cambios.
*   **Cambio de Dominio**: Si cambias a `archivos.meximova.com`:
    1.  Actualiza `ServerName` en Apache.
    2.  Actualiza `CDN_HOST` en `.env`.
    3.  Reinicia Apache y `media-service`.
