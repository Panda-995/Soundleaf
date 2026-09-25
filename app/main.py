"""HTTP application and same-origin session API."""

import asyncio
import hashlib
import json
import os
import re
import secrets
import shutil
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from app import importer, providers
from app.audio import safe_name
from app.cover import render_cover_svg
from app.security import password_hash, password_valid, validate_url
from app.store import Store, uid
from app.worker import (
    Worker,
    apply_pronunciation,
    book_pronunciation,
    norm_speaker,
    top_vote,
)


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# First run seeds this account; the client is forced to replace the password
# on first login (see must_change_password). The short default never passes
# the 8-character minimum for new passwords.
DEFAULT_USER = "admin"
DEFAULT_PASSWORD = "admin"


class Login(Model):
    # Minimum is 1 because the seeded default password is short; anything set
    # through /api/account/password still enforces the 8-character floor.
    name: str = Field(min_length=1, max_length=60)
    password: str = Field(min_length=1, max_length=200)


class PasswordChange(Model):
    current: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8, max_length=200)


class Segment(Model):
    text: str = Field(max_length=1200)
    voice: str = Field(default="", max_length=200)
    emotion: str = "neutral"
    speed: float = Field(default=1, ge=0.6, le=1.4)
    pause: int = Field(default=250, ge=0, le=3000)
    speaker: str = Field(default="旁白", max_length=60)


class PreviewBody(Segment):
    """Short audition; carries the book so its pronunciation dictionary applies."""

    book_id: str = Field(default="", max_length=64)


class ApplyMeta(Model):
    """AI-suggested book information, applied after the user edits it. A
    palette of 2+ colors also (re)generates the vector cover; without one the
    existing cover is kept (e.g. when an AI-drawn image cover is used). A
    field left out (None) keeps the stored value."""

    title: str = Field(default="", max_length=200)
    author: str = Field(default="", max_length=60)
    intro: str | None = None
    palette: list[str] = Field(default_factory=list, max_length=4)
    mood: str = Field(default="", max_length=12)


class ChapterSave(Model):
    revision: int
    title: str = Field(min_length=1, max_length=200)
    segments: list[Segment] = Field(min_length=1, max_length=4000)


class ImportChapter(Model):
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(max_length=2_000_000)


class ImportConfirm(Model):
    id: str
    title: str = Field(min_length=1, max_length=200)
    author: str = Field(default="", max_length=100)
    chapters: list[ImportChapter] = Field(min_length=1, max_length=1000)


class Selection(Model):
    chapter_ids: list[str] = Field(min_length=1, max_length=1000)


class NotifyModel(Model):
    enabled: bool = False
    kind: str = Field(default="ntfy", max_length=20)
    url: str = Field(default="", max_length=500)


class ExportSelection(Selection):
    format: str = "mp3"
    allow_stale: bool = False
    embed: bool = True


class Config(Model):
    provider: str = "minimax"
    base_url: str = Field(default="", max_length=500)
    model: str = Field(default="", max_length=150)
    voice: str = Field(default="", max_length=200)
    api_key: str = Field(default="", max_length=1000)
    allow_local: bool = False
    image_model: str = Field(default="", max_length=100)


def public_config(config):
    return {**{k: v for k, v in config.items() if k != "api_key"}, "has_key": bool(config.get("api_key"))}


