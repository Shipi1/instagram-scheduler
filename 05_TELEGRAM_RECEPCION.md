# Usuarios permitidos del bot

Copia `scripts/telegram_receive.py` y `scripts/telegram_users.json` juntos al servidor. No se necesitan librerías adicionales. Ejecuta:

```bash
cd ~/instagram-scheduler/scripts
python telegram_receive.py
```

Pega el token cuando lo pida (entrada oculta), o configura `TELEGRAM_BOT_TOKEN` en el entorno. No guardes el token en el JSON de usuarios.

La lista inicial está vacía: no se muestra el contenido de ningún mensaje. Abre tu bot en Telegram, pulsa Iniciar y envía un mensaje. La terminal mostrará `Usuario no autorizado: user_id=...`. Usa ese número para editar el archivo:

```bash
nano telegram_users.json
```

Ejemplo con dos usuarios (sustituye los números por los reales):

```json
{
  "allowed_user_ids": [123456789, 987654321]
}
```

Los identificadores son números, sin comillas; no uses `@username`. Añade o quita números para conceder o retirar acceso. JSON no permite comentarios ni una coma después del último elemento.

El receptor relee el archivo antes de procesar cada lote recibido: no hace falta reiniciar para aplicar cambios válidos. Guarda y envía un mensaje nuevo para probar. Los mensajes previamente ignorados no se recuperan. Si el archivo desaparece o es inválido, el receptor se detiene sin procesar más mensajes; corrígelo y vuelve a ejecutar el script. Una lista vacía bloquea a todos.

Para usar otra ubicación:

```bash
python telegram_receive.py --users-file /ruta/privada/telegram_users.json
```

Esto reemplaza el argumento anterior `--allowed-user-id`. Solo muestra mensajes privados de usuarios autorizados; los demás solo generan el aviso con su ID. No responde, descarga ni publica. Usa una sola instancia por bot y deja la terminal abierta durante la prueba. Ctrl+C lo detiene. No hay persistencia local del offset: tras un reinicio puede repetirse el último lote pendiente de confirmación.
