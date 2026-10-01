"""Offline local TTS: model catalog endpoints, provider wiring, clones."""

import io
import tarfile
import wave

import pytest

from app import local_tts, providers
from tests.conftest import import_book


def wav(seconds=2.0, rate=24000):
    output = io.BytesIO()
    with wave.open(output, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(b"\x00\x10" * int(rate * seconds))
    return output.getvalue()


def choose_local(client):
    result = client.put(
        "/api/settings/tts",
        json={"provider": "local", "base_url": "https://leftover.example/v1", "model": "speech-2.6-hd"},
    )
    assert result.status_code == 200, result.text
    return result.json()


def test_local_models_catalog(client):
    data = client.get("/api/local/models").json()
    assert [m["id"] for m in data["models"]] == ["kokoro-int8", "kokoro", "zipvoice"]
    assert all(m["state"] == "missing" for m in data["models"])
    # The runtime dependency ships in requirements.lock, so it must resolve.
    assert data["dependency"] is None


def test_download_rejects_unknown_model(client):
    assert client.post("/api/local/models/nope/download").status_code == 400
    assert client.delete("/api/local/models/nope").status_code == 400


def test_settings_local_provider(client):
    data = choose_local(client)
    # Cloud fields are blanked so leftovers cannot leak into local cache
    # identities; the voice is normalized to a valid built-in one.
    assert data["provider"] == "local" and data["base_url"] == "" and data["model"] == ""
    assert data["voice"] == "k:3"
    voices = client.get("/api/voices").json()
    assert len(voices["voices"]) == 103
    assert voices["voices"][0]["id"] == "k:0"
    assert voices["emotion"] is False
    # A rejected provider value still fails.
    assert client.put("/api/settings/tts", json={"provider": "nope"}).status_code == 400


def test_local_test_endpoint_reports_missing_models(client):
    choose_local(client)
    message = client.post("/api/settings/tts/test").json()["message"]
    assert "依赖" in message and "下载" in message


def test_local_voices_refresh_is_live(client):
    choose_local(client)
    assert client.post("/api/voices/refresh").json()["count"] == 103


def test_generate_with_local_engine(client, monkeypatch, wav_bytes):
    choose_local(client)
    calls = []

    def fake_synthesize(store, voice, text, speed=1.0):
        calls.append((voice, text, speed))
        return wav_bytes

    monkeypatch.setattr(local_tts, "synthesize", fake_synthesize)
    b = import_book(client)
    cid = b["chapters"][0]["id"]
    ident = client.post(f"/api/books/{b['id']}/generate", json={"chapter_ids": [cid]}).json()["ids"][0]
    store = client.app.state.store
    row = store.one("SELECT * FROM jobs WHERE id=?", (ident,))
    client.app.state.worker.update(ident, status="running")
    client.app.state.worker.run(row)
    chapter = client.get("/api/chapters/" + cid).json()
    assert chapter["active_audio"], "local generation should produce audio"
    assert calls and calls[0][0] == "k:3"


def test_local_emotion_degrades_to_speed_only(monkeypatch, wav_bytes):
    captured = {}

    def fake_synthesize(store, voice, text, speed=1.0):
        captured["speed"] = speed
        return wav_bytes

    monkeypatch.setattr(local_tts, "synthesize", fake_synthesize)
    config = {"provider": "local", "voice": "k:3"}
    segment = {"text": "他大喊。", "voice": "k:5", "emotion": "excited", "speed": 1.0}
    providers.synthesize(config, segment, store=object())
    assert captured["speed"] == pytest.approx(1.08)  # excited style speed, no pitch/volume
    segment["emotion"] = "whisper"
    providers.synthesize(config, segment, store=object())
    assert captured["speed"] == pytest.approx(0.92)  # whisper volume cue is MiniMax-only


def test_local_identity_scopes_to_local_provider(client, tmp_path):
    cloud = {"provider": "minimax", "voice": "male-qn-qingse"}
    assert providers.local_identity(cloud, {"voice": ""}, None) == {}
    local = {"provider": "local", "voice": "k:3"}
    assert providers.local_identity(local, {"voice": ""}, None) == {"local_engines": ["unavailable"]}
    signature = providers.local_identity(local, {"voice": ""}, client.app.state.store)
    assert signature == {"local_engines": ["kokoro-missing"]}


def test_signature_tracks_model_variant(client):
    store = client.app.state.store
    assert local_tts.signature(store, ["k:3"]) == {"local_engines": ["kokoro-missing"]}
    directory = local_tts.models_root(store) / "kokoro-int8"
    directory.mkdir(parents=True)
    (directory / "model.int8.onnx").write_bytes(b"x")
    (directory / "voices.bin").write_bytes(b"x")
    (directory / "tokens.txt").write_bytes(b"x")
    (directory / "espeak-ng-data").mkdir()
    (directory / "meta.json").write_text("{}")
    assert local_tts.signature(store, ["k:3"]) == {"local_engines": ["kokoro-int8"]}


def test_extract_flattens_single_top_dir(tmp_path):
    archive = tmp_path / "m.tar.bz2"
    inner = tmp_path / "pkg" / "kokoro-model"
    inner.mkdir(parents=True)
    (inner / "model.onnx").write_bytes(b"x")
    (inner / "espeak-ng-data").mkdir()
    with tarfile.open(archive, "w:bz2") as tar:
        tar.add(inner / "model.onnx", arcname="kokoro-model/model.onnx")
        tar.add(inner / "espeak-ng-data", arcname="kokoro-model/espeak-ng-data")
    staging = tmp_path / "staging"
    staging.mkdir()
    local_tts._extract(archive, staging)
    assert (staging / "model.onnx").is_file()
    assert (staging / "espeak-ng-data").is_dir()


def test_clone_register_list_delete(client):
    choose_local(client)
    audio = wav(2.0)
    result = client.post(
        "/api/voices/clone",
        data={"name": "旁白 · 沉稳男声", "text": "这是参考音频的原文。"},
        files={"file": ("ref.wav", audio, "audio/wav")},
    )
    assert result.status_code == 200, result.text
    voice = result.json()
    assert voice["id"].startswith("c:")
    listing = client.get("/api/voices").json()["voices"]
    assert any(v["id"] == voice["id"] for v in listing)
    # Identical material is rejected as a duplicate (stable id from content).
    duplicate = client.post(
        "/api/voices/clone",
        data={"name": "again", "text": "这是参考音频的原文。"},
        files={"file": ("ref.wav", audio, "audio/wav")},
    )
    assert duplicate.status_code == 400
    # A clone id is bindable as the narrator voice of a book.
    b = client.post(
        "/api/imports",
        files={"file": ("x.txt", "第一章 灯塔\n灯亮了。".encode(), "text/plain")},
    )
    data = b.json()
    book = client.post(
        "/api/imports/confirm",
        json={"id": data["id"], "title": "雾海来信", "chapters": data["chapters"]},
    ).json()
    assert client.put(f"/api/books/{book['id']}", json={"voice": voice["id"]}).status_code == 200
    # Unknown voices stay rejected.
    assert client.put(f"/api/books/{book['id']}", json={"voice": "k:999"}).status_code == 400
    assert client.delete("/api/voices/clone/" + voice["id"][2:]).status_code == 200
    assert client.delete("/api/voices/clone/" + voice["id"][2:]).status_code == 400
    assert not any(v["id"] == voice["id"] for v in client.get("/api/voices").json()["voices"])


def test_clone_rejects_bad_input(client):
    choose_local(client)
    long_audio = wav(40.0)
    too_long = client.post(
        "/api/voices/clone",
        data={"name": "x", "text": "原文"},
        files={"file": ("ref.wav", long_audio, "audio/wav")},
    )
    assert too_long.status_code == 400
    garbage = client.post(
        "/api/voices/clone",
        data={"name": "x", "text": "原文"},
        files={"file": ("ref.wav", b"not audio" * 1000, "audio/wav")},
    )
    assert garbage.status_code == 400


def test_switching_engines_keeps_old_bindings_failing_loudly(client, wav_bytes):
    """A cast binding made under a cloud provider keeps its cloud voice id
    after switching to the local engine. Synthesis must fail with a clear
    error — never silently read the character with the narrator voice."""
    # Bind a character under MiniMax, with the configured voice whitelisting it.
    # (A public IP literal keeps validate_url happy in sandboxes whose DNS
    # resolves every hostname to a private address.)
    assert client.put(
        "/api/settings/tts",
        json={"provider": "minimax", "base_url": "https://1.1.1.1/v1", "model": "speech-2.6-hd", "voice": "male-qn-qingse"},
    ).status_code == 200
    b = import_book(client, "第一章 台球\n占位。\n")
    cid = b["chapters"][0]["id"]
    # The cast whitelist reads the synced voice catalogue (test/refresh fills it).
    client.app.state.store.set("voices", [{"id": "male-qn-qingse", "name": "m", "description": ""}])
    assert client.put(f"/api/books/{b['id']}/cast", json={"speaker": "他", "voice": "male-qn-qingse"}).status_code == 200
    # Label the quoted line as the character so generation resolves its voice
    # through the cast table.
    c = client.get("/api/chapters/" + cid).json()
    segs = [
        {"text": "“站住。”他说。", "voice": "male-qn-qingse", "emotion": "neutral", "speed": 1, "pause": 250, "speaker": "他"},
        {"text": "他拦住了她。", "voice": "", "emotion": "neutral", "speed": 1, "pause": 250, "speaker": "旁白"},
    ]
    assert client.put(
        f"/api/chapters/{cid}", json={"revision": c["revision"], "title": c["title"], "segments": segs}
    ).status_code == 200
    # Switch to the local engine and generate: the stale binding cannot synthesize.
    assert client.put("/api/settings/tts", json={"provider": "local"}).status_code == 200
    ident = client.post(f"/api/books/{b['id']}/generate", json={"chapter_ids": [cid]}).json()["ids"][0]
    store = client.app.state.store
    row = store.one("SELECT * FROM jobs WHERE id=?", (ident,))
    client.app.state.worker.update(ident, status="running")
    # worker.run re-raises; the worker loop is what records the failure.
    with pytest.raises(ValueError) as excinfo:
        client.app.state.worker.run(row)
    assert "未知音色" in str(excinfo.value)
    # The narration (no cast binding) still synthesizes fine on the local engine.
    monkey_calls = []

    def fake(store_, voice, text, speed=1.0):
        monkey_calls.append(voice)
        return wav_bytes

    original = local_tts.synthesize
    local_tts.synthesize = fake
    try:
        b2 = import_book(client, "第二章 灯塔\n灯亮了。\n")
        cid2 = b2["chapters"][0]["id"]
        ident2 = client.post(f"/api/books/{b2['id']}/generate", json={"chapter_ids": [cid2]}).json()["ids"][0]
        row2 = store.one("SELECT * FROM jobs WHERE id=?", (ident2,))
        client.app.state.worker.update(ident2, status="running")
        client.app.state.worker.run(row2)
    finally:
        local_tts.synthesize = original
    assert monkey_calls == ["k:3"]


def test_cloud_connection_survives_local_roundtrip(client):
    """Switching to the local engine snapshots the cloud connection so
    switching back restores it without retyping (api_key never echoes)."""
    assert (
        client.put(
            "/api/settings/tts",
            json={"provider": "minimax", "base_url": "https://1.1.1.1/v1", "model": "speech-2.6-hd", "voice": "male-qn-qingse"},
        ).status_code
        == 200
    )
    data = client.put(
        "/api/settings/tts",
        json={"provider": "local", "base_url": "https://1.1.1.1/v1", "model": "speech-2.6-hd", "voice": "male-qn-qingse"},
    ).json()
    assert data["base_url"] == "" and data["model"] == "" and data["voice"] == "k:3"
    cloud = client.get("/api/settings").json()["tts_cloud"]
    assert cloud["base_url"] == "https://1.1.1.1/v1"
    assert cloud["model"] == "speech-2.6-hd" and cloud["voice"] == "male-qn-qingse"
    assert cloud["provider"] == "minimax" and "api_key" not in cloud
    # Repeated local saves (the form carries no cloud values then) must not
    # blank the snapshot.
    assert client.put("/api/settings/tts", json={"provider": "local", "voice": "k:5"}).status_code == 200
    again = client.get("/api/settings").json()["tts_cloud"]
    assert again["base_url"] == "https://1.1.1.1/v1" and again["voice"] == "male-qn-qingse"
    # The active config keeps a valid submitted local voice; only invalid
    # ones (like the minimax id above) get normalized to k:3.
    assert client.get("/api/settings").json()["tts"]["voice"] == "k:5"


def test_reset_voices_clears_every_reference(client, monkeypatch, wav_bytes):
    """The one-click reset drops narrator voice, cast rows and per-segment
    voices; revisions bump, stale markers fill, and generation works again
    with the default local voice."""
    # Bind everything under MiniMax first, then switch to the local engine.
    assert (
        client.put(
            "/api/settings/tts",
            json={"provider": "minimax", "base_url": "https://1.1.1.1/v1", "model": "speech-2.6-hd", "voice": "male-qn-qingse"},
        ).status_code
        == 200
    )
    b = import_book(client, "第一章 台球\n占位。\n")
    cid = b["chapters"][0]["id"]
    client.app.state.store.set("voices", [{"id": "male-qn-qingse", "name": "m", "description": ""}])
    assert client.put(f"/api/books/{b['id']}/cast", json={"speaker": "他", "voice": "male-qn-qingse"}).status_code == 200
    c = client.get("/api/chapters/" + cid).json()
    segs = [
        {"text": "“站住。”他说。", "voice": "male-qn-qingse", "emotion": "neutral", "speed": 1, "pause": 250, "speaker": "他"},
        {"text": "他拦住了她。", "voice": "", "emotion": "neutral", "speed": 1, "pause": 250, "speaker": "旁白"},
    ]
    assert client.put(
        f"/api/chapters/{cid}", json={"revision": c["revision"], "title": c["title"], "segments": segs}
    ).status_code == 200
    assert client.put(f"/api/books/{b['id']}", json={"voice": "male-qn-qingse"}).status_code == 200
    assert choose_local(client)["voice"] == "k:3"
    pre = client.get("/api/chapters/" + cid).json()["revision"]
    assert client.post(f"/api/books/{b['id']}/reset-voices").status_code == 200
    after_book = client.get("/api/books/" + b["id"]).json()
    assert after_book["voice"] == ""
    after_cast = client.get(f"/api/books/{b['id']}/cast").json()
    assert after_cast["narrator_voice"] == "" and all(not m["voice"] for m in after_cast["cast"])
    chapter = client.get("/api/chapters/" + cid).json()
    assert all(not s["voice"] for s in chapter["segments"])
    assert chapter["revision"] == pre + 1
    # Generation works again with the default local voice (k:3 normalized).
    calls = []

    def fake(store_, voice, text, speed=1.0):
        calls.append(voice)
        return wav_bytes

    monkeypatch.setattr(local_tts, "synthesize", fake)
    ident = client.post(f"/api/books/{b['id']}/generate", json={"chapter_ids": [cid]}).json()["ids"][0]
    row = client.app.state.store.one("SELECT * FROM jobs WHERE id=?", (ident,))
    client.app.state.worker.update(ident, status="running")
    client.app.state.worker.run(row)
    assert calls and all(v == "k:3" for v in calls)


def test_local_regen_segment_works(client, monkeypatch, wav_bytes):
    """Partial regen must run on the local engine too (it has no base_url)."""
    choose_local(client)
    b = import_book(client, "第一章 台球\n第一段。\n第二段。\n第三段。")
    cid = b["chapters"][0]["id"]
    monkeypatch.setattr(local_tts, "synthesize", lambda store_, voice, text, speed=1.0: wav_bytes)
    ident = client.post(f"/api/books/{b['id']}/generate", json={"chapter_ids": [cid]}).json()["ids"][0]
    row = client.app.state.store.one("SELECT * FROM jobs WHERE id=?", (ident,))
    client.app.state.worker.update(ident, status="running")
    client.app.state.worker.run(row)
    assert client.get("/api/chapters/" + cid).json()["active_audio"]
    result = client.post(f"/api/chapters/{cid}/regen-segment", json={"index": 1})
    assert result.status_code == 200, result.text
    regen_id = result.json()["id"]
    row = client.app.state.store.one("SELECT * FROM jobs WHERE id=?", (regen_id,))
    client.app.state.worker.update(regen_id, status="running")
    client.app.state.worker.run(row)  # raises if regen fails — that IS the bug signal
    client.app.state.worker.update(regen_id, status="succeeded", stage="已完成")
    assert client.get("/api/jobs/" + regen_id).json()["status"] == "succeeded"


def test_download_error_state_is_recoverable(client, monkeypatch):
    """A failed download must surface as its own state (not stuck
    'downloading') and leave delete + re-download available."""
    store = client.app.state.store
    monkeypatch.setitem(
        local_tts._downloads,
        "kokoro-int8",
        {"received": 100, "total": 10, "error": "ReadTimeout: boom"},
    )
    state = local_tts.status(store, "kokoro-int8")
    assert state["state"] == "error" and "ReadTimeout" in state["error"]
    # Deleting a dead download is allowed…
    assert client.delete("/api/local/models/kokoro-int8").status_code == 200
    # …and so is starting over.
    monkeypatch.setattr(local_tts, "_run_download", lambda store_, mid: None)
    result = client.post("/api/local/models/kokoro-int8/download")
    assert result.status_code == 200 and result.json()["state"] == "downloading"
    local_tts._downloads.pop("kokoro-int8", None)


def test_clone_rejects_oversized_metadata_and_missing_file(client):
    choose_local(client)
    long_name = client.post(
        "/api/voices/clone",
        data={"name": "x" * 61, "text": "原文"},
        files={"file": ("ref.wav", wav(2.0), "audio/wav")},
    )
    assert long_name.status_code == 400
    long_text = client.post(
        "/api/voices/clone",
        data={"name": "ok", "text": "长" * 301},
        files={"file": ("ref.wav", wav(2.0), "audio/wav")},
    )
    assert long_text.status_code == 400
    no_file = client.post("/api/voices/clone", data={"name": "x", "text": "原文"})
    assert no_file.status_code == 400


def test_cloud_snapshot_carries_api_key(client):
    assert (
        client.put(
            "/api/settings/tts",
            json={"provider": "minimax", "base_url": "https://1.1.1.1/v1", "model": "m", "voice": "v", "api_key": "sk-secret"},
        ).status_code
        == 200
    )
    store = client.app.state.store
    assert store.get("tts_cloud")["api_key"] == "sk-secret"
    # An empty key means "keep the old one" — in the active config and in the
    # snapshot alike.
    client.put(
        "/api/settings/tts",
        json={"provider": "minimax", "base_url": "https://1.1.1.1/v1", "model": "m", "voice": "v"},
    )
    assert store.get("tts")["api_key"] == "sk-secret"
    assert store.get("tts_cloud")["api_key"] == "sk-secret"
