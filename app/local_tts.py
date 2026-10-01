"""Offline local TTS engines (sherpa-onnx) and on-demand model management.

Everything runs on the machine: engines do CPU inference via sherpa-onnx and
model archives are downloaded once into DATA_DIR/local-models/. A meta.json
marker written after verification distinguishes complete downloads from
leftover partial artifacts, so a crashed download can never be loaded.

Voice ids are stable strings shared with the cast table:
  k:<sid>   built-in Kokoro speaker (v1.1-zh layout: 0-2 English female,
            3-57 Chinese female, 58-102 Chinese male)
  c:<hash>  user-registered ZipVoice clone; the hash covers the reference
            audio bytes and its transcript, so re-recording a clone always
            yields a new synthesis identity (stale cached audio is never
            reused under the old voice).
"""

import array
import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import wave
from pathlib import Path

import httpx

from app.audio import ffmpeg
from app.security import validate_url

RELEASE_PREFIX = "https://github.com/k2-fsa/sherpa-onnx/releases/download"
# Operator override for throttled routes: a URL prefix that takes the FULL
# original URL (ghproxy style, e.g. "https://ghfast.top"), so any GitHub
# release proxy or self-hosted cache works without path restructuring.
MIRROR_PREFIX = os.environ.get("SOUNDPAGE_TTS_MIRROR", "").strip().rstrip("/")

# zf_001, the v1.1-zh showcase voice — the narration default when the user
# switches to the local engine without picking one.
DEFAULT_VOICE = "k:3"

DOWNLOAD_CAP = 3 * 1024 * 1024 * 1024
MAX_CLONES = 50

MODELS = {
    "kokoro-int8": {
        "engine": "kokoro",
        "name": "Kokoro v1.1 中英 · int8",
        "description": "82M 参数多说话人模型，103 个内置音色（100 个中文），CPU 实时，推荐 NAS 使用。",
        "size": 147_031_220,
        "files": [("tts-models/kokoro-int8-multi-lang-v1_1.tar.bz2", True)],
        "verify": ("model*.onnx", "voices.bin", "tokens.txt", "espeak-ng-data"),
    },
    "kokoro": {
        "engine": "kokoro",
        "name": "Kokoro v1.1 中英 · 完整版",
        "description": "未量化的完整模型，音质略好于 int8，体积约为其三倍。",
        "size": 364_816_464,
        "files": [("tts-models/kokoro-multi-lang-v1_1.tar.bz2", True)],
        "verify": ("model*.onnx", "voices.bin", "tokens.txt", "espeak-ng-data"),
    },
    "zipvoice": {
        "engine": "zipvoice",
        "name": "ZipVoice 克隆 · int8 蒸馏",
        "description": "零样本音色克隆：上传几秒参考音频与原文，即可创建克隆音色（音色库页操作）。",
        "size": 109_162_785 + 54_157_409,
        "files": [
            ("tts-models/sherpa-onnx-zipvoice-distill-int8-zh-en-emilia.tar.bz2", True),
            ("vocoder-models/vocos_24khz.onnx", False),
        ],
        "verify": ("encoder*.onnx", "decoder*.onnx", "tokens.txt", "espeak-ng-data", "vocos*.onnx"),
    },
}

# Kokoro v1.1-zh ships names per speaker row, but the archive exposes only
# numeric sids; labels stay honest (gender group + index) until auditioned.
_KOKORO_GROUPS = ((0, 3, "英文女声"), (3, 58, "中文女声"), (58, 103, "中文男声"))

_lock = threading.Lock()
_downloads = {}  # model_id -> {"received","total","error","abort"}
_engines = {}  # (engine, model_id) -> (OfflineTts, model directory)


