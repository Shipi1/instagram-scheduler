# Descargar un Reel en el servidor

Copia `scripts/download_reel.py` y `scripts/prepare_video.py` juntos al servidor. Se recomienda Python 3.11 o posterior. Requiere yt-dlp y FFmpeg/ffprobe. No utiliza `.env` ni el token de Meta. Para descargar sin preparar, usa `--download-only` (en ese caso basta el primer script y yt-dlp).

## Preparación en Linux

Desde la carpeta donde hayas copiado el script:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U yt-dlp
sudo apt update
sudo apt install ffmpeg
python download_reel.py "https://www.instagram.com/reel/CODIGO/"
```

Si Linux indica que falta `venv`, instala el paquete correspondiente de tu distribución (por ejemplo, `python3-venv` en Debian/Ubuntu).

Por defecto, guarda los archivos en `~/ig-scheduler-files`, dentro del directorio personal del usuario que ejecuta el script. La carpeta se crea si no existe.

Para elegir otro destino:

```bash
python download_reel.py "https://www.instagram.com/reel/CODIGO/" --output-dir /srv/ig-scheduler/downloads
```

La carpeta se crea si no existe; el usuario que ejecuta el script necesita permiso para escribir. El nombre será `instagram_ID.mp4`. Los archivos completos existentes no se sobrescriben y las descargas parciales pueden reanudarse. Una descarga existente se reutiliza, sin comprobar si cambió el contenido remoto.

En Windows, desde la raíz del proyecto:

```powershell
py -3 -m pip install -U yt-dlp
py -3 .\scripts\download_reel.py "https://www.instagram.com/reel/CODIGO/" --output-dir .\tmp\downloads
```

## Cookies opcionales

Prueba primero sin cookies. Si Instagram exige una sesión, puedes usar un archivo de cookies en formato Mozilla/Netscape de una sesión autorizada:

```bash
python download_reel.py "https://www.instagram.com/reel/CODIGO/" --cookies /ruta/privada/instagram-cookies.txt
```

Las cookies son credenciales: guárdalas fuera de la carpeta pública HTTPS, no las subas al repositorio y restringe sus permisos. El token de publicación de Meta no sirve como sustituto. Tener cookies tampoco garantiza acceso ante límites o bloqueos de Instagram.

## Alcance y prueba pendiente

La descarga selecciona un único MP4, aceptando códecs desconocidos en los metadatos. Después ejecuta automáticamente `prepare_video.py`: revisa con ffprobe y genera `instagram_ID_ready.mp4` en la misma carpeta, conservando el original. Esta versión siempre recodifica para normalizar H.264/yuv420p, 30 fps, GOP cerrado de 2 segundos, AAC estéreo a 48 kHz/128 kbps cuando hay audio y MP4 con faststart. No inventa audio para videos silenciosos.

Mantiene la orientación y proporción (con el redondeo necesario a dimensiones pares), sin recortar ni añadir bandas. Limita el ancho a 1920 píxeles. Rechaza duración fuera de 3–900 segundos y salidas mayores de 300 MB, sin recortar automáticamente. Ajusta el límite de bitrate según la duración, con un máximo de 8 Mbps. Comprueba la salida con ffprobe y una decodificación completa antes de reemplazar el archivo `_ready.mp4`; si falla, no entrega una salida nueva incompleta. Repetir la preparación reemplaza el `_ready.mp4` anterior solo al completarse correctamente. No hay bloqueo para ejecuciones simultáneas sobre el mismo archivo.

La recodificación consume CPU y puede perder algo de calidad; se ha preferido un perfil uniforme a una optimización de copia sin recodificar. No garantiza aceptación por Meta: permisos, límites y procesamiento remoto se comprueban al publicar. Referencia: [especificaciones oficiales de Reels de Meta](https://www.postman.com/meta/instagram/folder/830j7my/reels-publishing).

Para preparar el archivo que ya descargaste sin volver a consultar Instagram:

```bash
python prepare_video.py ~/ig-scheduler-files/instagram_Deu5s_9tTgd.mp4
```

Prueba local: video sintético horizontal de 4 segundos convertido desde MPEG-4 a H.264/AAC y decodificado sin errores. Falta ejecutar esta preparación en el servidor con el Reel real.

En la prueba del usuario, yt-dlp descargó `Deu5s_9tTgd` desde el servidor sin cookies (2,79 MiB). El filtro original del script rechazó el formato; se corrigió para admitir metadatos de códecs desconocidos. Falta repetir la descarga con el script corregido. El aviso de Python 3.10 es una deprecación, no la causa de ese fallo; se recomienda migrar el entorno a Python 3.11 o posterior.

Admite enlaces directos `/reel/CODIGO/`, `/reels/CODIGO/` y `/p/CODIGO/` (publicaciones que contengan un único video). No admite perfiles, colecciones o enlaces compartidos que necesiten resolver una redirección. Una publicación de fotos o un carrusel no corresponde a un único Reel. Usa contenido propio o autorizado.

El script muestra la ruta final y termina con código 0 si encuentra el archivo descargado; los errores terminan con un código distinto de 0. No aloja el archivo por HTTPS, no publica y no borra archivos.

Se comprobaron sintaxis, ayuda y validación de enlaces localmente. Falta probar una descarga real con el enlace elegido desde el servidor; los resultados pueden variar según su IP y las restricciones de Instagram.

Referencia: [documentación oficial de yt-dlp](https://github.com/yt-dlp/yt-dlp) y [uso de cookies](https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp).
