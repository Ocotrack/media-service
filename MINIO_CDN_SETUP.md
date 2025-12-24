# Configuración de Almacenamiento MinIO con Apache2 y CDN

Este documento detalla la arquitectura y configuración específica para el proyecto `media-service`, utilizando MinIO como almacenamiento y **Apache2** como Reverse Proxy/CDN para la entrega de contenido público mediante URLs firmadas.

## 1. Arquitectura del Proyecto (Infraestructura de 2 Servidores)

### Servidor 1: Edge Server (Entrada a Internet)
*   **Función**: Reverse Proxy con terminación SSL
*   **Software**: Apache2 con Let's Encrypt
*   **Dominio Público**: `cdn.meximova.com`
*   **Puertos Expuestos**:
    *   Puerto 80 (HTTP) → Redirige a 443
    *   Puerto 443 (HTTPS) → Termina SSL y hace proxy
*   **Conexión Backend**: Proxy hacia `http://192.168.1.126:9003`

### Servidor 2: Storage Server (Red Interna - 192.168.1.126)
*   **Función**: Almacenamiento de objetos y API de media
*   **Software**: Docker con MinIO y Media Service
*   **Puertos**:
    *   `9003`: MinIO API (S3-compatible)
    *   `9004`: MinIO Web Console
    *   `8002`: Media Service API
*   **Contenedores Docker**:
    *   `minio`: Almacenamiento de objetos
    *   `media-service`: API para gestionar uploads y generar URLs firmadas

### Flujo de Datos

```
Usuario (Internet)
    ↓ HTTPS (443)
[Servidor 1] Apache2 (Termina SSL)
    ↓ HTTP (Red Interna)
http://192.168.1.126:9003
    ↓
[Servidor 2] Docker → MinIO Container
```

**Importante:**
- **Media Service** sube archivos directamente a MinIO usando la red interna de Docker (`minio:9003`)
- **Media Service** firma URLs usando el dominio público (`https://cdn.meximova.com`)
- Los usuarios acceden a archivos a través del Servidor 1 que hace proxy a MinIO

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

### Habilitar módulos necesarios en Apache (Servidor 1)

**IMPORTANTE**: Debes ejecutar estos comandos en el Servidor 1 (Edge), no en el Servidor 2 donde corre Docker.

```bash
# Habilitar módulos de proxy y SSL
sudo a2enmod ssl
sudo a2enmod proxy
sudo a2enmod proxy_http
sudo a2enmod headers
sudo a2enmod rewrite

# Verificar que estén habilitados
sudo apache2ctl -M | grep -E '(proxy|ssl|headers|rewrite)'

# Reiniciar Apache
sudo systemctl restart apache2
```

### Archivo de VirtualHost (`/etc/apache2/sites-available/cdn.meximova.com.conf`)

Esta configuración debe estar en el **Servidor 1 (Edge Server)** que tiene acceso directo a Internet.

