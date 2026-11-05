# Orquestador: despliegue y operación con Docker

## Estado de esta entrega

El punto de entrada `run_bot.py` conecta recepción de Telegram, lista de usuarios, SQLite, descarga, FFmpeg, carpeta HTTPS y publicación con Meta. Un receptor y un trabajador corren de forma independiente dentro del mismo contenedor. No expone puertos ni necesita webhooks: utiliza conexiones salientes HTTPS.

Se probaron localmente doce casos automatizados: flujo con APIs simuladas, descripciones, autorización, configuración, duplicados, offset persistente, recuperación, timeout de publicación, errores de notificación y conversión real con FFmpeg. Se verificó la sintaxis YAML de Compose, pero no se ha construido esta imagen Docker en el entorno de desarrollo porque Docker no está instalado. Falta la prueba integrada en el servidor con Telegram, Caddy y Meta reales. No se ha publicado contenido durante estas pruebas.

## 1. Copiar el proyecto

Copia el proyecto completo al servidor, no solo `run_bot.py`. Deben estar `app/`, `scripts/`, `config/telegram_users.example.json`, `requirements.txt`, `Dockerfile`, `compose.yaml` y `.dockerignore`. Los scripts descargador/preparador existentes también son necesarios.

Comprueba Docker Engine y el complemento Compose:

```bash
docker --version
docker compose version
cd ~/instagram-scheduler
```

Detén el receptor `telegram_receive.py` anterior con Ctrl+C. Solo un proceso debe consultar actualizaciones del mismo bot. No es necesario modificar ni reiniciar Caddy para arrancar el bot si su montaje ya es correcto.

## 2. Directorios y permisos

Ejecuta como el usuario normal que usas en el servidor:

```bash
mkdir -p data config ~/ig-scheduler-files
cp config/telegram_users.example.json config/telegram_users.json
nano config/telegram_users.json
```

Añade tus IDs numéricos y los de los otros usuarios. Si ya tenías una lista en `scripts/telegram_users.json`, puedes copiar esa lista a `config/telegram_users.json` en vez de crear una vacía. No sobrescribas una lista configurada con el ejemplo.

Comprueba los IDs del usuario del host:

```bash
id -u
id -g
```

El contenedor usa UID/GID 1000 por defecto. Si tus números son diferentes, añade `LOCAL_UID` y `LOCAL_GID` con esos valores a `.env`. Las carpetas `data/` y `~/ig-scheduler-files` deben permitir escritura a ese usuario; `config/` requiere lectura. Caddy necesita leer los MP4 finales (se crean con permisos 644). Evita crear estas carpetas con root; si ya pertenecen a otro usuario, corrige únicamente los directorios específicos después de comprobar sus rutas.

## 3. Configurar `.env`

Si no existe, copia `.env.example` como `.env`. Si ya tienes `.env` con tu token válido, edítalo y añade las claves faltantes sin reemplazar tus credenciales.

```bash
nano .env
chmod 600 .env
```

Configuración mínima:

```dotenv
TELEGRAM_BOT_TOKEN=TOKEN_DE_BOTFATHER
IG_ACCESS_TOKEN=TOKEN_VALIDO_DE_META
IG_USER_ID=17841408002274944
IG_EXPECTED_USERNAME=tula.posting
# Opcional: versión con formato vNN.N; puede quedar vacía.
GRAPH_API_VERSION=
DEFAULT_REEL_CAPTION="Mi descripción predeterminada #reels"
PUBLIC_MEDIA_BASE_URL=https://api.shipisnature.com/ig-scheduler/file
HOST_MEDIA_DIR=/home/ubuntu/ig-scheduler-files
PUBLISH_ENABLED=false
```

Sustituye tokens, cuenta y dominio si recreas el proyecto para otra persona. `GRAPH_API_VERSION` es opcional: vacía o ausente usa `https://graph.facebook.com`, igual que la prueba que funcionó. Si se indica, debe tener formato `vNN.N` y usarse una versión soportada y comprobada con `check_auth.py --login unified`. Fijarla es una recomendación para despliegues estables, no un requisito de arranque. Los trabajos guardan su versión; cambiarla con trabajos pendientes requiere revisar esos trabajos.

`DEFAULT_REEL_CAPTION` se usa solo si no hay descripción después del enlace. Puede ser vacía. Se guarda en SQLite al recibir el mensaje, por lo que cambiarla no altera trabajos existentes. Usa una sola línea en `.env`; los saltos escritos como `\n` no son una función de plantillas del bot. Para descripciones multilínea, envía el texto en Telegram.

`PUBLISH_ENABLED=false` descarga, convierte y verifica el HTTPS, pero no crea contenedores ni publica. El estado final es `PREPARED` y conserva archivos. `true` habilita la publicación automática de nuevos trabajos y de los reencolados explícitamente. No se convierte automáticamente un `PREPARED` al cambiar la variable.