@contextlib.contextmanager
def _model_cwd(directory):
    """Run engine construction / synthesis with the cwd on the model
    directory. The bundled espeak-ng C library resolves its data dir at
    synthesis time and rejects absolute paths on Windows (it silently falls
    back to /usr/share/espeak-ng-data and aborts), so engines are always
    driven with model-relative paths. Everything else in the app touches
    files through absolute paths (store.file), so the transient chdir is
    invisible to it; local synthesis is single-threaded (the one worker)."""
    previous = os.getcwd()
    os.chdir(directory)
    try:
        yield
    finally:
        os.chdir(previous)


def _sherpa():
    try:
        import sherpa_onnx  # heavy import kept lazy

        return sherpa_onnx
    except ImportError as exc:
        raise ValueError("本地引擎依赖未安装：官方 Docker 镜像已内置，自建环境请安装 sherpa-onnx") from exc


def models_root(store):
    root = store.file("local-models")
    root.mkdir(exist_ok=True)
    return root


def clones_root(store):
    root = store.file("clones")
    root.mkdir(exist_ok=True)
    return root


def _verified(store, model_id):
    """True when meta.json exists and every verify pattern (file or folder)
    matches."""
    directory = models_root(store) / model_id
    if not (directory / "meta.json").is_file():
        return False
    return _matches(directory, MODELS[model_id]["verify"])


def _first(directory, pattern):
    for path in sorted(directory.glob(pattern)):
        if path.is_file():
            return path
    return None


def _first_dir(directory, pattern):
    for path in sorted(directory.glob(pattern)):
        if path.is_dir():
            return path
    return None


def status(store, model_id):
    if _verified(store, model_id):
        return {"state": "ready"}
    with _lock:
        active = _downloads.get(model_id)
        if active:
            # A recorded error surfaces as its own state so the UI stops
            # polling and delete/re-download become available again.
            state = "error" if active.get("error") else "downloading"
            return {**active, "state": state}
    return {"state": "missing"}


def models_status(store):
    result = []
    for model_id, spec in MODELS.items():
        result.append(
            {
                "id": model_id,
                "name": spec["name"],
                "description": spec["description"],
                "size": spec["size"],
                "engine": spec["engine"],
                **status(store, model_id),
            }
        )
    return result


def dependency_error():
    """Human-readable reason the sherpa-onnx runtime is missing, or None."""
    try:
        import sherpa_onnx  # noqa: F401

        return None
    except ImportError as exc:
        return str(exc)


def start_download(store, model_id):
    if model_id not in MODELS:
        raise ValueError("未知的本地模型")
    if _verified(store, model_id):
        return status(store, model_id)
    with _lock:
        active = _downloads.get(model_id)
        if active and not active.get("abort") and not active.get("error"):
            raise ValueError("该模型正在下载中")
        _downloads[model_id] = {"received": 0, "total": MODELS[model_id]["size"], "error": ""}
    free = shutil.disk_usage(store.root).free
    needed = MODELS[model_id]["size"] * 2 + 200 * 1024 * 1024
    if free < needed:
        with _lock:
            _downloads.pop(model_id, None)
        raise ValueError(f"磁盘空间不足：下载并解压约需 {needed // (1024 ** 2)} MB，当前仅剩 {free // (1024 ** 2)} MB")
    threading.Thread(target=_run_download, args=(store, model_id), daemon=True).start()
    return status(store, model_id)


def abort_download(model_id):
    with _lock:
        active = _downloads.get(model_id)
        if active:
            active["abort"] = True


def delete_model(store, model_id):
    if model_id not in MODELS:
        raise ValueError("未知的本地模型")
    if status(store, model_id)["state"] == "downloading":
        raise ValueError("模型正在下载，请先取消")
    shutil.rmtree(models_root(store) / model_id, ignore_errors=True)
    with _lock:
        _engines.pop((MODELS[model_id]["engine"], model_id), None)


