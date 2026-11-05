"""Comprueba Instagram Login mediante una consulta GET; no publica contenido."""

import getpass
import argparse
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[1]


def load_env():
    """Lee asignaciones simples KEY=VALUE, sin ejecutar ni expandir su contenido."""
    path = ROOT / '.env'
    if not path.exists():
        return
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--login', choices=('instagram', 'unified'), default='instagram')
    parser.add_argument('--account-id', help='ID de la cuenta Instagram mostrado por Meta.')
    parser.add_argument('--prompt-token', action='store_true', help='Pedir token oculto, ignorando el guardado.')
    args = parser.parse_args()
    load_env()
    token = '' if args.prompt_token else os.getenv('IG_ACCESS_TOKEN', '').strip()
    if not token:
        token = getpass.getpass('Token de Instagram (entrada oculta): ').strip()
    if not token or token == 'REEMPLAZAR':
        print('Falta un token válido. Configura IG_ACCESS_TOKEN en .env.')
        return 1
    if token.lower().startswith('bearer ') or any(c.isspace() for c in token) or any(c in token for c in ('"', "'", '{', '}')):
        print('El token tiene espacios, comillas, JSON o el prefijo Bearer. Copia únicamente el valor del token.')
        return 1

    version = os.getenv('GRAPH_API_VERSION', '').strip()
    if version and not re.fullmatch(r'v\d+\.\d+', version):
        print('GRAPH_API_VERSION debe tener formato vNN.N o quedar vacía.')
        return 1
    account_id = args.account_id or os.getenv('IG_USER_ID', '').strip()
    if args.login == 'unified' and not re.fullmatch(r'\d+', account_id):
        print('Para inicio unificado indica --account-id con el ID numérico de Instagram.')
        return 1
    base = 'https://graph.facebook.com' if args.login == 'unified' else 'https://graph.instagram.com'
    if version:
        base += '/' + version
    path = f'/{account_id}?fields=id,username' if args.login == 'unified' else '/me?fields=user_id,username'
    request = urllib.request.Request(
        base + path,
        headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/json'},
        method='GET',
    )
    print(f'Consultando la cuenta ({args.login}) en {base}...')
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=30) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        print(f'Instagram respondió HTTP {exc.code}.')
        try:
            error = json.load(exc).get('error', {})
            if isinstance(error, dict):
                for field in ('message', 'type', 'code', 'error_subcode', 'fbtrace_id'):
                    if field in error:
                        print(f'{field}: {str(error[field]).replace(token, "[TOKEN OCULTO]")}')
                if error.get('code') == 190:
                    print('Revisa si el token venció, fue revocado o pertenece a otro flujo de login.')
        except (ValueError, AttributeError):
            print('La respuesta de error no contiene JSON reconocible.')
        print('Revisa token, permisos, roles de la app y versión de API.')
        return 1
    except (urllib.error.URLError, TimeoutError, OSError):
        print('No se pudo conectar. Revisa Internet, certificados y vuelve a intentar.')
        return 1
    except ValueError:
        print('Instagram no devolvió una respuesta JSON válida.')
        return 1

    id_field = 'id' if args.login == 'unified' else 'user_id'
    if not isinstance(result, dict) or not result.get(id_field) or not result.get('username'):
        print('La respuesta no contiene el ID y username. Revisa el producto y la versión configurados.')
        return 1
    username = str(result['username'])
    print(f'Cuenta autenticada: @{username}')
    print(f'IG_USER_ID={result[id_field]}')
    expected = os.getenv('IG_EXPECTED_USERNAME', '').strip().lstrip('@')
    if expected and username.casefold() != expected.casefold():
        print(f'ATENCIÓN: esperabas @{expected}; el token pertenece a otra cuenta.')
        return 1
    print('Autenticación y lectura básica correctas. No se ha publicado nada.')
    print('Esta consulta no comprueba el permiso de publicación ni la vigencia restante del token.')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError):
        print('\nPrueba cancelada.')
        sys.exit(1)
