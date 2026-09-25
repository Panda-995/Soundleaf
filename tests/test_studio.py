import io
import json
import math
import struct
import time
import wave
import zipfile

import pytest
from fastapi.testclient import TestClient

from app import audio, importer, providers
from app.main import create_app
from app.store import Store
from tests.conftest import import_book, run_job


def test_auth_csrf_and_no_public_audio(client):
    client.headers.pop("X-Soundleaf")
    assert client.post("/api/queue", json={"paused": True}).status_code == 403
    client.headers["X-Soundleaf"] = "1"
    # The setup endpoint is gone: accounts are seeded, not self-created.
    assert client.post("/api/setup", json={"name": "other", "password": "test-password"}).status_code == 405
    assert client.post("/api/logout").status_code == 200
    assert client.get("/api/books").status_code == 401
    assert client.get("/api/audio/anything").status_code == 401


def test_default_admin_and_forced_password_change(client):
    # Fresh data directories come with the seeded admin/admin account, and
    # login says the password must be replaced.
    r = client.post("/api/login", json={"name": "admin", "password": "admin"})
    assert r.status_code == 200 and r.json()["must_change_password"] is True
    # A page reload (bootstrap) keeps asking while the default is in force.
    assert client.get("/api/bootstrap").json() == {
        "authenticated": True,
        "must_change_password": True,
    }
    # Replacement requires the current password and keeps the 8-char floor.
    wrong_current = client.post(
        "/api/account/password", json={"current": "wrong-password", "password": "fresh-password-1"}
    )
    assert wrong_current.status_code == 401
    assert (
        client.post("/api/account/password", json={"current": "admin", "password": "short"}).status_code == 422
    )
    assert client.post("/api/account/password", json={"current": "admin", "password": "fresh-password-1"}).status_code == 200
    assert client.get("/api/bootstrap").json()["must_change_password"] is False
    assert client.post("/api/login", json={"name": "admin", "password": "admin"}).status_code == 401
    r = client.post("/api/login", json={"name": "admin", "password": "fresh-password-1"})
    assert r.status_code == 200 and r.json()["must_change_password"] is False
    # Changing the password revokes every other device's session while the
    # requesting device stays signed in.
    store = client.app.state.store
    user_id = store.one("SELECT id FROM users WHERE name='admin'")["id"]
    store.execute("INSERT INTO sessions VALUES (?,?,?)", ("decoy", user_id, time.time() + 3600))
    assert (
        client.post(
            "/api/account/password", json={"current": "fresh-password-1", "password": "fresh-password-2"}
        ).status_code
        == 200
    )
    assert store.one("SELECT * FROM sessions WHERE token='decoy'") is None
    assert client.get("/api/bootstrap").json()["authenticated"] is True
    # Wrong current-password guesses are rate limited like login attempts.
    for _ in range(8):
        assert (
            client.post(
                "/api/account/password",
                json={"current": "wrong-password", "password": "fresh-password-3"},
            ).status_code
            == 401
        )
    assert (
        client.post(
            "/api/account/password", json={"current": "wrong-password", "password": "fresh-password-3"}
        ).status_code
        == 429
    )


def test_import_encoding_and_original_retained(client):
    b = import_book(client)
    assert len(b["chapters"]) == 2
    c = client.get("/api/chapters/" + b["chapters"][0]["id"]).json()
    assert c["source"] == "灯亮了。"
    assert "".join(s["text"] for s in c["segments"]) == c["source"]
    chapters, encoding = importer.parse("第一章 家\n回家了。".encode("gb18030"), "book.txt")
    assert encoding == "gb18030" and chapters[0]["text"] == "回家了。"
    assert len(importer.chapter_split("他在想第三章的故事。\n窗外下雨。")) == 1


def test_segment_coverage():
    text = "  夜色。\n\n你好！" + "长" * 2600 + "，再见。\n"
    values = importer.segments(text)
    assert "".join(s["text"] for s in values) == text
    assert all(len(s["text"]) <= 1200 for s in values)


def test_epub_spine_and_script_removal():
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as z:
        z.writestr(
            "META-INF/container.xml",
            '<container><rootfiles><rootfile full-path="OEBPS/book.opf"/></rootfiles></container>',
        )
        z.writestr(
            "OEBPS/book.opf",
            '<package xmlns="http://www.idpf.org/2007/opf"><manifest><item id="a" href="a.xhtml"/>'
            '<item id="b" href="b.xhtml"/></manifest><spine><itemref idref="b"/><itemref idref="a"/></spine></package>',
        )
        z.writestr("OEBPS/a.xhtml", "<html><body><h1>第二章</h1><p>后面的故事。</p></body></html>")
        z.writestr(
            "OEBPS/b.xhtml", "<html><body><h1>第一章</h1><script>alert(1)</script><p>开头。</p></body></html>"
        )
    chapters, _ = importer.parse(data.getvalue(), "book.epub")
    assert [c["title"] for c in chapters] == ["第一章", "第二章"]
    assert chapters[0]["text"] == "开头。"


def test_epub_traversal_rejected():
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as z:
        z.writestr("../../escape", "bad")
    with pytest.raises(ValueError, match="不安全"):
        importer.parse(data.getvalue(), "book.epub")


def test_revision_conflict_and_ownership(client):
    b = import_book(client)
    c = client.get("/api/chapters/" + b["chapters"][0]["id"]).json()
    body = {"revision": c["revision"], "title": "新标题", "segments": c["segments"]}
    assert client.put("/api/chapters/" + c["id"], json=body).status_code == 200
    assert client.put("/api/chapters/" + c["id"], json=body).status_code == 409
    changed = client.get("/api/chapters/" + c["id"]).json()
    assert changed["source"] == c["source"]
    second = import_book(client)
    assert (
        client.post(f"/api/books/{second['id']}/generate", json={"chapter_ids": [c["id"]]}).status_code == 400
    )


