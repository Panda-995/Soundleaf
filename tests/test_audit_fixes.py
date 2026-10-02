import threading
from unittest.mock import patch

import pytest

from app import providers
from tests.conftest import import_book, run_job


def generate(client, book):
    cid = book["chapters"][0]["id"]
    job = client.post(f"/api/books/{book['id']}/generate", json={"chapter_ids": [cid]}).json()
    run_job(client, job["ids"][0])


def regen(client, cid, index):
    job = client.post(f"/api/chapters/{cid}/regen-segment", json={"index": index}).json()
    run_job(client, job["id"])


def export_status(client, book):
    return client.post(
        f"/api/books/{book['id']}/exports",
        json={"chapter_ids": [book["chapters"][0]["id"]], "format": "wav", "allow_stale": False},
    ).status_code


def test_stable_chinese_dictionary_clears_only_completed_segments(client, monkeypatch, wav_bytes):
    monkeypatch.setattr(providers, "synthesize", lambda *a: wav_bytes)
    book = import_book(client, "第一章 词典\n灯塔第一句。\n灯塔第二句。")
    cid = book["chapters"][0]["id"]
    generate(client, book)
    client.put(f"/api/books/{book['id']}/dict", json={"word": "灯塔", "replacement": "信号塔"})
    regen(client, cid, 0)
    assert client.get(f"/api/books/{book['id']}").json()["chapters"][0]["stale_count"] == 1
    assert export_status(client, book) == 409
    regen(client, cid, 1)
    assert client.get(f"/api/books/{book['id']}").json()["chapters"][0]["stale_count"] == 0
    assert export_status(client, book) == 200


def test_mid_regen_dictionary_change_requires_final_pronunciation(client, monkeypatch, wav_bytes):
    monkeypatch.setattr(providers, "synthesize", lambda *a: wav_bytes)
    book = import_book(client, "第一章 词典\n灯塔第一句。")
    cid = book["chapters"][0]["id"]
    generate(client, book)
    client.put(f"/api/books/{book['id']}/dict", json={"word": "灯塔", "replacement": "信号塔"})
    spoken = []

    def change_dictionary(*args):
        spoken.append(args[1]["text"])
        client.put(f"/api/books/{book['id']}/dict", json={"word": "灯塔", "replacement": "照明塔"})
        return wav_bytes

    monkeypatch.setattr(providers, "synthesize", change_dictionary)
    regen(client, cid, 0)
    assert "信号塔" in spoken[0]
    assert export_status(client, book) == 409
    monkeypatch.setattr(providers, "synthesize", lambda *a: spoken.append(a[1]["text"]) or wav_bytes)
    regen(client, cid, 0)
    assert "照明塔" in spoken[-1]
    assert export_status(client, book) == 200


def test_mid_generation_cast_change_keeps_each_old_segment_stale(client, monkeypatch, wav_bytes):
    store = client.app.state.store
    store.set("voices", [{"id": "old", "name": "旧"}, {"id": "new", "name": "新"}])
    book = import_book(client, "第一章 角色\n“第一句台词。”\n“第二句台词。”")
    cid = book["chapters"][0]["id"]
    chapter = client.get(f"/api/chapters/{cid}").json()
    for segment in chapter["segments"]:
        segment.update(speaker="小明", voice="old")
    client.put(f"/api/chapters/{cid}", json={k: chapter[k] for k in ("revision", "title", "segments")})
    spoken = []

    def change_cast(*args):
        spoken.append(args[1]["voice"])
        if len(spoken) == 1:
            client.put(f"/api/books/{book['id']}/cast", json={"speaker": "小明", "voice": "new"})
        return wav_bytes

    monkeypatch.setattr(providers, "synthesize", change_cast)
    generate(client, book)
    assert spoken == ["old", "old"]
    monkeypatch.setattr(providers, "synthesize", lambda *a: spoken.append(a[1]["voice"]) or wav_bytes)
    regen(client, cid, 0)
    assert spoken[-1] == "new"
    assert export_status(client, book) == 409
    regen(client, cid, 1)
    assert export_status(client, book) == 200