def _run_download(store, model_id):
    spec = MODELS[model_id]
    staging = models_root(store) / f"{model_id}.staging"
    final = models_root(store) / model_id
    try:
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
        for relative, archive in spec["files"]:
            _fetch_file(model_id, relative, staging)
            if archive:
                _extract(staging / Path(relative).name, staging)
                # The 100-400MB archives must not ride along into the model
                # directory (disk space on a NAS is the scarcest resource).
                (staging / Path(relative).name).unlink(missing_ok=True)
        missing = [pattern for pattern in spec["verify"] if not _matches(staging, (pattern,))]
        if missing:
            raise ValueError(f"下载内容校验失败，缺少 {', '.join(missing)}")
        shutil.rmtree(final, ignore_errors=True)
        final.mkdir()
        for child in staging.iterdir():
            shutil.move(str(child), str(final / child.name))
        (final / "meta.json").write_text(
            json.dumps({"id": model_id, "completed": time.time()}), encoding="utf-8"
        )
        with _lock:
            _downloads.pop(model_id, None)
            _engines.pop((spec["engine"], model_id), None)
    except Exception as exc:  # noqa: BLE001 -- surfaced verbatim in the model list
        with _lock:
            entry = _downloads.get(model_id)
            if entry and entry.get("abort"):
                _downloads.pop(model_id, None)
            else:
                if entry:
                    entry["error"] = f"{type(exc).__name__}: {exc}"[:200]
                else:
                    _downloads[model_id] = {"received": 0, "total": 0, "error": str(exc)[:200]}
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _matches(directory, patterns):
    """Verify patterns match files OR folders (espeak-ng-data is a folder)."""
    return all(any(directory.glob(pattern)) for pattern in patterns)


def _aborted(model_id):
    with _lock:
        entry = _downloads.get(model_id) or {}
        return bool(entry.get("abort"))


def _fetch_file(model_id, relative, staging):
    """Stream one catalog file to ``staging``, resuming from the bytes already
    on disk. GitHub's CDN throttles long single attempts on some routes, so
    each attempt continues where the previous one stopped (HTTP Range)."""
    original = f"{RELEASE_PREFIX}/{relative}"
    url = f"{MIRROR_PREFIX}/{original}" if MIRROR_PREFIX else original
    url = validate_url(url, allow_local=True)
    target = staging / Path(relative).name
    with _lock:
        _downloads.setdefault(model_id, {"received": 0, "total": 0, "error": ""})
    for attempt in range(5):
        if _aborted(model_id):
            raise ValueError("下载已取消")
        received = target.stat().st_size if target.exists() else 0
        if received > DOWNLOAD_CAP:
            raise ValueError("模型文件超过大小上限，已停止下载")
        try:
            headers = {"Range": f"bytes={received}-"} if received else {}
            with httpx.Client(
                timeout=httpx.Timeout(60, connect=15), trust_env=False, follow_redirects=True
            ) as client, client.stream("GET", url, headers=headers) as response:
                if response.status_code >= 300:
                    raise ValueError(f"模型下载返回 HTTP {response.status_code}")
                resumed = response.status_code == 206 and received > 0
                length = int(response.headers.get("content-length") or 0)
                if not resumed:
                    received = 0
                with _lock:
                    _downloads[model_id]["total"] = received + length
                    _downloads[model_id]["received"] = received
                with target.open("ab" if resumed else "wb") as handle:
                    for chunk in response.iter_bytes(1024 * 256):
                        if _aborted(model_id):
                            raise ValueError("下载已取消")
                        received += len(chunk)
                        # Per-chunk, not per-attempt: a server that lies about
                        # (or omits) content-length must still be capped.
                        if received > DOWNLOAD_CAP:
                            raise ValueError("模型文件超过大小上限，已停止下载")
                        handle.write(chunk)
                        with _lock:
                            _downloads[model_id]["received"] = received
            return
        except httpx.HTTPError:
            if attempt == 4:
                raise ValueError(
                    "模型下载多次中断；请检查网络，或在启动时设置 SOUNDPAGE_TTS_MIRROR 加速镜像"
                ) from None
            time.sleep(2 * (attempt + 1))


