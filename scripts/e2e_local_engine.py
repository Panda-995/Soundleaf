"""Full-stack E2E with the real local engine: HTTP API → worker → sherpa-onnx
inference → FFmpeg assembly → segment regen → MP3 ZIP export.

Run against a throwaway instance whose DATA_DIR/local-models is a REAL COPY
of output/local-smoke/local-models — a junction would be rejected by
store.file()'s traversal guard (resolve() lands outside DATA_DIR), which is
the guard working as designed. Requires the kokoro model downloaded once."""
import http.cookiejar
import io
import json
import time
import urllib.request
import uuid
import zipfile

BASE = "http://127.0.0.1:8783"
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def api(path, method="GET", body=None, raw=None, content_type=None):
    headers = {"X-Soundleaf": "1"}
    data = None
    if raw is not None:
        data = raw
        headers["Content-Type"] = content_type
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    with opener.open(req) as response:
        payload = response.read()
    return json.loads(payload) if payload[:1] in (b"{", b"[") else payload


def upload(path, filename, content):
    boundary = uuid.uuid4().hex
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
        f"Content-Type: text/plain\r\n\r\n".encode()
        + content
        + f"\r\n--{boundary}--\r\n".encode()
    )
    return api(path, "POST", raw=body, content_type=f"multipart/form-data; boundary={boundary}")


def wait_job(ident, timeout=420):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = api("/api/jobs/" + ident)
        if job["status"] not in ("queued", "running"):
            return job
        time.sleep(3)
    raise SystemExit(f"job {ident} timed out")


print("== login ==")
api("/api/login", "POST", {"name": "admin", "password": "admin"})
api("/api/account/password", "POST", {"current": "admin", "password": "e2e-test-password"})

print("== switch to local engine ==")
tts = api("/api/settings/tts", "PUT", {"provider": "local", "voice": "k:3"})
assert tts["provider"] == "local" and tts["voice"] == "k:3", tts

print("== import ==")
novel = "第一章 灯塔\n暮色落进海面的时候，他收到了一封信。\n“你还是来了。”她站在门边说。\n第二章 归途\n他把信收好，转身走进夜色。\n"
imp = upload("/api/imports", "novel.txt", novel.encode())
confirmed = api("/api/imports/confirm", "POST", {"id": imp["id"], "title": "雾海来信", "chapters": imp["chapters"]})
book_id = confirmed["id"]
book = api("/api/books/" + book_id)
cid = book["chapters"][0]["id"]
print(f"book={book_id} ch1={cid} chapters={len(book['chapters'])}")

print("== generate with real local synthesis ==")
job = wait_job(api("/api/books/" + book_id + "/generate", "POST", {"chapter_ids": [cid]})["ids"][0])
assert job["status"] == "succeeded", job
chapter = api("/api/chapters/" + cid)
assert chapter["active_audio"], chapter
audio_meta = api(f"/api/audio/{chapter['active_audio']}/metadata")
print(f"audio duration={audio_meta['duration']:.2f}s timeline={len(audio_meta['timeline'])} segs={len(chapter['segments'])}")
assert audio_meta["duration"] > 1

print("== regen segment 0 on the local engine ==")
regen = api(f"/api/chapters/{cid}/regen-segment", "POST", {"index": 0})
rjob = wait_job(regen["id"], timeout=240)
assert rjob["status"] == "succeeded", rjob
print("regen ok")

print("== export mp3 zip ==")
export = api(f"/api/books/{book_id}/exports", "POST", {"chapter_ids": [cid], "format": "mp3"})
assert wait_job(export["id"], timeout=240)["status"] == "succeeded"
package = api("/api/exports")[0]
blob = api(f"/api/exports/{package['id']}/download")
archive = zipfile.ZipFile(io.BytesIO(blob))
names = archive.namelist()
print("zip entries:", names)
assert any(n.endswith(".mp3") for n in names), names
print("E2E OK")
