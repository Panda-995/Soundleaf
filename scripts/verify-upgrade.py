"""Exercise v1.1.0 data with the current app; only writes to an explicit test directory."""

import argparse
import hashlib
import importlib.util
import io
import json
import time
import urllib.request
import wave
import zipfile
from http.cookiejar import CookieJar
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import audio, providers
from app.main import create_app
from app.security import password_hash
from app.store import Store


def seed(root, legacy_source):
    spec = importlib.util.spec_from_file_location("soundleaf_legacy_store", legacy_source)
    legacy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(legacy)
    store = legacy.Store(root)
    now = time.time()
    text = "灯塔亮起了。"
    segment = {"text": text, "speaker": "旁白", "voice": "", "emotion": "neutral", "speed": 1, "pause": 250}
    config = {**legacy.DEFAULTS["tts"], "voice": "fixture-calm", "api_key": "upgrade-fixture-secret"}
    store.set("tts", config)
    store.set("ai", {**legacy.DEFAULTS["ai"], "api_key": "upgrade-ai-fixture"})
    store.set("voices", [{"id": "fixture-calm", "name": "测试音色"}])
    store.set("favorites", ["fixture-calm"])
    store.set("paused", True)
    store.file("sources/legacy.txt").write_text("第一章 灯塔\n" + text, encoding="utf-8")
    store.file("covers/legacy.png").write_bytes(b"\x89PNG\r\n\x1a\nfixture")
    output = io.BytesIO()
    with wave.open(output, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(24000)
        handle.writeframes(b"\x00\x10" * 2400)
    store.file("audio/legacy-audio.wav").write_bytes(output.getvalue())
    audio.convert(store.file("audio/legacy-audio.wav"), store.file("audio/legacy-audio.mp3"), mp3=True)
    with zipfile.ZipFile(store.file("exports/legacy.zip"), "w") as archive:
        archive.writestr("第一章.wav", output.getvalue())
    with store.connect() as db:
        db.execute("INSERT INTO users VALUES (?,?,?)", ("legacy-user", "admin", password_hash("legacy-password")))
        db.execute(
            "INSERT INTO books (id,title,author,source,created,cover,intro,style) VALUES (?,?,?,?,?,?,?,?)",
            ("legacy-book", "旧版测试书", "测试作者", "sources/legacy.txt", now, "covers/legacy.png", "旧版简介", "{}"),
        )
        db.execute(
            "INSERT INTO chapters (id,book_id,position,title,source,text,segments,active_audio) VALUES (?,?,?,?,?,?,?,?)",
            ("legacy-chapter", "legacy-book", 1, "第一章 灯塔", text, text, json.dumps([segment]), "legacy-audio"),
        )
        db.execute(
            "INSERT INTO audio (id,chapter_id,revision,path,duration,peaks,timeline,created,cast_version) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            ("legacy-audio", "legacy-chapter", 1, "audio/legacy-audio.wav", 0.1, "[0.2]",
             '[{"index":0,"start":0,"end":0.1}]', now, 1),
        )
        db.execute("INSERT INTO cast VALUES (?,?,?,?)", ("legacy-book", "陈先生", "fixture-calm", now))
        db.execute("INSERT INTO dict VALUES (?,?,?,?)", ("legacy-book", "灯塔", "信号塔", now))
        db.execute("INSERT INTO progress VALUES (?,?,?)", ("legacy-book", "legacy-audio", 0.05))
        db.execute("INSERT INTO marks VALUES (?,?,?,?,?)", ("legacy-mark", "legacy-chapter", 0.05, "旧版标记", now))
        db.execute("INSERT INTO exports VALUES (?,?,?,?,?,?)", ("legacy-export", "legacy-book", "exports/legacy.zip", "wav", now, 1))
    snapshot = {"segments": [segment], "config": store.cipher.encrypt(json.dumps(config).encode()).decode()}
    queued = store.job("preview", snapshot)
    interrupted = store.job("analyze", snapshot, "legacy-book", "legacy-chapter")
    store.execute("UPDATE jobs SET status='running',stage='分析朗读节奏' WHERE id=?", (interrupted,))
    return store, queued, interrupted