def _extract(archive, staging):
    try:
        with tarfile.open(archive, "r:bz2") as tar:
            top = {member.name.split("/")[0] for member in tar.getmembers() if member.name.strip()}
            try:
                tar.extractall(staging, filter="data")
            except TypeError:  # Python < 3.11.4 has no filter parameter
                tar.extractall(staging)
    except tarfile.TarError as exc:
        raise ValueError(f"模型压缩包解压失败：{exc}") from exc
    # Archives carry a single top-level directory; fold its children up so
    # verify patterns and engine paths work on the model dir itself, even
    # when a bare extra file (the vocoder) sits beside it.
    if len(top) == 1:
        inner = staging / next(iter(top))
        if inner.is_dir():
            for child in inner.iterdir():
                shutil.move(str(child), str(staging / child.name))
            inner.rmdir()


def _threads():
    return max(1, min(4, os.cpu_count() or 2))


def _kokoro_model_id(store):
    for candidate in ("kokoro-int8", "kokoro"):
        if _verified(store, candidate):
            return candidate
    raise ValueError("还没有可用的本地音色模型，请先在设置中下载 Kokoro")


def _kokoro_engine(store, sherpa):
    """Load (or fetch the cached) Kokoro engine; returns (engine, model dir).
    All engine paths are model-relative — see _model_cwd."""
    model_id = _kokoro_model_id(store)
    with _lock:
        cached = _engines.get(("kokoro", model_id))
    if cached:
        return cached
    directory = models_root(store) / model_id
    lexicons = ",".join(sorted(p.name for p in directory.glob("lexicon*.txt")))
    fsts = ",".join(sorted(p.name for p in directory.glob("*.fst")))
    dict_dir = _first_dir(directory, "dict*")
    with _model_cwd(directory):
        config = sherpa.OfflineTtsConfig(
            model=sherpa.OfflineTtsModelConfig(
                kokoro=sherpa.OfflineTtsKokoroModelConfig(
                    model=_first(directory, "model*.onnx").name,
                    voices=_first(directory, "voices*.bin").name,
                    tokens="tokens.txt",
                    lexicon=lexicons,
                    data_dir=_first_dir(directory, "espeak-ng-data*").name,
                    dict_dir=dict_dir.name if dict_dir else "",
                ),
                num_threads=_threads(),
                provider="cpu",
            ),
            rule_fsts=fsts,
            max_num_sentences=1,
        )
        if not config.validate():
            raise ValueError("本地模型文件不完整，请删除后重新下载")
        engine = sherpa.OfflineTts(config)
    with _lock:
        _engines[("kokoro", model_id)] = (engine, directory)
    return engine, directory


def _zipvoice_engine(store, sherpa):
    with _lock:
        cached = _engines.get(("zipvoice", "zipvoice"))
    if cached:
        return cached
    directory = models_root(store) / "zipvoice"
    if not _verified(store, "zipvoice"):
        raise ValueError("克隆模型尚未下载，请先在设置中下载 ZipVoice")
    with _model_cwd(directory):
        config = sherpa.OfflineTtsConfig(
            model=sherpa.OfflineTtsModelConfig(
                zipvoice=sherpa.OfflineTtsZipvoiceModelConfig(
                    tokens="tokens.txt",
                    encoder=_first(directory, "encoder*.onnx").name,
                    decoder=_first(directory, "decoder*.onnx").name,
                    vocoder=_first(directory, "vocos*.onnx").name,
                    data_dir=_first_dir(directory, "espeak-ng-data*").name,
                    lexicon=(_first(directory, "lexicon*.txt").name if _first(directory, "lexicon*.txt") else ""),
                ),
                num_threads=_threads(),
                provider="cpu",
            ),
        )
        if not config.validate():
            raise ValueError("克隆模型文件不完整，请删除后重新下载")
        engine = sherpa.OfflineTts(config)
    with _lock:
        _engines[("zipvoice", "zipvoice")] = (engine, directory)
    return engine, directory