```apache
# ========================================================================
# Puerto 80 - Redirigir todo HTTP a HTTPS
# ========================================================================
<VirtualHost *:80>
    ServerName cdn.meximova.com
    ServerAdmin admin@meximova.com

    # Logs
    ErrorLog ${APACHE_LOG_DIR}/cdn_minio_http_error.log
    CustomLog ${APACHE_LOG_DIR}/cdn_minio_http_access.log combined

    # Redirigir todo el tráfico a HTTPS
    RewriteEngine On
    RewriteCond %{HTTPS} off
    RewriteRule ^(.*)$ https://%{HTTP_HOST}$1 [R=301,L]
</VirtualHost>

# ========================================================================
# Puerto 443 - Configuración HTTPS con SSL
# ========================================================================
<VirtualHost *:443>
    ServerName cdn.meximova.com
    ServerAdmin admin@meximova.com

    # Logs
    ErrorLog ${APACHE_LOG_DIR}/cdn_minio_ssl_error.log
    CustomLog ${APACHE_LOG_DIR}/cdn_minio_ssl_access.log combined

    # ====================================================================
    # Configuración SSL (Let's Encrypt)
    # ====================================================================
    SSLEngine on
    SSLCertificateFile /etc/letsencrypt/live/cdn.meximova.com/fullchain.pem
    SSLCertificateKeyFile /etc/letsencrypt/live/cdn.meximova.com/privkey.pem
    
    # Protocolos y cifrados seguros (recomendado)
    SSLProtocol all -SSLv3 -TLSv1 -TLSv1.1
    SSLCipherSuite HIGH:!aNULL:!MD5
    SSLHonorCipherOrder on
    
    # Security Headers
    Header always set Strict-Transport-Security "max-age=31536000; includeSubDomains"
    Header always set X-Content-Type-Options "nosniff"
    Header always set X-Frame-Options "SAMEORIGIN"

    # ====================================================================
    # Configuración Crítica para MinIO y URLs Firmadas
    # ====================================================================
    
    # 1. Preservar el Host original
    # Esto es OBLIGATORIO. Si Apache cambia el host a 'localhost' o IP,
    # la firma de AWS S3 fallará (SignatureDoesNotMatch).
    ProxyPreserveHost On

    # 2. No decodificar URLs
    # Evita que Apache modifique caracteres especiales en la firma
    AllowEncodedSlashes NoDecode

    # 3. Configuración del Proxy hacia Servidor 2 (MinIO)
    # IP del Servidor 2 (Storage): 192.168.1.126
    # Puerto API de MinIO: 9003
    ProxyPass / http://192.168.1.126:9003/ nocanon
    ProxyPassReverse / http://192.168.1.126:9003/

    # 4. Headers para que MinIO sepa que la conexión original es HTTPS
    RequestHeader set X-Forwarded-Proto "https"
    RequestHeader set X-Forwarded-Port "443"
    RequestHeader set X-Forwarded-For "%{REMOTE_ADDR}s"

    # 5. Ajustes de Headers de seguridad
    # Ocultar headers internos de MinIO
    Header unset Server
    Header unset X-Minio-Deployment-Id
    Header unset X-Amz-Request-Id

    # 6. Configuración para archivos grandes
    # Timeout largo para uploads/downloads grandes
    ProxyTimeout 300
    
    # Desactivar buffering para streaming directo
    SetEnv proxy-sendchunked 1
</VirtualHost>
```

### Habilitar el sitio y verificar configuración

```bash
# Habilitar el sitio
sudo a2ensite cdn.meximova.com.conf

# Deshabilitar el sitio default si existe
sudo a2dissite 000-default.conf

# Verificar sintaxis de configuración
sudo apache2ctl configtest

# Si todo está OK (Syntax OK), recargar Apache
sudo systemctl reload apache2

# Verificar que Apache esté corriendo
sudo systemctl status apache2
```

### Verificar certificados SSL de Let's Encrypt

```bash
# Ver certificados instalados
sudo certbot certificates

# Si necesitas crear/renovar el certificado para cdn.meximova.com
sudo certbot --apache -d cdn.meximova.com

# Verificar renovación automática
sudo certbot renew --dry-run
```

---

## 3. Configuración de MinIO (CRÍTICO para acceso público)

**IMPORTANTE**: Aunque tu aplicación funcione correctamente, MinIO puede bloquear el acceso a través del proxy si no está configurado correctamente.

### Problema: MinIO rechaza peticiones del proxy

MinIO **por defecto** valida varias cosas que pueden causar errores cuando se accede a través de Apache:

1. **Host Validation**: MinIO espera que el header `Host` coincida exactamente con su configuración
2. **Bucket Access Policy**: Los buckets NO son públicos por defecto
3. **Path Style vs Virtual Host Style**: MinIO puede estar esperando un estilo de URL específico
4. **Region Validation**: MinIO valida que la región en la firma coincida