Compose carga `.env` mediante `env_file`. Además fija rutas internas: SQLite y trabajo en `/data`, lista en `/config/telegram_users.json` y archivos públicos en `/media`. `HOST_MEDIA_DIR` es una ruta absoluta del host; no uses `~` en esa variable. El script de prueba `PUBLIC_MEDIA_URL` no se usa en el orquestador: cada trabajo genera su propia URL.

Los secretos no se copian a la imagen. Son visibles para administradores con acceso a Docker; no compartas la salida completa de `docker inspect` o `docker compose config`, porque puede incluirlos. `.dockerignore` excluye `.env`, cookies, datos y videos.

## 4. Compartir archivos con Caddy

El bot monta el directorio del host `/home/ubuntu/ig-scheduler-files` como `/media` con escritura. Caddy debe montar exactamente el mismo directorio, con lectura, en su propio Compose:

```yaml
volumes:
  - /home/ubuntu/ig-scheduler-files:/srv/ig-media:ro
```

Dentro del bloque del dominio del Caddyfile:

```caddyfile
handle_path /ig-scheduler/file/* {
    @staging path /.staging /.staging/*
    respond @staging 404
    root * /srv/ig-media
    file_server
}
```

Adapta esta sección al Caddy existente, sin reemplazar otras rutas. El directorio `.staging` contiene temporales con acceso restringido y debe permanecer excluido de HTTP. No habilites listado del directorio. No se necesita una red Docker compartida: el bot verifica la URL pública usando el dominio.

La correspondencia final debe ser:

```text
Host: /home/ubuntu/ig-scheduler-files/ID_ready.mp4
Bot:  /media/ID_ready.mp4
URL:  https://api.shipisnature.com/ig-scheduler/file/ID_ready.mp4
```

El bot descarga por HTTPS todos los bytes del archivo expuesto y compara su SHA-256 con la salida local. Exige 200, `video/mp4` y ausencia de redirecciones. Esto verifica la configuración desde el contenedor; la accesibilidad desde la infraestructura de Meta se confirma cuando Meta procesa el contenedor.

## 5. Construir y comprobar

```bash
docker compose build
docker compose run --rm bot python run_bot.py --check
```

`--check` valida variables, lista, FFmpeg y apertura de SQLite; no llama a Telegram ni Meta. Los permisos de escritura de archivos se terminan de verificar al preparar el primer trabajo. La imagen incluye Python 3.12, FFmpeg y la versión fijada de yt-dlp; no necesita el entorno virtual del host.

Después:

```bash
docker compose up -d bot
docker compose logs -f bot
```

Al arrancar, el servicio comprueba la identidad del bot, que no exista un webhook y la cuenta de Instagram. Un error de credenciales o configuración impide operar. Para errores de inicio persistentes, detén el servicio antes de corregirlo para evitar reinicios continuos.

## 6. Primera prueba desde Telegram

Escribe desde una cuenta presente en el JSON:

```text
https://www.instagram.com/p/CODIGO/

Esta es mi descripción de prueba.
#ejemplo
```

Usa un Reel propio/autorizado, sustituye `CODIGO` y espera `PREPARED`. Con `PUBLISH_ENABLED=false` no debe aparecer una publicación nueva en Instagram. Envía `/status` para ver tus cinco trabajos más recientes. `/start` y `/help` explican el formato.

Cuando la preparación funcione, cambia a `PUBLISH_ENABLED=true` en `.env` y recrea el contenedor:

```bash
docker compose up -d --force-recreate bot
```

`docker compose restart` por sí solo no aplica un entorno nuevo. Desde ese momento un mensaje válido publica sin pedir otra confirmación. Para probar puedes enviar otro Reel o reencolar expresamente el ya preparado:

```bash
docker compose stop bot
docker compose run --rm bot python run_bot.py --list-jobs
docker compose run --rm bot python run_bot.py --resume ID_DEL_TRABAJO
docker compose up -d bot
```

El argumento `--resume` solo admite `PREPARED` o `FAILED` sin contenedor ni publicación. Conserva la descripción original y vuelve a ejecutar las etapas locales. No permite reintentar una publicación de resultado ambiguo.

## 7. Persistencia y recuperación

`data/jobs.sqlite3` almacena trabajos, estados, eventos, respuestas pendientes y offset. Se vincula al ID del bot al arrancar: para cambiar de bot se usa un directorio de datos distinto, evitando reutilizar su offset por accidente. El registro del trabajo y el avance del offset se confirman en una transacción. Se bloquea repetir un shortcode para la misma cuenta, incluso si el intento falló; usa `--resume` cuando sea admisible. Un contenido equivalente con otro shortcode no se detecta.

El bloqueo `data/orchestrator.lock` impide dos orquestadores que comparten ese volumen. No impide conflictos si se usan bases de datos distintas con el mismo token; Telegram devolverá conflicto al consultar. No escales el servicio a varias réplicas.