def test_generation_cache_range_versions_and_export(client, monkeypatch, wav_bytes):
    calls = []
    monkeypatch.setattr(providers, "synthesize", lambda config, s: calls.append(s["text"]) or wav_bytes)
    b = import_book(client)
    ids = [c["id"] for c in b["chapters"]]
    submitted = client.post(f"/api/books/{b['id']}/generate", json={"chapter_ids": ids}).json()["ids"]
    assert client.post(f"/api/books/{b['id']}/generate", json={"chapter_ids": ids}).json()["ids"] == submitted
    results = [run_job(client, ident) for ident in submitted]
    assert len(calls) == 2
    first_audio = results[0]["audio_id"]
    streamed = client.get("/api/audio/" + first_audio, headers={"Range": "bytes=0-99"})
    assert streamed.status_code == 206 and len(streamed.content) == 100
    c = client.get("/api/chapters/" + ids[0]).json()
    c["segments"][0]["pause"] = 800
    assert (
        client.put(
            "/api/chapters/" + ids[0],
            json={"revision": c["revision"], "title": c["title"], "segments": c["segments"]},
        ).status_code
        == 200
    )
    export_request = {"chapter_ids": ids, "format": "mp3"}
    assert client.post(f"/api/books/{b['id']}/exports", json=export_request).status_code == 409
    new_job = client.post(f"/api/books/{b['id']}/generate", json={"chapter_ids": [ids[0]]}).json()["ids"][0]
    new_result = run_job(client, new_job)
    assert len(calls) == 2  # Only pause changed: no extra provider call.
    assert new_result["audio_id"] != first_audio
    assert len(client.get("/api/chapters/" + ids[0]).json()["versions"]) == 2
    assert client.get("/api/chapters/" + ids[1]).json()["active_audio"] == results[1]["audio_id"]
    export_job = client.post(f"/api/books/{b['id']}/exports", json=export_request).json()["id"]
    run_job(client, export_job)
    history = client.get("/api/exports").json()
    downloaded = client.get(f"/api/exports/{history[0]['id']}/download")
    with zipfile.ZipFile(io.BytesIO(downloaded.content)) as z:
        assert len([n for n in z.namelist() if n.endswith(".mp3")]) == 2
        manifest = json.loads(z.read("manifest.json"))
        assert [c["position"] for c in manifest["chapters"]] == [1, 2]


def test_stale_job_never_promotes_over_new_revision(client, monkeypatch, wav_bytes):
    monkeypatch.setattr(providers, "synthesize", lambda config, s: wav_bytes)
    b = import_book(client)
    cid = b["chapters"][0]["id"]
    ident = client.post(f"/api/books/{b['id']}/generate", json={"chapter_ids": [cid]}).json()["ids"][0]
    c = client.get("/api/chapters/" + cid).json()
    c["segments"][0]["text"] = "修改后的内容。"
    client.put("/api/chapters/" + cid, json={"revision": 1, "title": c["title"], "segments": c["segments"]})
    run_job(client, ident)
    c = client.get("/api/chapters/" + cid).json()
    assert c["active_audio"] is None and len(c["versions"]) == 1


def test_provider_keys_encrypted(client, monkeypatch):
    monkeypatch.setattr("app.main.validate_url", lambda url, local: url)
    secret = "secret-do-not-store-plaintext"
    config = {
        "provider": "minimax",
        "base_url": "https://example.com/v1",
        "model": "speech",
        "voice": "voice",
        "api_key": secret,
    }
    result = client.put("/api/settings/tts", json=config)
    assert result.status_code == 200 and secret not in result.text
    store = client.app.state.store
    raw = store.one("SELECT value FROM settings WHERE key='tts'")["value"]
    assert secret not in raw and store.get("tts")["api_key"] == secret
    reopened = Store(store.root)
    assert reopened.get("tts")["api_key"] == secret


def test_ai_validation_never_rewrites_source(client, monkeypatch):
    b = import_book(client)
    cid = b["chapters"][0]["id"]
    store = client.app.state.store
    store.set("ai", {"base_url": "https://example.com/v1", "model": "test", "api_key": ""})
    monkeypatch.setattr(
        providers,
        "request",
        lambda *a, **kw: {
            "choices": [
                {
                    "message": {
                        "content": '{"segments":[{"index":0,"speaker":"林晚","voice_hint":"青年女性 温柔",'
                        '"emotion":"calm","speed":0.9,"pause":500,"reason":"舒缓"}]}'
                    }
                }
            ]
        },
    )
    ident = client.post(f"/api/chapters/{cid}/analyze").json()["id"]
    run_job(client, ident)
    c = client.get("/api/chapters/" + cid).json()
    assert c["suggestion"]["segments"][0]["speed"] == 0.9
    # "灯亮了。" quotes nobody: the AI's character label is corrected to 旁白
    # so pure narration can never inherit a character voice.
    assert c["suggestion"]["segments"][0]["speaker"] == "旁白"
    assert c["suggestion"]["segments"][0]["voice"] == ""
    assert c["source"] == "灯亮了。" and c["segments"][0]["speed"] == 1
    monkeypatch.setattr(
        providers, "request", lambda *a, **kw: {"choices": [{"message": {"content": '{"segments":[]}'}}]}
    )
    with pytest.raises(ValueError, match="格式"):
        providers.analyze(store.get("ai"), c["segments"])


def test_ai_speaker_is_optional_and_defaults_pass(client, monkeypatch):
    """Older AI responses without speaker/voice_hint must keep working."""
    store = client.app.state.store
    store.set("ai", {"base_url": "https://example.com/v1", "model": "test", "api_key": ""})
    monkeypatch.setattr(
        providers,
        "request",
        lambda *a, **kw: {
            "choices": [
                {
                    "message": {
                        "content": '{"segments":[{"index":0,"emotion":"calm","speed":0.95,"pause":400,"reason":"节奏舒缓"}]}'
                    }
                }
            ]
        },
    )
    segments = [
        {"text": "夜很深。", "voice": "", "emotion": "neutral", "speed": 1, "pause": 250, "speaker": "旁白"}
    ]
    values = providers.analyze(store.get("ai"), segments)
    assert values[0]["speaker"] == "旁白"
    assert values[0]["voice_hint"] == ""


def test_restart_recovers_queue_but_preserves_uncertain_requests(tmp_path):
    root = tmp_path / "persist"
    first = create_app(root, start_worker=False)
    store = first.state.store
    store.set("paused", True)
    one = store.job("preview", {})
    two = store.job("preview", {})
    store.execute("UPDATE jobs SET status='running',stage='合成片段' WHERE id=?", (one,))
    store.execute("UPDATE jobs SET status='running',stage='请求语音服务' WHERE id=?", (two,))
    second = create_app(root)
    with TestClient(second):
        assert second.state.store.one("SELECT status FROM jobs WHERE id=?", (one,))["status"] == "queued"
        assert (
            second.state.store.one("SELECT status FROM jobs WHERE id=?", (two,))["status"] == "needs_review"
        )