@pytest.mark.parametrize(
    "kind,stage",
    [
        ("analyze", "分析朗读节奏"),
        ("restructure", "按语义归并段落"),
        ("restructure", "AI 正在按语义归并段落"),
        ("analyze_chapters", "识别章节结构"),
        ("analyze_chapters", "识别原文章节标题"),
    ],
)
def test_restart_does_not_replay_legacy_ai_requests(client, kind, stage):
    store = client.app.state.store
    ident = store.job(kind, {})
    store.execute("UPDATE jobs SET status='running',stage=? WHERE id=?", (stage, ident))
    with patch.object(client.app.state.worker.thread, "start"):
        client.app.state.worker.start()
    assert store.one("SELECT status FROM jobs WHERE id=?", (ident,))["status"] == "needs_review"


@pytest.mark.parametrize(
    "endpoint,provider_call",
    [
        ("/api/chapters/{cid}/analyze", "analyze"),
        ("/api/chapters/{cid}/restructure", "restructure_chapter"),
        ("/api/books/{bid}/analyze-chapters", "analyze_chapters"),
        ("/api/books/{bid}/analyze-book", "analyze_book"),
        ("/api/books/{bid}/generate-cover", "generate_cover_image"),
        ("/api/preview", "synthesize"),
    ],
)
def test_paid_request_recovery_uses_persisted_state_not_display_text(client, monkeypatch, endpoint, provider_call):
    store = client.app.state.store
    store.set("ai", {"base_url": "https://example.com/v1", "model": "test", "image_model": "test", "api_key": ""})
    book = import_book(client)
    cid = book["chapters"][0]["id"]
    response = client.post(endpoint.format(cid=cid, bid=book["id"]), json={"text": "验证请求恢复"})
    assert response.status_code == 200, response.text
    ident = response.json()["id"]

    def interrupt(*args, **kwargs):
        assert store.one("SELECT remote_inflight FROM jobs WHERE id=?", (ident,))["remote_inflight"] == 1
        raise providers.UncertainResult("unknown provider result")

    monkeypatch.setattr(providers, provider_call, interrupt)
    with pytest.raises(providers.UncertainResult):
        run_job(client, ident)
    store.execute("UPDATE jobs SET stage='a translated stage' WHERE id=?", (ident,))
    with patch.object(client.app.state.worker.thread, "start"):
        client.app.state.worker.start()
    assert store.one("SELECT status FROM jobs WHERE id=?", (ident,))["status"] == "needs_review"


def test_cover_cleanup_waits_for_upload_commit(client, monkeypatch):
    book = import_book(client)
    store = client.app.state.store
    worker = client.app.state.worker
    orphan = store.file("covers/orphan.png")
    orphan.write_bytes(b"orphan")
    execute = store.execute
    started = threading.Event()
    done = threading.Event()
    threads = []

    def sweep():
        started.set()
        worker.sweep_orphans()
        done.set()

    def interleave(sql, args=()):
        if sql.startswith("UPDATE books SET cover=?"):
            thread = threading.Thread(target=sweep)
            threads.append(thread)
            thread.start()
            assert started.wait(2)
            done.wait(0.5)
        return execute(sql, args)

    monkeypatch.setattr(store, "execute", interleave)
    response = client.post(
        f"/api/books/{book['id']}/cover",
        files={"file": ("test.png", b"\x89PNG\r\n\x1a\ntest", "image/png")},
    )
    for thread in threads:
        thread.join(5)
        assert not thread.is_alive()
    assert response.status_code == 200
    assert store.file(store.one("SELECT cover FROM books WHERE id=?", (book["id"],))["cover"]).exists()
    assert client.get(f"/api/books/{book['id']}/cover").status_code == 200
    assert not orphan.exists()
