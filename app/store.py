from contextlib import contextmanager
import sqlite3
import time
import uuid


class Store:
    def __init__(self, path):
        self.path = str(path)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, update_id INTEGER UNIQUE NOT NULL,
                    chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
                    source_url TEXT NOT NULL, shortcode TEXT NOT NULL,
                    account TEXT NOT NULL, version TEXT NOT NULL,
                    caption TEXT NOT NULL, status TEXT NOT NULL,
                    created REAL NOT NULL, updated REAL NOT NULL,
                    container_id TEXT, media_id TEXT, permalink TEXT,
                    error TEXT, cleanup TEXT NOT NULL DEFAULT 'PENDING',
                    UNIQUE(account, shortcode)
                );
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
                CREATE TABLE IF NOT EXISTS events (
                    job_id TEXT, status TEXT, created REAL
                );
                CREATE TABLE IF NOT EXISTS outbox (
                    id INTEGER PRIMARY KEY, chat_id INTEGER, text TEXT,
                    attempts INTEGER DEFAULT 0, due REAL DEFAULT 0,
                    sent INTEGER DEFAULT 0
                );
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def offset(self):
        with self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key='offset'").fetchone()
            return int(row[0]) if row else 0

    def bind_bot(self, bot_id):
        with self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key='bot_id'").fetchone()
            if row and row[0] != str(bot_id):
                raise RuntimeError('Esta base de datos pertenece a otro bot. Usa un DATA_DIR diferente.')
            db.execute("INSERT OR IGNORE INTO settings VALUES ('bot_id',?)", (str(bot_id),))

    def receive(self, update_id, message, request=None, reply=None, account='', version=''):
        """Aceptar trabajo, respuesta y offset en una sola transacción."""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT value FROM settings WHERE key='offset'").fetchone()
            if row and update_id < int(row[0]):
                return
            if request:
                url, caption = request
                shortcode = url.rstrip('/').rsplit('/', 1)[1]
                existing = db.execute('SELECT * FROM jobs WHERE account=? AND shortcode=?',
                                      (account, shortcode)).fetchone()
                if existing:
                    reply = f"Ya registrado: {existing['id']} ({existing['status']})."
                    if existing['permalink']:
                        reply += '\n' + existing['permalink']
                else:
                    job_id = uuid.uuid4().hex
                    now = time.time()
                    db.execute('''INSERT INTO jobs
                        (id,update_id,chat_id,user_id,source_url,shortcode,account,version,
                         caption,status,created,updated) VALUES (?,?,?,?,?,?,?,?,?,'QUEUED',?,?)''',
                        (job_id, update_id, message['chat']['id'], message['from']['id'],
                         url, shortcode, account, version, caption, now, now))
                    db.execute('INSERT INTO events VALUES (?,?,?)', (job_id, 'QUEUED', now))
                    reply = f'Trabajo recibido: {job_id}'
            if reply and message:
                db.execute('INSERT INTO outbox(chat_id,text) VALUES (?,?)',
                           (message['chat']['id'], reply))
            db.execute("INSERT OR REPLACE INTO settings VALUES ('offset',?)", (str(update_id + 1),))

    def get(self, job_id):
        with self.connect() as db:
            return db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()

    def rows(self, sql, args=()):
        with self.connect() as db:
            return db.execute(sql, args).fetchall()

    def change(self, job_id, status, notice=None, **fields):
        allowed = {'container_id', 'media_id', 'permalink', 'error', 'cleanup'}
        if not fields.keys() <= allowed:
            raise ValueError('Campo de estado inválido')
        with self.connect() as db:
            updates = {'status': status, 'updated': time.time(), **fields}
            db.execute('UPDATE jobs SET ' + ','.join(f'{k}=?' for k in updates) + ' WHERE id=?',
                       (*updates.values(), job_id))
            db.execute('INSERT INTO events VALUES (?,?,?)', (job_id, status, time.time()))
            if notice:
                row = db.execute('SELECT chat_id FROM jobs WHERE id=?', (job_id,)).fetchone()
                db.execute('INSERT INTO outbox(chat_id,text) VALUES (?,?)',
                           (row[0], f'{job_id}: {notice}'))

    def summary(self, user_id):
        rows = self.rows('SELECT id,status,permalink FROM jobs WHERE user_id=? ORDER BY created DESC LIMIT 5',
                         (user_id,))
        return '\n'.join(f"{r['id']}: {r['status']} {r['permalink'] or ''}" for r in rows) or 'Sin trabajos.'