def test_download_and_progress_validate_book(client, monkeypatch, wav_bytes):
    monkeypatch.setattr(providers, "synthesize", lambda config, s: wav_bytes)
    b = import_book(client)
    ident = client.post(
        f"/api/books/{b['id']}/generate", json={"chapter_ids": [b["chapters"][0]["id"]]}
    ).json()["ids"][0]
    audio = run_job(client, ident)["audio_id"]
    assert (
        client.put(f"/api/books/{b['id']}/progress", json={"audio_id": audio, "seconds": 0.05}).status_code
        == 200
    )
    assert client.get(f"/api/books/{b['id']}/progress").json()["seconds"] == 0.05
    assert (
        client.put(f"/api/books/{b['id']}/progress", json={"audio_id": audio, "seconds": 999999}).status_code
        == 400
    )


def test_retry_cannot_duplicate_active_chapter_job(client):
    b = import_book(client)
    endpoint = f"/api/books/{b['id']}/generate"
    selection = {"chapter_ids": [b["chapters"][0]["id"]]}
    old = client.post(endpoint, json=selection).json()["ids"][0]
    client.post(f"/api/jobs/{old}/cancel")
    active = client.post(endpoint, json=selection).json()["ids"][0]
    assert active != old
    assert client.post(f"/api/jobs/{old}/retry").status_code == 409
    client.post(f"/api/jobs/{active}/cancel")
    assert client.post(f"/api/jobs/{old}/retry").status_code == 200
    assert client.post(f"/api/jobs/{old}/retry").status_code == 400


def test_delete_book_cascades_chapters_audio_and_files(client, monkeypatch, wav_bytes, tmp_path):
    monkeypatch.setattr(providers, "synthesize", lambda config, s: wav_bytes)
    b = import_book(client)
    store = client.app.state.store
    # Trigger generation so audio rows and cache files exist.
    ident = client.post(
        f"/api/books/{b['id']}/generate", json={"chapter_ids": [b["chapters"][0]["id"]]}
    ).json()["ids"][0]
    run_job(client, ident)
    book_row = store.one("SELECT * FROM books WHERE id=?", (b["id"],))
    audio_row = store.one("SELECT * FROM audio WHERE chapter_id=?", (b["chapters"][0]["id"],))
    source_path = store.file(book_row["source"])
    assert source_path.exists() and store.file(audio_row["path"]).exists()

    assert client.delete(f"/api/books/{b['id']}").status_code == 200
    assert client.get(f"/api/books/{b['id']}").status_code == 404
    assert not store.file(book_row["source"]).exists()
    assert not store.file(audio_row["path"]).exists()
    assert not store.file(audio_row["path"]).with_suffix(".mp3").exists()


def test_analyze_chapters_previews_before_applying(client, monkeypatch):
    b = import_book(client)
    store = client.app.state.store
    store.set("ai", {"base_url": "https://example.com/v1", "model": "test"})

    def response(config, endpoint, body, timeout=None):
        rows = json.loads(body["messages"][-1]["content"])["candidates"]
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "boundaries": [
                                    r["line"] for r in rows if r["text"].startswith(("第一章", "第二章"))
                                ]
                            }
                        )
                    }
                }
            ]
        }

    monkeypatch.setattr(providers, "request", response)
    ident = client.post(f"/api/books/{b['id']}/analyze-chapters").json()["id"]
    run_job(client, ident)
    proposed = client.get("/api/jobs/" + ident).json()["proposed"]
    assert len(proposed) == 2
    assert "".join(c["text"] for c in proposed) == "第一章 灯塔\n灯亮了。\n第二章 来信\n他打开信封。"
    assert client.get(f"/api/books/{b['id']}").json()["chapters"][0]["id"] == b["chapters"][0]["id"]
    # Arbitrary client text cannot replace a book; only a complete server preview can.
    assert (
        client.post(
            f"/api/books/{b['id']}/apply-chapters", json={"chapters": [{"title": "X", "text": "X"}]}
        ).status_code
        == 409
    )
    assert client.post(f"/api/books/{b['id']}/apply-chapters", json={"job_id": ident}).status_code == 200
    after = client.get(f"/api/books/{b['id']}").json()
    assert after["chapters"][0]["id"] != b["chapters"][0]["id"]
    assert client.post(f"/api/books/{b['id']}/apply-chapters", json={"job_id": ident}).status_code == 409


def test_analyze_chapters_requires_ai_config(client):
    import_book(client)
    b = client.get("/api/books").json()[0]
    store = client.app.state.store
    store.set("ai", {"base_url": "", "model": "", "api_key": "", "allow_local": False})
    # ValueError is mapped to HTTP 400 by the global handler.
    assert client.post(f"/api/books/{b['id']}/analyze-chapters").status_code == 400


def test_boundary_detection_never_truncates_long_book(monkeypatch):
    text = "开场\n第一章 海\n" + "长" * 130000 + "\n第二章 山\n尾声。"

    def response(config, endpoint, body, timeout=None):
        rows = json.loads(body["messages"][-1]["content"])["candidates"]
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "boundaries": [
                                    r["line"] for r in rows if r["text"].startswith(("第一章", "第二章"))
                                ]
                            }
                        )
                    }
                }
            ]
        }

    monkeypatch.setattr(providers, "request", response)
    chapters = providers.analyze_chapters({"model": "test"}, text)
    assert "".join(c["text"] for c in chapters) == text
    assert len(chapters) == 3 and chapters[1]["title"] == "第一章 海"
    monkeypatch.setattr(
        providers, "request", lambda *args, **kw: {"choices": [{"message": {"content": '{"boundaries":[999999]}'}}]}
    )
    with pytest.raises(ValueError):
        providers.analyze_chapters({"model": "test"}, text)


