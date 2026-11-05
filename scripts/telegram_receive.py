#!/usr/bin/env python3
"""Muestra mensajes privados de Telegram en la terminal, sin responder."""

import argparse
from datetime import datetime, timezone
from getpass import getpass
import json
import os
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class APIError(RuntimeError):
    def __init__(self, code, description, retry_after=5):
        super().__init__(description)
        self.code = code
        self.retry_after = retry_after


def call(token, method, **params):
    request = Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=json.dumps(params).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with build_opener(NoRedirect()).open(request, timeout=40) as response:
            data = json.load(response)
    except HTTPError as error:
        # Nunca mostrar la URL del error: contiene el token.
        raise APIError(error.code, f"Telegram respondió HTTP {error.code}.") from None
    except (URLError, TimeoutError, OSError):
        raise APIError(0, "No se pudo conectar con Telegram.") from None
    if not data.get("ok"):
        raise APIError(data.get("error_code"), "Telegram rechazó la consulta.",
                       data.get("parameters", {}).get("retry_after", 5))
    return data["result"]


def display(message):
    sender = message.get("from", {})
    timestamp = datetime.fromtimestamp(message["date"], timezone.utc).isoformat()
    # JSON escapa secuencias de control para no ejecutarlas en la terminal.
    print(json.dumps({
        "fecha_utc": timestamp,
        "user_id": sender.get("id"),
        "username": sender.get("username"),
        "chat_id": message["chat"]["id"],
        "texto": message.get("text") or message.get("caption") or "[mensaje sin texto]",
    }, ensure_ascii=False), flush=True)


def load_allowed_users(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise RuntimeError(f"No se puede leer la lista de usuarios: {path}. Revisa que exista y sea JSON válido.") from error
    users = data.get("allowed_user_ids") if isinstance(data, dict) else None
    if not isinstance(users, list) or any(type(user) is not int or user <= 0 for user in users):
        raise RuntimeError("allowed_user_ids debe ser una lista de números enteros positivos.")
    return set(users)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--users-file", type=Path,
                        default=Path(__file__).resolve().with_name("telegram_users.json"),
                        help="JSON de usuarios permitidos (por defecto, junto al script)")
    args = parser.parse_args()
    try:
        load_allowed_users(args.users_file)
    except RuntimeError as error:
        parser.exit(1, f"Error: {error}\n")
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip() or getpass("Token del bot (entrada oculta): ").strip()
    if not token or ":" not in token or any(c.isspace() for c in token):
        parser.exit(1, "El token no tiene un formato válido.\n")
    try:
        bot = call(token, "getMe")
        if call(token, "getWebhookInfo").get("url"):
            parser.exit(1, "El bot tiene un webhook activo. Desactívalo antes de usar este receptor.\n")
        print(f"Conectado a @{bot['username']}. Esperando mensajes privados. Ctrl+C para salir.", flush=True)
        print(f"Lista de usuarios: {args.users_file}. Se relee en cada lote de mensajes.", flush=True)
        offset = None
        while True:
            try:
                params = {"timeout": 25, "allowed_updates": ["message"]}
                if offset is not None:
                    params["offset"] = offset
                updates = call(token, "getUpdates", **params)
                allowed_users = load_allowed_users(args.users_file)
                for update in updates:
                    message = update.get("message")
                    if message and message["chat"]["type"] == "private":
                        user_id = message.get("from", {}).get("id")
                        if user_id in allowed_users:
                            display(message)
                        else:
                            print(f"Usuario no autorizado: user_id={user_id}. Mensaje ignorado.", flush=True)
                    offset = update["update_id"] + 1
            except APIError as error:
                if error.code in {400, 401, 403, 404, 409}:
                    if error.code == 409:
                        raise RuntimeError("Conflicto: cierra cualquier otro receptor del mismo bot y revisa sus webhooks.") from None
                    raise RuntimeError(f"{error} Revisa el token y la configuración del bot.") from None
                print(f"{error} Reintentando…", flush=True)
                time.sleep(min(60, max(1, error.retry_after)))
    except (APIError, RuntimeError, ValueError) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nReceptor detenido.")
