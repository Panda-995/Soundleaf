"""SQLite state and encrypted provider configuration; all state lives under DATA_DIR."""

import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from cryptography.fernet import Fernet

DEFAULTS = {
    "tts": {
        "provider": "minimax",
        "base_url": "https://api.minimax.cn/v1",
        "model": "speech-2.6-hd",
        "voice": "male-qn-qingse",
        "api_key": "",
        "allow_local": False,
    },
    "ai": {"base_url": "", "model": "", "api_key": "", "allow_local": False, "image_model": ""},
    "voices": [],
    "favorites": [],
    "paused": False,
}


def uid():
    return uuid.uuid4().hex


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        for folder in ("sources", "audio", "cache", "exports", "tmp", "covers"):
            (self.root / folder).mkdir(exist_ok=True)
        key_path = self.root / "secret.key"
        if not key_path.exists():
            try:
                fd = os.open(key_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(fd, "wb") as f:
                    f.write(Fernet.generate_key())
            except FileExistsError:
                pass
        self.cipher = Fernet(key_path.read_bytes())
        self.path = self.root / "studio.sqlite3"
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, name TEXT UNIQUE NOT NULL, password TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS books (id TEXT PRIMARY KEY, title TEXT NOT NULL, author TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL, created REAL NOT NULL, voice TEXT NOT NULL DEFAULT '', cover TEXT);
                CREATE TABLE IF NOT EXISTS imports (id TEXT PRIMARY KEY, name TEXT NOT NULL, source TEXT NOT NULL,
                    chapters TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS chapters (id TEXT PRIMARY KEY, book_id TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
                    position INTEGER NOT NULL, title TEXT NOT NULL, source TEXT NOT NULL, text TEXT NOT NULL,
                    segments TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1, active_audio TEXT,
                    suggestion TEXT, excluded INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS audio (id TEXT PRIMARY KEY, chapter_id TEXT REFERENCES chapters(id) ON DELETE CASCADE,
                    revision INTEGER NOT NULL, path TEXT NOT NULL, duration REAL NOT NULL, peaks TEXT NOT NULL,
                    timeline TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, kind TEXT NOT NULL, book_id TEXT,
                    chapter_id TEXT, status TEXT NOT NULL, stage TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0,
                    total INTEGER NOT NULL DEFAULT 0, payload TEXT NOT NULL, error TEXT NOT NULL DEFAULT '',
                    cancel INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL, updated REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS job_status ON jobs(status, created);
                CREATE INDEX IF NOT EXISTS chapter_book ON chapters(book_id, position);
                CREATE TABLE IF NOT EXISTS exports (id TEXT PRIMARY KEY, book_id TEXT NOT NULL, path TEXT NOT NULL,
                    format TEXT NOT NULL, created REAL NOT NULL, count INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS cast (book_id TEXT NOT NULL, speaker TEXT NOT NULL, voice TEXT NOT NULL,
                    updated REAL NOT NULL, PRIMARY KEY (book_id, speaker));
                CREATE TABLE IF NOT EXISTS dict (book_id TEXT NOT NULL, word TEXT NOT NULL, replacement TEXT NOT NULL,
                    updated REAL NOT NULL, PRIMARY KEY (book_id, word));
                CREATE TABLE IF NOT EXISTS progress (book_id TEXT PRIMARY KEY, audio_id TEXT NOT NULL, seconds REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS marks (id TEXT PRIMARY KEY, chapter_id TEXT NOT NULL, seconds REAL NOT NULL,
                    note TEXT NOT NULL, created REAL NOT NULL);
            """)
            # Light migrations for columns added after v0.1.
            for statement in (
                "ALTER TABLE books ADD COLUMN style TEXT",
                "ALTER TABLE books ADD COLUMN intro TEXT",
                "ALTER TABLE books ADD COLUMN cast_version INTEGER NOT NULL DEFAULT 1",
                "ALTER TABLE audio ADD COLUMN quality TEXT",
                "ALTER TABLE audio ADD COLUMN cast_version INTEGER",
                "ALTER TABLE chapters ADD COLUMN stale_segments TEXT",
            ):
                try:
                    db.execute(statement)
                except sqlite3.OperationalError:
                    pass  # column already exists

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def rows(self, sql, args=()):
        with self.connect() as db:
            return [dict(r) for r in db.execute(sql, args)]

    def one(self, sql, args=()):
        rows = self.rows(sql, args)
        return rows[0] if rows else None

    def execute(self, sql, args=()):
        with self.connect() as db:
            return db.execute(sql, args).rowcount

    def get(self, key):
        row = self.one("SELECT value FROM settings WHERE key=?", (key,))
        if row:
            return json.loads(self.cipher.decrypt(row["value"].encode()))
        return json.loads(json.dumps(DEFAULTS.get(key)))

    def set(self, key, value):
        encrypted = self.cipher.encrypt(json.dumps(value).encode()).decode()
        self.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, encrypted))

    def file(self, relative):
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("文件路径无效")
        return path

    def job(self, kind, payload, book_id=None, chapter_id=None, db=None):
        """Insert a queued job. Pass an open transaction's ``db`` (BEGIN
        IMMEDIATE) to make a check-then-enqueue sequence atomic."""
        ident = uid()
        sql = (
            "INSERT INTO jobs (id,kind,book_id,chapter_id,status,stage,payload,created,updated) "
            "VALUES (?,?,?,?,?,?,?,?,?)"
        )
        args = (
            ident,
            kind,
            book_id,
            chapter_id,
            "queued",
            "等待处理",
            json.dumps(payload, ensure_ascii=False),
            time.time(),
            time.time(),
        )
        if db is not None:
            db.execute(sql, args)
        else:
            self.execute(sql, args)
        return ident
