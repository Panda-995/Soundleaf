"""Feature tests: pronunciation dictionary, M4B export and book AI analysis."""

import io
import json
import wave
import zipfile

from app import providers
from app.cover import render_cover_svg
from app.worker import apply_pronunciation, book_pronunciation
from tests.conftest import import_book, run_job


def make_wav(frames=2400):
    output = io.BytesIO()
    with wave.open(output, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(24000)
        f.writeframes(b"\x00\x10" * frames)
    return output.getvalue()


def test_apply_pronunciation_longest_first():
    entries = [("重庆", "chóngqìng"), ("重", "zhòng")]  # longest-first order
    assert apply_pronunciation("重庆的重量", entries) == "chóngqìng的zhòng量"
    assert apply_pronunciation("没有命中", entries) == "没有命中"


def test_book_pronunciation_sorted_longest_first(client):
    from tests.conftest import import_book

    b = import_book(client)
    store = client.app.state.store
    for word in ("塔", "灯塔来客", "灯塔"):
        store.execute(
            "INSERT OR REPLACE INTO dict VALUES (?,?,?,?)", (b["id"], word, word + "X", 0)
        )
    names = [w for w, _ in book_pronunciation(store, b["id"])]
    assert names == ["灯塔来客", "灯塔", "塔"]
    assert book_pronunciation(store, "") == []
    assert book_pronunciation(store, "no-such-book") == []


def test_dict_roundtrip_and_validation(client):
    from tests.conftest import import_book

    b = import_book(client)
    url = f"/api/books/{b['id']}/dict"
    assert client.get(url).json() == []
    ok = client.put(url, json={"word": "灯塔", "replacement": "信号塔"})
    assert ok.status_code == 200 and ok.json()["affected"] == 0  # no audio yet
    entries = client.get(url).json()
    assert entries == [{"word": "灯塔", "replacement": "信号塔"}]
    # Same word again replaces the entry instead of duplicating it.
    client.put(url, json={"word": "灯塔", "replacement": "灯楼"})
    assert client.get(url).json() == [{"word": "灯塔", "replacement": "灯楼"}]
    # An empty replacement removes the entry.
    assert client.put(url, json={"word": "灯塔", "replacement": ""}).status_code == 200
    assert client.get(url).json() == []
    # Validation.
    assert client.put(url, json={"word": "", "replacement": "x"}).status_code == 400
    assert client.put(url, json={"word": "w" * 61, "replacement": "x"}).status_code == 400
    same = client.put(url, json={"word": "灯", "replacement": "灯"})
    assert same.status_code == 400


def test_dict_applies_to_generation_and_marks_affected_chapters(client, monkeypatch, wav_bytes):
    monkeypatch.setattr(providers, "synthesize", lambda config, s: wav_bytes)
    b = import_book(client, text="第一章 灯塔\n海边的灯塔亮了。\n第二章 来信\n他打开信封。")
    ids = [c["id"] for c in b["chapters"]]
    # Generate both chapters first, so the dictionary has audio to mark stale.
    job_ids = client.post(f"/api/books/{b['id']}/generate", json={"chapter_ids": ids}).json()["ids"]
    for ident in job_ids:
        run_job(client, ident)
    result = client.put(f"/api/books/{b['id']}/dict", json={"word": "灯塔", "replacement": "信号塔"})
    assert result.status_code == 200
    detail = client.get("/api/books/" + b["id"]).json()
    chapters = {c["id"]: c for c in detail["chapters"]}
    # 段级标记：只有包含该词的片段进入 stale_segments，章节 revision 不动。
    assert chapters[ids[0]]["stale_count"] == 1 and chapters[ids[1]]["stale_count"] == 0
    assert chapters[ids[0]]["revision"] == chapters[ids[1]]["revision"] == 1

    calls = []
    monkeypatch.setattr(providers, "synthesize", lambda config, s: calls.append(s["text"]) or wav_bytes)
    regen_ids = client.post(
        f"/api/books/{b['id']}/generate", json={"chapter_ids": ids}
    ).json()["ids"]
    for ident in regen_ids:
        run_job(client, ident)
    spoken = "".join(calls)
    assert "信号塔" in spoken and "灯塔" not in spoken


def test_preview_applies_dictionary(client):
    from tests.conftest import import_book

    b = import_book(client)
    client.put(f"/api/books/{b['id']}/dict", json={"word": "灯塔", "replacement": "信号塔"})
    store = client.app.state.store
    ident = client.post(
        "/api/preview", json={"text": "灯塔的故事", "book_id": b["id"]}
    ).json()["id"]
    payload = json.loads(store.one("SELECT payload FROM jobs WHERE id=?", (ident,))["payload"])
    assert payload["segments"][0]["text"] == "信号塔的故事"
    # Without a book context the text passes through untouched.
    plain = client.post("/api/preview", json={"text": "灯塔的故事"}).json()["id"]
    payload = json.loads(store.one("SELECT payload FROM jobs WHERE id=?", (plain,))["payload"])
    assert payload["segments"][0]["text"] == "灯塔的故事"


def test_m4b_export_single_file_with_chapter_navigation(client, monkeypatch, wav_bytes):
    monkeypatch.setattr(providers, "synthesize", lambda config, s: wav_bytes)
    b = import_book(client)
    ids = [c["id"] for c in b["chapters"]]
    for ident in client.post(f"/api/books/{b['id']}/generate", json={"chapter_ids": ids}).json()["ids"]:
        run_job(client, ident)
    job_id = client.post(
        f"/api/books/{b['id']}/exports",
        json={"chapter_ids": ids, "format": "m4b", "embed": True},
    ).json()["id"]
    run_job(client, job_id)
    history = client.get("/api/exports").json()
    assert history[0]["format"] == "m4b" and history[0]["count"] == 2

    downloaded = client.get(f"/api/exports/{history[0]['id']}/download")
    assert downloaded.status_code == 200
    assert ".m4b" in downloaded.headers.get("content-disposition", "")
    body = downloaded.content
    assert len(body) > 1000 and body[4:8] == b"ftyp"  # MP4 container signature

    # The ZIP path keeps its .zip download name and manifest.
    zip_id = client.post(
        f"/api/books/{b['id']}/exports", json={"chapter_ids": ids, "format": "mp3"}
    ).json()["id"]
    run_job(client, zip_id)
    # exports rows use their own file uid, not the job id.
    entry = client.get("/api/exports").json()[0]
    assert entry["format"] == "mp3" and entry["count"] == 2
    blob = client.get(f"/api/exports/{entry['id']}/download").content
    assert blob[:2] == b"PK"
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        assert "manifest.json" in z.namelist()


def test_m4b_rejects_stale_audio_like_other_formats(client, monkeypatch, wav_bytes):
    monkeypatch.setattr(providers, "synthesize", lambda config, s: wav_bytes)
    b = import_book(client)
    cid = b["chapters"][0]["id"]
    run_job(
        client,
        client.post(f"/api/books/{b['id']}/generate", json={"chapter_ids": [cid]}).json()["ids"][0],
    )
    c = client.get("/api/chapters/" + cid).json()
    c["segments"][0]["text"] = "改过之后的正文。"
    client.put(
        "/api/chapters/" + cid,
        json={"revision": c["revision"], "title": c["title"], "segments": c["segments"]},
    )
    result = client.post(
        f"/api/books/{b['id']}/exports", json={"chapter_ids": [cid], "format": "m4b"}
    )
    assert result.status_code == 409


def test_analyze_book_and_apply_meta(client, monkeypatch):
    b = import_book(client)
    # AI 未配置时给出明确提示。
    denied = client.post(f"/api/books/{b['id']}/analyze-book")
    assert denied.status_code == 400
    client.put(
        "/api/settings/ai",
        json={
            "provider": "minimax",
            "base_url": "https://8.8.8.8/v1",
            "model": "m",
            "image_model": "test-image-model",
            "allow_local": False,
        },
    )
    seen = {}

    def fake_request(config, endpoint, body, **kwargs):
        seen["title"] = json.loads(body["messages"][1]["content"])["title"]
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "author": "推断作者",
                                "intro": "一个关于海边灯塔的故事简介。",
                                "tags": ["悬疑", "海边"],
                                "palette": ["#22302B", "#101820", "#8FD3B6"],
                                "mood": "海边悬疑",
                            },
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        }

    monkeypatch.setattr(providers, "request", fake_request)
    job_id = client.post(f"/api/books/{b['id']}/analyze-book").json()["id"]
    result = run_job(client, job_id)
    assert result["status"] == "succeeded"
    assert seen["title"] == b["title"]
    meta = result["meta"]
    assert meta["author"] == "推断作者"
    assert meta["palette"][0] == "#22302b"  # normalized lowercase with '#'

    # 应用：写入 author/intro，并生成 SVG 封面。
    store = client.app.state.store
    store.execute("UPDATE users SET name=name")  # no-op keeps fixture style
    applied = client.post(
        f"/api/books/{b['id']}/apply-meta",
        json={
            "author": "推断作者",
            "intro": "一个关于海边灯塔的故事简介。",
            "palette": meta["palette"],
            "mood": "海边悬疑",
        },
    )
    assert applied.status_code == 200
    detail = client.get("/api/books/" + b["id"]).json()
    assert detail["author"] == "推断作者"
    assert "灯塔" in detail["intro"]
    cover_path = store.file(detail["cover"])
    assert cover_path.suffix == ".svg" and cover_path.exists()
    served = client.get(f"/api/books/{b['id']}/cover")
    assert served.status_code == 200 and b"<svg" in served.content

    # 无配色时仅应用资料，保留现有封面。
    before = detail["cover"]
    applied2 = client.post(
        f"/api/books/{b['id']}/apply-meta",
        json={"author": "作者二", "intro": "简介二"},
    )
    assert applied2.status_code == 200
    detail2 = client.get("/api/books/" + b["id"]).json()
    assert detail2["author"] == "作者二" and detail2["intro"] == "简介二"
    assert detail2["cover"] == before

    # 自定义书名：分析按传入书名进行，应用时可改名。
    seen.clear()
    job_id = client.post(
        f"/api/books/{b['id']}/analyze-book", json={"title": "自定义书名"}
    ).json()["id"]
    run_job(client, job_id)
    assert seen["title"] == "自定义书名"

    # AI 生图封面：mock 图片模型，封面按内容嗅探落盘并应用。
    png = b"\x89PNG\r\n\x1a\n" + b"fakeimagedata" * 8
    monkeypatch.setattr(providers, "generate_cover_image", lambda cfg, t, mood="", tags=None, extra="": (png, ".png"))
    cover_job = client.post(
        f"/api/books/{b['id']}/generate-cover",
        json={"title": "自定义书名", "mood": "海边悬疑", "tags": ["悬疑"]},
    ).json()["id"]
    cover_result = run_job(client, cover_job)
    assert cover_result["status"] == "succeeded"
    detail3 = client.get("/api/books/" + b["id"]).json()
    assert detail3["cover"].endswith(".png")
    served_png = client.get(f"/api/books/{b['id']}/cover")
    assert served_png.content.startswith(b"\x89PNG")


def test_render_cover_svg_escapes_and_wraps():
    svg = render_cover_svg("一个特别特别特别长的书名需要截断处理", "作者", ["#111111", "#222222"], "氛围")
    assert "<svg" in svg and "…&quot;" not in svg
    assert 'class="t"' in svg
    escaped = render_cover_svg('<b>标题</b>', "作者&名", ["#111111", "#222222"])
    assert "&lt;b&gt;" in escaped and "作者&amp;名" in escaped


def test_update_book_accepts_intro(client):
    b = import_book(client)
    url = f"/api/books/{b['id']}"
    assert client.put(url, json={"title": "改名", "intro": "一段简介"}).status_code == 200
    assert client.get(url).json()["intro"] == "一段简介"
    # 不传 intro 时保留原值。
    assert client.put(url, json={"title": "再改名"}).status_code == 200
    assert client.get(url).json()["intro"] == "一段简介"
