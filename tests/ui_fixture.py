"""Isolated browser test fixture. Synthetic audio is NOT a real speech model."""

import io
import json
import math
import os
import struct
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import uvicorn


class MockProvider(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.send_json({"data": [{"id": "test-model"}]})

    def send_json(self, payload):
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        if self.path.endswith("get_voice"):
            return self.send_json(
                {
                    "system_voice": [
                        {
                            "voice_id": "fixture-calm",
                            "voice_name": "测试音色 · 远山",
                            "description": ["集成测试音频，不是真实朗读"],
                        },
                        {
                            "voice_id": "fixture-soft",
                            "voice_name": "测试音色 · 清禾",
                            "description": ["用于验证切换音色的接口"],
                        },
                    ],
                    "base_resp": {"status_code": 0},
                }
            )
        if self.path.endswith("images/generations"):
            import base64

            png = b"\x89PNG\r\n\x1a\n" + b"fakeaicover" * 16
            return self.send_json(
                {"data": [{"b64_json": base64.b64encode(png).decode()}]}
            )
        if self.path.endswith("chat/completions"):
            content = body["messages"][-1]["content"]
            system_prompt = body["messages"][0]["content"] if body.get("messages") else ""
            if "图书资料助理" in system_prompt:
                # Book analysis: return metadata shaped for the studio.
                title = "这本书"
                try:
                    title = json.loads(content).get("title") or title
                except ValueError:
                    pass
                return self.send_json(
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": json.dumps(
                                        {
                                            "author": "测试作者",
                                            "intro": f"《{title}》的集成测试简介，用于验证 AI 分析与封面生成流程。",
                                            "tags": ["悬疑", "海边"],
                                            "palette": ["#22302b", "#101820", "#8fd3b6"],
                                            "mood": "海边悬疑",
                                        },
                                        ensure_ascii=False,
                                    )
                                }
                            }
                        ]
                    }
                )
            try:
                payload = json.loads(content)
            except ValueError:
                payload = None
            if isinstance(payload, dict) and "units" in payload:
                # Restructure: the studio sends fine dialogue/narration units
                # and expects index-only groups with a speaker each.
                groups = []
                for u in payload["units"]:
                    speaker = "沈雾" if u["kind"] == "dialogue" else "旁白"
                    if groups and groups[-1]["speaker"] == speaker:
                        groups[-1]["units"].append(u["index"])
                    else:
                        groups.append({"units": [u["index"]], "speaker": speaker})
                return self.send_json(
                    {"choices": [{"message": {"content": json.dumps({"groups": groups}, ensure_ascii=False)}}]}
                )
            if payload is None:
                payload = {}
            if "candidates" in payload:
                values = {
                    "boundaries": [
                        r["line"]
                        for r in payload["candidates"]
                        if r["text"].startswith(("第一章", "第二章", "第三章"))
                    ]
                }
            else:
                values = {
                    "segments": [
                        {
                            "index": s["index"],
                            "speaker": "沈雾" if "“" in s["text"] else "旁白",
                            "voice": "fixture-soft" if "“" in s["text"] else "fixture-calm",
                            "voice_hint": "温柔女声" if "“" in s["text"] else "沉稳叙述",
                            "emotion": "calm",
                            "speed": 0.9 if "“" in s["text"] else 1.05,
                            "pause": 350,
                            "reason": "集成测试建议，验证角色和音色分析",
                        }
                        for s in payload["segments"]
                    ]
                }
            return self.send_json({"choices": [{"message": {"content": json.dumps(values)}}]})
        output = io.BytesIO()
        with wave.open(output, "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(24000)
            samples = [
                int(6500 * math.sin(i * 0.06) * (0.55 + 0.45 * math.sin(i / 2700))) for i in range(48000)
            ]
            f.writeframes(struct.pack("<" + "h" * len(samples), *samples))
        self.send_json({"data": {"audio": output.getvalue().hex()}, "base_resp": {"status_code": 0}})


if __name__ == "__main__":
    root = Path("output/runtime") / f"browser-data-{int(time.time())}"
    os.environ["DATA_DIR"] = str(root.resolve())
    from app.main import app

    server = ThreadingHTTPServer(("127.0.0.1", 18781), MockProvider)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=8781, access_log=False)
