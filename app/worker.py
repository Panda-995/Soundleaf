"""One durable worker per application process; run Uvicorn with one worker."""

import hashlib
import json
import re
import threading
import time
import zipfile

from app import audio, providers
from app.store import uid

_SPEAKER_NOISE = re.compile(r"[\s（）()\[\]【】“”\"'‘’·、，。！？!?…\-—_]+")


def norm_speaker(name):
    """Canonical speaker key: strip whitespace, parentheses and punctuation so
    「汪淼」「 汪淼 」「汪淼（青年）」 collapse to one character."""
    cleaned = _SPEAKER_NOISE.sub("", (name or "").strip())
    return cleaned or "旁白"


def match_speaker(table, speaker):
    """Look up a normalized speaker; fall back to a unique prefix/extension
    match so name variants resolve to the same entry."""
    if speaker in table:
        return table[speaker]
    candidates = [
        key
        for key in table
        if key and key != "旁白" and min(len(key), len(speaker)) >= 2
        and (key.startswith(speaker) or speaker.startswith(key))
    ]
    return table[candidates[0]] if len(candidates) == 1 else None


def top_vote(counts):
    """Most frequent value in a ``{value: count}`` map (first inserted wins ties)."""
    return max(counts.items(), key=lambda kv: kv[1])[0]


def speaker_bindings(segments):
    """Chapter-level speaker→voice table from the stored script.

    Per-segment voice fields can drift (an AI suggestion missing a voice, a
    manual tweak); synthesizing them literally makes one character alternate
    between two voices across a chapter. The most frequently used non-empty
    voice wins per normalized speaker, so every line of a character stays
    consistent.
    """
    counts: dict[str, dict[str, int]] = {}
    for seg in segments:
        speaker = norm_speaker(seg.get("speaker"))
        voice = (seg.get("voice") or "").strip()
        if speaker != "旁白" and voice:
            counts.setdefault(speaker, {})
            counts[speaker][voice] = counts[speaker].get(voice, 0) + 1
    return {speaker: top_vote(v) for speaker, v in counts.items()}


def resolved_segment(segment, bindings, cast=None):
    """Effective synthesis form of one segment.

    Hard rules: text without any quoted span is narration and always reads
    with the default narrator voice — even when a stale label names a
    character. Quoted dialogue reads with the character's voice, resolved as
    book cast → chapter binding → the segment's own value, so one character
    cannot alternate between voices within or across chapters.
    """
    speaker = norm_speaker(segment.get("speaker"))
    if speaker == "旁白" or not QUOTED.search(segment.get("text", "")):
        return {**segment, "voice": ""}
    voice = match_speaker(cast or {}, speaker) if cast else None
    return {**segment, "voice": voice or bindings.get(speaker) or segment.get("voice") or ""}


QUOTED = re.compile(r"(“[^”]*”|「[^」]*」|『[^』]*』|\"[^\"\n]+\")")


def apply_pronunciation(text, entries):
    """Book pronunciation dictionary, applied just before synthesis: swap
    error-prone words for a spelling the engine reads correctly. Entries must
    be sorted longest-word-first so 「重庆」 wins over 「重」. Replacement only
    touches the spoken text — the stored script keeps the original writing.
    The result is hard-capped: a pathological dictionary (chained expansions
    like a→aa, aa→aaaa) must not stall the single worker or inflate the text
    that gets billed."""
    cap = max(2400, len(text) * 2 + 200)
    for word, replacement in entries:
        text = text.replace(word, replacement)
        if len(text) > cap:
            raise ValueError("读音词典使文本异常膨胀，请检查可能互相放大的词条")
    return text


def book_pronunciation(store, book_id):
    """Longest-first pronunciation entries for one book (empty when none)."""
    if not book_id:
        return []
    return sorted(
        ((r["word"], r["replacement"]) for r in
         store.rows("SELECT word,replacement FROM dict WHERE book_id=?", (book_id,))),
        key=lambda e: (-len(e[0]), e[0]),
    )


def synthesis_units(segment, default_voice):
    """Split a character-attributed segment at quote boundaries.

    A segment like ``“别动。”他伸手拦住了她。`` carries one speaker label, but
    only the quoted words are the character speaking; the narration tail must
    read with the default narrator voice. Quoted spans keep the segment's
    voice / emotion; everything outside them falls back to the default voice.
    Segments without their own voice, narrated by 旁白, or already on the
    default voice are returned unchanged.
    """
    if (
        segment.get("speaker")
        and segment["speaker"] != "旁白"
        and segment.get("voice")
        and segment["voice"] != default_voice
    ):
        parts = [p for p in QUOTED.split(segment["text"]) if p.strip()]
        if len(parts) > 1:
            return [
                {**segment, "text": part}
                if QUOTED.fullmatch(part)
                else {
                    **segment,
                    "text": part,
                    "voice": default_voice or "",
                    "emotion": "neutral",
                    "speaker": "旁白",
                }
                for part in parts
            ]
    return [segment]


