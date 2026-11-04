#!/usr/bin/env python3
"""Prepara un MP4 para publicación, conservando la proporción del video."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile


def run(command):
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"{command[0]} falló: {result.stderr[-3000:]}")
    return result.stdout


def require_tools():
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise RuntimeError(f"Falta {tool}. En Ubuntu: sudo apt install ffmpeg")


def probe(path):
    return json.loads(run([
        "ffprobe", "-v", "error", "-show_streams", "-show_format",
        "-of", "json", str(path),
    ]))


def check(info, path, prepared=False):
    videos = [s for s in info["streams"] if s["codec_type"] == "video"
              and not s.get("disposition", {}).get("attached_pic")]
    if len(videos) != 1:
        raise RuntimeError("Se requiere exactamente una pista de video.")
    duration = float(info["format"].get("duration", 0))
    if not 3 <= duration <= 900:
        raise RuntimeError(f"Duración fuera del rango de 3–900 segundos: {duration:.2f}s.")
    if prepared:
        video = videos[0]
        if video.get("codec_name") != "h264" or video.get("pix_fmt") != "yuv420p":
            raise RuntimeError("La salida no tiene H.264/yuv420p.")
        if video["width"] > 1920 or video["width"] % 2 or video["height"] % 2:
            raise RuntimeError("Dimensiones de salida inválidas.")
        for stream in info["streams"]:
            if stream["codec_type"] == "audio" and (
                stream.get("codec_name") != "aac"
                or int(stream.get("sample_rate", 0)) > 48000
                or stream.get("channels", 0) > 2
            ):
                raise RuntimeError("El audio de salida no cumple el perfil AAC.")
        if path.stat().st_size > 300_000_000:
            raise RuntimeError("La salida supera 300 MB; requiere menor bitrate.")
    return duration


def prepare_video(source):
    require_tools()
    source = Path(source).expanduser().resolve()
    if not source.is_file():
        raise RuntimeError(f"No existe el archivo: {source}")
    info = probe(source)
    duration = check(info, source)
    # Margen para que incluso videos largos permanezcan bajo 300 MB.
    bitrate = min(8_000_000, int(280_000_000 * 8 / duration) - 128_000)
    output = source.with_name(source.stem + "_ready.mp4")
    print("Preparando H.264/AAC a 30 fps; se conserva la proporción, sin recortar.")
    # Temporal en el mismo disco: nunca se expone una salida final incompleta.
    with tempfile.TemporaryDirectory(prefix=".prepare-", dir=source.parent) as folder:
        temporary = Path(folder) / "video.mp4"
        run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-i", str(source), "-map", "0:V:0", "-map", "0:a:0?",
            "-map_metadata", "-1", "-map_chapters", "-1",
            "-vf", "scale=w='max(2,trunc(iw*sar/2)*2)':h=ih,setsar=1,scale=w='min(1920,iw)':h=ih:force_original_aspect_ratio=decrease:force_divisible_by=2,fps=30,format=yuv420p",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-maxrate", str(bitrate), "-bufsize", str(bitrate * 2),
            "-g", "60", "-keyint_min", "60", "-sc_threshold", "0",
            "-flags", "+cgop", "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
            "-ac", "2", "-movflags", "+faststart", str(temporary),
        ])
        check(probe(temporary), temporary, prepared=True)
        # Decodificar también detecta archivos truncados o corruptos.
        run(["ffmpeg", "-v", "error", "-xerror", "-nostdin", "-i", str(temporary),
             "-map", "0:v:0", "-map", "0:a:0?", "-f", "null", "-"])
        temporary.replace(output)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    args = parser.parse_args()
    try:
        print(f"Archivo preparado: {prepare_video(args.file)}")
    except (OSError, RuntimeError, ValueError) as error:
        parser.exit(1, f"Error: {error}\n")
