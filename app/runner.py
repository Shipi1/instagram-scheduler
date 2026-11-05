import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import time

from app.clients import Instagram, RemoteError, verify_public
from app.config import Config
from app.store import Store
from scripts.download_reel import reel_url
from scripts.prepare_video import prepare_video, require_tools
from scripts.telegram_receive import APIError, call as telegram, load_allowed_users


HELP = ('Envía un enlace de Instagram en la primera línea y una descripción debajo. '
        'Sin descripción se usa la predeterminada. El bot publica automáticamente si está habilitado. '
        '/status muestra tus últimos trabajos.')


def parse_message(text, default):
    lines = text.strip().splitlines()
    if not lines:
        raise ValueError('Mensaje vacío.')
    try:
        url = reel_url(lines[0])
    except argparse.ArgumentTypeError as error:
        raise ValueError(str(error)) from None
    caption = '\n'.join(lines[1:]).strip() or default
    if len(caption) > 2200:
        raise ValueError('La descripción supera 2200 caracteres.')
    return url, caption


class Runner:
    def __init__(self, config, store, stop):
        self.c, self.store, self.stop = config, store, stop
        self.ig = Instagram(config)

    def recover(self):
        for job in self.store.rows("SELECT * FROM jobs WHERE status IN ('CREATING_CONTAINER','PUBLISHING')"):
            self.store.change(job['id'], 'NEEDS_REVIEW',
                              'Operación de Meta interrumpida. Requiere revisión; no se reintentará.',
                              error='Respuesta remota desconocida tras reinicio.')
        for job in self.store.rows("SELECT * FROM jobs WHERE status IN ('DOWNLOADING','PREPARING','HOSTING')"):
            self.store.change(job['id'], 'QUEUED')

    def receive(self, update):
        message = update.get('message')
        request = reply = None
        if message and message.get('chat', {}).get('type') == 'private':
            user = message.get('from', {}).get('id')
            if user in load_allowed_users(self.c.users):
                text = message.get('text') or message.get('caption') or ''
                command = text.split(maxsplit=1)[0].split('@')[0] if text else ''
                if command in {'/start', '/help'}:
                    reply = HELP
                elif command == '/status':
                    reply = self.store.summary(user)
                else:
                    try:
                        request = parse_message(text, self.c.caption)
                    except ValueError as error:
                        reply = f'{error}\n{HELP}'
            else:
                print(f'Usuario no autorizado: user_id={user}', flush=True)
        self.store.receive(update['update_id'], message, request, reply, self.c.account, self.c.version)

    def flush_notifications(self):
        rows = self.store.rows('SELECT * FROM outbox WHERE sent=0 AND attempts<8 AND due<=? ORDER BY id LIMIT 10',
                               (time.time(),))
        for row in rows:
            try:
                if row['chat_id'] not in load_allowed_users(self.c.users):
                    with self.store.connect() as db:
                        db.execute('UPDATE outbox SET sent=1 WHERE id=?', (row['id'],))
                    continue
                telegram(self.c.telegram_token, 'sendMessage', chat_id=row['chat_id'], text=row['text'])
            except APIError:
                with self.store.connect() as db:
                    db.execute('UPDATE outbox SET attempts=attempts+1,due=? WHERE id=?',
                               (time.time() + min(3600, 30 * 2 ** row['attempts']), row['id']))
            else:
                with self.store.connect() as db:
                    db.execute('UPDATE outbox SET sent=1 WHERE id=?', (row['id'],))

    def download(self, job, folder):
        command = [sys.executable, str(Path(__file__).resolve().parents[1] / 'scripts/download_reel.py'),
                   job['source_url'], '--output-dir', str(folder), '--download-only']
        if self.c.cookies:
            # yt-dlp guarda su cookie jar al salir: trabajar sobre una copia privada.
            cookie_copy = folder / 'session.cookies.txt'
            shutil.copyfile(self.c.cookies, cookie_copy)
            os.chmod(cookie_copy, 0o600)
            command += ['--cookies', str(cookie_copy)]
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=900)
        if result.returncode:
            raise RuntimeError('Falló yt-dlp. Revisa acceso al Reel, versión y cookies si fueran necesarias.')
        files = [p for p in folder.glob('instagram_*.mp4') if not p.stem.endswith('_ready')]
        if len(files) != 1:
            raise RuntimeError('La descarga no produjo un único MP4.')
        return files[0]

    def expose(self, ready, target):
        # El temporal privado no queda accesible por el servidor de archivos.
        import tempfile
        staging = self.c.public / '.staging'
        staging.mkdir(mode=0o700, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=staging) as folder:
            temporary = Path(folder) / 'video.mp4'
            shutil.copyfile(ready, temporary)
            os.chmod(temporary, 0o644)
            temporary.replace(target)

    def process(self, job):
        job_id = job['id']
        if job['account'] != self.c.account or job['version'] != self.c.version:
            self.store.change(job_id, 'NEEDS_REVIEW', 'La cuenta o versión cambió; revisar antes de continuar.')
            return
        if job['user_id'] not in load_allowed_users(self.c.users):
            self.store.change(job_id, 'CANCELLED', error='Usuario retirado de la lista.')
            return
        folder = self.c.data / 'work' / job_id
        public = self.c.public / f'{job_id}_ready.mp4'
        url = self.c.public_url + '/' + public.name
        if job['status'] == 'QUEUED':
            folder.mkdir(parents=True, exist_ok=True)
            self.store.change(job_id, 'DOWNLOADING', 'Descargando video.')
            original = self.download(job, folder)
            self.store.change(job_id, 'PREPARING', 'Preparando video.')
            ready = prepare_video(original)
            if self.stop.is_set():
                return
            self.store.change(job_id, 'HOSTING')
            self.expose(ready, public)
            verify_public(url, public)
            if not self.c.publish:
                self.store.change(job_id, 'PREPARED', 'Video preparado y HTTPS verificado. Publicación deshabilitada.')
                return
            if job['user_id'] not in load_allowed_users(self.c.users):
                self.store.change(job_id, 'CANCELLED', error='Usuario retirado antes de publicar.')
                return
            self.ig.identity()
            if self.stop.is_set():
                return
            self.store.change(job_id, 'CREATING_CONTAINER')
            result = self.ig.call('POST', f'{self.c.account}/media', media_type='REELS',
                                  video_url=url, caption=job['caption'], share_to_feed='false')
            self.store.change(job_id, 'PROCESSING', 'Instagram está procesando el video.', container_id=str(result['id']))
        job = self.store.get(job_id)
        if job['status'] in {'PROCESSING', 'READY_TO_PUBLISH'}:
            if not self.c.publish:
                return
            deadline = time.monotonic() + 900
            while not self.stop.is_set():
                result = self.ig.call('GET', job['container_id'], fields='status_code,status')
                code = result.get('status_code')
                if code == 'FINISHED':
                    break
                if code in {'ERROR', 'EXPIRED', 'PUBLISHED'}:
                    raise RuntimeError(f'Contenedor {code}; revisión necesaria.')
                if time.monotonic() >= deadline:
                    raise RuntimeError('Se agotó la espera del contenedor; conservar ID para revisión.')
                self.stop.wait(30)
            if self.stop.is_set():
                return
            self.store.change(job_id, 'READY_TO_PUBLISH')
            if job['user_id'] not in load_allowed_users(self.c.users):
                self.store.change(job_id, 'CANCELLED', error='Usuario retirado antes de publicar.')
                return
            self.store.change(job_id, 'PUBLISHING')
            result = self.ig.call('POST', f'{self.c.account}/media_publish', creation_id=job['container_id'])
            self.store.change(job_id, 'PUBLISHED', media_id=str(result['id']))
        if self.store.get(job_id)['status'] == 'PUBLISHED':
            self.finalize(self.store.get(job_id))

    def finalize(self, job):
        if not job['permalink']:
            result = self.ig.call('GET', job['media_id'], fields='id,permalink')
            link = result.get('permalink')
            if not link:
                raise RemoteError('Meta no devolvió permalink todavía.')
            self.store.change(job['id'], 'PUBLISHED', f'Publicado: {link}', permalink=link)
        if job['cleanup'] != 'DONE':
            folder = (self.c.data / 'work' / job['id']).resolve()
            public = (self.c.public / f"{job['id']}_ready.mp4").resolve()
            if folder.parent != (self.c.data / 'work').resolve() or public.parent != self.c.public.resolve():
                raise RuntimeError('Ruta de limpieza inválida.')
            public.unlink(missing_ok=True)
            if folder.exists():
                shutil.rmtree(folder)
            self.store.change(job['id'], 'PUBLISHED', cleanup='DONE')

    def worker(self):
        while not self.stop.is_set():
            try:
                load_allowed_users(self.c.users)
                for job in self.store.rows("SELECT * FROM jobs WHERE status='PUBLISHED' AND (permalink IS NULL OR cleanup!='DONE')"):
                    try:
                        self.finalize(job)
                    except (RuntimeError, OSError):
                        print(f"{job['id']}: finalización pendiente; se reintentará.", flush=True)
                states = "'QUEUED','PROCESSING','READY_TO_PUBLISH'" if self.c.publish else "'QUEUED'"
                rows = self.store.rows(f"SELECT * FROM jobs WHERE status IN ({states}) ORDER BY created LIMIT 1")
                if rows:
                    job = rows[0]
                    try:
                        self.process(job)
                    except Exception as error:
                        self.fail(job['id'], error)
            except RuntimeError:
                print('Lista de usuarios no válida; trabajador en espera.', flush=True)
            except Exception as error:
                print(f'Trabajador detenido por error interno: {type(error).__name__}', flush=True)
                self.stop.set()
                return
            self.stop.wait(5)

    def fail(self, job_id, error):
        status = self.store.get(job_id)['status']
        if status == 'PUBLISHED':
            print(f'{job_id}: publicado; finalización pendiente.', flush=True)
        elif status == 'PROCESSING' and isinstance(error, RemoteError):
            print(f'{job_id}: consulta fallida; se consultará el mismo contenedor.', flush=True)
        else:
            state = 'NEEDS_REVIEW' if status in {'CREATING_CONTAINER','PROCESSING','READY_TO_PUBLISH','PUBLISHING'} else 'FAILED'
            detail = str(error) if isinstance(error, (RemoteError, RuntimeError)) else type(error).__name__
            detail = detail.replace(self.c.ig_token, '[OCULTO]').replace(self.c.telegram_token, '[OCULTO]')[:500]
            self.store.change(job_id, state, f'{state}. Etapa: {status}. Revisa los logs.', error=detail)
            print(json.dumps({'job': job_id, 'status': state, 'error': detail}, ensure_ascii=False), flush=True)

    def run(self):
        bot = telegram(self.c.telegram_token, 'getMe')
        self.store.bind_bot(bot['id'])
        if telegram(self.c.telegram_token, 'getWebhookInfo').get('url'):
            raise RuntimeError('Hay un webhook activo; desactívalo antes de usar polling.')
        self.ig.identity()
        self.recover()
        thread = threading.Thread(target=self.worker, daemon=True)
        thread.start()
        print(f'Orquestador listo. Publicación habilitada: {self.c.publish}', flush=True)
        try:
            while not self.stop.is_set():
                try:
                    load_allowed_users(self.c.users)
                    self.flush_notifications()
                    updates = telegram(self.c.telegram_token, 'getUpdates', offset=self.store.offset(),
                                       timeout=25, allowed_updates=['message'])
                    for update in updates:
                        if self.stop.is_set():
                            break
                        self.receive(update)
                except APIError as error:
                    if error.code in {400,401,403,404,409}:
                        raise RuntimeError(f'Telegram HTTP {error.code}; revisa token, webhook u otro receptor.') from None
                    print('Telegram no disponible; reintentando.', flush=True)
                    self.stop.wait(5)
                except RuntimeError:
                    print('Lista de usuarios inválida; recepción en espera.', flush=True)
                    self.stop.wait(5)
        finally:
            self.stop.set()
            thread.join(timeout=5)


