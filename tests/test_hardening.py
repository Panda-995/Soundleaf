"""Regression tests for the 2026-09 hardening pass: guards, validations and
cleanups that must never regress. Kept separate from test_studio.py by topic."""

import io
import wave
import zipfile

import pytest

from app import audio, importer, providers
from app.security import validate_url
from app.store import Store
from app.worker import QUOTED as WORKER_QUOTED
from tests.conftest import import_book


def make_wav(frames=24):
    output = io.BytesIO()
    with wave.open(output, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(24000)
        f.writeframes(b"\x00\x10" * frames)
    return output.getvalue()


def write_wav(path, frames=24):
    path.write_bytes(make_wav(frames))
    return path


def test_quoted_regex_corner_bracket_matches_importer():
    # 『…』 blocks must close on 』; a stray 」 inside must not break the span.
    text = "『你说「走」的时候就走』他说。"
    assert WORKER_QUOTED.search(text)
    assert providers.QUOTED.search(text)
    assert providers.QUOTED.search("『别走』")
    # Consistency with the importer's splitter for the same pattern.
    parts = importer.director_segments("『别走』他说。")
    assert "".join(p["text"] for p in parts) == "『别走』他说。"


def test_store_file_rejects_traversal(tmp_path):
    store = Store(tmp_path)
    for candidate in ("../escape", "audio/../../escape", "a/../b/../../../c"):
        with pytest.raises(ValueError):
            store.file(candidate)
    assert store.file("audio/ok.wav").is_relative_to(store.root)


def test_validate_url_rules():
    # Userinfo, query strings and fragments are rejected before any lookup.
    with pytest.raises(ValueError):
        validate_url("http://user:pass@8.8.8.8/v1", allow_local=True)
    with pytest.raises(ValueError):
        validate_url("https://8.8.8.8/v1?x=1")
    with pytest.raises(ValueError):
        validate_url("https://8.8.8.8/v1#frag")
    # Plain HTTP needs the local exception; global HTTPS literals pass.
    with pytest.raises(ValueError):
        validate_url("http://8.8.8.8/v1")
    assert validate_url("https://8.8.8.8/v1") == "https://8.8.8.8/v1"
    # Loopback and LAN addresses need the explicit local exception.
    with pytest.raises(ValueError):
        validate_url("http://127.0.0.1:8080/v1")
    assert validate_url("http://127.0.0.1:8080/v1", allow_local=True)
    with pytest.raises(ValueError):
        validate_url("https://10.1.2.3/v1")
    assert validate_url("https://10.1.2.3/v1", allow_local=True)


def test_apply_chapters_survives_legacy_payload(client):
    b = import_book(client)
    store = client.app.state.store
    job_id = store.job(
        "analyze_chapters", {"proposed": []}, b["id"]
    )
    store.execute("UPDATE jobs SET status='succeeded' WHERE id=?", (job_id,))
    result = client.post(
        f"/api/books/{b['id']}/apply-chapters", json={"job_id": job_id}
    )
    assert result.status_code == 400, "missing payload keys must be a client error, not 500"


def test_generate_rejects_oversized_chapter_before_billing(client):
    b = import_book(client, text="第一章 长章\n" + "字" * 200_100)
    result = client.post(
        f"/api/books/{b['id']}/generate", json={"chapter_ids": [c["id"] for c in b["chapters"]]}
    )
    assert result.status_code == 400
    assert "拆分" in result.json()["detail"]


def test_concatenate_and_splice_refuse_over_capacity(tmp_path, monkeypatch):
    monkeypatch.setattr(audio, "MAX_WAV_FRAMES", 100)
    first = write_wav(tmp_path / "a.wav", 80)
    second = write_wav(tmp_path / "b.wav", 80)
    with pytest.raises(ValueError, match="容量上限"):
        audio.concatenate([first, second], [0, 0], tmp_path / "out.wav")
    with pytest.raises(ValueError, match="容量"):
        audio.splice_segment(first, tmp_path / "s.wav", 0, 0.001, second)


def test_strip_think_removes_reasoning_block_completely():
    cleaned = providers._strip_think('<reasoning>想一下</reasoning>{"a":1}')
    assert cleaned == '{"a":1}'
    assert providers._strip_think("<think>only</think>ok") == "ok"
    # An unclosed block is left intact — the JSON extractor handles the tail.
    assert providers._strip_think("<think>never closed") == "<think>never closed"


def test_epub_single_oversized_resource_rejected():
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as z:
        z.writestr(
            "META-INF/container.xml",
            '<container><rootfiles><rootfile full-path="book.opf"/></rootfiles></container>',
        )
        z.writestr("book.opf", '<package><manifest><item id="a" href="a.xhtml"/></manifest>'
                                '<spine><itemref idref="a"/></spine></package>')
        z.writestr("a.xhtml", "x" * (31 * 1024 * 1024))
    with pytest.raises(ValueError, match="30MB"):
        importer.parse(data.getvalue(), "book.epub")


def test_update_book_voice_whitelist_allows_unchanged_voice(client):
    b = import_book(client)
    url = f"/api/books/{b['id']}"
    # Same voice (still empty), just a title edit: never blocked by the list.
    assert client.put(url, json={"voice": b["voice"], "title": "改名"}).status_code == 200
    # Changing to an unknown voice is rejected.
    denied = client.put(url, json={"voice": "voice-not-in-list", "title": "改名"})
    assert denied.status_code == 400
    # The configured default voice is always acceptable.
    client.put(
        "/api/settings/tts",
        json={"provider": "minimax", "base_url": "https://api.minimax.cn/v1", "model": "m", "voice": "male-qn-qingse"},
    )
    assert client.put(url, json={"voice": "male-qn-qingse", "title": "改名"}).status_code == 200


def test_retry_rejects_job_whose_chapter_is_gone(client):
    b = import_book(client)
    cid = b["chapters"][0]["id"]
    store = client.app.state.store
    job_id = store.job("generate", {}, b["id"], cid)
    store.execute("UPDATE jobs SET status='failed',error='x' WHERE id=?", (job_id,))
    store.execute("DELETE FROM chapters WHERE id=?", (cid,))
    result = client.post(f"/api/jobs/{job_id}/retry")
    assert result.status_code == 409
    assert "章节已删除" in result.json()["detail"]


def test_cover_replacement_removes_previous_file(client):
    b = import_book(client)
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    assert client.post(f"/api/books/{b['id']}/cover", files={"file": ("a.png", png, "image/png")}).status_code == 200
    store = client.app.state.store
    first_path = store.file(store.one("SELECT cover FROM books WHERE id=?", (b["id"],))["cover"])
    assert first_path.exists()
    assert client.post(f"/api/books/{b['id']}/cover", files={"file": ("b.png", png, "image/png")}).status_code == 200
    assert not first_path.exists()


def test_csp_header_on_responses(client):
    result = client.get("/api/books")
    policy = result.headers.get("Content-Security-Policy", "")
    assert "default-src 'self'" in policy
    assert "frame-ancestors 'none'" in policy
