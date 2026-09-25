import io
import wave

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path / "studio", start_worker=False)
    with TestClient(app) as client:
        client.headers["X-Soundleaf"] = "1"
        # A fresh data directory always carries the seeded default account.
        assert client.post("/api/login", json={"name": "admin", "password": "admin"}).status_code == 200
        yield client


@pytest.fixture
def wav_bytes():
    output = io.BytesIO()
    with wave.open(output, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(24000)
        f.writeframes(b"\x00\x10" * 2400)
    return output.getvalue()


def import_book(client, text="第一章 灯塔\n灯亮了。\n第二章 来信\n他打开信封。"):
    result = client.post("/api/imports", files={"file": ("小说.txt", text.encode(), "text/plain")})
    assert result.status_code == 200, result.text
    data = result.json()
    result = client.post(
        "/api/imports/confirm",
        json={"id": data["id"], "title": "雾海来信", "author": "测试作者", "chapters": data["chapters"]},
    )
    assert result.status_code == 200, result.text
    return client.get("/api/books/" + result.json()["id"]).json()


def run_job(client, ident):
    store = client.app.state.store
    worker = client.app.state.worker
    row = store.one("SELECT * FROM jobs WHERE id=?", (ident,))
    worker.update(ident, status="running")
    worker.run(row)
    worker.update(ident, status="succeeded", stage="已完成")
    return client.get("/api/jobs/" + ident).json()