def verify(root, legacy_source):
    if root.exists() and any(root.iterdir()):
        raise ValueError("Compatibility verification requires an empty test directory")
    old, queued, interrupted = seed(root, legacy_source)
    key_digest = hashlib.sha256(old.file("secret.key").read_bytes()).hexdigest()
    tables = ("users", "books", "chapters", "audio", "cast", "dict", "progress", "marks", "exports", "settings")
    before = {table: old.rows(f"SELECT * FROM {table}") for table in tables}
    app = create_app(root, start_worker=False)
    store = app.state.store
    assert hashlib.sha256(store.file("secret.key").read_bytes()).hexdigest() == key_digest
    for table in tables:
        assert store.rows(f"SELECT * FROM {table}") == before[table], table
    assert store.get("tts")["api_key"] == "upgrade-fixture-secret"
    assert store.get("ai")["api_key"] == "upgrade-ai-fixture"
    assert store.one("PRAGMA integrity_check")["integrity_check"] == "ok"
    assert store.one("SELECT remote_inflight FROM jobs WHERE id=?", (queued,))["remote_inflight"] == 0
    # Reopen and perform startup recovery without executing the queue.
    Store(root)
    with patch.object(app.state.worker.thread, "start"):
        app.state.worker.start()
    assert store.one("SELECT status FROM jobs WHERE id=?", (queued,))["status"] == "queued"
    assert store.one("SELECT status FROM jobs WHERE id=?", (interrupted,))["status"] == "needs_review"
    with TestClient(app) as client:
        client.headers["X-Soundleaf"] = "1"
        assert client.get("/api/books").status_code == 401
        assert client.post("/api/login", json={"name": "admin", "password": "legacy-password"}).status_code == 200
        book = client.get("/api/books/legacy-book").json()
        assert book["title"] == "旧版测试书" and book["chapters"][0]["active_audio"] == "legacy-audio"
        assert client.get("/api/audio/legacy-audio").content == store.file("audio/legacy-audio.mp3").read_bytes()
        assert client.get("/api/books/legacy-book/cover").status_code == 200
        assert client.get("/api/books/legacy-book/progress").json()["seconds"] == 0.05
        assert client.get("/api/exports/legacy-export/download").status_code == 200
        assert client.get("/api/books/legacy-book/dict").json()[0]["replacement"] == "信号塔"
        chapter = client.get("/api/chapters/legacy-chapter").json()
        assert chapter["marks"][0]["note"] == "旧版标记"
        # New audio and an export are made using the old book and encrypted config.
        job_id = client.post("/api/books/legacy-book/generate", json={"chapter_ids": ["legacy-chapter"]}).json()["ids"][0]
        worker = app.state.worker
        with patch.object(providers, "synthesize", return_value=store.file("audio/legacy-audio.wav").read_bytes()):
            worker.update(job_id, status="running")
            worker.run(store.one("SELECT * FROM jobs WHERE id=?", (job_id,)))
            worker.update(job_id, status="succeeded", remote_inflight=0)
        export_id = client.post("/api/books/legacy-book/exports", json={"chapter_ids": ["legacy-chapter"], "format": "wav"}).json()["id"]
        worker.run(store.one("SELECT * FROM jobs WHERE id=?", (export_id,)))
        worker.update(export_id, status="succeeded")
        package = next(item for item in client.get("/api/exports").json() if item["id"] != "legacy-export")
        assert client.get(f"/api/exports/{package['id']}/download").status_code == 200
        assert client.get("/api/audio/legacy-audio").status_code == 200  # old version still readable
    print("v1.1.0 upgrade: accounts, encrypted settings, books, audio, covers, cast, dictionary, progress, marks, exports, queue, new generation/export and idempotent migration passed")


def verify_live(url):
    client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
    request = urllib.request.Request(url + "/api/login", data=json.dumps({"name": "admin", "password": "legacy-password"}).encode(),
                                     headers={"Content-Type": "application/json", "X-Soundleaf": "1"})
    assert client.open(request, timeout=10).status == 200
    book = json.load(client.open(url + "/api/books/legacy-book", timeout=10))
    assert book["title"] == "旧版测试书"
    assert json.load(client.open(url + "/api/books/legacy-book/progress", timeout=10))["seconds"] == 0.05
    assert client.open(url + "/api/audio/legacy-audio", timeout=10).status == 200
    assert client.open(url + "/api/exports/legacy-export/download", timeout=10).status == 200
    print("Native HTTP legacy login, book/audio/export and playback progress persistence passed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path)
    parser.add_argument("--legacy-store", type=Path)
    parser.add_argument("--live-url")
    args = parser.parse_args()
    if args.live_url:
        verify_live(args.live_url.rstrip("/"))
    elif args.data and args.legacy_store:
        verify(args.data.resolve(), args.legacy_store.resolve())
    else:
        parser.error("Use --data with --legacy-store, or --live-url")
