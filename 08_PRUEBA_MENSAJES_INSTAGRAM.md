# Prueba aislada: leer mensajes y un Reel compartido por Instagram

## Objetivo

`scripts/check_messages.py` usa únicamente GET. No responde, marca mensajes como leídos mediante acciones explícitas, descarga, crea trabajos ni publica. No modifica Telegram ni requiere un webhook para hacer la consulta puntual de conversaciones. Usa librería estándar de Python y `scripts/check_auth.py`; copia ambos si lo ejecutas fuera del proyecto.

La lectura todavía debe validarse con el token y flujo de esta cuenta: que la publicación funcione no demuestra que los permisos de mensajería estén concedidos. Este experimento no altera el host/token del publicador existente.

## 1. Enviar dos mensajes desde la cuenta personal

En el chat privado con la cuenta profesional conectada (en nuestro caso `@tula.posting`):

1. Envía un texto reconocible, por ejemplo `prueba-dm-001`.
2. En un Reel propio o autorizado, pulsa Compartir y envíalo a esa misma cuenta, sin copiar manualmente el enlace.

Haz la consulta poco después para que ambos mensajes estén entre los más recientes. Revisa también si llegaron a Solicitudes en Instagram. En modo desarrollo puede hacer falta asignar los roles de prueba correspondientes; con usuarios externos pueden aplicar requisitos de acceso avanzado/revisión. No asumir que una respuesta vacía demuestra que la API no soporta mensajes.

## 2. Ejecutar en el servidor sin Docker

Desde la raíz del proyecto con tu entorno virtual activado y `.env` configurado:

```bash
python scripts/check_messages.py --list-conversations
```

Lee `IG_ACCESS_TOKEN`, `IG_USER_ID`, `IG_EXPECTED_USERNAME` si está definido y `GRAPH_API_VERSION` opcional desde `.env`. También acepta `--account-id` y `--prompt-token` (entrada oculta).

El modo predeterminado es `--login unified`: usa `graph.facebook.com` y autentica por ID, como la publicación validada. `--login instagram` selecciona explícitamente `graph.instagram.com` para un token de ese flujo; no se prueba otro host automáticamente ante un error. Si Meta requiere otro tipo de token/ID para mensajería en la configuración de tu app, se deberá verificar ese flujo antes de adaptar la prueba; no se debe sustituir a ciegas por un token de Página.

## 3. Ejecutar con Docker Compose

Actualiza el código y reconstruye la imagen para incluir el nuevo script:

```bash
docker compose build bot
docker compose run --rm bot python scripts/check_messages.py --list-conversations
```

Puede ejecutarse con el orquestador de Telegram activo: esta herramienta no consulta `getUpdates`, no toma el bloqueo del trabajador ni toca SQLite. No llama a las funciones de publicación aunque `PUBLISH_ENABLED=true` esté configurado.

## 4. Identificar al remitente

El listado muestra IDs de conversación y sus participantes, sin consultar el contenido de mensajes:

```json
{"conversation_id":"CONVERSACION","participants":[{"id":"123456789","username":"mi_cuenta"}],"updated_time":"..."}
```

La forma concreta de los participantes depende de lo que devuelva Meta. Copia el ID del remitente que reconoce la API de mensajería; no es el ID de Telegram ni necesariamente un ID público obtenido de otra API. `--sender @username` solo puede encontrarlo si Meta devuelve `username`; si falta ese campo, usa el ID del listado.

## 5. Consultar solo sus mensajes

```bash
python scripts/check_messages.py --sender 123456789
```

O dentro de Docker:

```bash
docker compose run --rm bot python scripts/check_messages.py --sender 123456789 --limit 10
```

Alternativa si aparece su username en participantes:

```bash
python scripts/check_messages.py --sender @mi_cuenta
```

Se selecciona la conversación por participantes y solo se imprime el contenido enviado por ese remitente; las respuestas de la cuenta profesional no se imprimen. Se consultan hasta 10 mensajes recientes por conversación por defecto, máximo 20; no es una descarga de todo el historial. El límite incluye mensajes en ambos sentidos, por lo que puede mostrar menos mensajes entrantes. No se pagina el historial de mensajes en esta primera prueba.

Busca el texto `prueba-dm-001` y, en el otro mensaje, los campos `attachments` o `shares`. Se intentan por separado: un campo no soportado genera `attachments_diagnostic` o `shares_diagnostic` y no impide mostrar texto/otros campos. Un valor null o vacío no demuestra que el webhook tampoco vaya a entregar información del Reel compartido.

Se recorren hasta 5 páginas de conversaciones, 25 elementos por página solicitados; ajusta `--max-pages 10` si necesitas revisar más. El script reconstruye consultas usando cursores, no sigue URLs de paginación con tokens. Una consulta nueva puede volver a mostrar mensajes ya vistos: no guarda offset ni es un receptor continuo.

## 6. Interpretar la prueba

| Resultado | Siguiente paso |
|---|---|
| Error OAuth o permisos | Conservar código/subcódigo y comprobar permisos de mensajería, token y roles del flujo real |
| Lista vacía | Verificar cuenta destino, mensaje reciente, solicitudes, roles y acceso a mensajes de herramientas conectadas |
| Conversación visible, cero mensajes del remitente | Comprobar su ID/username y ampliar `--limit` hasta 20 |
| Texto visible | Lectura de DMs confirmada para esa prueba |
| Reel compartido con URL de Instagram | Verificar si el enlace encaja con los formatos aceptados por el descargador |
| Solo URL de un archivo/CDN | Evaluar descarga del adjunto en una integración independiente; el descargador actual solo acepta enlaces de Instagram |
| Adjuntos no disponibles en consulta | Probar un webhook de mensajes antes de concluir que no es posible recibir el Reel |

La siguiente prueba, solo si hace falta, será un webhook HTTPS que registre el evento real de Compartir. No está implementado aquí. Antes de conectar DMs a la publicación se requiere otra lista de remitentes autorizados, IDs y deduplicación por mensaje, independientes de Telegram. No se debe encolar automáticamente cualquier mensaje que llegue a la cuenta.

La salida contiene contenido privado y puede incluir URLs firmadas temporales; no la publiques ni la subas al repositorio. El script no guarda archivos de respuesta y oculta el token configurado en errores y salida de detalles. Comparte para diagnóstico solo campos necesarios, quitando datos personales y enlaces firmados.

## Referencias

- [Meta: Conversations API](https://www.postman.com/meta/messenger-platform-api/folder/22794852-255610cd-47f5-4f4d-b3fa-71aec360be9a): operaciones de conversaciones/mensajes y requisitos según flujo.
- [Meta: Instagram API, mensajería y contenido compartido](https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api).

Validación local: pruebas sin red para selección del remitente, ausencia de lectura de contenido en el listado, cursores, host/versión y campos de adjuntos no soportados. Falta la consulta real; no se presupone que el token actual incluya mensajería.