def create_app(data_dir=None, start_worker=True):
    store = Store(data_dir or os.environ.get("DATA_DIR", "data"))
    if not store.one("SELECT id FROM users LIMIT 1"):
        store.execute(
            "INSERT INTO users VALUES (?,?,?)",
            (uid(), DEFAULT_USER, password_hash(DEFAULT_PASSWORD)),
        )
    worker = Worker(store)
    login_failures = {}
    pw_failures = {}
    # User ids whose password provably no longer matches the seeded default;
    # spares every later bootstrap/login a needless PBKDF2 round. Process
    # memory like the rate limiters: after a restart the check runs once more.
    default_changed = set()

    @asynccontextmanager
    async def lifespan(app):
        if start_worker:
            worker.start()
        yield
        worker.stop.set()
        if start_worker:
            await asyncio.to_thread(worker.thread.join, 5)

    app = FastAPI(title="声页", version="1.1.0", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.store = store
    app.state.worker = worker

    @app.middleware("http")
    async def guard(request, call_next):
        path = request.url.path
        if path.startswith("/api/"):
            try:
                content_length = int(request.headers.get("content-length", "0") or 0)
            except ValueError:
                return JSONResponse({"detail": "请求长度无效"}, 400)
            if content_length > 52 * 1024 * 1024:
                return JSONResponse({"detail": "请求超过 50MB 限制"}, 413)
            if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("x-soundleaf") != "1":
                return JSONResponse({"detail": "请求来源无效，请刷新页面"}, 403)
            # Chunked bodies carry no content-length and would bypass the cap.
            if "chunked" in request.headers.get("transfer-encoding", "").lower():
                return JSONResponse({"detail": "请求体无效或超过大小限制"}, 413)
            if path not in ("/api/bootstrap", "/api/login"):
                token = request.cookies.get("soundleaf", "")
                session = store.one(
                    "SELECT * FROM sessions WHERE token=? AND expires>?",
                    (hashlib.sha256(token.encode()).hexdigest(), time.time()),
                )
                if not session:
                    return JSONResponse({"detail": "请先登录"}, 401)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        # The built frontend is fully self-contained (external bundle, no fonts,
        # no CDN); inline style attributes need 'unsafe-inline', audio plays
        # from same-origin and blob: URLs.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; "
            "font-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
        )
        if path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ValueError)
    async def value_error(request, exc):
        return JSONResponse({"detail": str(exc)}, 400)

    @app.exception_handler(providers.UncertainResult)
    async def network_error(request, exc):
        return JSONResponse({"detail": str(exc)}, 502)

    def chapter(ident):
        row = store.one("SELECT * FROM chapters WHERE id=?", (ident,))
        if not row:
            raise HTTPException(404, "章节不存在")
        return row

    def book(ident):
        row = store.one("SELECT * FROM books WHERE id=?", (ident,))
        if not row:
            raise HTTPException(404, "书籍不存在")
        return row

    def snapshot(config):
        return store.cipher.encrypt(json.dumps(config).encode()).decode()

    @app.get("/health/live")
    def live():
        return {"status": "ok"}

    @app.get("/health/ready")
    def ready():
        store.one("SELECT 1")
        writable = os.access(store.root, os.W_OK)
        alive = worker.thread.is_alive() if start_worker else True
        return JSONResponse(
            {"ready": writable and alive, "worker": alive, "data_writable": writable},
            200 if writable and alive else 503,
        )

    def current_user(request: Request):
        token = hashlib.sha256(request.cookies.get("soundleaf", "").encode()).hexdigest()
        session = store.one(
            "SELECT user_id FROM sessions WHERE token=? AND expires>?", (token, time.time())
        )
        if not session:
            return None
        return store.one("SELECT * FROM users WHERE id=?", (session["user_id"],))

    def still_default_password(user):
        """Whether the account still carries the seeded default password.
        A negative answer is memoized for the process lifetime: the API can
        never set the password back to the default (8-char floor), so one
        verified "changed" saves all future bootstraps the PBKDF2 round."""
        if user["id"] in default_changed:
            return False
        if password_valid(DEFAULT_PASSWORD, user["password"]):
            return True
        default_changed.add(user["id"])
        return False

    @app.get("/api/bootstrap")
    def bootstrap(request: Request):
        user = current_user(request)
        return {
            "authenticated": bool(user),
            # While the seeded default password is still in force, the client
            # keeps asking for a replacement — including after a page reload.
            "must_change_password": bool(user) and still_default_password(user),
        }

    def issue_session(user_id, response):
        token = secrets.token_urlsafe(32)
        store.execute("DELETE FROM sessions WHERE expires<?", (time.time(),))
        store.execute(
            "INSERT INTO sessions VALUES (?,?,?)",
            (hashlib.sha256(token.encode()).hexdigest(), user_id, time.time() + 7 * 86400),
        )
        response.set_cookie(
            "soundleaf",
            token,
            httponly=True,
            samesite="strict",
            max_age=7 * 86400,
            secure=os.environ.get("COOKIE_SECURE") == "true",
        )
        return {"ok": True}

    @app.post("/api/login")
    def login(body: Login, request: Request, response: Response):
        host = request.client.host
        attempts = [t for t in login_failures.get(host, []) if t > time.time() - 300]
        if len(attempts) >= 8:
            raise HTTPException(429, "尝试次数过多，请 5 分钟后再试")
        row = store.one("SELECT * FROM users WHERE name=?", (body.name,))
        if not row or not password_valid(body.password, row["password"]):
            login_failures[host] = attempts + [time.time()]
            raise HTTPException(401, "用户名或密码不正确")
        login_failures.pop(host, None)
        result = issue_session(row["id"], response)
        result["must_change_password"] = still_default_password(row)
        return result

    @app.post("/api/account/password")
    def change_password(body: PasswordChange, request: Request):
        user = current_user(request)
        if not user:
            raise HTTPException(401, "请先登录")
        host = request.client.host
        attempts = [t for t in pw_failures.get(host, []) if t > time.time() - 300]
        if len(attempts) >= 8:
            raise HTTPException(429, "尝试次数过多，请 5 分钟后再试")
        if not password_valid(body.current, user["password"]):
            pw_failures[host] = attempts + [time.time()]
            raise HTTPException(401, "当前密码不正确")
        pw_failures.pop(host, None)
        store.execute(
            "UPDATE users SET password=? WHERE id=?", (password_hash(body.password), user["id"])
        )
        # The new password invalidates every other device's session; this
        # request's own session stays so the current page remains signed in.
        token = hashlib.sha256(request.cookies.get("soundleaf", "").encode()).hexdigest()
        store.execute("DELETE FROM sessions WHERE user_id=? AND token<>?", (user["id"], token))
        default_changed.add(user["id"])
        return {"ok": True}

    @app.post("/api/logout")
    def logout(request: Request, response: Response):
        token = hashlib.sha256(request.cookies.get("soundleaf", "").encode()).hexdigest()
        store.execute("DELETE FROM sessions WHERE token=?", (token,))
        response.delete_cookie("soundleaf")
        return {"ok": True}

    @app.get("/api/settings")
    def settings():
        usage = shutil.disk_usage(store.root)
        return {
            "tts": public_config(store.get("tts")),
            "ai": public_config(store.get("ai")),
            "notify": store.get("notify"),
            "paused": store.get("paused"),
            "favorites": store.get("favorites"),
            "data_dir": str(store.root),
            "free_bytes": usage.free,
            "total_bytes": usage.total,
        }

    @app.put("/api/settings/notify")
    def save_notify_settings(body: NotifyModel):
        store.set("notify", body.model_dump())
        return body.model_dump()

    @app.post("/api/settings/notify/test")
    def test_notify_settings():
        error = providers.send_notification(
            store.get("notify") or {},
            "声页测试通知",
            "如果你看到这条消息，说明完成通知配置成功。",
        )
        if error:
            raise ValueError(f"通知发送失败：{error}")
        return {"message": "测试通知已发送"}

    @app.put("/api/settings/{kind}")
    def save_settings(kind: str, body: Config):
        if kind not in ("ai", "tts"):
            raise HTTPException(404)
        value = body.model_dump()
        if value["base_url"]:
            value["base_url"] = validate_url(value["base_url"], value["allow_local"])
        if kind == "tts" and body.provider not in ("minimax", "compatible"):
            raise ValueError("不支持的语音服务类型")
        if not value["api_key"]:
            value["api_key"] = store.get(kind).get("api_key", "")
        store.set(kind, value)
        if kind == "tts":
            store.set("voices", [])
        return public_config(value)

    @app.post("/api/settings/{kind}/test")
    def test_settings(kind: str):
        if kind not in ("ai", "tts"):
            raise HTTPException(404)
        config = store.get(kind)
        if kind == "tts" and config["provider"] == "minimax":
            voices = providers.list_voices(config)
            store.set("voices", voices)
            return {"message": f"已连接，获取到 {len(voices)} 个音色"}
        url = validate_url(config["base_url"], config.get("allow_local"))
        try:
            with httpx.Client(timeout=15, trust_env=False, follow_redirects=False) as client:
                result = client.get(
                    url + "/models", headers={"Authorization": "Bearer " + config.get("api_key", "")}
                )
            if result.status_code != 200:
                raise ValueError(
                    f"模型目录返回 HTTP {result.status_code}；部分兼容服务不提供模型目录，可用短试听验证"
                )
        except httpx.HTTPError as exc:
            raise ValueError("无法连接服务，请检查地址和网络") from exc
        return {"message": "模型目录可访问；具体模型和音色请使用短试听验证"}

    @app.get("/api/voices")
    def voices():
        values = store.get("voices")
        config = store.get("tts")
        if not values and config.get("voice"):
            values = [
                {
                    "id": config["voice"],
                    "name": config["voice"],
                    "description": "当前配置音色",
                    "category": "custom",
                }
            ]
        return {
            "voices": values,
            "emotion": config["provider"] == "minimax",
            "favorites": store.get("favorites"),
        }

    @app.post("/api/voices/refresh")
    def refresh_voices():
        values = providers.list_voices(store.get("tts"))
        store.set("voices", values)
        return {"count": len(values)}

    @app.post("/api/voices/favorite")
    def favorite(body: dict):
        value = str(body.get("voice", ""))[:200]
        values = store.get("favorites")
        if value in values:
            values.remove(value)
        elif len(values) < 200:
            values.append(value)
        store.set("favorites", values)
        return values

    @app.post("/api/imports")
    def upload(file: UploadFile, encoding: str = "auto"):
        filename = file.filename or ""
        if not filename:
            raise HTTPException(400, "请选择要上传的文件")
        data = file.file.read(50 * 1024 * 1024 + 1)
        if len(data) > 50 * 1024 * 1024:
            raise HTTPException(413, "文件不能超过 50MB")
        chapters, codec = importer.parse(data, filename, encoding)
        ident = uid()
        relative = f"sources/{ident}{Path(filename).suffix.lower()}"
        store.file(relative).write_bytes(data)
        store.execute(
            "INSERT INTO imports VALUES (?,?,?,?,?)",
            (ident, filename, relative, json.dumps(chapters, ensure_ascii=False), time.time()),
        )
        return {"id": ident, "name": Path(filename).stem, "chapters": chapters, "encoding": codec}

    @app.post("/api/imports/confirm")
    def confirm(body: ImportConfirm):
        if sum(len(c.text) for c in body.chapters) > importer.MAX_TEXT:
            raise ValueError("正文超过 200 万字")
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            source = db.execute("SELECT * FROM imports WHERE id=?", (body.id,)).fetchone()
            if not source:
                raise HTTPException(409, "导入记录已确认或失效，请重新上传")
            ident = uid()
            db.execute(
                "INSERT INTO books (id,title,author,source,created) VALUES (?,?,?,?,?)",
                (ident, body.title, body.author, source["source"], time.time()),
            )
            for i, c in enumerate(body.chapters):
                db.execute(
                    "INSERT INTO chapters (id,book_id,position,title,source,text,segments) VALUES (?,?,?,?,?,?,?)",
                    (
                        uid(),
                        ident,
                        i + 1,
                        c.title,
                        c.text,
                        c.text,
                        json.dumps(importer.segments(c.text), ensure_ascii=False),
                    ),
                )
            db.execute("DELETE FROM imports WHERE id=?", (body.id,))
        return {"id": ident}

    @app.get("/api/books")
    def books():
        return store.rows(
            "SELECT b.*,count(c.id) chapters,sum(CASE WHEN c.active_audio IS NOT NULL THEN 1 ELSE 0 END) completed "
            "FROM books b LEFT JOIN chapters c ON c.book_id=b.id GROUP BY b.id ORDER BY b.created DESC"
        )

    @app.get("/api/books/{ident}")
    def get_book(ident: str):
        row = book(ident)
        row["chapters"] = store.rows(
            "SELECT c.id,c.title,c.position,c.revision,c.active_audio,c.excluded,"
            "length(c.text) characters,a.duration,a.revision audio_revision,"
            "(CASE WHEN a.cast_version IS NOT NULL AND a.cast_version!=b.cast_version "
            "THEN 1 ELSE 0 END) voice_stale,"
            "(CASE WHEN c.stale_segments IS NOT NULL THEN json_array_length(c.stale_segments) "
            "ELSE 0 END) stale_count "
            "FROM chapters c LEFT JOIN audio a ON c.active_audio=a.id "
            "LEFT JOIN books b ON b.id=c.book_id WHERE c.book_id=? ORDER BY c.position",
            (ident,),
        )
        return row

    @app.put("/api/books/{ident}")
    def update_book(ident: str, body: dict):
        row = book(ident)
        voice = str(body.get("voice", row["voice"]))[:200]
        title = str(body.get("title", row["title"])).strip()[:200]
        if not title:
            raise ValueError("书名不能为空")
        intro_raw = body.get("intro")
        intro = str(intro_raw).strip()[:2000] if isinstance(intro_raw, str) else row["intro"]
        style_raw = body.get("style")
        style = None
        if isinstance(style_raw, dict):
            try:
                style = json.dumps(
                    {
                        "preset": str(style_raw.get("preset") or "immersive")[:40],
                        "narration_speed": max(0.7, min(1.3, float(style_raw.get("narration_speed") or 1))),
                        "dialogue_pause": max(0.4, min(2.5, float(style_raw.get("dialogue_pause") or 1))),
                        "narration_pause": max(0.4, min(2.5, float(style_raw.get("narration_pause") or 1))),
                    }
                )
            except (TypeError, ValueError):
                style = None
        changed_voice = voice != row["voice"]
        if changed_voice and voice:
            # Same whitelist rule as cast bindings, checked only when the voice
            # actually changes so editing title/style never needs a re-sync.
            allowed = {v["id"] for v in store.get("voices")}
            configured = store.get("tts").get("voice")
            if configured:
                allowed.add(configured)
            if voice not in allowed:
                raise ValueError("未知音色，请从音色列表中选择")
        changed_style = style is not None and style != row["style"]
        with store.connect() as db:
            db.execute(
                "UPDATE books SET title=?,voice=?,style=?,intro=? WHERE id=?",
                (title, voice, style if style is not None else row["style"], intro, ident),
            )
            if changed_voice:
                db.execute(
                    "UPDATE chapters SET revision=revision+1,suggestion=NULL WHERE book_id=?", (ident,)
                )
            elif changed_style:
                # Style changes affect the delivered audio but not the script
                # or the AI suggestions, so only the revision is bumped.
                db.execute("UPDATE chapters SET revision=revision+1 WHERE book_id=?", (ident,))
            # Narrator-voice or style changes affect EVERY segment of chapters
            # with audio. Mark all indices in stale_segments so partial regens
            # clear the flag one segment at a time instead of the whole
            # chapter at once (the revision bump alone would be wiped by the
            # first partial regen's promotion).
            if changed_voice or changed_style:
                for ch in db.execute(
                    "SELECT id,segments FROM chapters WHERE book_id=? AND active_audio IS NOT NULL",
                    (ident,),
                ).fetchall():
                    count = len(json.loads(ch["segments"]))
                    db.execute(
                        "UPDATE chapters SET stale_segments=? WHERE id=?",
                        (json.dumps(list(range(count))), ch["id"]),
                    )
        return {"ok": True}

    @app.get("/api/books/{ident}/cast")
    def get_cast(ident: str):
        """Book-level character table: every speaker with line counts, its
        bound voice (book cast wins, else chapter majority), and which
        chapters contain it."""
        row = book(ident)
        cast_rows = {
            r["speaker"]: r["voice"]
            for r in store.rows("SELECT speaker,voice FROM cast WHERE book_id=?", (ident,))
        }
        speakers: dict = {}
        narration_lines = 0
        voice_counts: dict = {}
        chapter_info = []
        for c in store.rows(
            "SELECT id,title,position,active_audio,revision,segments FROM chapters WHERE book_id=? ORDER BY position",
            (ident,),
        ):
            present = set()
            for s in json.loads(c["segments"]):
                speaker = norm_speaker(s.get("speaker"))
                voice = (s.get("voice") or "").strip()
                if speaker == "旁白":
                    narration_lines += 1
                    continue
                present.add(speaker)
                entry = speakers.setdefault(
                    speaker,
                    {"speaker": speaker, "lines": 0, "sample": (s.get("text") or "").strip()[:60]},
                )
                entry["lines"] += 1
                if voice:
                    voice_counts.setdefault(speaker, {})
                    voice_counts[speaker][voice] = voice_counts[speaker].get(voice, 0) + 1
            chapter_info.append(
                {
                    "id": c["id"],
                    "title": c["title"],
                    "position": c["position"],
                    "has_audio": bool(c["active_audio"]),
                    "speakers": sorted(present),
                }
            )
        # Chapter-majority fallback for speakers the cast table does not know.
        majorities = {speaker: top_vote(counts) for speaker, counts in voice_counts.items()}
        cast_list = [
            {
                **speakers[speaker],
                "voice": cast_rows.get(speaker, majorities.get(speaker, "")),
                "bound": speaker in cast_rows,
            }
            for speaker in sorted(speakers, key=lambda s: -speakers[s]["lines"])
        ]
        return {
            "cast": cast_list,
            "narrator_voice": row["voice"],
            "narration_lines": narration_lines,
            "chapters": chapter_info,
        }

    @app.put("/api/books/{ident}/cast")
    def set_cast_voice(ident: str, body: dict):
        """Bind one character to one voice (or clear the binding with an empty
        voice, falling back to the chapter majority). Generation reads the
        cast first, so the change applies book-wide on the next regeneration.
        """
        book(ident)
        speaker = norm_speaker(str(body.get("speaker") or ""))
        voice = str(body.get("voice") or "").strip()[:200]
        if not speaker or speaker == "旁白":
            raise ValueError("旁白使用书籍默认音色，请在下方调整")
        if voice:
            allowed = {v["id"] for v in store.get("voices")}
            if voice not in allowed:
                raise ValueError("未知音色，请从音色列表中选择")
        # A voice change makes existing audio VOICE-stale (it still sounds
        # like the old voice) — but must not act like a script revision bump:
        # that would discard in-flight generation output entirely. Instead a
        # per-book cast_version is stamped onto every generated audio; audio
        # stamped with an older version is surfaced as 音色待更新 in the UI
        # while staying playable.
        # Per-segment voice staleness: every segment whose speaker is the
        # rebound character joins stale_segments, so partial regens clear the
        # flag one segment at a time (the cast_version stamp keeps the
        # chapter-level 音色待更新 badge until the last one is done).
        affected = 0
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE books SET cast_version=cast_version+1 WHERE id=?", (ident,))
            if voice:
                db.execute(
                    "INSERT OR REPLACE INTO cast VALUES (?,?,?,?)",
                    (ident, speaker, voice, time.time()),
                )
            else:
                db.execute("DELETE FROM cast WHERE book_id=? AND speaker=?", (ident, speaker))
            for ch in db.execute(
                "SELECT id,segments,stale_segments FROM chapters "
                "WHERE book_id=?",
                (ident,),
            ).fetchall():
                segs = json.loads(ch["segments"])
                indices = [
                    i
                    for i, sg in enumerate(segs)
                    if norm_speaker((sg or {}).get("speaker")) == speaker
                ]
                if not indices:
                    continue
                prev = json.loads(ch["stale_segments"]) if ch["stale_segments"] else []
                merged = sorted(set(prev) | set(indices))
                affected += len(indices)
                db.execute(
                    "UPDATE chapters SET stale_segments=? WHERE id=?",
                    (json.dumps(merged), ch["id"]),
                )
        return {"ok": True, "speaker": speaker, "voice": voice, "affected": affected}

    @app.get("/api/books/{ident}/dict")
    def get_dict(ident: str):
        """Book pronunciation dictionary: words that must be spoken differently
        from their written form (multi-tone characters, names, place names)."""
        book(ident)
        return store.rows(
            "SELECT word,replacement FROM dict WHERE book_id=? ORDER BY updated DESC", (ident,)
        )

    @app.put("/api/books/{ident}/dict")
    def set_dict_entry(ident: str, body: dict):
        """Upsert one entry; an empty replacement removes it. Chapters whose
        text contains the word get their revision bumped so the UI shows which
        audio is now outdated — nothing is re-synthesized automatically."""
        book(ident)
        word = str(body.get("word") or "").strip()
        replacement = str(body.get("replacement") or "").strip()
        if not word or len(word) > 60:
            raise ValueError("词条需要在 1–60 字之间")
        if len(replacement) > 120:
            raise ValueError("替换写法需要在 120 字以内")
        if word == replacement:
            raise ValueError("替换写法与词条相同，没有需要修正的读音")
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            # No-op edits (re-saving an identical entry, deleting a missing
            # one) must not mark generated audio stale.
            old = db.execute(
                "SELECT replacement FROM dict WHERE book_id=? AND word=?", (ident, word)
            ).fetchone()
            if replacement:
                if old and old["replacement"] == replacement:
                    return {"ok": True, "affected": 0}
                # Limit applies only to NEW entries; modifying existing ones
                # is always allowed.
                if not old and (
                    db.execute("SELECT COUNT(*) c FROM dict WHERE book_id=?", (ident,)).fetchone()["c"]
                    >= 200
                ):
                    raise ValueError("每本书最多 200 条读音词条")
                db.execute(
                    "INSERT OR REPLACE INTO dict VALUES (?,?,?,?)",
                    (ident, word, replacement, time.time()),
                )
            else:
                if not old:
                    return {"ok": True, "affected": 0}
                db.execute("DELETE FROM dict WHERE book_id=? AND word=?", (ident, word))
        # Mark ONLY the segments that contain the word stale (per-segment
        # tracking), so regenerating them one by one clears the flag without
        # a full-chapter regeneration. No revision bump: the audio version
        # stays put and partial regens stay meaningful.
        affected = 0
        for ch in store.rows(
            "SELECT id,segments,stale_segments FROM chapters WHERE book_id=?",
            (ident,),
        ):
            segs = json.loads(ch["segments"])
            indices = [i for i, sg in enumerate(segs) if word in (sg.get("text") or "")]
            if not indices:
                continue
            prev = json.loads(ch["stale_segments"]) if ch["stale_segments"] else []
            merged = sorted(set(prev) | set(indices))
            store.execute(
                "UPDATE chapters SET stale_segments=? WHERE id=?",
                (json.dumps(merged), ch["id"]),
            )
            affected += len(indices)
        return {"ok": True, "affected": affected}

    @app.post("/api/books/{ident}/analyze-book")
    def analyze_book(ident: str, body: dict | None = None):
        """One AI call guessing author/intro/tags/cover-palette from a title
        (defaults to the book's own, and may be a custom variant) plus the
        first chapter's opening. Result is a suggestion the user edits and
        applies — nothing is written to the book automatically."""
        row = book(ident)
        title = str((body or {}).get("title") or row["title"]).strip()[:200] or row["title"]
        config = store.get("ai")
        if not config.get("base_url") or not config.get("model"):
            raise ValueError("请先配置 AI 分析服务")
        excerpt_row = store.one(
            "SELECT text FROM chapters WHERE book_id=? ORDER BY position LIMIT 1", (ident,)
        )
        payload = {
            "title": title,
            "excerpt": (excerpt_row["text"] or "")[:400] if excerpt_row else "",
            "config": snapshot(config),
        }
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT id FROM jobs WHERE book_id=? AND kind='analyze_book' "
                "AND status IN ('queued','running','needs_review')",
                (ident,),
            ).fetchone()
            job_id = (
                existing["id"] if existing else store.job("analyze_book", payload, ident, db=db)
            )
        return {"id": job_id}

    @app.post("/api/books/{ident}/generate-cover")
    def generate_cover(ident: str, body: dict | None = None):
        """Draw the book cover with the configured image model (OpenAI-style
        /images/generations). Runs as a job; the finished image is applied as
        the book cover immediately."""
        row = book(ident)
        config = store.get("ai")
        if not config.get("base_url"):
            raise ValueError("请先配置 AI 分析服务的基础地址")
        if not config.get("image_model"):
            raise ValueError("请先在设置 → AI 分析中填写生图模型")
        body = body or {}
        payload = {
            "title": str(body.get("title") or row["title"]).strip()[:200] or row["title"],
            "mood": str(body.get("mood") or "")[:12],
            "tags": [str(t).strip()[:20] for t in (body.get("tags") or []) if str(t).strip()][:6],
            "extra": str(body.get("extra") or "").strip()[:300],
            "config": snapshot(config),
        }
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT id FROM jobs WHERE book_id=? AND kind='generate_cover' "
                "AND status IN ('queued','running')",
                (ident,),
            ).fetchone()
            job_id = (
                existing["id"] if existing else store.job("generate_cover", payload, ident, db=db)
            )
        return {"id": job_id}

    @app.post("/api/books/{ident}/apply-meta")
    def apply_meta(ident: str, body: ApplyMeta):
        """Apply AI-suggested book information: optional title rename,
        author/intro text, and — when a palette was suggested — a generated
        SVG cover drawn from it."""
        row = book(ident)
        title = body.title.strip() or row["title"]
        palette = []
        for token in body.palette:
            if re.fullmatch(r"#?[0-9a-fA-F]{6}", token):
                palette.append("#" + token.lstrip("#").lower())
        cover_relative = row["cover"]
        if len(palette) >= 2:
            svg = render_cover_svg(
                title, body.author.strip() or row["author"], palette, body.mood.strip()
            )
            cover_relative = f"covers/{uid()}.svg"
            store.file(cover_relative).write_text(svg, encoding="utf-8")
        intro = row["intro"] if body.intro is None else body.intro.strip()[:500]
        with store.connect() as db:
            db.execute(
                "UPDATE books SET title=?,author=?,intro=?,cover=? WHERE id=?",
                (title, body.author.strip() or row["author"], intro, cover_relative, ident),
            )
        if cover_relative != row["cover"] and row["cover"]:
            try:
                store.file(row["cover"]).unlink(missing_ok=True)
            except OSError:
                pass
        return {"ok": True}

    def structure(db, ident):
        return [
            dict(r)
            for r in db.execute(
                "SELECT id,revision,position FROM chapters WHERE book_id=? ORDER BY position", (ident,)
            )
        ]

    def require_idle(db, ident):
        if db.execute(
            "SELECT id FROM jobs WHERE book_id=? AND status='running' LIMIT 1", (ident,)
        ).fetchone():
            raise HTTPException(409, "本书仍有任务运行，请取消任务并等待停止后再操作")

    def clear_book_content(db, ident):
        paths = [
            r["path"]
            for r in db.execute(
                "SELECT a.path FROM audio a JOIN chapters c ON c.id=a.chapter_id WHERE c.book_id=?", (ident,)
            )
        ]
        exports = [r["path"] for r in db.execute("SELECT path FROM exports WHERE book_id=?", (ident,))]
        db.execute(
            "DELETE FROM marks WHERE chapter_id IN (SELECT id FROM chapters WHERE book_id=?)", (ident,)
        )
        db.execute("DELETE FROM progress WHERE book_id=?", (ident,))
        db.execute("DELETE FROM exports WHERE book_id=?", (ident,))
        db.execute("DELETE FROM jobs WHERE book_id=?", (ident,))
        # NOTE: cast bindings and the pronunciation dict are BOOK-level and
        # must survive clear_book_content — it also runs when applying an AI
        # chapter re-split, which only replaces chapter content. Full deletion
        # of them happens in delete_book below.
        db.execute("DELETE FROM chapters WHERE book_id=?", (ident,))
        return paths + [str(Path(p).with_suffix(".mp3")) for p in paths] + exports

    def clean_files(paths):
        pending = 0
        for relative in paths:
            if relative:
                try:
                    store.file(relative).unlink(missing_ok=True)
                except OSError:
                    pending += 1
        return pending

    @app.delete("/api/books/{ident}")
    def delete_book(ident: str):
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM books WHERE id=?", (ident,)).fetchone()
            if not row:
                raise HTTPException(404, "书籍不存在")
            require_idle(db, ident)
            paths = clear_book_content(db, ident) + [row["source"], row["cover"]]
            db.execute("DELETE FROM cast WHERE book_id=?", (ident,))
            db.execute("DELETE FROM dict WHERE book_id=?", (ident,))
            db.execute("DELETE FROM books WHERE id=?", (ident,))
        return {"ok": True, "cleanup_pending": clean_files(paths)}

    @app.post("/api/books/{ident}/analyze-chapters")
    def analyze_chapters(ident: str):
        row = book(ident)
        config = store.get("ai")
        if not config.get("base_url") or not config.get("model"):
            raise ValueError("请先配置 AI 分析服务与模型")
        text = importer.source_text(store.file(row["source"]).read_bytes(), row["source"])
        with store.connect() as db:
            # BEGIN IMMEDIATE takes the write lock up front: without it, two
            # concurrent requests can both SELECT "no existing job" and then
            # both INSERT — the duplicate-enqueue bug, reintroduced.
            db.execute("BEGIN IMMEDIATE")
            expected = structure(db, ident)
            # Atomic check-then-enqueue: a double click must not create two
            # paid analysis jobs.
            existing = db.execute(
                "SELECT id FROM jobs WHERE book_id=? AND kind='analyze_chapters' "
                "AND status IN ('queued','running','needs_review')",
                (ident,),
            ).fetchone()
            job_id = (
                existing["id"]
                if existing
                else store.job(
                    "analyze_chapters",
                    {"text": text, "structure": expected, "config": snapshot(config)},
                    ident,
                    db=db,
                )
            )
        return {"id": job_id}

    @app.post("/api/books/{ident}/apply-chapters")
    def apply_chapters(ident: str, body: dict):
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            job = db.execute(
                "SELECT * FROM jobs WHERE id=? AND book_id=? AND kind='analyze_chapters' "
                "AND status='succeeded'",
                (body.get("job_id"), ident),
            ).fetchone()
            if not job:
                raise HTTPException(409, "分章预览已失效，请重新分析")
            payload = json.loads(job["payload"])
            chapters = payload.get("proposed", [])
            payload_text = payload.get("text")
            payload_structure = payload.get("structure")
            if (
                not chapters
                or payload_text is None
                or payload_structure is None
                or "".join(c["text"] for c in chapters) != payload_text
            ):
                raise ValueError("分章结果不完整，现有章节未修改")
            if structure(db, ident) != payload_structure:
                raise HTTPException(409, "章节已修改，请重新分析后再应用")
            require_idle(db, ident)
            paths = clear_book_content(db, ident)
            for i, c in enumerate(chapters):
                db.execute(
                    "INSERT INTO chapters (id,book_id,position,title,source,text,segments) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (
                        uid(),
                        ident,
                        i + 1,
                        c["title"],
                        c["text"],
                        c["text"],
                        json.dumps(importer.director_segments(c["text"]), ensure_ascii=False),
                    ),
                )
        return {"ok": True, "count": len(chapters), "cleanup_pending": clean_files(paths)}

    @app.post("/api/books/{ident}/cover")
    def cover_upload(ident: str, file: UploadFile):
        row = book(ident)
        data = file.file.read(5 * 1024 * 1024 + 1)
        if len(data) > 5 * 1024 * 1024:
            raise ValueError("封面不能超过 5MB")
        ext = (
            ".png"
            if data.startswith(b"\x89PNG\r\n\x1a\n")
            else ".jpg"
            if data.startswith(b"\xff\xd8\xff")
            else None
        )
        if not ext:
            raise ValueError("封面支持 PNG 和 JPG")
        relative = f"covers/{uid()}{ext}"
        store.file(relative).write_bytes(data)
        store.execute("UPDATE books SET cover=? WHERE id=?", (relative, ident))
        # Replace, don't accumulate: drop the previous upload's file.
        if row["cover"] and row["cover"] != relative:
            try:
                store.file(row["cover"]).unlink(missing_ok=True)
            except OSError:
                pass  # best-effort; the DB already points at the new cover
        return {"ok": True}

    @app.get("/api/books/{ident}/cover")
    def book_cover(ident: str):
        row = book(ident)
        if not row["cover"]:
            raise HTTPException(404)
        return FileResponse(store.file(row["cover"]))

    @app.get("/api/chapters/{ident}")
    def get_chapter(ident: str):
        row = chapter(ident)
        row["segments"] = json.loads(row["segments"])
        row["suggestion"] = json.loads(row["suggestion"]) if row["suggestion"] else None
        # Surface the latest successful restructure suggestion, if any.
        job = store.one(
            "SELECT payload FROM jobs WHERE chapter_id=? AND kind='restructure' "
            "AND status='succeeded' ORDER BY created DESC LIMIT 1",
            (ident,),
        )
        if job and job.get("payload"):
            try:
                payload = json.loads(job["payload"])
            except (ValueError, TypeError):
                payload = None
            if payload and payload.get("proposed") and payload.get("existing_revision") == row["revision"]:
                row["restructure"] = {
                    "segments": payload["proposed"],
                    "existing_revision": payload["existing_revision"],
                }
            else:
                row["restructure"] = None
        else:
            row["restructure"] = None
        row["versions"] = store.rows(
            "SELECT id,revision,duration,created FROM audio WHERE chapter_id=? ORDER BY created DESC",
            (ident,),
        )
        row["marks"] = store.rows("SELECT * FROM marks WHERE chapter_id=? ORDER BY created DESC", (ident,))
        return row

    @app.put("/api/chapters/{ident}")
    def save_chapter(ident: str, body: ChapterSave):
        chapter(ident)
        values = [s.model_dump() for s in body.segments]
        if any(s["emotion"] not in providers.EMOTIONS for s in values):
            raise ValueError("不支持的情绪参数")
        with store.connect() as db:
            # Which segment indices does this save make stale relative to the
            # active audio? Union with previously tracked ones; cleared per
            # index when a partial regen refreshes that segment.
            before = db.execute(
                "SELECT segments,active_audio,stale_segments FROM chapters WHERE id=?", (ident,)
            ).fetchone()
            changed = []
            if before and before["active_audio"]:
                old_segments = json.loads(before["segments"]) if before["segments"] else []
                limit = max(len(old_segments), len(values))
                prev_stale = json.loads(before["stale_segments"]) if before["stale_segments"] else []
                for i in range(limit):
                    old_seg = old_segments[i] if i < len(old_segments) else None
                    new_seg = values[i] if i < len(values) else None
                    if old_seg != new_seg or i in prev_stale:
                        changed.append(i)
                changed = sorted(set(changed))
            changed_row = db.execute(
                "UPDATE chapters SET title=?,segments=?,text=?,revision=revision+1,suggestion=NULL,"
                "stale_segments=? "
                "WHERE id=? AND revision=?",
                (
                    body.title,
                    json.dumps(values, ensure_ascii=False),
                    "".join(s["text"] for s in values),
                    json.dumps(changed, ensure_ascii=False) if before and before["active_audio"] else None,
                    ident,
                    body.revision,
                ),
            )
            changed = changed_row.rowcount
            if not changed:
                raise HTTPException(409, "章节已经更新，请重新打开后再编辑")
            # Sync the book-level character table in the same transaction, but
            # LEARN-ONLY: register characters that have no binding yet (e.g.
            # from an adopted AI suggestion). Never overwrite an explicit cast
            # binding here — chapter segments may still carry a stale voice,
            # and replacing the binding would silently revert what the user
            # set on the cast page.
            row = db.execute("SELECT book_id FROM chapters WHERE id=?", (ident,)).fetchone()
            counts = {}
            for s in values:
                speaker = norm_speaker(s["speaker"])
                if speaker != "旁白" and s["voice"] and providers.QUOTED.search(s["text"] or ""):
                    counts.setdefault(speaker, {})
                    counts[speaker][s["voice"]] = counts[speaker].get(s["voice"], 0) + 1
            for speaker, vc in counts.items():
                voice = top_vote(vc)
                db.execute(
                    "INSERT OR IGNORE INTO cast VALUES (?,?,?,?)",
                    (row["book_id"], speaker, voice, time.time()),
                )
        return get_chapter(ident)

    @app.post("/api/books/{ident}/reorder")
    def reorder(ident: str, body: Selection):
        rows = store.rows("SELECT id FROM chapters WHERE book_id=?", (ident,))
        if sorted(body.chapter_ids) != sorted(r["id"] for r in rows):
            raise ValueError("排序必须包含本书全部章节且不能重复")
        with store.connect() as db:
            for i, cid in enumerate(body.chapter_ids):
                db.execute("UPDATE chapters SET position=? WHERE id=?", (i + 1, cid))
        return {"ok": True}

    @app.post("/api/preview")
    def preview(body: PreviewBody):
        if not body.text.strip() or len(body.text) > 300:
            raise ValueError("试听文本需要在 1–300 字之间")
        config = store.get("tts")
        if not config["base_url"] or not config["model"]:
            raise ValueError("请先配置语音服务和模型")
        segment = body.model_dump()
        # The audition must sound like the final render: apply the book's
        # pronunciation dictionary exactly like generation does.
        pronunciation = book_pronunciation(store, body.book_id) if body.book_id else []
        if pronunciation:
            segment["text"] = apply_pronunciation(segment["text"], pronunciation)
        return {"id": store.job("preview", {"segments": [segment], "config": snapshot(config)})}

    @app.post("/api/books/{ident}/generate")
    def generate(ident: str, body: Selection):
        row = book(ident)
        config = store.get("tts")
        if not config.get("base_url") or not config.get("model"):
            raise ValueError("请先配置语音服务")
        if row["voice"]:
            config["voice"] = row["voice"]
        ids = []
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for cid in dict.fromkeys(body.chapter_ids):
                c = db.execute("SELECT * FROM chapters WHERE id=? AND book_id=?", (cid, ident)).fetchone()
                if not c:
                    raise ValueError("选择中包含不属于本书的章节")
                if not c["text"].strip():
                    raise ValueError(f"{c['title']} 没有正文，请先编辑")
                # Far below the WAV capacity ceiling (~24h ≈ 2M chars), so an
                # over-long chapter fails before any synthesis is billed
                # instead of corrupting at concat time.
                if len(c["text"]) > 200_000:
                    raise ValueError(f"《{c['title']}》超过 20 万字，请先拆分章节再生成")
                exists = db.execute(
                    "SELECT id FROM jobs WHERE chapter_id=? AND kind='generate' "
                    "AND status IN ('queued','running','needs_review')",
                    (cid,),
                ).fetchone()
                if exists:
                    ids.append(exists["id"])
                    continue
                job_id = uid()
                values = json.loads(c["segments"])
                payload = {"segments": values, "revision": c["revision"], "config": snapshot(config)}
                db.execute(
                    "INSERT INTO jobs (id,kind,book_id,chapter_id,status,stage,payload,created,updated) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        job_id,
                        "generate",
                        ident,
                        cid,
                        "queued",
                        "等待合成",
                        json.dumps(payload),
                        time.time(),
                        time.time(),
                    ),
                )
                ids.append(job_id)
        return {"ids": ids}

    @app.post("/api/chapters/{ident}/analyze")
    def analyze(ident: str):
        row = chapter(ident)
        config = store.get("ai")
        if not config.get("base_url") or not config.get("model"):
            raise ValueError("请先配置 AI 分析服务与模型；也可以手动调整朗读参数")
        # Analyze the saved narration script, so suggestions align 1:1 with the
        # segments the user sees — including an adopted AI semantic segmentation.
        payload = {
            "segments": json.loads(row["segments"]),
            "voices": store.get("voices")
            or [{"id": store.get("tts")["voice"], "name": "默认音色", "description": ""}],
            "cast": {
                seg["speaker"]: {"voice": seg["voice"]}
                for c in store.rows(
                    "SELECT segments FROM chapters WHERE book_id=? ORDER BY position",
                    (row["book_id"],),
                )
                for seg in json.loads(c["segments"])
                if seg.get("voice")
            },
            "revision": row["revision"],
            "config": snapshot(config),
        }
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT id FROM jobs WHERE chapter_id=? AND kind='analyze' AND status IN ('queued','running')",
                (ident,),
            ).fetchone()
            job_id = existing["id"] if existing else store.job("analyze", payload, row["book_id"], ident, db=db)
        return {"id": job_id}

    @app.post("/api/chapters/{ident}/restructure")
    def restructure(ident: str):
        """Ask the LLM to redivide a chapter into semantic narration units."""
        row = chapter(ident)
        config = store.get("ai")
        if not config.get("base_url") or not config.get("model"):
            raise ValueError("请先配置 AI 分析服务与模型；也可以手动调整分段")
        if len(row["text"]) > 20000:
            raise ValueError("本章超过 2 万字，AI 优化分段前请先手动拆分章节")
        payload = {
            "text": row["text"],
            "revision": row["revision"],
            "config": snapshot(config),
        }
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT id FROM jobs WHERE chapter_id=? AND kind='restructure' AND status IN ('queued','running')",
                (ident,),
            ).fetchone()
            job_id = (
                existing["id"] if existing else store.job("restructure", payload, row["book_id"], ident, db=db)
            )
        return {"id": job_id}

    @app.post("/api/chapters/{ident}/dismiss-restructure")
    def dismiss_restructure(ident: str):
        """Mark the latest AI restructure suggestion as consumed without applying it."""
        store.execute(
            "UPDATE jobs SET status='cancelled', stage='已被忽略' "
            "WHERE chapter_id=? AND kind='restructure' AND status='succeeded'",
            (ident,),
        )
        return {"ok": True}

    @app.post("/api/chapters/{ident}/regen-segment")
    def regen_segment(ident: str, body: dict):
        """Re-synthesize one segment in place: replace its slice of the
        chapter audio (PCM splice), shift the timeline, and promote the new
        version — without touching any other segment."""
        row = chapter(ident)
        config = store.get("tts")
        if not config.get("base_url") or not config.get("model"):
            raise ValueError("请先配置语音服务")
        book_row = book(row["book_id"])
        if book_row["voice"]:
            config["voice"] = book_row["voice"]
        try:
            index = int(body.get("index"))
        except (TypeError, ValueError):
            raise ValueError("片段序号无效")
        segments = json.loads(row["segments"])
        if not 0 <= index < len(segments):
            raise ValueError("片段序号超出范围")
        if not segments[index].get("text", "").strip():
            raise ValueError("该片段没有正文")
        if not row["active_audio"]:
            raise ValueError("本章还没有生成音频，请先生成本章")
        audio_row = store.one("SELECT * FROM audio WHERE id=?", (row["active_audio"],))
        # NOTE: audio_revision may lag chapter revision here ON PURPOSE — the
        # whole point of a partial regen is to bring ONE segment's audio up to
        # date after an edit + save. The splice works on the stored timeline
        # (which belongs to this audio file), and the promotion below is still
        # revision-guarded, so a newer edit made after enqueue can't be
        # overwritten by stale output.
        timeline = json.loads(audio_row["timeline"])
        if not any(e["index"] == index for e in timeline):
            raise ValueError("音频时间轴中找不到该片段，请先生成本章")
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT id FROM jobs WHERE chapter_id=? AND kind='regen_segment' "
                "AND status IN ('queued','running')",
                (ident,),
            ).fetchone()
            job_id = (
                existing["id"]
                if existing
                else store.job(
                    "regen_segment",
                    {"index": index, "revision": row["revision"], "config": snapshot(config)},
                    row["book_id"],
                    ident,
                    db=db,
                )
            )
        return {"id": job_id}

    @app.get("/api/jobs")
    def jobs():
        rows = store.rows(
            "SELECT j.id,j.kind,j.book_id,j.chapter_id,j.status,j.stage,j.done,j.total,j.error,j.created,"
            "c.title chapter_title,b.title book_title FROM jobs j LEFT JOIN chapters c ON c.id=j.chapter_id "
            "LEFT JOIN books b ON b.id=j.book_id ORDER BY j.created DESC LIMIT 300"
        )
        return {"jobs": rows, "paused": store.get("paused")}

    @app.get("/api/jobs/{ident}")
    def job_result(ident: str):
        row = store.one("SELECT * FROM jobs WHERE id=?", (ident,))
        if not row:
            raise HTTPException(404)
        payload = json.loads(row.pop("payload"))
        row["audio_id"] = payload.get("audio_id")
        # Surface the AI chapter preview so the UI can render it without re-reading the job payload.
        if row["kind"] == "analyze_chapters":
            row["proposed"] = payload.get("proposed") or []
        elif row["kind"] == "analyze_book":
            row["meta"] = payload.get("meta")
        return row

    @app.post("/api/jobs/{ident}/cancel")
    def cancel(ident: str):
        store.execute(
            "UPDATE jobs SET cancel=1,status=CASE WHEN status='running' THEN status ELSE 'cancelled' END "
            "WHERE id=? AND status IN ('queued','running','needs_review','failed')",
            (ident,),
        )
        return {"ok": True}

    @app.post("/api/jobs/{ident}/retry")
    def retry(ident: str):
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE id=?", (ident,)).fetchone()
            if not row or row["status"] not in ("failed", "needs_review", "cancelled"):
                raise ValueError("任务当前不能重试")
            if row["chapter_id"] and not db.execute(
                "SELECT id FROM chapters WHERE id=?", (row["chapter_id"],)
            ).fetchone():
                raise HTTPException(409, "章节已删除，这条任务无法重试")
            if (
                row["chapter_id"]
                and db.execute(
                    "SELECT id FROM jobs WHERE chapter_id=? AND kind=? AND id!=? "
                    "AND status IN ('queued','running','needs_review')",
                    (row["chapter_id"], row["kind"], ident),
                ).fetchone()
            ):
                raise HTTPException(409, "本章已有同类任务，请等待完成后再重试")
            # Book-level jobs carry no chapter_id; dedup them by book+kind so a
            # retry cannot run alongside a freshly enqueued analysis.
            if (
                not row["chapter_id"]
                and row["book_id"]
                and row["kind"] in ("analyze_chapters", "analyze_book", "generate_cover")
                and db.execute(
                    "SELECT id FROM jobs WHERE book_id=? AND kind=? AND id!=? "
                    "AND status IN ('queued','running','needs_review')",
                    (row["book_id"], row["kind"], ident),
                ).fetchone()
            ):
                raise HTTPException(409, "本书已有同类任务，请等待完成后再重试")
            # Keep the original text/model snapshot; new settings require a new generation.
            db.execute(
                "UPDATE jobs SET status='queued',cancel=0,error='',stage='等待重试' WHERE id=?", (ident,)
            )
        return {"ok": True}

    @app.post("/api/queue")
    def queue(body: dict):
        store.set("paused", bool(body.get("paused")))
        return {"paused": store.get("paused")}

    @app.get("/api/audio/{ident}/metadata")
    def audio_metadata(ident: str):
        row = store.one("SELECT * FROM audio WHERE id=?", (ident,))
        if not row:
            raise HTTPException(404, "音频不存在")
        row.pop("path")
        row["peaks"] = json.loads(row["peaks"])
        row["timeline"] = json.loads(row["timeline"])
        if row["quality"]:
            row["quality"] = json.loads(row["quality"])
        return row

    @app.get("/api/audio/{ident}")
    def audio_file(ident: str, format: str = "mp3", download: bool = False):
        if format not in ("mp3", "wav"):
            raise ValueError("支持 MP3 和 WAV")
        row = store.one(
            "SELECT a.*,c.title FROM audio a LEFT JOIN chapters c ON c.id=a.chapter_id WHERE a.id=?", (ident,)
        )
        if not row:
            raise HTTPException(404, "音频不存在")
        path = store.file(row["path"]).with_suffix("." + format)
        if not path.exists():
            raise HTTPException(404, "音频文件丢失，请重新生成或恢复备份")
        return FileResponse(
            path,
            media_type="audio/mpeg" if format == "mp3" else "audio/wav",
            filename=safe_name(row["title"] or "音色试听") + "." + format if download else None,
        )

    @app.post("/api/books/{ident}/exports")
    def export(ident: str, body: ExportSelection):
        row = book(ident)
        if body.format not in ("mp3", "wav", "m4b"):
            raise ValueError("不支持的导出格式")
        selected = []
        for cid in set(body.chapter_ids):
            c = chapter(cid)
            if c["book_id"] != ident or not c["active_audio"]:
                raise ValueError("选择的章节不属于本书或还没有音频")
            version = store.one(
                "SELECT revision,cast_version FROM audio WHERE id=?", (c["active_audio"],)
            )
            stale_list = json.loads(c["stale_segments"]) if c["stale_segments"] else []
            voice_stale = (
                version["cast_version"] is not None and version["cast_version"] != row["cast_version"]
            )
            if (version["revision"] != c["revision"] or stale_list or voice_stale) and not body.allow_stale:
                detail = "所选章节包含待更新音频"
                if stale_list:
                    detail += f"（{len(stale_list)} 段待重生成）"
                if voice_stale:
                    detail += "（音色已更换）"
                raise HTTPException(409, detail + "，请重新生成或明确允许导出旧版本")
            selected.append(
                {
                    "title": c["title"],
                    "position": c["position"],
                    "audio_id": c["active_audio"],
                    "revision": version["revision"],
                }
            )
        payload = {
            "title": row["title"],
            "author": row["author"],
            "format": body.format,
            "embed": body.embed,
            "chapters": sorted(selected, key=lambda c: c["position"]),
        }
        return {"id": store.job("export", payload, ident)}

    @app.get("/api/exports")
    def exports():
        return store.rows(
            "SELECT e.id,e.book_id,e.format,e.created,e.count,b.title FROM exports e "
            "LEFT JOIN books b ON b.id=e.book_id ORDER BY e.created DESC"
        )

    @app.get("/api/exports/{ident}/download")
    def download_export(ident: str):
        row = store.one(
            "SELECT e.*,b.title FROM exports e LEFT JOIN books b ON b.id=e.book_id WHERE e.id=?", (ident,)
        )
        if not row:
            raise HTTPException(404)
        path = store.file(row["path"])
        if not path.exists():
            raise HTTPException(404, "导出包文件丢失，请重新导出")
        return FileResponse(path, filename=safe_name(row["title"] or "有声书") + path.suffix)

    @app.get("/api/books/{ident}/progress")
    def get_progress(ident: str):
        return store.one("SELECT * FROM progress WHERE book_id=?", (ident,)) or {}

    @app.put("/api/books/{ident}/progress")
    def save_progress(ident: str, body: dict):
        book(ident)
        seconds = float(body.get("seconds") or 0)
        audio_id = str(body.get("audio_id") or "")
        row = store.one(
            "SELECT a.duration FROM audio a JOIN chapters c ON c.id=a.chapter_id WHERE a.id=? AND c.book_id=?",
            (audio_id, ident),
        )
        if not row or not 0 <= seconds <= row["duration"] + 1:
            raise ValueError("播放进度无效")
        store.execute("INSERT OR REPLACE INTO progress VALUES (?,?,?)", (ident, audio_id, seconds))
        return {"ok": True}

    @app.post("/api/chapters/{ident}/marks")
    def add_mark(ident: str, body: dict):
        chapter(ident)
        note = str(body.get("note", "")).strip()[:1000]
        seconds = float(body.get("seconds") or 0)
        if not note or not 0 <= seconds < 1000000:
            raise ValueError("请填写有效的问题说明")
        mark = {"id": uid(), "seconds": seconds, "note": note, "created": time.time()}
        store.execute(
            "INSERT INTO marks VALUES (?,?,?,?,?)",
            (mark["id"], ident, mark["seconds"], mark["note"], mark["created"]),
        )
        # Return the row so the client can append it without a refetch.
        return {"ok": True, "mark": mark}

    frontend = Path(os.environ.get("FRONTEND_DIR", Path(__file__).parent.parent / "frontend" / "dist"))
    if frontend.exists():
        app.mount("/", StaticFiles(directory=frontend, html=True), name="web")
    return app


app = create_app()