def main():
    parser = argparse.ArgumentParser(description='Orquestador de Telegram a Instagram')
    parser.add_argument('--check', action='store_true', help='Validar configuración y herramientas sin llamar APIs')
    parser.add_argument('--list-jobs', action='store_true', help='Mostrar trabajos sin iniciar el bot')
    parser.add_argument('--resume', metavar='JOB_ID', help='Reencolar PREPARED o FAILED sin contenedor')
    args = parser.parse_args()
    config = Config.load()
    require_tools()
    load_allowed_users(config.users)
    store = Store(config.data / 'jobs.sqlite3')
    if args.check:
        print('Configuración, usuarios, SQLite y FFmpeg correctos. No se consultaron APIs.')
        return
    if args.list_jobs:
        for row in store.rows('SELECT id,status,error,media_id,permalink FROM jobs ORDER BY created'):
            print(json.dumps(dict(row), ensure_ascii=False))
        return
    if os.name != 'posix':
        raise RuntimeError('El servicio requiere Linux (usa Docker); los tests funcionan en Windows.')
    import fcntl
    with (config.data / 'orchestrator.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Ya existe un orquestador usando este volumen.') from None
        if args.resume:
            job = store.get(args.resume)
            if not job or job['status'] not in {'PREPARED','FAILED'} or job['container_id'] or job['media_id']:
                raise RuntimeError('Solo se pueden reencolar PREPARED/FAILED sin contenedor ni publicación.')
            store.change(job['id'], 'QUEUED', error=None)
            print('Trabajo reencolado. Arranca el servicio para procesarlo.')
            return
        stop = threading.Event()
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda *_: stop.set())
        Runner(config, store, stop).run()