### Solución: Configurar bucket con política anónima (read-only)

Para que los archivos sean accesibles públicamente a través del CDN, necesitas configurar la política del bucket:

#### Opción 1: Usar MinIO Client (mc) - Recomendado

```bash
# En el Servidor 2, ejecutar en el contenedor de MinIO o con mc instalado

# 1. Configurar alias de MinIO
docker exec -it minio mc alias set localminio http://localhost:9003 admin Casamago1.

# 2. Verificar que el bucket existe
docker exec -it minio mc ls localminio/media

# 3. Configurar política de acceso PÚBLICO (solo lectura) para el bucket
docker exec -it minio mc anonymous set download localminio/media

# 4. Verificar la política aplicada
docker exec -it minio mc anonymous get localminio/media
```

**Respuesta esperada**: `Access permission for 'localminio/media' is 'download'`

#### Opción 2: Usar la Consola Web de MinIO

1. Accede a la consola web: `http://192.168.1.126:9004`
2. Login con: `admin` / `Casamago1.`
3. Ve a **Buckets** → `media`
4. Click en **Manage** → **Access Rules**
5. Agregar regla:
   - **Prefix**: `*` (para todos los archivos)
   - **Access**: `readonly` o `download`
6. Guardar

#### Opción 3: Política JSON personalizada (Más control)

Si necesitas más control, puedes aplicar una política JSON:

```bash
# Crear archivo de política
cat > /tmp/bucket-policy.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {"AWS": ["*"]},
      "Action": ["s3:GetObject"],
      "Resource": ["arn:aws:s3:::media/*"]
    }
  ]
}
EOF

# Aplicar política
docker exec -i minio mc admin policy create localminio media-public /tmp/bucket-policy.json
docker exec -it minio mc anonymous set-json /tmp/bucket-policy.json localminio/media
```

### Configuración adicional de MinIO (Opcional pero recomendado)

#### Desactivar validación estricta de dominio (si hay problemas)

Si MinIO rechaza peticiones del proxy por validación de dominio, puedes desactivar la validación estricta:

```bash
# En el docker-compose.yml, añadir variables de entorno al servicio minio
services:
  minio:
    environment:
      # ... otras variables existentes
      MINIO_DOMAIN: cdn.meximova.com  # Dominio público del CDN
```

**IMPORTANTE**: Con esto, MinIO aceptará peticiones con `Host: cdn.meximova.com` además de `Host: 192.168.1.126:9003`.

### Verificación de acceso público

Una vez configurada la política del bucket, verifica que funcione:

```bash
# Desde el Servidor 1, probar acceso directo a MinIO
# (Asumiendo que ya tienes un archivo subido, por ejemplo: client1/test/uuid.webp)
curl -I http://192.168.1.126:9003/media/client1/test/uuid.webp

# Debe devolver 200 OK, NO 403 Forbidden
```

Si recibes `403 Forbidden`, significa que la política del bucket NO está configurada correctamente.

### Configuración en docker-compose.yml (Servidor 2)

Actualiza tu `docker-compose.yml` para incluir el dominio del CDN:

```yaml
services:
  minio:
    image: minio/minio:latest
    container_name: minio
    environment:
      MINIO_ROOT_USER: ${MINIO_ACCESS_KEY}
      MINIO_ROOT_PASSWORD: ${MINIO_SECRET_KEY}
      MINIO_DOMAIN: cdn.meximova.com  # ← AÑADIR ESTA LÍNEA
    command: server /data --address ":9003" --console-address ":9004"
    volumes:
      - minio_data:/data
    ports:
      - "9003:9003"
      - "9004:9004"
    restart: unless-stopped
```

Después de modificar `docker-compose.yml`:
```bash
docker-compose up -d --force-recreate minio
```



Asegúrate de que las variables de entorno en `.env` coincidan con esta arquitectura.

