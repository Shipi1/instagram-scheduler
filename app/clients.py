import hashlib
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener

from scripts.check_auth import NoRedirect


class RemoteError(RuntimeError):
    pass


class Instagram:
    def __init__(self, config):
        self.config = config
        self.base = f'https://graph.facebook.com/{config.version}'

    def call(self, method, path, **params):
        url = self.base + '/' + path
        if method == 'GET':
            url += '?' + urlencode(params)
        request = Request(url, method=method,
                          data=urlencode(params).encode() if method == 'POST' else None,
                          headers={'Authorization': 'Bearer ' + self.config.ig_token})
        try:
            with build_opener(NoRedirect()).open(request, timeout=45) as response:
                result = json.load(response)
            if not isinstance(result, dict) or 'error' in result:
                raise RemoteError('Respuesta de Meta inválida.')
            return result
        except HTTPError as error:
            # La respuesta puede contener información sensible; registrar solo el código.
            raise RemoteError(f'Meta HTTP {error.code}.') from None
        except (URLError, TimeoutError, OSError, ValueError):
            raise RemoteError('Meta: conexión fallida o respuesta inválida.') from None

    def identity(self):
        result = self.call('GET', self.config.account, fields='id,username')
        if (str(result.get('id')) != self.config.account
                or result.get('username', '').casefold() != self.config.expected.casefold()):
            raise RemoteError('La cuenta de Instagram no coincide con la configurada.')


def verify_public(url, file):
    """Descarga sin redirecciones y compara todos los bytes antes de llamar a Meta."""
    with file.open('rb') as source:
        expected = hashlib.file_digest(source, 'sha256').digest()
    try:
        with build_opener(NoRedirect()).open(url, timeout=60) as response:
            if response.status != 200 or response.headers.get_content_type() != 'video/mp4':
                raise RemoteError('La URL pública no devuelve HTTP 200 video/mp4.')
            digest, total = hashlib.sha256(), 0
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > file.stat().st_size:
                    raise RemoteError('El archivo HTTPS no coincide con el preparado.')
                digest.update(chunk)
            if total != file.stat().st_size or digest.digest() != expected:
                raise RemoteError('El archivo HTTPS no coincide con el preparado.')
    except (URLError, OSError, TimeoutError):
        raise RemoteError('No se pudo verificar la descarga HTTPS pública.') from None