def _wav_bytes(samples, sample_rate):
    """Pack float samples into a mono 16-bit WAV the audio pipeline accepts."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(int(sample_rate))
        frames = array.array("h", (max(-32768, min(32767, int(s * 32767))) for s in samples))
        if sys.byteorder != "little":
            frames.byteswap()
        handle.writeframes(frames.tobytes())
    return buffer.getvalue()


def _reference_samples(path):
    """Reference audio as float samples; clones are stored as 24k mono WAV."""
    with wave.open(str(path), "rb") as handle:
        rate = handle.getframerate()
        raw = handle.readframes(handle.getnframes())
    values = array.array("h")
    values.frombytes(raw)
    if sys.byteorder != "little":
        values.byteswap()
    return [s / 32768 for s in values], rate


def synthesize(store, voice, text, speed=1.0):
    """Synthesize one segment locally; returns WAV bytes (any sample rate —
    the audio pipeline transcodes to 24 kHz mono)."""
    sherpa = _sherpa()
    voice = (voice or "").strip() or DEFAULT_VOICE
    speed = max(0.5, min(1.6, float(speed) or 1.0))
    if voice.startswith("k:"):
        try:
            sid = int(voice[2:])
        except ValueError as exc:
            raise ValueError(f"未知音色：{voice}") from exc
        if not 0 <= sid < 103:
            raise ValueError(f"未知音色：{voice}")
        engine, directory = _kokoro_engine(store, sherpa)
        gen = sherpa.GenerationConfig()
        gen.sid = sid
        gen.speed = speed
        with _model_cwd(directory):
            audio = engine.generate(text, gen)
        if not len(audio.samples):
            raise ValueError("本地引擎没有返回音频，请检查模型文件")
        return _wav_bytes(audio.samples, audio.sample_rate)
    if voice.startswith("c:"):
        clone = _find_clone(store, voice[2:])
        if not clone:
            raise ValueError("克隆音色不存在或已被删除")
        engine, directory = _zipvoice_engine(store, sherpa)
        samples, rate = _reference_samples(store.file(clone["file"]))
        gen = sherpa.GenerationConfig()
        gen.reference_audio = samples
        gen.reference_sample_rate = rate
        gen.reference_text = clone["text"]
        gen.num_steps = 4
        gen.speed = speed
        gen.extra["min_char_in_sentence"] = "30"
        with _model_cwd(directory):
            audio = engine.generate(text, gen)
        if not len(audio.samples):
            raise ValueError("本地克隆引擎没有返回音频，请检查参考音频与文本")
        return _wav_bytes(audio.samples, audio.sample_rate)
    raise ValueError(
        f"未知音色：{voice}（可能来自其他语音服务的绑定；请在角色库重新绑定音色，或使用“清除全部音色绑定”）"
    )


def kokoro_catalog():
    voices = []
    for sid in range(103):
        label = next(name for start, stop, name in _KOKORO_GROUPS if start <= sid < stop)
        index = sid - next(start for start, stop, _ in _KOKORO_GROUPS if start <= sid < stop) + 1
        voices.append(
            {
                "id": f"k:{sid}",
                "name": f"{label} {index}",
                "description": f"本地 Kokoro 音色（内置说话人 {sid}）",
                "category": "local",
            }
        )
    return voices


def list_voices(store):
    """Built-in voices (catalog is static data, independent of download state)
    plus the user's registered clones."""
    voices = kokoro_catalog()
    voices.extend(
        {
            "id": f"c:{clone['id']}",
            "name": clone["name"],
            "description": f"克隆音色 · 参考音频约 {clone.get('seconds', 0):.0f} 秒",
            "category": "clone",
        }
        for clone in clones(store)
    )
    return voices