### Archivo `.env` (Servidor 2 - donde corre Docker)

**IMPORTANTE**: Este archivo debe estar en el Servidor 2 (192.168.1.126) donde corre el `media-service` y MinIO.

```bash
# --- MinIO Credenciales ---
MINIO_ACCESS_KEY=admin
MINIO_SECRET_KEY=Casamago1.
MINIO_BUCKET=media
MINIO_REGION=us-east-1

# --- Configuración Interna (Docker a Docker) ---
# Usado por la app para subir/borrar archivos y validar buckets
# Esto es comunicación INTERNA dentro de Docker, NO usa SSL
MINIO_ENDPOINT_INTERNAL=minio:9003
MINIO_USE_SSL=false

# --- Configuración Pública (Para generar URLs firmadas) ---
# Usado EXCLUSIVAMENTE para generar la firma de la URL
# Debe coincidir EXACTAMENTE con el dominio público del Servidor 1
# IMPORTANTE: NO incluir puerto porque 443 (HTTPS) es el default
MINIO_ENDPOINT_PUBLIC=cdn.meximova.com
MINIO_PUBLIC_USE_SSL=true

# --- Configuración Media Service ---
MEDIA_URL_TTL_SECONDS=3600
API_KEYS=tu_api_key_aqui
PORT=8002
ENV=production
```

### Explicación de la configuración de red:

| Variable | Valor | Propósito |
|----------|-------|----------|
| `MINIO_ENDPOINT_INTERNAL` | `minio:9003` | Comunicación interna Docker. La app sube archivos directamente a MinIO |
| `MINIO_USE_SSL` | `false` | Conexión interna NO usa SSL |
| `MINIO_ENDPOINT_PUBLIC` | `cdn.meximova.com` | Dominio público para firmar URLs (sin puerto) |
| `MINIO_PUBLIC_USE_SSL` | `true` | Las URLs públicas SÍ usan HTTPS |

**Flujo completo:**
1. **Upload**: `media-service` → `minio:9003` (HTTP interno)
2. **Generar URL**: Firma con `https://cdn.meximova.com` (HTTPS público)
3. **Usuario descarga**: `https://cdn.meximova.com` → Servidor 1 Apache → `http://192.168.1.126:9003` → MinIO

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
*   **Síntoma**: La URL se genera correctamente, pero al abrirla en el navegador devuelve XML con error `SignatureDoesNotMatch`.
*   **Causas posibles**:
    1. Apache no está preservando el header `Host` original
    2. La variable `MINIO_ENDPOINT_PUBLIC` no coincide con el dominio público
    3. Hay un mismatch entre HTTP/HTTPS en la firma
*   **Soluciones**:
    1. Verifica que `ProxyPreserveHost On` esté en la config de Apache
    2. Verifica que `MINIO_ENDPOINT_PUBLIC=cdn.meximova.com` (sin puerto, sin `https://`)
    3. Verifica que `MINIO_PUBLIC_USE_SSL=true`
    4. En Servidor 1, verifica logs: `sudo tail -f /var/log/apache2/cdn_minio_ssl_error.log`

### Error `Connection refused` o `Timeout`
*   **Síntoma**: La app falla al intentar generar URLs o subir archivos.
*   **Causas posibles**:
    1. El contenedor MinIO no está corriendo
    2. El puerto 9003 no está expuesto en el Servidor 2
    3. Firewall bloqueando comunicación entre Servidor 1 y Servidor 2
*   **Soluciones**:
    1. En Servidor 2: `docker ps | grep minio` (debe estar corriendo)
    2. En Servidor 2: `netstat -tuln | grep 9003` (debe estar escuchando)
    3. En Servidor 1: `curl http://192.168.1.126:9003` (debe responder)
    4. Verificar firewall: `sudo ufw status` o `sudo iptables -L`

