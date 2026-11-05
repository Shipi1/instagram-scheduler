"""Prueba de Reel con inicio unificado. Guarda estado para evitar reenvíos."""

import argparse
import getpass
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from check_auth import ROOT, NoRedirect, load_env


def save(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(state, indent=2), encoding='utf-8')
    temp.replace(path)


def run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video-url')
    parser.add_argument('--account-id')
    parser.add_argument('--caption', default='Prueba técnica de publicación')
    parser.add_argument('--prompt-token', action='store_true')
    parser.add_argument('--publish', action='store_true', help='Publicar realmente al terminar el procesamiento.')
    parser.add_argument('--state', type=Path, default=ROOT / 'tmp' / 'publish-test.json')
    args = parser.parse_args()
    load_env()
    account = args.account_id or os.getenv('IG_USER_ID', '').strip()
    if not re.fullmatch(r'\d+', account):
        raise RuntimeError('Indica --account-id o IG_USER_ID numérico.')
    version = os.getenv('GRAPH_API_VERSION', '').strip()
    if version and not re.fullmatch(r'v\d+\.\d+', version):
        raise RuntimeError('GRAPH_API_VERSION debe ser vNN.N o quedar vacía.')
    token = '' if args.prompt_token else os.getenv('IG_ACCESS_TOKEN', '').strip()
    if not token:
        token = getpass.getpass('Token de Instagram (entrada oculta): ').strip()
    if not token or token == 'REEMPLAZAR' or any(c.isspace() for c in token):
        raise RuntimeError('Copia únicamente el token válido, sin Bearer ni espacios.')
    base = 'https://graph.facebook.com' + ('/' + version if version else '')
    opener = urllib.request.build_opener(NoRedirect())

    def call(method, path, data=None, fields=None):
        url = f'{base}/{path}'
        if fields:
            url += '?' + urllib.parse.urlencode({'fields': fields})
        request = urllib.request.Request(
            url, method=method,
            data=urllib.parse.urlencode(data).encode() if data is not None else None,
            headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/json'},
        )
        try:
            with opener.open(request, timeout=45) as response:
                result = json.load(response)
            if not isinstance(result, dict):
                raise RuntimeError('Respuesta inesperada de Meta.')
            return result
        except urllib.error.HTTPError as exc:
            try:
                error = json.load(exc).get('error', {})
                detail = json.dumps(error, ensure_ascii=False).replace(token, '[TOKEN OCULTO]')
            except (ValueError, AttributeError):
                detail = 'Respuesta sin detalle JSON.'
            raise RuntimeError(f'Meta HTTP {exc.code}: {detail}') from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            raise RuntimeError('Fallo de conexión o respuesta inválida. No se reintentó la petición.') from None

    profile = call('GET', account, fields='id,username')
    if str(profile.get('id')) != account or not profile.get('username'):
        raise RuntimeError('No se pudo comprobar la identidad de la cuenta.')
    print('Cuenta: @' + profile['username'])
    expected = os.getenv('IG_EXPECTED_USERNAME', '').strip().lstrip('@')
    if expected and expected.casefold() != profile['username'].casefold():
        raise RuntimeError('El usuario autenticado no coincide con IG_EXPECTED_USERNAME.')
    state = json.loads(args.state.read_text(encoding='utf-8')) if args.state.exists() else {}
    if state:
        if state.get('account_id') != account or state.get('base') != base:
            raise RuntimeError('El estado guardado pertenece a otra cuenta o versión de API.')
        if args.video_url and state.get('video_url') != args.video_url:
            raise RuntimeError('Ya existe otra prueba en este archivo. Usa otro --state para un video nuevo.')
        if state.get('media_id'):
            print('Ya publicado. MEDIA_ID=' + state['media_id'])
            details = call('GET', state['media_id'], fields='id,permalink')
            print('Permalink:', details.get('permalink', '(no devuelto)'))
            return
        if state.get('stage') in {'CREATING', 'PUBLISHING'}:
            raise RuntimeError('Una petición anterior pudo completarse sin guardar respuesta. Revisa Instagram y reconcilia el estado antes de reintentar; no borres este archivo.')
    else:
        video_url = args.video_url or os.getenv('PUBLIC_MEDIA_URL', '').strip()
        parts = urllib.parse.urlsplit(video_url)
        if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password:
            raise RuntimeError('Indica --video-url con una URL HTTPS directa al MP4.')
        state = {'account_id': account, 'base': base, 'video_url': video_url, 'stage': 'CREATING'}
        save(args.state, state)
        container = call('POST', f'{account}/media', data={
            'media_type': 'REELS', 'video_url': video_url,
            'caption': args.caption, 'share_to_feed': 'false',
        })
        state.update(container_id=str(container['id']), stage='PROCESSING')
        save(args.state, state)
    container_id = state['container_id']
    print('CONTAINER_ID=' + container_id)
    print('Estado local:', args.state)
    deadline = time.monotonic() + 15 * 60
    while True:
        status = call('GET', container_id, fields='status_code,status')
        code = status.get('status_code')
        print('Procesamiento:', code)
        if code == 'FINISHED':
            break
        if code in {'ERROR', 'EXPIRED', 'PUBLISHED'}:
            raise RuntimeError(f'Contenedor {code}: {status.get("status", "")}. No se enviará otra publicación.')
        if time.monotonic() >= deadline:
            raise RuntimeError('Se agotó el tiempo. Ejecuta otra vez con el mismo --state para consultar este contenedor.')
        time.sleep(30)
    if not args.publish:
        print('Video procesado. Aún no publicado. Repite con --publish y el mismo --state para publicarlo.')
        return
    state['stage'] = 'PUBLISHING'
    save(args.state, state)
    published = call('POST', f'{account}/media_publish', data={'creation_id': container_id})
    state.update(media_id=str(published['id']), stage='PUBLISHED')
    save(args.state, state)
    print('Publicado. MEDIA_ID=' + state['media_id'])
    details = call('GET', state['media_id'], fields='id,permalink')
    print('Permalink:', details.get('permalink', '(no devuelto)'))
    print('Comprueba el Reel y luego retira el MP4 del alojamiento HTTPS.')


if __name__ == '__main__':
    try:
        run()
    except (RuntimeError, OSError, ValueError, KeyError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        sys.exit(1)
    except (KeyboardInterrupt, EOFError):
        print('\nInterrumpido. Conserva el archivo de estado antes de reintentar.')
        sys.exit(1)