def test_speech_analysis_separates_dialogue_and_validates_voices(monkeypatch):
    text = "林舟看着远方。“你终于来了。”沈雾轻声说。\n海风渐起。"
    parts = importer.director_segments(text)
    assert "".join(s["text"] for s in parts) == text
    assert any(s["text"] == "“你终于来了。”" for s in parts)

    def response(config, endpoint, body, timeout=None):
        request = json.loads(body["messages"][-1]["content"])
        values = [
            {
                "index": s["index"],
                "speaker": "沈雾" if "“" in s["text"] else "旁白",
                "voice": "soft" if "“" in s["text"] else "calm",
                "emotion": "calm",
                "speed": 0.9,
                "pause": 300,
            }
            for s in request["segments"]
        ]
        return {"choices": [{"message": {"content": json.dumps({"segments": values})}}]}

    monkeypatch.setattr(providers, "request", response)
    values = providers.analyze({"model": "test"}, parts, [{"id": "soft"}, {"id": "calm"}])
    assert {v["voice"] for v in values} == {"soft", "calm"}
    assert "".join(v["text"] for v in values) == text
    # A fabricated voice is dropped (falls back to the book default) instead
    # of failing the whole analysis.
    values = providers.analyze({"model": "test"}, parts, [{"id": "only-known-voice"}])
    assert {v["voice"] for v in values} == {""}
    assert "".join(v["text"] for v in values) == text


def test_delete_rejects_running_job_then_removes_related_records(client):
    b = import_book(client)
    store = client.app.state.store
    job = store.job("generate", {}, b["id"], b["chapters"][0]["id"])
    store.execute("UPDATE jobs SET status='running' WHERE id=?", (job,))
    assert client.delete("/api/books/" + b["id"]).status_code == 409
    assert client.get("/api/books/" + b["id"]).status_code == 200
    store.execute("UPDATE jobs SET status='cancelled' WHERE id=?", (job,))
    store.execute("INSERT INTO marks VALUES (?,?,?,?,?)", ("mark", b["chapters"][0]["id"], 0, "note", 0))
    store.file("exports/test.zip").write_bytes(b"test")
    store.execute(
        "INSERT INTO exports VALUES (?,?,?,?,?,?)", ("export", b["id"], "exports/test.zip", "mp3", 0, 1)
    )
    assert client.delete("/api/books/" + b["id"]).status_code == 200
    assert not store.rows("SELECT * FROM jobs WHERE book_id=?", (b["id"],))
    assert not store.rows("SELECT * FROM marks")
    assert not store.file("exports/test.zip").exists()


def test_apply_rejects_stale_preview_and_decodes_gb18030(client, monkeypatch):
    b = import_book(client)
    store = client.app.state.store
    source = "第一章 灯塔\n灯亮了。\n第二章 来信\n他打开信封。"
    store.file(b["source"]).write_bytes(source.encode("gb18030"))
    assert importer.source_text(store.file(b["source"]).read_bytes(), b["source"]) == source
    store.set("ai", {"base_url": "https://example.com/v1", "model": "test"})
    monkeypatch.setattr(
        providers, "analyze_chapters", lambda config, text, progress: [{"title": "正文", "text": text}]
    )
    job = client.post(f"/api/books/{b['id']}/analyze-chapters").json()["id"]
    run_job(client, job)
    c = client.get("/api/chapters/" + b["chapters"][0]["id"]).json()
    client.put(
        "/api/chapters/" + c["id"],
        json={"title": "已修改", "revision": c["revision"], "segments": c["segments"]},
    )
    assert client.post(f"/api/books/{b['id']}/apply-chapters", json={"job_id": job}).status_code == 409
    assert client.get("/api/chapters/" + c["id"]).json()["title"] == "已修改"


def test_restructure_flow_preview_and_adopt(client, monkeypatch):
    text = "第一章 夜航\n夜很深。海风推着船。\n“你终于来了。”她轻声说。\n第二章 来信\n他打开信封。"
    b = import_book(client, text)
    store = client.app.state.store
    store.set("ai", {"base_url": "https://example.com/v1", "model": "test", "api_key": ""})
    cid = b["chapters"][0]["id"]
    detail = client.get("/api/chapters/" + cid).json()
    source = detail["source"]
    # The model only ever sees fine narration/dialogue units and returns
    # indices plus a speaker per group.
    seen_bodies = []

    def fake_request(config, endpoint, body, timeout=None):
        payload = json.loads(body["messages"][-1]["content"])
        seen_bodies.append(payload)
        units = payload["units"]
        assert [u["kind"] for u in units] == ["narration", "dialogue", "narration"]
        groups = [
            {"units": [0], "speaker": "旁白"},
            {"units": [1], "speaker": "林晚"},
            {"units": [2], "speaker": "旁白"},
        ]
        return {"choices": [{"message": {"content": json.dumps({"groups": groups}, ensure_ascii=False)}}]}

    monkeypatch.setattr(providers, "request", fake_request)
    first = client.post(f"/api/chapters/{cid}/restructure")
    assert first.status_code == 200
    # A queued restructure job is returned instead of enqueueing a duplicate.
    assert client.post(f"/api/chapters/{cid}/restructure").json()["id"] == first.json()["id"]
    run_job(client, first.json()["id"])
    preview = client.get("/api/chapters/" + cid).json()
    proposed = preview["restructure"]["segments"]
    assert preview["restructure"]["existing_revision"] == preview["revision"]
    assert [u["index"] for u in seen_bodies[0]["units"]] == [0, 1, 2]
    assert "".join(s["text"] for s in proposed) == source
    # Quote carries the character, attribution and narration stay 旁白.
    assert [s["speaker"] for s in proposed] == ["旁白", "林晚", "旁白"]
    assert [s["pause"] for s in proposed] == [250, 300, 250]
    result = client.put(
        "/api/chapters/" + cid,
        json={"revision": preview["revision"], "title": preview["title"], "segments": proposed},
    )
    assert result.status_code == 200, result.text
    updated = client.get("/api/chapters/" + cid).json()
    assert len(updated["segments"]) == 3
    assert "".join(s["text"] for s in updated["segments"]) == source
    assert updated["revision"] == preview["revision"] + 1
    # The preview is tied to the old revision and disappears after adoption.
    assert updated["restructure"] is None and updated["suggestion"] is None


def test_restructure_length_guard(client):
    b = import_book(client, "第一章 长夜\n" + "很长的句子。" * 4000)
    store = client.app.state.store
    store.set("ai", {"base_url": "https://example.com/v1", "model": "test", "api_key": ""})
    result = client.post(f"/api/chapters/{b['chapters'][0]['id']}/restructure")
    assert result.status_code == 400
    assert "2 万字" in result.json()["detail"]


