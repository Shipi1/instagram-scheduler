# Estado validado y operación local de Instagram Reposter

**Actualizado:** 2026-11-04. Este documento y los scripts reales prevalecen sobre los ejemplos de diseño de las guías 01 y 02.

## 1. Resultado real

La autenticación y publicación de un Reel mediante la API oficial de Meta **funcionaron** desde Windows/PowerShell con Python 3.14. El servidor HTTPS ya está disponible.

| Dato | Resultado comprobado |
|---|---|
| Cuenta | `@tula.posting` |
| IG_USER_ID | `17841408002274944` |
| Configuración de la app | API de Instagram con inicio de sesión unificado |
| Host utilizado | `https://graph.facebook.com` |
| MP4 | `https://api.shipisnature.com/ig-scheduler/file/reeltest.mp4` |
| Descarga completa comprobada | HTTP 200, `video/mp4`, 13.413.721 bytes |
| Contenedor | `18355296577266743` |
| Procesamiento | `IN_PROGRESS` → `FINISHED` |
| Media ID | `17922389886451078` |
| Reel publicado | https://www.instagram.com/reel/DfViqEmE20P/ |

Esto demuestra lectura básica y autorización efectiva para publicar con ese token en esa cuenta. No se ha consultado la lista exacta de permisos, cuotas ni expiración restante. No se ha confirmado la clasificación específica Business/Creator. La URL temporal puede retirarse después de publicar; no es una dependencia permanente del Reel.

## 2. Cómo funciona la autenticación por token

En Meta for Developers se creó una app con el caso de uso «Administrar mensajes y contenidos en Instagram». La consola mostró **inicio de sesión unificado**. Se agregó la cuenta de Instagram y se generó el token en «Generar tokens de acceso».

Los scripts no reciben contraseñas ni abren una sesión web. Usan el token ya emitido en cada petición:

```http
Authorization: Bearer TOKEN
```

Guardar el token únicamente en `.env` o introducirlo mediante entrada oculta. No publicarlo en Git, URLs, capturas o logs. El ID de cuenta y el identificador de configuración de login no son tokens.

La primera prueba asumía Instagram Login sobre `graph.instagram.com` y devolvió HTTP 401 / OAuthException 190: `Cannot parse access token`. Consultar directamente la cuenta en `graph.facebook.com` con el flujo unificado sí funcionó. Por tanto, el error inicial no demostraba que el token estuviera vencido.

**Para esta app usar el flujo comprobado sobre `graph.facebook.com`.** No mezclar las instrucciones y permisos `instagram_business_*` de Instagram Login con el flujo unificado. No se archivó la lista exacta de permisos; la publicación exitosa verifica la capacidad requerida para esta prueba.

## 3. Scripts y configuración local

Implementados: `scripts/check_auth.py`, `scripts/publish_test.py`, `.env.example` y exclusiones de Git. Ambos scripts usan la biblioteca estándar: **no necesitan requests ni python-dotenv**. El destino futuro de la integración sigue siendo Linux/Python 3.12+.

Ejemplo de `.env`, sin valores secretos reales:

```dotenv
IG_ACCESS_TOKEN=REEMPLAZAR
IG_USER_ID=17841408002274944
IG_EXPECTED_USERNAME=tula.posting
GRAPH_API_VERSION=
PUBLIC_MEDIA_URL=https://api.shipisnature.com/ig-scheduler/file/reeltest.mp4
```

El archivo se carga desde la raíz del proyecto. Variables existentes en el entorno tienen prioridad. El lector admite asignaciones simples, sin expansión ni comentarios al final de valores. `--prompt-token` ignora el token guardado y pide uno con entrada oculta.

La prueba exitosa usó el endpoint **sin versión explícita**. `GRAPH_API_VERSION` admite una versión soportada con formato `vNN.N`; fijar y validar una antes del despliegue estable. No se ha comprobado una versión numérica específica.

Autenticación, desde PowerShell en la raíz:

```powershell
py -3 .\scripts\check_auth.py --login unified --account-id 17841408002274944 --prompt-token
```

La petición es `GET https://graph.facebook.com/17841408002274944?fields=id,username`. El script debe mostrar `@tula.posting`. Introducir solamente el token, sin `Bearer` ni comillas.

**Atención:** `check_auth.py` aún tiene `instagram` como opción predeterminada. Indicar `--login unified` para esta cuenta. El publisher ya usa el host de Facebook directamente.

## 4. Publicación y descripción del Reel

El archivo debe ser un MP4 propio o autorizado, descargable directamente por HTTPS sin login ni cookies. Perfil inicial conservador: video corto vertical H.264 y audio AAC. Meta obtiene el video desde sus servidores; localhost y rutas locales no sirven.

Crear un contenedor y esperar su procesamiento **sin publicar**:

```powershell
py -3 .\scripts\publish_test.py --account-id 17841408002274944 --video-url "https://TU_DOMINIO/video.mp4" --caption "Mi descripción" --state .\tmp\video-nuevo.json --prompt-token
```

