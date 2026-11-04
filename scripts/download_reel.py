#!/usr/bin/env python3
"""Descarga un Reel de Instagram con yt-dlp, sin usar el token de Meta."""

import argparse
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit


def reel_url(value):
    """Aceptar solo enlaces directos a un Reel y descartar parámetros de rastreo."""
    try:
        parsed = urlsplit(value.strip())
        valid = (
            parsed.scheme == "https"
            and parsed.hostname in {"instagram.com", "www.instagram.com", "m.instagram.com"}
            and parsed.port in {None, 443}
            and not parsed.username
            and not parsed.password
        )
    except ValueError:
        valid = False
    match = re.fullmatch(r"/reels?/([A-Za-z0-9_-]+)/?", parsed.path) if valid else None
    if not match:
        raise argparse.ArgumentTypeError(
            "Usa un enlace HTTPS directo: https://www.instagram.com/reel/CODIGO/"
        )
    return f"https://www.instagram.com/reel/{match.group(1)}/"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", type=reel_url, help="Enlace directo del Reel")
    parser.add_argument(
        "--output-dir", type=Path, default=Path.cwd() / "downloads",
        help="Carpeta de destino (por defecto: ./downloads)",
    )
    parser.add_argument("--cookies", type=Path, help="Archivo opcional de cookies Netscape")
    args = parser.parse_args()

    try:
        from yt_dlp import YoutubeDL
        from yt_dlp.utils import DownloadError
    except ImportError:
        print("Falta yt-dlp. Instala: python3 -m pip install -U yt-dlp", file=sys.stderr)
        return 2

    if args.cookies and not args.cookies.is_file():
        parser.error("No existe el archivo indicado en --cookies.")

    try:
        destination = args.output_dir.expanduser().resolve()
        destination.mkdir(parents=True, exist_ok=True)
        options = {
            # Un único MP4 con audio y video evita depender de FFmpeg.
            "format": "best[ext=mp4][vcodec!=none][acodec!=none]",
            "outtmpl": str(destination / "instagram_%(id)s.%(ext)s"),
            "noplaylist": True,
            "overwrites": False,
            "continuedl": True,
            "socket_timeout": 30,
            "retries": 3,
            "fragment_retries": 3,
            "windowsfilenames": True,
        }
        if args.cookies:
            options["cookiefile"] = str(args.cookies.resolve())
        with YoutubeDL(options) as downloader:
            info = downloader.extract_info(args.url, download=True)
            if not info or info.get("_type") in {"playlist", "multi_video"}:
                raise RuntimeError("No se obtuvo un único video del Reel.")
            path = Path(downloader.prepare_filename(info)).resolve()
            if not path.is_file() or path.stat().st_size == 0:
                raise RuntimeError("No se encontró un archivo descargado válido.")
        print(f"\nArchivo: {path}")
        print(f"Tamaño: {path.stat().st_size:,} bytes")
        print("Descarga completada. No se ha publicado nada.")
        return 0
    except DownloadError:
        print(
            "No se pudo descargar. Revisa el mensaje de yt-dlp de arriba. "
            "Prueba actualizar yt-dlp; si Instagram exige iniciar sesión, usa --cookies. "
            "Las restricciones de Instagram o de la IP del servidor también pueden impedirlo.",
            file=sys.stderr,
        )
        return 1
    except (OSError, RuntimeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nDescarga interrumpida.", file=sys.stderr)
        sys.exit(130)