def test_restructure_falls_back_to_paragraph_units(monkeypatch):
    text = "夜很深。\n\n“你终于来了。”\n海风渐起。"
    unusable = json.dumps({"groups": [{"units": [0]}]}, ensure_ascii=False)
    monkeypatch.setattr(
        providers, "request", lambda *a, **kw: {"choices": [{"message": {"content": unusable}}]}
    )
    pieces = providers.restructure_chapter({"model": "test"}, text)
    # Incomplete grouping falls back to per-unit labeling, never a failure.
    assert "".join(c["text"] for c in pieces) == text
    assert [c["hint"] for c in pieces] == ["narration", "dialogue", "narration"]


def test_restructure_separates_multiple_speakers_in_one_paragraph(monkeypatch):
    """Two characters quoting inside one paragraph must become separate
    segments with their own speakers; narration stays 旁白."""
    text = "“你好。”张三说。“你也好。”李四笑道。"
    reply = json.dumps(
        {
            "groups": [
                {"units": [0], "speaker": "张三"},
                {"units": [1], "speaker": "旁白"},
                {"units": [2], "speaker": "李四"},
                {"units": [3], "speaker": "旁白"},
            ]
        },
        ensure_ascii=False,
    )
    monkeypatch.setattr(
        providers, "request", lambda *a, **kw: {"choices": [{"message": {"content": reply}}]}
    )
    pieces = providers.restructure_chapter({"model": "test"}, text)
    assert "".join(c["text"] for c in pieces) == text
    assert [c["speaker"] for c in pieces] == ["张三", "旁白", "李四", "旁白"]
    assert [c["hint"] for c in pieces] == ["dialogue", "narration", "dialogue", "narration"]


def test_restructure_splits_mixed_group_by_local_kind(monkeypatch):
    """A model group that glues narration onto a character's dialogue is
    split locally so narration never reads with the character's voice."""
    text = "“走吧。”她说。"
    reply = json.dumps({"groups": [{"units": [0, 1], "speaker": "林晚"}]}, ensure_ascii=False)
    monkeypatch.setattr(
        providers, "request", lambda *a, **kw: {"choices": [{"message": {"content": reply}}]}
    )
    pieces = providers.restructure_chapter({"model": "test"}, text)
    assert "".join(c["text"] for c in pieces) == text
    assert [c["speaker"] for c in pieces] == ["林晚", "旁白"]
    assert [c["hint"] for c in pieces] == ["dialogue", "narration"]


def test_restructure_splits_oversized_units(monkeypatch):
    text = "这一句很长。" * 300 + "\n尾声。"
    merged = json.dumps(
        {"groups": [{"units": [0, 1], "speaker": "旁白"}]},
        ensure_ascii=False,
    )
    monkeypatch.setattr(
        providers, "request", lambda *a, **kw: {"choices": [{"message": {"content": merged}}]}
    )
    pieces = providers.restructure_chapter({"model": "test"}, text)
    assert "".join(c["text"] for c in pieces) == text
    assert len(pieces) >= 2
    assert all(len(c["text"]) <= 1200 for c in pieces)


def test_emotion_styles_map_to_provider_params(monkeypatch):
    """Extended styles map onto the provider's supported emotion enum plus
    prosody tweaks; stuttering is simulated by text repetition at synthesis."""
    captured = {}

    def fake_request(config, endpoint, body, audio=False, timeout=None, retries=0):
        captured.update(body)
        return {"data": {"audio": "00"}, "base_resp": {"status_code": 0}}

    monkeypatch.setattr(providers, "request", fake_request)
    segment = {
        "text": "大家好，今天来晚了。",
        "voice": "v1",
        "emotion": "charming",
        "speed": 1.0,
        "pause": 250,
        "speaker": "旁白",
    }
    providers.synthesize({"provider": "minimax", "model": "m"}, segment)
    setting = captured["voice_setting"]
    # Styles only tint the delivery through the provider's emotion enum and a
    # small speed tendency — pitch/volume stay untouched so one character
    # cannot sound like a different person across emotions.
    assert setting["emotion"] == "calm"
    assert setting["speed"] == 0.94
    assert setting["vol"] == 1 and "pitch" not in setting
    stutter = {**segment, "emotion": "stutter"}
    providers.synthesize({"provider": "minimax", "model": "m"}, stutter)
    assert "大、大家好" in captured["text"]
    # Unknown emotions degrade to the default style instead of failing.
    providers.synthesize({"provider": "minimax", "model": "m"}, {**segment, "emotion": "moonwalk"})
    assert "emotion" not in captured["voice_setting"]
    # Whisper keeps its volume cue.
    providers.synthesize({"provider": "minimax", "model": "m"}, {**segment, "emotion": "whisper"})
    assert captured["voice_setting"]["vol"] == 0.6


def test_analyze_uses_saved_script_segments(client, monkeypatch):
    """Voice and speed suggestions must follow the script the user adopted."""
    b = import_book(client)
    cid = b["chapters"][0]["id"]
    detail = client.get("/api/chapters/" + cid).json()
    custom = [
        {"text": "灯亮了。", "voice": "", "emotion": "neutral", "speed": 1, "pause": 250, "speaker": "旁白"},
        {
            "text": "远处传来汽笛。",
            "voice": "",
            "emotion": "neutral",
            "speed": 1,
            "pause": 400,
            "speaker": "旁白",
        },
    ]
    saved = client.put(
        "/api/chapters/" + cid,
        json={"revision": detail["revision"], "title": detail["title"], "segments": custom},
    )
    assert saved.status_code == 200, saved.text
    store = client.app.state.store
    store.set("ai", {"base_url": "https://example.com/v1", "model": "test", "api_key": ""})
    seen = []

    def fake_request(config, endpoint, body, timeout=None):
        batch = json.loads(body["messages"][-1]["content"])["segments"]
        seen.append(batch)
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "segments": [
                                    {
                                        "index": s["index"],
                                        "speaker": "旁白",
                                        "emotion": "calm",
                                        "speed": 0.95,
                                        "pause": 300,
                                        "reason": "舒缓",
                                    }
                                    for s in batch
                                ]
                            }
                        )
                    }
                }
            ]
        }

    monkeypatch.setattr(providers, "request", fake_request)
    ident = client.post(f"/api/chapters/{cid}/analyze").json()["id"]
    run_job(client, ident)
    assert [s["text"] for s in seen[0]] == ["灯亮了。", "远处传来汽笛。"]
    c = client.get("/api/chapters/" + cid).json()
    assert c["suggestion"]["segments"][1]["text"] == "远处传来汽笛。"
    assert c["suggestion"]["segments"][1]["speed"] == 0.95


