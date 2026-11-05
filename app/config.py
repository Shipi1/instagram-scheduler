from dataclasses import dataclass
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from scripts.check_auth import load_env


@dataclass
class Config:
    telegram_token: str
    ig_token: str
    account: str
    version: str
    expected: str
    caption: str
    users: Path
    data: Path
    public: Path
    public_url: str
    publish: bool
    cookies: str

    @classmethod
    def load(cls):
        load_env()
        def required(key):
            value = os.getenv(key, '').strip()
            if not value or value == 'REEMPLAZAR':
                raise RuntimeError(f'Configura {key}.')
            return value
        tg, ig = required('TELEGRAM_BOT_TOKEN'), required('IG_ACCESS_TOKEN')
        if any(c.isspace() for c in tg + ig) or ':' not in tg:
            raise RuntimeError('Formato de token inválido.')
        account, version = required('IG_USER_ID'), required('GRAPH_API_VERSION')
        if not account.isdigit() or not re.fullmatch(r'v\d+\.\d+', version):
            raise RuntimeError('Revisa IG_USER_ID y GRAPH_API_VERSION (vNN.N).')
        url = required('PUBLIC_MEDIA_BASE_URL').rstrip('/')
        parts = urlsplit(url)
        if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
            raise RuntimeError('PUBLIC_MEDIA_BASE_URL debe ser HTTPS sin credenciales ni parámetros.')
        data = Path(os.getenv('DATA_DIR', './data')).expanduser().resolve()
        public = Path(required('PUBLIC_MEDIA_DIR')).expanduser().resolve()
        users = Path(os.getenv('TELEGRAM_USERS_FILE', './config/telegram_users.json')).expanduser().resolve()
        root = Path(__file__).resolve().parents[1]
        if (data == public or data in public.parents or public in data.parents
                or root == public or public in root.parents
                or public == users or public in users.parents):
            raise RuntimeError('Las carpetas pública, privada y de configuración deben estar separadas.')
        for folder in (data, data / 'work', public):
            folder.mkdir(parents=True, exist_ok=True)
        caption = os.getenv('DEFAULT_REEL_CAPTION', '')
        if len(caption) > 2200:
            raise RuntimeError('DEFAULT_REEL_CAPTION supera 2200 caracteres.')
        publish = os.getenv('PUBLISH_ENABLED', 'false').lower()
        if publish not in {'true', 'false'}:
            raise RuntimeError('PUBLISH_ENABLED debe ser true o false.')
        cookies = os.getenv('INSTAGRAM_COOKIES_FILE', '').strip()
        if cookies and (not Path(cookies).is_file() or public in Path(cookies).resolve().parents):
            raise RuntimeError('Revisa INSTAGRAM_COOKIES_FILE; debe ser privado y existir.')
        return cls(tg, ig, account, version, required('IG_EXPECTED_USERNAME').lstrip('@'),
                   caption, users, data, public, url, publish == 'true', cookies)