| Estado tras reiniciar | Comportamiento |
|---|---|
| `DOWNLOADING`, `PREPARING`, `HOSTING` | Vuelve a cola, sin mutación previa de Meta |
| `PROCESSING`, `READY_TO_PUBLISH` | Consulta el contenedor guardado si la publicación está habilitada |
| `CREATING_CONTAINER`, `PUBLISHING` | `NEEDS_REVIEW`; no repite el POST |
| `PUBLISHED` | Recupera permalink/limpieza pendientes; nunca republica |
| `PREPARED`, `FAILED`, `CANCELLED`, `NEEDS_REVIEW` | No se reencola automáticamente |

Una consulta de estado que falla por red se reintenta sobre el mismo contenedor. Una respuesta ambigua o error al crear/publicar se deja en revisión conservadoramente, incluso si podría ser un rechazo definitivo. El plazo de procesamiento es de 15 minutos por intento de consulta; una interrupción de red/reinicio puede reiniciar ese plazo. No hay reconciliación automática de resultados ambiguos todavía.

Para `NEEDS_REVIEW`, conserva base de datos y archivos, consulta el estado remoto y la cuenta antes de decidir. No borres la base ni cambies estados manualmente para forzar un reenvío. Este MVP no incorpora un comando automático para resolver esa revisión.

Las notificaciones tienen cola persistente con hasta ocho intentos y espera creciente. Si falla su entrega, el Reel sigue `PUBLISHED`. Un reinicio entre enviar una notificación y registrar el envío puede repetir esa notificación, sin repetir la publicación. Consultar `/status` permite recuperar el enlace.

La publicación exitosa guarda `media_id` antes de recuperar el permalink. Cuando obtiene el enlace elimina solo los archivos de ese trabajo, mantiene el historial y vuelve a intentar una limpieza fallida. Los trabajos fallidos, preparados o en revisión conservan archivos para diagnóstico; vigila espacio disponible. No hay aún caducidad ni cuota de disco automáticas.

## 8. Cambiar usuarios, cookies y actualizar

Edita `config/telegram_users.json` desde el host; se monta el directorio completo para que los reemplazos del archivo también sean visibles. Se relee antes de aceptar y empezar trabajos y antes de los POST. Una lista inválida pone recepción y trabajador en espera. Se cancelan los trabajos pendientes de usuarios retirados; una petición ya enviada no se puede deshacer.

Si un usuario nuevo escribe al bot, los logs muestran su `user_id` sin el contenido de su mensaje. Agrégalo al JSON y pídele que envíe un mensaje nuevo; los ignorados no se recuperan.

Si Instagram exige cookies, coloca un archivo Netscape privado en `config/cookies.txt` y configura `INSTAGRAM_COOKIES_FILE=/config/cookies.txt`. El directorio no es público. El trabajador hace una copia privada en la carpeta del trabajo para que yt-dlp pueda actualizar su cookie jar sin escribir en `/config`. Las actualizaciones de sesión no se guardan en el archivo fuente; reemplázalo manualmente si caduca. La copia se limpia con el trabajo exitoso y se retiene en intentos fallidos para diagnóstico, por lo que los respaldos de `data/` también contienen credenciales sensibles. Mantén esta función desactivada mientras no sea necesaria.

Para actualizar código o la versión fijada en `requirements.txt`:

```bash
docker compose up -d --build bot
```

No borres `data/` para actualizar. Para respaldar SQLite de forma simple, detén el bot y copia todo `data/` (incluyendo archivos WAL si existen); no copies únicamente un archivo SQLite abierto. Conserva también configuración privada de forma segura.

## 9. Límites actuales y siguientes mejoras

Un solo trabajador, una cuenta Instagram, mensajes privados, Reels individuales, sin horario programado. No hay cancelación desde Telegram, panel de administración, reconciliación automática, cuotas ni limpieza por antigüedad. Las descargas y conversiones fallidas requieren reencolado explícito; no hay reintentos automáticos ilimitados. `yt-dlp` puede fallar por cambios de Instagram o restricciones de la IP del contenedor/servidor.

Una parada termina la recepción y evita iniciar un nuevo POST; una descarga/conversión en curso puede ser interrumpida al finalizar el contenedor y se recupera desde su etapa local. El contenedor usa `init` y un período de parada de 45 segundos. Las mutaciones remotas interrumpidas se dejan en revisión.

La preparación mantiene proporción y usa el perfil ya implementado; no garantiza aceptación por Meta. En ningún caso se intercambian el token de descarga/cookies, el de Telegram y el de publicación: cada credencial tiene su función.

Referencias: [arquitectura](06_ARQUITECTURA_ORQUESTADOR.md), [Telegram getUpdates](https://core.telegram.org/bots/api#getupdates), [Docker Compose y variables de entorno](https://docs.docker.com/compose/how-tos/environment-variables/set-environment-variables/).