def test_synthesis_units_split_dialogue_and_narration():
    from app.worker import synthesis_units

    character = {
        "text": "“请不要在我家里抽烟。”汪淼拦住了他。",
        "voice": "male-warm",
        "emotion": "angry",
        "speed": 1,
        "pause": 250,
        "speaker": "汪淼",
    }
    units = synthesis_units(character, "narrator-default")
    assert [u["voice"] for u in units] == ["male-warm", "narrator-default"]
    assert [u["speaker"] for u in units] == ["汪淼", "旁白"]
    assert units[1]["emotion"] == "neutral"
    assert "".join(u["text"] for u in units) == character["text"]
    # Narration segments and default-voice segments are never split.
    plain = {**character, "text": "他拦住了他。", "speaker": "旁白"}
    assert synthesis_units(plain, "narrator-default") == [plain]
    default_voice = {**character, "voice": "narrator-default"}
    assert synthesis_units(default_voice, "narrator-default") == [default_voice]
    no_voice = {**character, "voice": ""}
    assert synthesis_units(no_voice, "narrator-default") == [no_voice]


def test_request_retries_transient_rejections(monkeypatch):
    attempts = []

    def fake_once(config, endpoint, body, audio, timeout):
        attempts.append(1)
        if len(attempts) < 3:
            raise providers.Rejected("语音服务拒绝请求，错误码 1002。", retryable=True)
        return {"ok": True}

    monkeypatch.setattr(providers, "_request_once", fake_once)
    monkeypatch.setattr(providers.time, "sleep", lambda seconds: None)
    result = providers.request({"base_url": "https://x/v1"}, "/t2a_v2", {}, retries=2)
    assert result == {"ok": True} and len(attempts) == 3
    # Non-retryable rejections surface immediately.
    attempts.clear()
    monkeypatch.setattr(
        providers,
        "_request_once",
        lambda *a: (_ for _ in ()).throw(providers.Rejected("密钥无效", retryable=False)),
    )
    with pytest.raises(ValueError, match="密钥无效"):
        providers.request({"base_url": "https://x/v1"}, "/t2a_v2", {}, retries=2)


def test_synthesis_resolves_speaker_bindings(monkeypatch, wav_bytes, client):
    """Narration is pinned to the default voice; a character keeps one voice
    for the whole chapter even when individual segments lost theirs."""
    from app.worker import resolved_segment, speaker_bindings

    segments = [
        {"text": "夜很深。", "voice": "stray", "emotion": "neutral", "speed": 1, "pause": 250, "speaker": "旁白"},
        {"text": "“站住。”", "voice": "male-a", "emotion": "neutral", "speed": 1, "pause": 250, "speaker": "汪淼"},
        {"text": "他停下脚步。", "voice": "", "emotion": "neutral", "speed": 1, "pause": 250, "speaker": "旁白"},
        {"text": "“走吧。”", "voice": "", "emotion": "neutral", "speed": 1, "pause": 250, "speaker": "汪淼"},
        {"text": "“好的。”", "voice": "male-b", "emotion": "neutral", "speed": 1, "pause": 250, "speaker": "汪淼"},
    ]
    bindings = speaker_bindings(segments)
    # male-a and male-b both appear once; either may win, but it must be one
    # of them and every 汪淼 segment resolves to it.
    assert bindings["汪淼"] in ("male-a", "male-b")
    assert resolved_segment(segments[0], bindings)["voice"] == ""
    assert resolved_segment(segments[2], bindings)["voice"] == ""
    assert resolved_segment(segments[1], bindings)["voice"] == bindings["汪淼"]
    assert resolved_segment(segments[3], bindings)["voice"] == bindings["汪淼"]
    assert resolved_segment(segments[4], bindings)["voice"] == bindings["汪淼"]


def test_voice_rules_narration_mislabel_and_book_cast(client, monkeypatch, wav_bytes):
    """Hard synthesis rules: text without quotes is narration (default voice)
    even when mislabeled; a character's voice persists across chapters via
    the book cast; name variants share one voice."""
    from app.worker import norm_speaker

    b = import_book(client, "第一章 灯塔\n占位。\n第二章 来信\n占位。")
    store = client.app.state.store
    c1 = client.get("/api/chapters/" + b["chapters"][0]["id"]).json()
    segs = [
        {"text": "“站住。”", "voice": "wangMiao", "emotion": "neutral", "speed": 1, "pause": 250, "speaker": "汪淼"},
        {"text": "汪淼拦住了他。", "voice": "wangMiao", "emotion": "neutral", "speed": 1, "pause": 250, "speaker": "汪淼"},
        {"text": "他停下了。", "voice": "", "emotion": "neutral", "speed": 1, "pause": 250, "speaker": "旁白"},
    ]
    saved = client.put(
        "/api/chapters/" + c1["id"],
        json={"revision": c1["revision"], "title": c1["title"], "segments": segs},
    )
    assert saved.status_code == 200, saved.text
    # Saving synced the book cast: 汪淼 → wangMiao (only the quoted line counts).
    cast = store.rows("SELECT speaker, voice FROM cast WHERE book_id=?", (b["id"],))
    assert [(r["speaker"], r["voice"]) for r in cast] == [(norm_speaker("汪淼"), "wangMiao")]

    seen = []

    def fake_synth(config, segment):
        seen.append((segment["text"], segment["voice"]))
        return wav_bytes

    monkeypatch.setattr(providers, "synthesize", fake_synth)
    job = client.post(
        f"/api/books/{b['id']}/generate", json={"chapter_ids": [c1["id"]]}
    ).json()["ids"][0]
    run_job(client, job)
    # Quote keeps the character voice; the mislabeled quote-less narration
    # falls back to the default narrator voice.
    assert ("“站住。”", "wangMiao") in seen
    assert ("汪淼拦住了他。", "") in seen
    assert ("他停下了。", "") in seen

    # Chapter 2: name variant with no voice at all inherits the book cast.
    c2 = client.get("/api/chapters/" + b["chapters"][1]["id"]).json()
    segs2 = [
        {
            "text": "“走吧。”",
            "voice": "",
            "emotion": "neutral",
            "speed": 1,
            "pause": 250,
            "speaker": "汪淼（青年）",
        }
    ]
    saved2 = client.put(
        "/api/chapters/" + c2["id"],
        json={"revision": c2["revision"], "title": c2["title"], "segments": segs2},
    )
    assert saved2.status_code == 200, saved2.text
    seen.clear()
    job2 = client.post(
        f"/api/books/{b['id']}/generate", json={"chapter_ids": [c2["id"]]}
    ).json()["ids"][0]
    run_job(client, job2)
    assert seen == [("“走吧。”", "wangMiao")]