Publicarlo: repetir ese comando con **`--publish`** y el mismo `--state`. También puede incluirse `--publish` desde la primera ejecución para completar todo el flujo.

La descripción se envía como **`caption` al crear el contenedor**. Por ejemplo:

```powershell
py -3 .\scripts\publish_test.py --account-id 17841408002274944 --video-url "https://TU_DOMINIO/otro.mp4" --caption "Un momento para recordar ✨ #reels #naturaleza" --state .\tmp\otro.json --publish --prompt-token
```

Para varias líneas, preparar una variable PowerShell y pasarla a `--caption`:

```powershell
$descripcionReel = "Primera línea`n`nSegunda línea #reels"
# Usar en el comando: --caption $descripcionReel
```

Sin `--caption`, la descripción predeterminada es **«Prueba técnica de publicación»**, usada en la publicación comprobada. Los ejemplos personalizados y multilínea no se han publicado como ensayos adicionales. Cambiar `--caption` al reanudar **no modifica el contenedor existente**. `REEL_CAPTION` y `REEL_CAPTION_PREFIX` de los diseños antiguos no se leen en el script actual.

Secuencia real, sobre `https://graph.facebook.com` y Bearer token:

```http
GET  /{ig_user_id}?fields=id,username
POST /{ig_user_id}/media
     media_type=REELS&video_url={https_url}&caption={descripcion}&share_to_feed=false
GET  /{container_id}?fields=status_code,status
POST /{ig_user_id}/media_publish
     creation_id={container_id}
GET  /{media_id}?fields=id,permalink
```

Los POST usan formulario codificado. El script consulta cada 30 segundos por hasta 15 minutos y publica solo en `FINISHED`. `share_to_feed=false` no convierte el Reel en privado.

## 5. Estado, duplicados y limpieza

`tmp/publish-test.json` contiene el resultado de la publicación ya realizada y está excluido de Git. **No eliminarlo para repetir el mismo Reel.**

- Si existe `media_id`, el script consulta el enlace y no vuelve a publicar.
- Si existe un contenedor en procesamiento, lo reutiliza.
- Si quedó en `CREATING` o `PUBLISHING`, detiene la ejecución: una petición pudo completarse sin guardar respuesta. Reconciliar con Instagram antes de reintentar; no borrar el estado para forzar otro POST.
- Para una prueba nueva usar otro `--state`. La deduplicación es por archivo, no global; rutas distintas pueden generar publicaciones duplicadas.
- Ejecutar una sola instancia por estado: aún no hay bloqueo entre procesos.
- Después de confirmar publicación, retirar manualmente el MP4 del servidor. Aún no se implementó transferencia/borrado remoto ni se comprobó la limpieza de este archivo.

## 6. yt-dlp, cookies y «YouTube Upload»

yt-dlp descarga el Reel mediante su extractor de Instagram; **no utiliza el token de Meta**. El token se usa para la publicación posterior.

El operador informa que **hasta ahora no se le han solicitado cookies**. No se configuran como requisito inicial. Esto no garantiza descargas anónimas para todos los Reels ni el mismo comportamiento desde el servidor Linux.

```powershell
py -3 -m pip install -U yt-dlp
py -3 -m yt_dlp --no-playlist -P .\tmp "https://www.instagram.com/reel/CODIGO/"
```

Si posteriormente Instagram exige una sesión, evaluar cookies de un navegador con sesión autorizada, por ejemplo `--cookies-from-browser firefox`. No exportarlas mientras no sean necesarias; son credenciales de sesión y no deben versionarse. La extracción puede fallar por cambios del sitio, restricciones o límites de red.

**«YouTube Upload» queda como término por aclarar:** por contexto se interpreta provisionalmente como yt-dlp / su clase Python `YoutubeDL`. Esa clase también descarga Instagram; su nombre no significa subir a YouTube. No se ha implementado ni probado publicación en YouTube. Si se pretende añadirla, requiere definir un flujo independiente.

## 7. Pendiente para retomar después de compactar

1. Probar `scripts/download_reel.py` desde el servidor con un Reel y verificar el MP4 descargado. El script independiente y sus instrucciones están en [04_DESCARGAR_REEL_EN_SERVIDOR.md](04_DESCARGAR_REEL_EN_SERVIDOR.md); todavía no se ha validado una descarga real con él.
2. Definir la transferencia al alojamiento HTTPS y el borrado remoto.
3. Conectar descarga → FFmpeg cuando haga falta → HTTPS → publisher validado.
4. Implementar Telegram, SQLite, reconciliación y limpieza automática.
5. Fijar versión Graph y comprobar permisos, cuotas y renovación del token.

La publicación aislada ya está demostrada; el flujo integrado de la guía 02 sigue siendo diseño, no una implementación completa.

## Fuentes y evidencia

- Evidencia primaria local: salida de los scripts y `tmp/publish-test.json`; no contiene el token.
- [Meta — colección oficial de Instagram API](https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api)
- [yt-dlp — documentación](https://github.com/yt-dlp/yt-dlp)
- [yt-dlp — extractor de Instagram](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/instagram.py)
