"""Regression tests for the second hardening round: stale-segment tracking,
cast_version voice staleness, concurrent enqueue atomicity, dict cascade."""

import itertools
import json
import threading

from app import providers
from tests.conftest import import_book, run_job


def make_wav(frames=2400):
    import io
    import wave

    output = io.BytesIO()
    with wave.open(output, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(24000)
        f.writeframes(b"\x00\x10" * frames)
    return output.getvalue()


def test_concurrent_analyze_chapters_enqueue_creates_one_job(client, monkeypatch):
    """Two simultaneous clicks on AI 章节识别 must produce ONE paid job."""
    b = import_book(client)
    client.put(
        "/api/settings/ai",
        json={
            "provider": "minimax",
            "base_url": "https://8.8.8.8/v1",
            "model": "m",
            "allow_local": False,
        },
    )
    results = []
    barrier = threading.Barrier(2)

    def hit():
        barrier.wait()
        results.append(
            client.post(f"/api/books/{b['id']}/analyze-chapters").json()
        )

    threads = [threading.Thread(target=hit) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    ids = [r.get("id") for r in results]
    assert len(ids) == 2 and ids[0] == ids[1], ids
    store = client.app.state.store
    count = store.one(
        "SELECT count(*) c FROM jobs WHERE book_id=? AND kind='analyze_chapters'",
        (b["id"],),
    )["c"]
    assert count == 1


def test_book_delete_cascades_dict_entries(client):
    b = import_book(client)
    client.put(f"/api/books/{b['id']}/dict", json={"word": "灯塔", "replacement": "信号塔"})
    store = client.app.state.store
    assert store.one("SELECT count(*) c FROM dict WHERE book_id=?", (b["id"],))["c"] == 1
    client.delete("/api/books/" + b["id"])
    assert store.one("SELECT count(*) c FROM dict WHERE book_id=?", (b["id"],))["c"] == 0


def test_retry_book_level_job_dedups_against_fresh_enqueue(client):
    b = import_book(client)
    client.put(
        "/api/settings/ai",
        json={
            "provider": "minimax",
            "base_url": "https://8.8.8.8/v1",
            "model": "m",
            "allow_local": False,
        },
    )
    store = client.app.state.store
    stale_job = store.job("analyze_chapters", {}, b["id"])
    store.execute("UPDATE jobs SET status='needs_review' WHERE id=?", (stale_job,))
    # Retrying the stale job revives it...
    assert client.post(f"/api/jobs/{stale_job}/retry").status_code == 200
    # ...and a fresh enqueue must dedup into the revived job, not double-bill.
    fresh = client.post(f"/api/books/{b['id']}/analyze-chapters").json()
    assert fresh["id"] == stale_job
    # And a second retry while queued is refused (already active again).
    assert client.post(f"/api/jobs/{stale_job}/retry").status_code == 400


def test_edit_two_segments_regen_one_leaves_rest_stale(client, monkeypatch, wav_bytes):
    """Regenerating ONE of two edited segments must keep the chapter marked
    stale (the other segment's audio still holds old text) — until the second
    regen completes."""
    monkeypatch.setattr(providers, "synthesize", lambda config, s: wav_bytes)
    b = import_book(client, "第一章 台球\n第一段的内容。\n第二段的内容。\n第三段的内容。")
    cid = b["chapters"][0]["id"]
    run_job(
        client,
        client.post(f"/api/books/{b['id']}/generate", json={"chapter_ids": [cid]}).json()["ids"][0],
    )
    # Edit segments 0 and 1, save.
    c = client.get("/api/chapters/" + cid).json()
    segs = c["segments"]
    segs[0]["text"] = "第一段改写。"
    segs[1]["text"] = "第二段改写。"
    assert (
        client.put(
            "/api/chapters/" + cid,
            json={"revision": c["revision"], "title": c["title"], "segments": segs},
        ).status_code
        == 200
    )
    # Regen segment 0 only.
    store = client.app.state.store
    job0 = client.post(f"/api/chapters/{cid}/regen-segment", json={"index": 0}).json()["id"]
    run_job(client, job0)
    chapter = client.get("/api/chapters/" + cid).json()
    stale = json.loads(store.one("SELECT stale_segments FROM chapters WHERE id=?", (cid,))["stale_segments"])
    assert stale == [1], "segment 1 must remain stale"
    assert chapter["versions"][0]["revision"] == chapter["revision"]

    # Regen segment 1 too — now the chapter audio is fully current.
    job1 = client.post(f"/api/chapters/{cid}/regen-segment", json={"index": 1}).json()["id"]
    run_job(client, job1)
    chapter = client.get("/api/chapters/" + cid).json()
    assert store.one("SELECT stale_segments FROM chapters WHERE id=?", (cid,))["stale_segments"] is None
    assert chapter["versions"][0]["revision"] == chapter["revision"]


def test_regen_applies_changed_pause_without_residual(client, monkeypatch, wav_bytes):
    """A regenerated segment replaces its WHOLE slot (speech + old pause) and
    the new pause lands as real silence: timeline end matches file duration,
    no residual/overlap even for the LAST segment with a changed pause."""
    monkeypatch.setattr(providers, "synthesize", lambda config, s: wav_bytes)
    b = import_book(client, "第一章 台球\n第一段的内容。\n第二段的内容。")
    cid = b["chapters"][0]["id"]
    run_job(
        client,
        client.post(f"/api/books/{b['id']}/generate", json={"chapter_ids": [cid]}).json()["ids"][0],
    )
    # Pause of segment 1 (last) changed 250ms -> 1000ms; longer speech too.
    c = client.get("/api/chapters/" + cid).json()
    segs = c["segments"]
    segs[1]["pause"] = 1000
    segs[1]["text"] = "改写后的最后一句话，比原来长了不少。"
    client.put(
        "/api/chapters/" + cid,
        json={"revision": c["revision"], "title": c["title"], "segments": segs},
    )
    job = client.post(f"/api/chapters/{cid}/regen-segment", json={"index": 1}).json()["id"]
    run_job(client, job)
    chapter = client.get("/api/chapters/" + cid).json()
    meta = client.get(f"/api/audio/{chapter['active_audio']}/metadata").json()
    timeline = meta["timeline"]
    # No overlap: each entry starts at or after the previous entry's end.
    for prev, cur in itertools.pairwise(timeline):
        assert cur["start"] >= prev["end"] - 0.001
    # No residual: the timeline's final end equals the file duration.
    assert abs(timeline[-1]["end"] - meta["duration"]) < 0.02


def test_cast_change_marks_voice_stale_but_keeps_audio_playable(client, monkeypatch):
    """A cast rebinding must surface as 音色待更新 (voice_stale) WITHOUT
    touching chapter revisions — so a generation that is mid-flight still
    promotes its output, and export warns instead of silently passing."""
    b = import_book(client, "第一章 雾中的信\n“站住。”沈雾说。")
    # 先生成一版音频（旧音色），之后换绑定才能体现"音色待更新"。
    import io as _io
    import wave as _wave

    out = _io.BytesIO()
    with _wave.open(out, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(24000)
        f.writeframes(b"\x00\x10" * 4800)
    wav_bytes = out.getvalue()
    monkeypatch.setattr(providers, "synthesize", lambda config, s: wav_bytes)
    run_job(
        client,
        client.post(
            f"/api/books/{b['id']}/generate",
            json={"chapter_ids": [b["chapters"][0]["id"]]},
        ).json()["ids"][0],
    )
    from tests.conftest import client as _c  # noqa: F401

    store = client.app.state.store
    store.set("voices", [{"id": "fixture-soft", "name": "清禾"}, {"id": "fixture-calm", "name": "远山"}])
    # Explicit binding of the speaker found in the chapter segments.
    resp = client.put(f"/api/books/{b['id']}/cast", json={"speaker": "沈雾", "voice": "fixture-soft"})
    assert resp.status_code == 200
    book = client.get("/api/books/" + b["id"]).json()
    chapter = book["chapters"][0]
    assert chapter["voice_stale"] == 1
    # Script revision untouched: no false "待更新" from the script check.
    assert chapter["revision"] == chapter["audio_revision"]
    # Rebinding back does not stack revisions either.
    client.put(f"/api/books/{b['id']}/cast", json={"speaker": "沈雾", "voice": "fixture-calm"})
    book = client.get("/api/books/" + b["id"]).json()
    assert book["chapters"][0]["revision"] == chapter["revision"]
    assert book["chapters"][0]["voice_stale"] == 1