def test_resolved_segment_name_variants_and_narration_rule():
    from app.worker import resolved_segment

    bindings = {"汪淼": "voiceA"}
    cast = {"汪淼": "voiceA"}
    variant = {"text": "“嗯。”", "voice": "", "speaker": " 汪淼（青年） ", "pause": 250}
    assert resolved_segment(variant, bindings, cast)["voice"] == "voiceA"
    # Quote-less text is narration even with a character label and voice.
    mislabeled = {"text": "他停下了。", "voice": "voiceA", "speaker": "汪淼", "pause": 250}
    assert resolved_segment(mislabeled, bindings, cast)["voice"] == ""


def test_restructure_fuses_inline_quotes(monkeypatch):
    """A quotation that is a name/title, not speech (model marks it 旁白),
    fuses back into the surrounding sentence instead of carving it apart."""
    text = "那是一年前，汪淼是“中华二号”高能加速器项目的负责人。"
    reply = json.dumps({"groups": [{"units": [0, 1, 2], "speaker": "旁白"}]}, ensure_ascii=False)
    monkeypatch.setattr(
        providers, "request", lambda *a, **kw: {"choices": [{"message": {"content": reply}}]}
    )
    pieces = providers.restructure_chapter({"model": "test"}, text)
    assert len(pieces) == 1
    assert pieces[0]["text"] == text
    assert pieces[0]["speaker"] == "旁白" and pieces[0]["hint"] == "narration"


def test_restructure_never_leaves_orphan_punctuation(monkeypatch):
    """Connector punctuation between a quote and the following narration is
    attached to the quote's segment, never left as a standalone "。" piece."""
    text = "“先生们”。，汪淼看看对面的人。"
    reply = json.dumps(
        {"groups": [{"units": [0], "speaker": "将军"}, {"units": [1], "speaker": "旁白"}]},
        ensure_ascii=False,
    )
    monkeypatch.setattr(
        providers, "request", lambda *a, **kw: {"choices": [{"message": {"content": reply}}]}
    )
    pieces = providers.restructure_chapter({"model": "test"}, text)
    assert "".join(c["text"] for c in pieces) == text
    assert [c["text"] for c in pieces] == ["“先生们”。，", "汪淼看看对面的人。"]
    assert [c["speaker"] for c in pieces] == ["将军", "旁白"]


def test_book_cast_management(client):
    b = import_book(client, "第一章 台球\n“站住。”丁仪说。\n汪淼点头。\n“走吧。”丁仪又说。")
    store = client.app.state.store
    store.set("voices", [{"id": "d2", "name": "低沉"}, {"id": "d3", "name": "清朗"}])
    cid = b["chapters"][0]["id"]
    detail = client.get("/api/chapters/" + cid).json()
    segs = [
        {"text": "“站住。”丁仪说。", "voice": "d2", "emotion": "neutral", "speed": 1, "pause": 250, "speaker": "丁仪"},
        {"text": "汪淼点头。", "voice": "", "emotion": "neutral", "speed": 1, "pause": 250, "speaker": "旁白"},
        {"text": "“走吧。”丁仪又说。", "voice": "d2", "emotion": "neutral", "speed": 1, "pause": 250, "speaker": "丁仪"},
    ]
    saved = client.put("/api/chapters/" + cid, json={"revision": detail["revision"], "title": detail["title"], "segments": segs})
    assert saved.status_code == 200, saved.text

    data = client.get(f"/api/books/{b['id']}/cast").json()
    ding = next(c for c in data["cast"] if c["speaker"] == norm("丁仪"))
    assert ding["lines"] == 2 and ding["voice"] == "d2" and ding["bound"] is True
    assert "旁白" not in [c["speaker"] for c in data["cast"]]
    assert data["narrator_voice"] == ""
    assert data["chapters"][0]["speakers"] == [norm("丁仪")]

    # Rebind to a known voice.
    assert (
        client.put(f"/api/books/{b['id']}/cast", json={"speaker": "丁仪", "voice": "d3"}).json()["voice"]
        == "d3"
    )
    assert (
        client.get(f"/api/books/{b['id']}/cast").json()["cast"][0]["voice"] == "d3"
    )
    # Unknown voice rejected; narrator rejected; empty voice clears binding.
    assert client.put(f"/api/books/{b['id']}/cast", json={"speaker": "丁仪", "voice": "nope"}).status_code == 400
    assert client.put(f"/api/books/{b['id']}/cast", json={"speaker": "旁白", "voice": "d3"}).status_code == 400
    assert client.put(f"/api/books/{b['id']}/cast", json={"speaker": "丁仪", "voice": ""}).status_code == 200
    assert client.get(f"/api/books/{b['id']}/cast").json()["cast"][0]["voice"] == "d2"  # chapter majority


def norm(name):
    from app.worker import norm_speaker

    return norm_speaker(name)