def clones(store):
    return store.get("clones") or []


def _find_clone(store, ident):
    for clone in clones(store):
        if clone["id"] == ident:
            return clone
    return None


def register_clone(store, name, text, data, filename):
    """Register a zero-shot cloning voice from uploaded reference audio.

    The id hashes the audio bytes and the transcript: identical uploads are
    rejected as duplicates, changed material always becomes a new voice (and
    therefore a new synthesis identity for the cache)."""
    name = (name or "").strip()
    text = (text or "").strip()
    if not name:
        raise ValueError("请填写克隆音色的名称")
    if len(name) > 60:
        raise ValueError("克隆名称不能超过 60 字")
    if not text:
        raise ValueError("请填写与参考音频一致的原文")
    if len(text) > 300:
        raise ValueError("参考原文不能超过 300 字")
    if not (4 * 1024 <= len(data) <= 20 * 1024 * 1024):
        raise ValueError("参考音频需要在 4KB–20MB 之间")
    suffix = re.sub(r"[^a-z0-9]", "", (Path(filename or "").suffix or ".wav").lower())[:5] or "wav"
    ident = hashlib.sha256(data + b"\0" + text.encode()).hexdigest()[:12]
    if _find_clone(store, ident):
        raise ValueError("该参考音频已注册过克隆音色")
    if len(clones(store)) >= MAX_CLONES:
        raise ValueError("克隆音色数量已达上限，请先删除不用的克隆")
    source = clones_root(store) / f"upload-{ident}.{suffix}"
    target = clones_root(store) / f"{ident}.wav"
    source.write_bytes(data)
    result = subprocess.run(
        [
            ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source), "-ac", "1", "-ar", "24000", "-sample_fmt", "s16",
            str(target),
        ],
        capture_output=True,
        timeout=120,
        check=False,
    )
    source.unlink(missing_ok=True)
    if result.returncode != 0 or not target.is_file():
        raise ValueError("参考音频无法解码，请使用 wav / mp3 / m4a 等常见格式")
    with wave.open(str(target), "rb") as handle:
        seconds = handle.getnframes() / handle.getframerate()
    if not 1 <= seconds <= 30:
        target.unlink(missing_ok=True)
        raise ValueError("参考音频需要在 1–30 秒之间")
    entries = [
        clone for clone in clones(store) if clone["id"] != ident
    ] + [
        {
            "id": ident,
            "name": name,
            "text": text,
            "file": f"clones/{ident}.wav",
            "seconds": round(seconds, 1),
            "created": time.time(),
        }
    ]
    store.set("clones", entries)
    return {"id": f"c:{ident}", "name": name, "description": f"克隆音色 · 参考音频约 {seconds:.0f} 秒", "category": "clone"}


def delete_clone(store, ident):
    kept = [clone for clone in clones(store) if clone["id"] != ident]
    if len(kept) == len(clones(store)):
        raise ValueError("克隆音色不存在")
    for clone in clones(store):
        if clone["id"] == ident:
            store.file(clone["file"]).unlink(missing_ok=True)
    store.set("clones", kept)


def signature(store, voices):
    """Cache-identity inputs: which engine files would serve these voices.

    Covers model-variant switches (int8 vs fp32) and later model downloads;
    clone ids already hash their own material."""
    resolved = []
    for voice in voices:
        voice = (voice or "").strip() or DEFAULT_VOICE
        if voice.startswith("k:"):
            resolved.append(
                "kokoro-int8"
                if _verified(store, "kokoro-int8")
                else "kokoro"
                if _verified(store, "kokoro")
                else "kokoro-missing"
            )
        elif voice.startswith("c:"):
            resolved.append("zipvoice" if _verified(store, "zipvoice") else "zipvoice-missing")
        else:
            resolved.append(f"voice:{voice}")
    return {"local_engines": sorted(set(resolved))}
