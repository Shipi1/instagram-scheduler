#!/usr/bin/env python3
"""Prueba de solo lectura de conversaciones y mensajes de Instagram."""

import argparse
import getpass
import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, build_opener

try:
    from .check_auth import NoRedirect, load_env
except ImportError:
    from check_auth import NoRedirect, load_env


class ReadError(RuntimeError):
    pass


class Client:
    def __init__(self, token, login, version):
        self.token = token
        host = 'graph.facebook.com' if login == 'unified' else 'graph.instagram.com'
        self.base = 'https://' + host + ('/' + version if version else '')

    def get(self, path, **params):
        # Nunca seguir paging.next: puede contener tokens. Reconstruir usando cursores.
        url = self.base + '/' + path + '?' + urlencode(params)
        request = Request(url, headers={'Authorization': 'Bearer ' + self.token,
                                        'Accept': 'application/json'}, method='GET')
        try:
            with build_opener(NoRedirect()).open(request, timeout=30) as response:
                result = json.load(response)
            if not isinstance(result, dict):
                raise ReadError('Respuesta inesperada de Meta.')
            return result
        except HTTPError as error:
            detail = {}
            try:
                payload = json.load(error).get('error', {})
                detail = {k: payload[k] for k in ('code', 'error_subcode', 'message', 'fbtrace_id') if k in payload}
            except (ValueError, AttributeError, TypeError):
                pass
            safe = json.dumps(detail, ensure_ascii=False).replace(self.token, '[TOKEN OCULTO]')
            raise ReadError(f'Meta HTTP {error.code}: {safe}') from None
        except (URLError, OSError, TimeoutError, ValueError):
            raise ReadError('Conexión fallida o respuesta JSON inválida.') from None


def matches(person, sender):
    if sender.isdigit():
        return str(person.get('id', '')) == sender
    return str(person.get('username', '')).lstrip('@').casefold() == sender.lstrip('@').casefold()


def conversations(client, account, max_pages):
    params = {'platform': 'instagram', 'fields': 'id,participants,updated_time', 'limit': 25}
    seen = set()
    for _ in range(max_pages):
        result = client.get(quote(account, safe='') + '/conversations', **params)
        data = result.get('data')
        if not isinstance(data, list):
            raise ReadError('Respuesta sin lista de conversaciones.')
        yield from data
        paging = result.get('paging', {})
        after = paging.get('cursors', {}).get('after')
        if not paging.get('next') or not after or after in seen:
            return
        seen.add(after)
        params['after'] = after
    print(f'Límite de {max_pages} páginas alcanzado; puede haber conversaciones sin revisar.')


def inspect(client, account, sender, max_pages=5, limit=10, list_only=False):
    found = count = 0
    for conversation in conversations(client, account, max_pages):
        participants = conversation.get('participants', {}).get('data', [])
        if list_only:
            print(json.dumps({'conversation_id': conversation['id'], 'participants': participants,
                              'updated_time': conversation.get('updated_time')}, ensure_ascii=False))
            found += 1
            continue
        if not any(matches(person, sender) for person in participants):
            continue
        found += 1
        # Primero IDs: los detalles enriquecidos se consultan individualmente para
        # que un campo de adjuntos no soportado no impida leer el texto.
        result = client.get(quote(conversation['id'], safe=''), fields=f'messages.limit({limit}){{id,created_time}}')
        for message in result.get('messages', {}).get('data', []):
            path = quote(message['id'], safe='')
            detail = client.get(path, fields='id,created_time,from,to,message')
            if not matches(detail.get('from', {}), sender):
                # Para @username, el nombre puede faltar en from. Usar el ID del
                # participante ya identificado, nunca asumir que un mensaje es entrante.
                ids = {str(p.get('id')) for p in participants if matches(p, sender)}
                if str(detail.get('from', {}).get('id')) not in ids:
                    continue
            for field in ('attachments', 'shares'):
                try:
                    extra = client.get(path, fields='id,' + field)
                    detail[field] = extra.get(field)
                except ReadError as error:
                    detail[field + '_diagnostic'] = str(error)
            output = json.dumps({'conversation_id': conversation['id'], **detail}, ensure_ascii=False)
            print(output.replace(client.token, '[TOKEN OCULTO]'))
            count += 1
    if list_only:
        print(f'Conversaciones listadas: {found}. No se consultó el contenido de mensajes.')
    else:
        print(f'Conversaciones coincidentes: {found}. Mensajes entrantes mostrados: {count}.')
        if not count:
            print('Sin resultados no demuestra que no haya DMs: revisa ID, permisos, roles, solicitudes y límites de consulta.')
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--login', choices=['unified', 'instagram'], default='unified')
    parser.add_argument('--account-id', help='ID de la cuenta receptora; por defecto IG_USER_ID')
    parser.add_argument('--prompt-token', action='store_true')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--list-conversations', action='store_true', help='Listar participantes e IDs, sin contenido')
    mode.add_argument('--sender', help='ID de mensajería del remitente o @username si Meta lo devuelve')
    parser.add_argument('--limit', type=int, default=10, choices=range(1, 21), metavar='1-20')
    parser.add_argument('--max-pages', type=int, default=5, choices=range(1, 51), metavar='1-50')
    args = parser.parse_args()
    load_env()
    account = args.account_id or os.getenv('IG_USER_ID', '').strip()
    if not re.fullmatch(r'\d+', account):
        parser.error('Configura IG_USER_ID o --account-id numérico.')
    version = os.getenv('GRAPH_API_VERSION', '').strip()
    if version and not re.fullmatch(r'v\d+\.\d+', version):
        parser.error('GRAPH_API_VERSION debe ser vNN.N o vacía.')
    token = '' if args.prompt_token else os.getenv('IG_ACCESS_TOKEN', '').strip()
    token = token or getpass.getpass('Token de Instagram (entrada oculta): ').strip()
    if not token or token == 'REEMPLAZAR' or any(c.isspace() for c in token):
        parser.error('Usa únicamente un token válido, sin Bearer ni espacios.')
    if args.sender and not re.fullmatch(r'@?[A-Za-z0-9_.]+', args.sender):
        parser.error('--sender debe ser un ID numérico o username, sin URL.')
    client = Client(token, args.login, version)
    print(f'Prueba GET de mensajería ({args.login}) en {client.base}. No se envía ni publica nada.')
    if args.login == 'unified':
        profile = client.get(account, fields='id,username')
        if str(profile.get('id')) != account:
            raise ReadError('La identidad de la cuenta no coincide.')
    else:
        profile = client.get('me', fields='user_id,username')
        if str(profile.get('user_id')) != account:
            raise ReadError('La identidad de la cuenta no coincide.')
    expected = os.getenv('IG_EXPECTED_USERNAME', '').strip().lstrip('@')
    if expected and profile.get('username', '').casefold() != expected.casefold():
        raise ReadError('La cuenta no coincide con IG_EXPECTED_USERNAME.')
    print('Cuenta receptora: @' + profile.get('username', '(sin username)'))
    inspect(client, account, args.sender, args.max_pages, args.limit, args.list_conversations)
    print('Prueba finalizada. Las URLs de adjuntos pueden ser temporales; no se descargaron.')


if __name__ == '__main__':
    try:
        main()
    except (ReadError, OSError) as error:
        print(f'Error: {error}')
        print('Comprueba permisos de mensajería, roles y flujo de login. No cambies el token/host de publicación que ya funciona.')
        raise SystemExit(1)
    except KeyboardInterrupt:
        print('\nPrueba interrumpida.')