def test_segment_regen_splices_in_place(client, monkeypatch, wav_bytes):
    import io
    import wave

    b = import_book(client, "第一章 台球\n第一段。\n第二段。\n第三段。")
    cid = b["chapters"][0]["id"]
    job = client.post(f"/api/books/{b['id']}/generate", json={"chapter_ids": [cid]}).json()["ids"][0]
    monkeypatch.setattr(providers, "synthesize", lambda config, s: wav_bytes)
    run_job(client, job)
    old = client.get("/api/chapters/" + cid).json()
    old_audio_id = old["active_audio"]
    meta = client.get(f"/api/audio/{old_audio_id}/metadata").json()
    assert abs(meta["duration"] - 0.8) < 0.05  # 3 × 0.1s + 2 × 250ms pauses

    # Drop segment 2's cached audio so the regen must actually synthesize it,
    # with a longer duration, and only for that one segment.
    from app.worker import resolved_segment, speaker_bindings

    store = client.app.state.store
    segs = old["segments"]
    resolved = resolved_segment(segs[1], speaker_bindings(segs), {})
    worker = client.app.state.worker
    cached = worker.synthesize_to_cache(resolved, store.get("tts"), None, "")
    cached.unlink()

    calls = []

    def long_wav(config, segment):
        calls.append(segment["text"])
        output = io.BytesIO()
        with wave.open(output, "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(24000)
            f.writeframes(b"\x00\x10" * 24000)  # 1.0s, much longer than 0.1s
        return output.getvalue()

    monkeypatch.setattr(providers, "synthesize", long_wav)
    result = client.post(f"/api/chapters/{cid}/regen-segment", json={"index": 1})
    assert result.status_code == 200, result.text
    run_job(client, result.json()["id"])
    assert calls == [segs[1]["text"]]  # only the target segment is re-synthesized

    new_meta = client.get(f"/api/audio/{client.get('/api/chapters/' + cid).json()['active_audio']}/metadata").json()
    assert abs(new_meta["duration"] - 1.7) < 0.05  # 0.8 - 0.1 + 1.0
    by_index = {t["index"]: t for t in new_meta["timeline"]}
    # The replaced span covers the new audio plus the preserved 250ms pause.
    assert abs(by_index[1]["end"] - by_index[1]["start"] - 1.25) < 0.05
    assert by_index[2]["start"] >= by_index[1]["end"]  # later segments shifted

    # Editing + saving stales the audio, and a partial regen is exactly the
    # tool to refresh ONE segment: it must succeed after the save (P1 fix —
    # it used to 409 and force a full-chapter regeneration), synthesize the
    # NEW text (changed text also changes the cache key), splice in place,
    # and promote the result to the current revision.
    segs[1]["text"] = "第二段改写后的句子。\n"
    save = client.put(
        "/api/chapters/" + cid,
        json={"revision": client.get("/api/chapters/" + cid).json()["revision"], "title": "台球", "segments": segs},
    )
    assert save.status_code == 200
    calls.clear()
    after_edit = client.post(f"/api/chapters/{cid}/regen-segment", json={"index": 1})
    assert after_edit.status_code == 200, after_edit.text
    run_job(client, after_edit.json()["id"])
    assert calls == [segs[1]["text"]]
    final = client.get("/api/chapters/" + cid).json()
    # versions[0] is the newest — its revision equals the chapter's: promoted.
    assert final["versions"][0]["revision"] == final["revision"]


def test_reading_style_scales_pauses_without_resynthesis(client, monkeypatch, wav_bytes):
    b = import_book(client, "第一章 台球\n第一段。\n第二段。\n第三段。")
    cid = b["chapters"][0]["id"]
    calls = []
    monkeypatch.setattr(
        providers,
        "synthesize",
        lambda config, s: (calls.append(s["text"]), wav_bytes)[1],
    )
    run_job(client, client.post(f"/api/books/{b['id']}/generate", json={"chapter_ids": [cid]}).json()["ids"][0])
    assert len(calls) == 3
    # Pause scaling lives entirely in the concatenation layer: zero synthesis.
    assert (
        client.put(
            f"/api/books/{b['id']}",
            json={"style": {"preset": "custom", "narration_pause": 2.0}},
        ).status_code
        == 200
    )
    run_job(client, client.post(f"/api/books/{b['id']}/generate", json={"chapter_ids": [cid]}).json()["ids"][0])
    assert len(calls) == 3
    meta = client.get(
        f"/api/audio/{client.get('/api/chapters/' + cid).json()['active_audio']}/metadata"
    ).json()
    by_index = {t["index"]: t for t in meta["timeline"]}
    # Entry 0 spans its audio plus the scaled 500ms pause.
    assert abs((by_index[0]["end"] - by_index[0]["start"]) - 0.6) < 0.05


def test_generation_flags_silent_audio(client, monkeypatch):
    silent = io.BytesIO()
    with wave.open(silent, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(24000)
        f.writeframes(b"\x00\x00" * 2400)
    b = import_book(client, "第一章 台球\n第一段。\n第二段。")
    monkeypatch.setattr(providers, "synthesize", lambda config, s: silent.getvalue())
    run_job(
        client,
        client.post(f"/api/books/{b['id']}/generate", json={"chapter_ids": [b["chapters"][0]["id"]]}).json()["ids"][0],
    )
    cid = b["chapters"][0]["id"]
    meta = client.get(
        f"/api/audio/{client.get('/api/chapters/' + cid).json()['active_audio']}/metadata"
    ).json()
    assert meta["quality"]["segments"]
    assert all("silent" in q["issues"] for q in meta["quality"]["segments"])


def test_notify_settings_roundtrip(client):
    assert client.put(
        "/api/settings/notify",
        json={"enabled": True, "kind": "bark", "url": "https://api.day.app/key"},
    ).status_code == 200
    saved = client.get("/api/settings").json()["notify"]
    assert saved["enabled"] is True and saved["kind"] == "bark"
    # Partial body applies defaults (only the full settings form calls this).
    assert client.put("/api/settings/notify", json={"enabled": True}).status_code == 200


def test_normalize_loudness_targets_shared_rms(tmp_path):
    import audioop

    def make(name, amp, frames=24000):
        path = tmp_path / name
        with wave.open(str(path), "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(24000)
            f.writeframes(
                b"".join(
                    struct.pack("<h", int(amp * math.sin(i * 0.05)))
                    for i in range(frames)
                )
            )
        return path

    def rms_of(path):
        with wave.open(str(path), "rb") as w:
            return audioop.rms(w.readframes(w.getnframes()), 2)

    soft = make("soft.wav", 2000)
    before = rms_of(soft)
    audio.normalize_loudness(soft)
    after = rms_of(soft)
    assert before < 2000 and 2500 < after < 4500  # boosted toward the target

    hot = make("hot.wav", 20000)
    audio.normalize_loudness(hot)
    assert rms_of(hot) < 6000  # hot input is attenuated, never boosted

    # Silence is left untouched.
    silent = make("silent.wav", 0)
    audio.normalize_loudness(silent)
    assert rms_of(silent) == 0


def test_split_units_keeps_whitespace_after_punctuation_run():
    """Regression: "…… " before a newline once lost its trailing space in the
    punctuation peel, tripping the integrity check on real novels."""
    text = "“我们要坐飞船走！飞船万岁！” \n…… \n小星老师按了一下手腕上的全息显示器。"
    stream, units = providers._split_units(text)
    joined = "".join(v if k == "gap" else units[v]["text"] for k, v in stream)
    assert joined == text