class Cancelled(Exception):
    pass


def materialize_segments(existing, pieces):
    """Map AI-suggested boundaries back to studio segments.

    ``existing`` is the list of segments stored on the chapter (text + voice +
    speaker, ordered by source). ``pieces`` is what the LLM returned: each item
    has ``text`` (a contiguous source substring) and ``hint`` (narration /
    dialogue / aside / pause). We pair each new piece with the existing
    segment that owns the largest share of its characters, then carry over
    voice / speaker. Dialogue hints inherit the first voice assigned to that
    speaker across existing segments; everything else defaults to neutral
    narration.
    """

    # Build a list of (start, end, voice, speaker) so we can binary-search
    # boundaries and avoid quadratic scans for long chapters.
    spans = []
    cursor = 0
    for seg in existing:
        start = cursor
        end = cursor + len(seg.get("text", ""))
        spans.append(
            {
                "start": start,
                "end": end,
                "voice": seg.get("voice", ""),
                "speaker": seg.get("speaker", "旁白"),
            }
        )
        cursor = end
    speaker_voice: dict[str, str] = {}
    for span in spans:
        if span["voice"]:
            speaker_voice.setdefault(span["speaker"], span["voice"])

    def _lookup(start: int, end: int):
        best = None
        for span in spans:
            if span["end"] <= start:
                continue
            if span["start"] >= end:
                break
            overlap = min(span["end"], end) - max(span["start"], start)
            if overlap <= 0:
                continue
            if best is None or overlap > best["overlap"]:
                best = {**span, "overlap": overlap}
        return best

    result = []
    cursor = 0
    for piece in pieces:
        text = piece.get("text", "")
        if not text:
            continue
        start = cursor
        end = cursor + len(text)
        anchor = _lookup(start, end)
        # An explicit speaker on the piece (from AI grouping) wins; otherwise
        # inherit from the existing segment covering the same characters.
        speaker = piece.get("speaker") or (anchor or {}).get("speaker") or "旁白"
        voice = ""
        hint = piece.get("hint", "narration")
        if hint == "dialogue":
            voice = speaker_voice.get(speaker, "")
        elif anchor and anchor.get("voice"):
            voice = anchor["voice"]
        if hint == "pause" or not text.strip():
            voice = ""
            emotion = "neutral"
            speed = 1.0
            pause = 600
        else:
            emotion = "neutral"
            speed = 1.0
            pause = 300 if hint == "dialogue" else 250
        result.append(
            {
                "text": text,
                "voice": voice,
                "emotion": emotion,
                "speed": speed,
                "pause": pause,
                "speaker": speaker if hint == "dialogue" else "旁白",
            }
        )
        cursor = end
    return result


