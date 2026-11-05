# Instagram Scheduler

Prototipo Python: Telegram → descarga de Reel → FFmpeg → HTTPS → publicación oficial en Instagram. Cola y estados en SQLite; despliegue con Docker Compose.

Empieza por [07_DESPLIEGUE_DOCKER.md](07_DESPLIEGUE_DOCKER.md): configuración, usuarios, volúmenes compartidos con Caddy y primera prueba. Por defecto `PUBLISH_ENABLED=false` prepara archivos sin publicar. El flujo completo requiere una prueba real en el servidor.

- [Arquitectura y decisiones](06_ARQUITECTURA_ORQUESTADOR.md)
- [Autenticación y publicación aislada validadas](03_ESTADO_VALIDADO_Y_OPERACION.md)
- [Descarga y preparación aisladas](04_DESCARGAR_REEL_EN_SERVIDOR.md)
- [Receptor de Telegram aislado](05_TELEGRAM_RECEPCION.md)
- [Prueba de lectura de DMs y Reels compartidos en Instagram](08_PRUEBA_MENSAJES_INSTAGRAM.md)

Pruebas locales sin credenciales ni publicaciones:

```bash
python -m unittest discover -s tests -v
```

Las pruebas de conversión usan FFmpeg/ffprobe si están instalados. Para el despliegue, la imagen los incluye.