### Error 502 Bad Gateway (Apache)
*   **Síntoma**: Al acceder a `https://cdn.meximova.com`, Apache devuelve 502.
*   **Causas posibles**:
    1. Apache (Servidor 1) no puede conectar con MinIO (Servidor 2)
    2. MinIO no está corriendo en el Servidor 2
    3. La IP o puerto en la config de Apache es incorrecta
*   **Soluciones**:
    1. Desde Servidor 1: `curl -I http://192.168.1.126:9003/minio/health/live`
    2. Verificar configuración: `ProxyPass / http://192.168.1.126:9003/`
    3. Ver logs de Apache: `sudo tail -f /var/log/apache2/cdn_minio_ssl_error.log`
    4. En Servidor 2: `docker logs minio -f`

### Error SSL: Certificate Invalid
*   **Síntoma**: El navegador muestra advertencia de certificado inválido.
*   **Causas posibles**:
    1. Let's Encrypt no está configurado correctamente
    2. El certificado expiró
    3. El dominio no apunta al Servidor 1
*   **Soluciones**:
    1. Verificar certificados: `sudo certbot certificates`
    2. Renovar certificado: `sudo certbot renew`
    3. Verificar DNS: `dig cdn.meximova.com` o `nslookup cdn.meximova.com`
    4. Verificar sintaxis SSL en Apache: `sudo apache2ctl -S`

### URLs generadas con HTTP en lugar de HTTPS
*   **Síntoma**: Las URLs firmadas empiezan con `http://` en lugar de `https://`.
*   **Causa**: Variable `MINIO_PUBLIC_USE_SSL=false` o no está definida.
*   **Solución**: En el `.env` del Servidor 2, asegúrate de tener `MINIO_PUBLIC_USE_SSL=true`

### Comandos útiles para debugging

```bash
# En Servidor 1 (Edge - Apache)
sudo tail -f /var/log/apache2/cdn_minio_ssl_error.log
sudo apache2ctl -S  # Ver configuración de VirtualHosts
sudo apache2ctl -M  # Ver módulos habilitados
curl -I https://cdn.meximova.com  # Probar conexión HTTPS

# En Servidor 2 (Storage - Docker)
docker ps  # Ver contenedores corriendo
docker logs minio -f  # Ver logs de MinIO en tiempo real
docker logs media-service -f  # Ver logs del servicio
netstat -tuln | grep -E '(9003|9004)'  # Verificar puertos
curl http://localhost:9003/minio/health/live  # Healthcheck MinIO

# Probar desde Servidor 1 hacia Servidor 2
curl -v http://192.168.1.126:9003/minio/health/live
```

---

## 5. Mantenimiento

### Rotación de Claves
Si cambias `MINIO_ACCESS_KEY` o `MINIO_SECRET_KEY`:
1. Actualizar variables en el `.env` del Servidor 2
2. Reiniciar contenedores: `docker-compose restart`
3. Apache no necesita cambios

### Renovación de certificados SSL
Let's Encrypt renueva automáticamente, pero puedes forzar:
```bash
sudo certbot renew --force-renewal
sudo systemctl reload apache2
```

### Cambio de Dominio
Si cambias de `cdn.meximova.com` a otro dominio:
1. En Servidor 1:
   - Actualiza `ServerName` en `/etc/apache2/sites-available/cdn.meximova.com.conf`
   - Obtén nuevo certificado: `sudo certbot --apache -d nuevo-dominio.com`
   - Recarga Apache: `sudo systemctl reload apache2`
2. En Servidor 2:
   - Actualiza `MINIO_ENDPOINT_PUBLIC` en `.env`
   - Reinicia: `docker-compose restart media-service`

### Backup de configuración
```bash
# Servidor 1: Backup de Apache
sudo cp /etc/apache2/sites-available/cdn.meximova.com.conf /root/backups/

# Servidor 2: Backup de variables y datos
cp .env .env.backup
docker exec minio mc admin config export minio > /root/backups/minio-config.json
```