class Worker:
    CLEANUP_INTERVAL = 6 * 3600

    def __init__(self, store):
        self.store = store
        self.stop = threading.Event()
        self.heartbeat = time.time()
        self.next_cleanup = time.time()
        self.thread = threading.Thread(target=self.loop, name="soundleaf-worker", daemon=True)

    def start(self):
        # A request in flight may already have been billed. Never replay it silently.
        # The listed stages are exactly the paid-call windows of the job kinds.
        self.store.execute(
            "UPDATE jobs SET status='needs_review',error='服务请求中断，结果可能已生成。确认服务端结果后重试。' "
            "WHERE status='running' AND stage IN ('请求语音服务','AI 绘制封面','分析书籍资料')"
        )
        self.store.execute("UPDATE jobs SET status='queued',stage='恢复任务' WHERE status='running'")
        self.thread.start()

    def update(self, job_id, **fields):
        fields["updated"] = time.time()
        self.store.execute(
            "UPDATE jobs SET " + ",".join(f"{k}=?" for k in fields) + " WHERE id=?",
            (*fields.values(), job_id),
        )

    def check(self, job_id):
        if self.stop.is_set():
            raise Cancelled()
        row = self.store.one("SELECT cancel FROM jobs WHERE id=?", (job_id,))
        if not row or row["cancel"]:
            raise Cancelled()

    def claim(self):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM jobs WHERE status='queued' AND cancel=0 ORDER BY created LIMIT 1"
            ).fetchone()
            if row:
                db.execute("UPDATE jobs SET status='running',updated=? WHERE id=?", (time.time(), row["id"]))
                return dict(row)
        return None

    def cleanup(self):
        """Bounded retention. Terminal jobs, unconfirmed imports and preview
        audio otherwise grow without limit on a long-lived install."""
        now = time.time()
        self.store.execute(
            "DELETE FROM jobs WHERE status IN ('succeeded','failed','cancelled','needs_review') "
            "AND updated<?",
            (now - 7 * 86400,),
        )
        for row in self.store.rows(
            "SELECT id,source FROM imports WHERE created<?", (now - 48 * 3600,)
        ):
            try:
                self.store.file(row["source"]).unlink(missing_ok=True)
            except OSError:
                # Keep the row so a later cycle retries the file removal
                # instead of stranding an orphaned source forever.
                continue
            self.store.execute("DELETE FROM imports WHERE id=?", (row["id"],))
        for row in self.store.rows(
            "SELECT id,path FROM audio WHERE chapter_id IS NULL AND created<?", (now - 86400,)
        ):
            for suffix in (".wav", ".mp3"):
                try:
                    self.store.file(row["path"]).with_suffix(suffix).unlink(missing_ok=True)
                except OSError:
                    pass
            self.store.execute("DELETE FROM audio WHERE id=?", (row["id"],))
        self.store.execute("DELETE FROM sessions WHERE expires<?", (now,))

    def loop(self):
        while not self.stop.is_set():
            self.heartbeat = time.time()
            if time.time() >= self.next_cleanup:
                self.next_cleanup = time.time() + self.CLEANUP_INTERVAL
                try:
                    self.cleanup()
                except Exception:  # noqa: BLE001 -- cleanup is best-effort
                    import traceback

                    traceback.print_exc()
            if self.store.get("paused"):
                self.stop.wait(0.5)
                continue
            job = self.claim()
            if not job:
                self.stop.wait(0.5)
                continue
            try:
                try:
                    self.run(job)
                    self.update(job["id"], status="succeeded", stage="已完成")
                except Cancelled:
                    self.update(job["id"], status="cancelled", stage="已取消")
                except providers.UncertainResult as exc:
                    self.update(job["id"], status="needs_review", error=str(exc), stage="结果待确认")
                except (ValueError, OSError, zipfile.BadZipFile) as exc:
                    message = (
                        str(exc) if isinstance(exc, ValueError) else "文件处理失败，请检查磁盘空间和目录写入权限"
                    )
                    self.update(job["id"], status="failed", error=message, stage="处理失败")
                except Exception as exc:  # noqa: BLE001 -- isolate task failures so the durable worker stays alive
                    # Provider responses can contain secrets or text: do not expose arbitrary tracebacks.
                    import traceback
                    traceback.print_exc()
                    self.update(
                        job["id"],
                        status="failed",
                        error=f"任务处理异常：{type(exc).__name__}: {exc}"[:200],
                        stage="处理失败",
                    )
            except Exception:  # noqa: BLE001 -- a failing status write (locked DB, disk error)
                # must never take the worker thread down; /health/ready has no
                # second line of defence behind it.
                import traceback
                traceback.print_exc()
                self.stop.wait(1)

    def synthesize_to_cache(self, segment, config, job_id=None, label=""):
        """Synthesize one resolved segment into the shared cache (merging
        quote/narration units) and return the wav path. Reused when the
        identity (text/voice/emotion/speed) is unchanged."""
        options = {k: v for k, v in config.items() if k != "api_key"}
        # Pause is added during assembly, so it need not invalidate synthesis.
        identity = {k: v for k, v in segment.items() if k not in ("pause", "speaker")}
        # v2: emotion styles no longer shift pitch/volume — cached audio from
        # the old timbre-shifting mapping must not be reused.
        digest = hashlib.sha256(
            json.dumps(["tts-v2", options, identity], sort_keys=True).encode()
        ).hexdigest()
        cached = self.store.file(f"cache/{digest}.wav")
        if cached.exists():
            return cached
        if job_id:
            self.update(job_id, stage="请求语音服务")
        units = synthesis_units(segment, config.get("voice", ""))
        try:
            if len(units) == 1:
                audio.atomic_audio(providers.synthesize(config, units[0]), cached)
            else:
                parts = []
                for unit in units:
                    temporary = cached.with_name(f"{cached.stem}.u{len(parts)}.tmp.wav")
                    audio.atomic_audio(providers.synthesize(config, unit), temporary)
                    parts.append(temporary)
                # A short breath between the quote and the narration tail.
                audio.concatenate(parts, [200] * len(parts), cached)
        except ValueError as exc:
            preview = segment["text"].strip()[:24]
            where = f"{label}「{preview}…」" if label else f"「{preview}…」"
            raise ValueError(f"{where}合成失败：{exc}") from exc
        finally:
            for temporary in cached.parent.glob(f"{cached.stem}.u*.tmp.wav"):
                temporary.unlink(missing_ok=True)
        # Loudness normalization: one shared RMS target keeps different voices,
        # emotions and providers at a similar perceived volume.
        audio.normalize_loudness(cached)
        return cached

    def run(self, job):
        payload = json.loads(job["payload"])
        if job["kind"] == "export":
            return self.export(job, payload)
        config = json.loads(self.store.cipher.decrypt(payload["config"].encode()))
        if job["kind"] == "analyze":
            self.update(job["id"], stage="分析朗读节奏", total=len(payload["segments"]))
            suggestions = []
            cast = payload.get("cast", {}).copy()
            # Bounded batches do not send an entire long novel to the provider.
            for offset in range(0, len(payload["segments"]), 16):
                self.check(job["id"])
                values = providers.analyze(
                    config, payload["segments"][offset : offset + 16], payload.get("voices", []), cast
                )
                for value in values:
                    if value.get("voice"):
                        cast[value["speaker"]] = {"voice": value["voice"]}
                for value in values:
                    value["index"] += offset
                suggestions.extend(values)
                self.update(job["id"], done=len(suggestions))
            self.check(job["id"])
            # Present one consistent cast: text without quotes is narration —
            # even when the AI mislabeled it as a character — so it reads with
            # the book default, and each character keeps a single voice even
            # when individual AI answers drifted.
            counts: dict[str, dict[str, int]] = {}
            for value in suggestions:
                speaker = norm_speaker(value.get("speaker"))
                if speaker != "旁白" and not QUOTED.search(value.get("text", "")):
                    speaker = "旁白"
                    value["speaker"] = "旁白"
                voice = value.get("voice") or ""
                if speaker != "旁白" and voice:
                    counts.setdefault(speaker, {})
                    counts[speaker][voice] = counts[speaker].get(voice, 0) + 1
            cast_voices = {speaker: top_vote(v) for speaker, v in counts.items()}
            for value in suggestions:
                speaker = norm_speaker(value.get("speaker"))
                value["voice"] = "" if speaker == "旁白" else cast_voices.get(speaker, "")
            self.store.execute(
                "UPDATE chapters SET suggestion=? WHERE id=? AND revision=?",
                (
                    json.dumps({"revision": payload["revision"], "segments": suggestions}),
                    job["chapter_id"],
                    payload["revision"],
                ),
            )
            return
        if job["kind"] == "restructure":
            self.update(job["id"], stage="按语义归并段落", total=1)

            def progress(done, total):
                self.check(job["id"])
                self.update(
                    job["id"],
                    done=done,
                    total=total,
                    stage="AI 正在按语义归并段落",
                )

            pieces = providers.restructure_chapter(
                config, payload["text"], progress
            )
            self.check(job["id"])
            # Convert the AI-suggested boundaries into the studio's segment
            # shape, preserving every existing voice / speaker hint where the
            # original segment covered the same characters.
            chapter_id = job.get("chapter_id") or ""
            existing_rows = (
                self.store.rows(
                    "SELECT segments FROM chapters WHERE id=?",
                    (chapter_id,),
                )
                if chapter_id
                else []
            )
            existing = (
                json.loads(existing_rows[0]["segments"])
                if existing_rows and existing_rows[0].get("segments")
                else []
            )
            proposed = materialize_segments(existing, pieces)
            self.update(job["id"], stage="等待用户确认", done=1)
            self.store.execute(
                "UPDATE jobs SET payload=? WHERE id=?",
                (
                    json.dumps(
                        {
                            **payload,
                            "proposed": proposed,
                            "existing_revision": payload["revision"],
                        }
                    ),
                    job["id"],
                ),
            )
            return
        if job["kind"] == "generate_cover":
            self.update(job["id"], stage="AI 绘制封面", total=1)
            image, ext = providers.generate_cover_image(
                config,
                payload["title"],
                payload.get("mood", ""),
                payload.get("tags"),
                payload.get("extra", ""),
            )
            self.check(job["id"])
            ident = uid()
            relative = f"covers/{ident}{ext}"
            temporary = self.store.file(f"tmp/{ident}{ext}")
            try:
                temporary.write_bytes(image)
                temporary.replace(self.store.file(relative))
            except OSError as exc:
                raise ValueError("封面保存失败，请检查磁盘空间") from exc
            finally:
                temporary.unlink(missing_ok=True)
            old = self.store.one("SELECT cover FROM books WHERE id=?", (job["book_id"],))
            self.store.execute(
                "UPDATE books SET cover=? WHERE id=?", (relative, job["book_id"])
            )
            if old and old["cover"] and old["cover"] != relative:
                try:
                    self.store.file(old["cover"]).unlink(missing_ok=True)
                except OSError:
                    pass
            payload["cover"] = relative
            self.update(job["id"], done=1)
            self.store.execute(
                "UPDATE jobs SET payload=? WHERE id=?",
                (json.dumps(payload, ensure_ascii=False), job["id"]),
            )
            return
        if job["kind"] == "analyze_book":
            self.update(job["id"], stage="分析书籍资料", total=1)
            meta = providers.analyze_book(config, payload["title"], payload.get("excerpt", ""))
            self.check(job["id"])
            self.update(job["id"], stage="等待用户确认", done=1)
            self.store.execute(
                "UPDATE jobs SET payload=? WHERE id=?",
                (
                    json.dumps({**payload, "meta": meta}, ensure_ascii=False),
                    job["id"],
                ),
            )
            return
        if job["kind"] == "analyze_chapters":
            self.update(job["id"], stage="识别章节结构", total=1)

            def progress(done, total):
                self.check(job["id"])
                self.update(job["id"], done=done, total=total, stage="识别原文章节标题")

            proposed = providers.analyze_chapters(config, payload["text"], progress)
            self.check(job["id"])
            self.update(job["id"], stage="等待用户确认", done=1)
            # Keep the proposed structure in the job payload so the UI can preview before applying.
            self.store.execute(
                "UPDATE jobs SET payload=? WHERE id=?",
                (
                    json.dumps(
                        {
                            **payload,
                            "proposed": proposed,
                            "result": "preview",
                        },
                        ensure_ascii=False,
                    ),
                    job["id"],
                ),
            )
            return
        if job["kind"] == "regen_segment":
            # Cast version as of job start — see the generate block note.
            regen_cast_row = self.store.one("SELECT cast_version FROM books WHERE id=?", (job["book_id"],))
            regen_cast_version = regen_cast_row["cast_version"] if regen_cast_row else 1
            self.update(job["id"], stage="解析角色音色", total=1)
            row = self.store.one("SELECT * FROM chapters WHERE id=?", (job["chapter_id"],))
            segments = json.loads(row["segments"])
            index = payload["index"]
            if not 0 <= index < len(segments):
                raise ValueError("片段序号超出范围")
            bindings = speaker_bindings(segments)
            cast = {
                norm_speaker(r["speaker"]): r["voice"]
                for r in self.store.rows(
                    "SELECT speaker, voice FROM cast WHERE book_id=?", (job["book_id"],)
                )
            }
            segment = resolved_segment(segments[index], bindings, cast)
            speaker = norm_speaker(segment.get("speaker"))
            pronunciation = book_pronunciation(self.store, job["book_id"])
            pron_snapshot = json.dumps(pronunciation, ensure_ascii=False)
            if pronunciation:
                spoken = apply_pronunciation(segment["text"], pronunciation)
                if spoken != segment["text"]:
                    segment = {**segment, "text": spoken}
            style = {}
            style_row = self.store.one("SELECT style FROM books WHERE id=?", (job["book_id"],))
            if style_row and style_row["style"]:
                try:
                    style = json.loads(style_row["style"])
                except ValueError:
                    style = {}
            # Identical narration tint and pause scaling to full-chapter
            # generation, so a regenerated slice stays consistent with the
            # timeline its neighbours were spliced from.
            dialogue_pause = max(0.4, min(2.5, float(style.get("dialogue_pause") or 1)))
            narration_pause = max(0.4, min(2.5, float(style.get("narration_pause") or 1)))
            narration_speed = max(0.7, min(1.3, float(style.get("narration_speed") or 1)))
            if speaker == "旁白" and narration_speed != 1:
                segment = {**segment, "speed": round(max(0.5, min(2, segment["speed"] * narration_speed)), 2)}
            cached = self.synthesize_to_cache(segment, config, job["id"], f"片段 {index + 1}")
            audio_row = self.store.one("SELECT * FROM audio WHERE id=?", (row["active_audio"],))
            if not audio_row:
                raise ValueError("章节音频文件不存在，请先生成本章")
            timeline = json.loads(audio_row["timeline"])
            entry = next((e for e in timeline if e["index"] == index), None)
            if not entry:
                raise ValueError("音频时间轴中找不到该片段，请先生成本章")
            seg_duration, _ = audio.metadata(cached)
            self.update(job["id"], stage="就地拼接音频", done=1)
            new_id = uid()
            relative = f"audio/{new_id}.wav"
            target = self.store.file(relative)
            # Timeline entries span the segment audio PLUS its trailing pause.
            # Replace the WHOLE old slot (speech + old pause) with the new
            # speech + the new (style-scaled) pause as silence — otherwise a
            # changed pause leaves residual silence or overlaps the next
            # segment, and a shorter last segment leaves stale audio at EOF.
            pause = (
                max(
                    0,
                    min(
                        3000,
                        round(
                            (segments[index].get("pause") or 0)
                            * (narration_pause if speaker == "旁白" else dialogue_pause)
                        ),
                    ),
                )
                / 1000
            )
            # A full generation puts NO trailing pause after the last timeline
            # slot — a partial regen of that slot must not add one either.
            is_last_slot = bool(timeline) and timeline[-1].get("index") == index
            effective_pause = 0 if is_last_slot else pause
            audio.splice_segment(
                self.store.file(audio_row["path"]),
                target,
                entry["start"],
                entry["end"],
                cached,
                tail_silence=effective_pause,
            )
            duration, peaks = audio.metadata(target)
            delta = duration - audio_row["duration"]
            for e in timeline:
                if e["index"] == index:
                    e["end"] = round(e["start"] + seg_duration + effective_pause, 4)
                elif e["start"] > entry["start"]:
                    e["start"] = round(e["start"] + delta, 4)
                    e["end"] = round(e["end"] + delta, 4)
            self.update(job["id"], stage="转码 MP3")
            audio.convert(
                target, target.with_suffix(".mp3"), mp3=True, timeout=max(300, int(duration) + 120)
            )
            self.check(job["id"])
            _, issues = providers.inspect_wav_quality(cached, len(segment["text"].strip()))
            prev_quality = json.loads(audio_row["quality"])["segments"] if audio_row["quality"] else []
            prev_quality = [q for q in prev_quality if q["index"] != index]
            if issues:
                prev_quality.append({"index": index, "issues": issues})
            quality_json = json.dumps({"segments": prev_quality}) if prev_quality else None
            with self.store.connect() as db:
                db.execute(
                    "INSERT INTO audio VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        new_id,
                        job["chapter_id"],
                        payload["revision"],
                        relative,
                        duration,
                        json.dumps(peaks),
                        json.dumps(timeline),
                        time.time(),
                        quality_json,
                        regen_cast_version,
                    ),
                )
                # Never promote stale output over a newer text revision.
                promoted = db.execute(
                    "UPDATE chapters SET active_audio=? WHERE id=? AND revision=?",
                    (new_id, job["chapter_id"], payload["revision"]),
                ).rowcount
                # Only when THIS output got promoted may the segment leave the
                # stale list (a newer edit supersedes the regen and its stale
                # records stay). An empty list means the whole chapter audio is
                # current again — realign the audio revision so the plain
                # revision staleness check also clears.
                stale_row = db.execute(
                    "SELECT stale_segments,revision FROM chapters WHERE id=?", (job["chapter_id"],)
                ).fetchone()
                # Re-read pronunciation: if it was changed between segment
                # synthesis and promotion, the audio already reflects the OLD
                # dict — keep the stale marker so the user knows to re-do it.
                pron_now = json.dumps(book_pronunciation(self.store, job["book_id"]))
                dict_stable = pron_now == pron_snapshot
                if promoted and stale_row and stale_row["stale_segments"]:
                    stale = json.loads(stale_row["stale_segments"])
                    if dict_stable:
                        stale = sorted(i for i in stale if i != index)
                    if stale:
                        db.execute(
                            "UPDATE chapters SET stale_segments=? WHERE id=?",
                            (json.dumps(stale), job["chapter_id"]),
                        )
                    else:
                        db.execute("UPDATE chapters SET stale_segments=NULL WHERE id=?", (job["chapter_id"],))
                        db.execute(
                            "UPDATE audio SET revision=? WHERE id=? AND revision=?",
                            (stale_row["revision"], new_id, payload["revision"]),
                        )
                payload["audio_id"] = new_id
                db.execute("UPDATE jobs SET payload=? WHERE id=?", (json.dumps(payload), job["id"]))
            return
        # Cast version as of JOB START (when the cast was loaded for
        # synthesis) — reading it at completion would silently relabel audio
        # synthesized with the old voice as current after a mid-job rebind.
        cast_version_row = self.store.one(
            "SELECT cast_version FROM books WHERE id=?", (job["book_id"],)
        )
        cast_version = cast_version_row["cast_version"] if cast_version_row else 1
        segments = payload["segments"]
        bindings = speaker_bindings(segments)
        # Book reading style: pause scaling applies at concatenation (speech
        # cache is reused untouched), narration speed tints synthesis only.
        style = {}
        style_row = (
            self.store.one("SELECT style FROM books WHERE id=?", (job["book_id"],))
            if job["book_id"]
            else None
        )
        if style_row and style_row["style"]:
            try:
                style = json.loads(style_row["style"])
            except ValueError:
                style = {}
        dialogue_pause = max(0.4, min(2.5, float(style.get("dialogue_pause") or 1)))
        narration_pause = max(0.4, min(2.5, float(style.get("narration_pause") or 1)))
        narration_speed = max(0.7, min(1.3, float(style.get("narration_speed") or 1)))
        # Book-level cast wins over per-chapter drift so a character keeps one
        # voice across chapters; new bindings learned here are stored back.
        cast = {}
        pronunciation = []
        if job["book_id"]:
            cast = {
                norm_speaker(r["speaker"]): r["voice"]
                for r in self.store.rows(
                    "SELECT speaker, voice FROM cast WHERE book_id=?", (job["book_id"],)
                )
            }
            for speaker, voice in bindings.items():
                if speaker != "旁白" and speaker not in cast:
                    self.store.execute(
                        "INSERT OR REPLACE INTO cast VALUES (?,?,?,?)",
                        (job["book_id"], speaker, voice, time.time()),
                    )
                    cast[speaker] = voice
            pronunciation = book_pronunciation(self.store, job["book_id"])
        paths, pauses, indexes, quality = [], [], [], []
        self.update(job["id"], total=len(segments))
        for i, segment in enumerate(segments):
            self.check(job["id"])
            if not segment["text"].strip():
                continue
            # Narration is pinned to the default voice and characters to their
            # book-level voice; the cache key follows the resolved voice so a
            # re-bound voice is re-synthesized instead of reused stale.
            segment = resolved_segment(segment, bindings, cast)
            if pronunciation:
                spoken = apply_pronunciation(segment["text"], pronunciation)
                if spoken != segment["text"]:
                    segment = {**segment, "text": spoken}
            speaker = norm_speaker(segment.get("speaker"))
            if speaker == "旁白" and narration_speed != 1:
                segment = {
                    **segment,
                    "speed": round(max(0.5, min(2, segment["speed"] * narration_speed)), 2),
                }
            cached = self.synthesize_to_cache(segment, config, job["id"], f"片段 {i + 1}")
            audio.metadata(cached)
            paths.append(cached)
            pauses.append(
                max(
                    0,
                    min(
                        3000,
                        round(
                            segment["pause"]
                            * (narration_pause if speaker == "旁白" else dialogue_pause)
                        ),
                    ),
                )
            )
            indexes.append(i)
            _, issues = providers.inspect_wav_quality(cached, len(segment["text"].strip()))
            if issues:
                quality.append({"index": i, "issues": issues})
            self.update(job["id"], stage="合成片段", done=i + 1)
        self.check(job["id"])
        if not paths:
            raise ValueError("章节没有可朗读的内容")
        self.update(job["id"], stage="拼接章节")
        ident = uid()
        relative = f"audio/{ident}.wav"
        target = self.store.file(relative)
        timeline = audio.concatenate(paths, pauses, target)
        for entry, index in zip(timeline, indexes, strict=True):
            entry["index"] = index
        duration, peaks = audio.metadata(target)
        # Hours-long chapters need more than the default 300s to transcode.
        audio.convert(target, target.with_suffix(".mp3"), mp3=True, timeout=max(300, int(duration) + 120))
        self.check(job["id"])
        with self.store.connect() as db:
            db.execute(
                "INSERT INTO audio VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    ident,
                    job["chapter_id"],
                    payload.get("revision", 0),
                    relative,
                    duration,
                    json.dumps(peaks),
                    json.dumps(timeline),
                    time.time(),
                    json.dumps({"segments": quality}) if quality else None,
                    cast_version,
                ),
            )
            if job["chapter_id"]:
                # Never promote stale job output over a newer text revision.
                # The stale-segment list may only be cleared when THIS output
                # actually got promoted AND the dict hasn't changed mid-flight
                # (a mid-generation dict change means some segments were
                # synthesized with the old pronunciation).
                pron_unchanged = json.dumps(pronunciation, ensure_ascii=False) == json.dumps(
                    book_pronunciation(self.store, job["book_id"]), ensure_ascii=False
                )
                if pron_unchanged:
                    promoted = db.execute(
                        "UPDATE chapters SET active_audio=?,stale_segments=NULL WHERE id=? AND revision=?",
                        (ident, job["chapter_id"], payload["revision"]),
                    ).rowcount
                else:
                    promoted = db.execute(
                        "UPDATE chapters SET active_audio=? WHERE id=? AND revision=?",
                        (ident, job["chapter_id"], payload["revision"]),
                    ).rowcount
                if not promoted:
                    db.execute(
                        "UPDATE chapters SET stale_segments=NULL WHERE id=? AND revision=?",
                        (job["chapter_id"], payload["revision"]),
                    )
            payload["audio_id"] = ident
            db.execute("UPDATE jobs SET payload=? WHERE id=?", (json.dumps(payload), job["id"]))
        # Completion notice: fired when the LAST active job of a book finishes,
        # so batch generation produces one summary push instead of spam.
        if job["kind"] == "generate" and job["book_id"]:
            remaining = self.store.one(
                "SELECT id FROM jobs WHERE book_id=? AND status IN ('queued','running') AND id!=?",
                (job["book_id"], job["id"]),
            )
            if not remaining:
                notify_config = self.store.get("notify") or {}
                if notify_config.get("enabled"):
                    book_row = self.store.one(
                        "SELECT title FROM books WHERE id=?", (job["book_id"],)
                    )
                    stats = self.store.one(
                        "SELECT count(*) total, sum(CASE WHEN active_audio IS NOT NULL THEN 1 ELSE 0 END) done "
                        "FROM chapters WHERE book_id=?",
                        (job["book_id"],),
                    )
                    error = providers.send_notification(
                        notify_config,
                        f"《{book_row['title']}》生成完成",
                        f"已完成 {stats['done'] or 0}/{stats['total']} 章。打开声页试听或导出。",
                    )
                    if error:
                        print(f"[notify] 发送失败: {error}")

    def export(self, job, payload):
        if payload["format"] == "m4b":
            return self.export_m4b(job, payload)
        ident = uid()
        relative = f"exports/{ident}.zip"
        target = self.store.file(relative)
        temporary = target.with_suffix(".part")
        self.update(job["id"], stage="打包音频", total=len(payload["chapters"]))
        book_row = (
            self.store.one("SELECT title,author,cover FROM books WHERE id=?", (job["book_id"],))
            if job["book_id"]
            else None
        )
        cover_path = None
        if book_row and book_row["cover"]:
            candidate = self.store.file(book_row["cover"])
            # FFmpeg cannot decode SVG artwork; embed bitmap covers only.
            if candidate.exists() and candidate.suffix.lower() != ".svg":
                cover_path = candidate
        embed = bool(payload.get("embed", True)) and payload["format"] == "mp3"
        try:
            with zipfile.ZipFile(temporary, "w", zipfile.ZIP_STORED) as archive:
                for i, chapter in enumerate(payload["chapters"]):
                    self.check(job["id"])
                    item = self.store.one("SELECT * FROM audio WHERE id=?", (chapter["audio_id"],))
                    if not item:
                        raise ValueError("选择的音频版本不存在")
                    path = self.store.file(item["path"]).with_suffix("." + payload["format"])
                    name = (
                        f"{chapter['position']:04d}_{audio.safe_name(chapter['title'])}.{payload['format']}"
                    )
                    if embed:
                        # ID3 tags (and the book cover) so player apps show
                        # proper book/chapter information after import.
                        tagged = self.store.file(f"tmp/{uid()}.mp3")
                        try:
                            audio.embed_metadata(
                                path,
                                tagged,
                                {
                                    "title": chapter["title"],
                                    "artist": book_row["author"] if book_row else "",
                                    "album": book_row["title"] if book_row else "",
                                    "track": str(chapter["position"]),
                                },
                                cover_path,
                            )
                            archive.write(tagged, name)
                        finally:
                            tagged.unlink(missing_ok=True)
                    else:
                        archive.write(path, name)
                    self.update(job["id"], done=i + 1)
                archive.writestr("manifest.json", json.dumps(payload, ensure_ascii=False, indent=2))
            self.check(job["id"])
            temporary.replace(target)
            self.store.execute(
                "INSERT INTO exports VALUES (?,?,?,?,?,?)",
                (ident, job["book_id"], relative, payload["format"], time.time(), len(payload["chapters"])),
            )
        finally:
            temporary.unlink(missing_ok=True)

    def export_m4b(self, job, payload):
        """One audiobook file with chapter navigation: chapter PCM is
        concatenated and encoded to AAC inside an .m4b container with chapter
        marks, book title/author and (when present) the cover embedded."""
        ident = uid()
        relative = f"exports/{ident}.m4b"
        target = self.store.file(relative)
        temporary = target.with_suffix(".part")
        list_file = self.store.file(f"tmp/{ident}.concat")
        meta_file = self.store.file(f"tmp/{ident}.meta")
        book_row = (
            self.store.one("SELECT title,author,cover FROM books WHERE id=?", (job["book_id"],))
            if job["book_id"]
            else None
        )
        cover = None
        if book_row and book_row["cover"]:
            candidate = self.store.file(book_row["cover"])
            # FFmpeg cannot decode SVG artwork; embed bitmap covers only.
            if candidate.exists() and candidate.suffix.lower() != ".svg":
                cover = candidate
        try:
            self.update(job["id"], stage="打包有声书", total=len(payload["chapters"]))
            entries, total, lines = [], 0.0, [";FFMETADATA1"]
            if book_row:
                lines.append("title=" + audio.ffmetadata_escape(book_row["title"]))
                if book_row["author"]:
                    lines.append("artist=" + audio.ffmetadata_escape(book_row["author"]))
            for chapter in payload["chapters"]:
                self.check(job["id"])
                item = self.store.one("SELECT * FROM audio WHERE id=?", (chapter["audio_id"],))
                if not item:
                    raise ValueError("选择的音频版本不存在")
                entries.append(self.store.file(item["path"]))
                lines += [
                    "[CHAPTER]",
                    "TIMEBASE=1/1000",
                    f"START={round(total * 1000)}",
                    f"END={round((total + item['duration']) * 1000)}",
                    "title=" + audio.ffmetadata_escape(chapter["title"]),
                ]
                total += item["duration"]
                self.update(job["id"], done=len(entries))
            # concat demuxer manifest; a literal quote inside a quoted name is
            # written as ' (close, backslash-escaped quote, reopen). LF line
            # endings: text() would translate to CRLF on Windows and pollute
            # FFMetadata chapter titles with trailing \r.
            def _concat_entry(path):
                quoted = path.as_posix().replace("'", "'\\''")
                return f"file '{quoted}'"

            list_file.write_text(
                "\n".join(_concat_entry(p) for p in entries) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            meta_file.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
            meta_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
            audio.build_m4b(list_file, meta_file, temporary, cover=cover, total_duration=total)
            temporary.replace(target)
            self.store.execute(
                "INSERT INTO exports VALUES (?,?,?,?,?,?)",
                (ident, job["book_id"], relative, "m4b", time.time(), len(payload["chapters"])),
            )
        finally:
            for leftover in (temporary, list_file, meta_file):
                leftover.unlink(missing_ok=True)
