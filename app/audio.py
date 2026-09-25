"""Audio normalization, concatenation, and peak extraction using FFmpeg and PCM."""

import array
import os
import shutil
import subprocess
import sys
import wave
from pathlib import Path


def ffmpeg():
    explicit = os.environ.get("FFMPEG_PATH")
    if explicit:
        return explicit
    binary = shutil.which("ffmpeg")
    if binary:
        return binary
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError as exc:
        raise ValueError("未找到 FFmpeg，请安装或配置 FFMPEG_PATH；官方 Docker 构建已包含") from exc


def convert(source, destination, mp3=False, timeout=300):
    codec = ["-c:a", "libmp3lame", "-b:a", "192k"] if mp3 else ["-c:a", "pcm_s16le"]
    result = subprocess.run(
        [
            ffmpeg(),
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "24000",
            *codec,
            str(destination),
        ],
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode:
        raise ValueError("音频无法解码或转码失败，请检查输入音频与磁盘空间")


def metadata(path):
    with wave.open(str(path), "rb") as audio:
        frames = audio.getnframes()
        if (
            audio.getframerate() != 24000
            or audio.getnchannels() != 1
            or audio.getsampwidth() != 2
            or frames == 0
        ):
            raise ValueError("音频格式不正确或没有有效声音数据")
        # Normalize to at most 2400 peaks regardless of duration: 10-hour
        # chapters would otherwise produce millions of points in the DB and
        # in the metadata response.
        window = max(180, (frames + 2399) // 2400)
        size = max(1, (frames + window - 1) // window)
        peaks = []
        while raw := audio.readframes(size):
            values = array.array("h", raw)
            if sys.byteorder != "little":
                values.byteswap()
            peaks.append(round(max(abs(v) for v in values) / 32768, 4))
        return frames / 24000, peaks


def _fade_edges(raw: bytes, fade_frames: int = 120):
    """Apply a ~5ms linear fade to both ends of PCM data so segment junctions
    never click or pop."""
    values = array.array("h")
    values.frombytes(raw)
    fade = min(fade_frames, len(values) // 2)
    if fade <= 0:
        return raw
    for i in range(fade):
        factor = i / fade
        values[i] = int(values[i] * factor)
        values[len(values) - 1 - i] = int(values[len(values) - 1 - i] * factor)
    if sys.byteorder != "little":
        values.byteswap()
    return values.tobytes()


# The WAV container stores chunk sizes as unsigned 32-bit byte counts; past
# ~4 GiB the header silently overflows and every player sees a corrupt file.
# Cap at ~24.8 hours of studio PCM (24 kHz / 16-bit / mono) with headroom.
MAX_WAV_FRAMES = 2**31 - 65536


def _check_capacity(frames):
    if frames > MAX_WAV_FRAMES:
        raise ValueError("章节音频超过 WAV 容量上限（约 24 小时），请把章节拆短后重试")


def concatenate(paths, pauses, destination, fade_frames: int = 120):
    elapsed, timeline, written = 0.0, [], 0
    with wave.open(str(destination), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(24000)
        for i, (path, pause) in enumerate(zip(paths, pauses, strict=True)):
            start = elapsed
            with wave.open(str(path), "rb") as source:
                duration = source.getnframes() / source.getframerate()
                _check_capacity(written + source.getnframes())
                # Micro-fades at every segment edge keep junctions silent
                # instead of letting half-waves click against each other.
                out.writeframesraw(_fade_edges(source.readframes(source.getnframes()), fade_frames))
            written += source.getnframes()
            elapsed += duration
            if i < len(paths) - 1:
                silence = int(24000 * pause / 1000)
                _check_capacity(written + silence)
                out.writeframesraw(b"\0" * (silence * 2))
                written += silence
                elapsed += pause / 1000
            timeline.append({"index": i, "start": start, "end": elapsed})
    return timeline


def safe_name(value):
    return "".join(c if c.isalnum() or c in " _-" else "_" for c in value).strip(" .")[:100] or "章节"


def ffmetadata_escape(value):
    """Escape a string for an FFMetadata file: '=', ';', '#', '\\' and
    newlines are special and must be backslash-escaped; stray carriage
    returns become spaces (CRLF sources would otherwise leak into titles)."""
    out = []
    for c in str(value):
        if c in "=;#\\":
            out.append("\\" + c)
        elif c == "\n":
            out.append("\\n")
        elif c == "\r":
            out.append(" ")
        else:
            out.append(c)
    return "".join(out)


def build_m4b(list_path, meta_path, destination, cover=None, total_duration=0):
    """Concatenate same-format PCM chapter files into one AAC .m4b audiobook
    with chapter marks from the FFMetadata file, plus an optional embedded
    cover image. `timeout` scales with the book duration at the call site.
    All inputs come first, then every output option — ffmpeg attaches an
    option to the nearest FOLLOWING file, so output options placed before the
    cover input get misparsed as input options and the mux fails."""
    cover_path = Path(str(cover)) if cover else None
    cmd = [
        ffmpeg(), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "concat", "-safe", "0", "-i", str(list_path),
        "-i", str(meta_path),
    ]
    if cover_path:
        cmd += ["-i", str(cover_path)]
    cmd += ["-map", "0:a", "-map_metadata", "1"]
    if cover_path:
        cmd += [
            "-map", "2:v",
            "-c:v", "png" if cover_path.suffix.lower() == ".png" else "mjpeg",
            "-disposition:v", "attached_pic",
        ]
    cmd += [
        "-c:a", "aac", "-b:a", "96k", "-ac", "1", "-ar", "24000",
        "-f", "mp4", "-movflags", "+faststart", str(destination),
    ]
    result = subprocess.run(
        cmd, capture_output=True, timeout=max(600, int(total_duration * 2) + 300), check=False
    )
    produced = Path(destination)
    if result.returncode or not produced.exists() or produced.stat().st_size == 0:
        raise ValueError("M4B 有声书文件生成失败，请重试")


def atomic_audio(raw, destination):
    path = Path(destination)
    incoming = path.with_suffix(".input")
    temporary = path.with_suffix(".tmp.wav")
    try:
        incoming.write_bytes(raw)
        convert(incoming, temporary)
        metadata(temporary)
        temporary.replace(path)
    finally:
        incoming.unlink(missing_ok=True)
        temporary.unlink(missing_ok=True)


def splice_segment(source, destination, start, end, replacement, tail_silence=0.0):
    """Replace the [start, end] seconds of `source` with the audio of
    `replacement` (24 kHz mono wav) followed by `tail_silence` seconds of
    silence, and return the new total duration. `end` must span the ENTIRE
    old segment slot (speech + its trailing pause): replacing the speech but
    keeping the old pause would leave residual silence or overlap whenever
    the new pause differs. Both files must share the studio PCM format."""
    rate = 24000
    with wave.open(str(source), "rb") as src:
        if src.getframerate() != rate or src.getnchannels() != 1 or src.getsampwidth() != 2:
            raise ValueError("章节音频格式不正确，请重新生成本章")
        total_frames = src.getnframes()
        start_f = max(0, min(total_frames, round(start * rate)))
        end_f = max(start_f, min(total_frames, round(end * rate)))
        silence_frames = max(0, round(tail_silence * rate))
        with wave.open(str(replacement), "rb") as rep:
            if rep.getframerate() != rate or rep.getnchannels() != 1 or rep.getsampwidth() != 2:
                raise ValueError("片段音频格式不正确")
            rep_frames = rep.getnframes()
            _check_capacity(start_f + rep_frames + silence_frames + (total_frames - end_f))
            rep_raw = _fade_edges(rep.readframes(rep_frames), 120)
            with wave.open(str(destination), "wb") as out:
                out.setnchannels(1)
                out.setsampwidth(2)
                out.setframerate(rate)

                def copy(reader, frames):
                    left = frames
                    while left > 0:
                        chunk = reader.readframes(min(65536, left))
                        if not chunk:
                            break
                        out.writeframesraw(chunk)
                        left -= len(chunk) // 2

                src.setpos(0)
                copy(src, start_f)
                out.writeframesraw(rep_raw)
                if silence_frames:
                    out.writeframesraw(b"\0" * (silence_frames * 2))
                src.setpos(end_f)
                while True:
                    chunk = src.readframes(65536)
                    if not chunk:
                        break
                    out.writeframesraw(chunk)
    with wave.open(str(destination), "rb") as out:
        return out.getnframes() / rate


def embed_metadata(source, destination, meta, cover=None):
    """Copy an MP3 with ID3 tags (title/artist/album/track) and an optional
    embedded cover image attached."""
    cmd = [ffmpeg(), "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source)]
    if cover:
        cmd += ["-i", str(cover), "-map", "0:a", "-map", "1:v", "-disposition:s:v", "attached_pic"]
    cmd += ["-c:a", "copy", "-id3v2_version", "3"]
    for key, value in meta.items():
        cmd += ["-metadata", f"{key}={value}"]
    if cover:
        cmd += ["-metadata:s:v", "title=Album cover", "-metadata:s:v", "comment=Cover (front)"]
    cmd += [str(destination)]
    result = subprocess.run(cmd, capture_output=True, timeout=120, check=False)
    if result.returncode or not Path(destination).exists():
        raise ValueError("元数据写入失败，请重试导出")


try:
    import audioop

    def _pcm_rms(raw):
        return audioop.rms(raw, 2)

    def _pcm_mul(raw, factor):
        return audioop.mul(raw, 2, factor)

    def _pcm_max(raw):
        return audioop.max(raw, 2)

except ImportError:  # Python 3.13 removed audioop
    import math
    import struct

    def _pcm_rms(raw):
        count = len(raw) // 2
        if not count:
            return 0
        acc = sum(v * v for v, in struct.iter_unpack("<h", raw))
        return int(math.sqrt(acc / count))

    def _pcm_mul(raw, factor):
        return b"".join(
            struct.pack("<h", max(-32768, min(32767, int(v * factor))))
            for v, in struct.iter_unpack("<h", raw)
        )

    def _pcm_max(raw):
        return max((abs(v) for v, in struct.iter_unpack("<h", raw)), default=0)


def normalize_loudness(path, target_rms=3300, max_gain=2.5):
    """Scale a segment's PCM toward a shared RMS target so different voices,
    emotions and providers land at a similar perceived loudness. The gain is
    peak-limited to avoid clipping; pure silence is left untouched."""
    with wave.open(str(path), "rb") as w:
        raw = w.readframes(w.getnframes())
    if not raw:
        return
    rms = _pcm_rms(raw)
    if rms < 1:
        return
    factor = max(0.25, min(max_gain, target_rms / rms))
    peak = _pcm_max(raw) or 1
    factor = min(factor, 32000 / peak)
    if abs(factor - 1.0) < 0.02:
        return
    normalized = _pcm_mul(raw, factor)
    with wave.open(str(path), "rb") as w:
        params = w.getparams()
    temporary = path.with_name(path.name + ".norm")
    with wave.open(str(temporary), "wb") as out:
        out.setnchannels(params.nchannels)
        out.setsampwidth(params.sampwidth)
        out.setframerate(params.framerate)
        out.writeframes(normalized)
    temporary.replace(path)
