"""Bounded TXT/EPUB import without executing HTML or extracting ZIP paths."""

import io
import posixpath
import re
import zipfile
from urllib.parse import unquote

from bs4 import BeautifulSoup
from defusedxml import ElementTree

TITLE = re.compile(
    r"^\s*((?:第[零一二三四五六七八九十百千万两〇\d]+[章回节卷]|chapter\s+\d+)[^\n]{0,100})\s*$",
    re.IGNORECASE | re.MULTILINE,
)
MAX_TEXT = 2_000_000


def segments(text):
    """Use paragraph/sentence boundaries, retain every source character in order."""
    pieces = []
    start = 0
    for match in re.finditer(r"[。！？!?；;\n]+", text):
        end = match.end()
        if end - start >= 100 or "\n" in match.group():
            pieces.append(text[start:end])
            start = end
    if start < len(text):
        pieces.append(text[start:])
    result = []
    for piece in pieces:
        # Hard upper bound only for an exceptionally long sentence.
        for offset in range(0, len(piece), 1200):
            value = piece[offset : offset + 1200]
            result.append(
                {
                    "text": value,
                    "voice": "",
                    "emotion": "neutral",
                    "speed": 1.0,
                    "pause": 250,
                    "speaker": "旁白",
                }
            )
    return result


def chapter_split(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    if len(text) > MAX_TEXT:
        raise ValueError("正文超过 200 万字，请拆分后导入")
    if not text.strip():
        raise ValueError("文件没有可朗读的正文")
    matches = list(TITLE.finditer(text))
    result = []
    if matches:
        if text[: matches[0].start()].strip():
            result.append({"title": "序言", "text": text[: matches[0].start()].strip()})
        for i, match in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            result.append({"title": match[1].strip(), "text": text[match.end() : end].strip()})
    else:
        # Unheaded long books still get manageable paragraph-aligned chapters.
        blocks, current, length = [], [], 0
        for paragraph in text.splitlines(keepends=True):
            if length + len(paragraph) > 6000 and current:
                blocks.append("".join(current).strip())
                current, length = [], 0
            current.append(paragraph)
            length += len(paragraph)
        if current:
            blocks.append("".join(current).strip())
        result = [
            {"title": "正文" if len(blocks) == 1 else f"第{i + 1}章", "text": b} for i, b in enumerate(blocks)
        ]
    if len(result) > 1000:
        raise ValueError("章节超过 1000 章，请分卷导入")
    return result


def parse(data, filename, encoding="auto"):
    if filename.lower().endswith(".txt"):
        candidates = [encoding] if encoding != "auto" else ["utf-8-sig", "gb18030", "utf-16"]
        if encoding not in ("auto", "utf-8-sig", "gb18030", "utf-16"):
            raise ValueError("不支持的编码")
        for codec in candidates:
            try:
                text = data.decode(codec, errors="strict")
                return chapter_split(text), codec
            except UnicodeError:
                continue
        raise ValueError("无法识别文本编码，请选择 UTF-8 或 GB18030 后重试")
    if not filename.lower().endswith(".epub"):
        raise ValueError("目前支持 TXT 和无 DRM 的 EPUB 文件")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            items = archive.infolist()
            if len(items) > 5000 or sum(i.file_size for i in items) > 200 * 1024 * 1024:
                raise ValueError("EPUB 解压内容超限")
            for item in items:
                if item.filename.startswith(("/", "\\")) or ".." in item.filename.replace("\\", "/").split(
                    "/"
                ):
                    raise ValueError("EPUB 包含不安全路径")
                # file_size is self-declared, but zipfile.read truncates to it,
                # so this bounds the BeautifulSoup parse of any single document.
                if item.file_size > 30 * 1024 * 1024:
                    raise ValueError("EPUB 单个资源超过 30MB，无法解析")
            if "META-INF/encryption.xml" in archive.namelist():
                raise ValueError("此 EPUB 包含加密资源，请使用无加密版本")
            container = ElementTree.fromstring(archive.read("META-INF/container.xml"))
            rootfile = next(e for e in container.iter() if e.tag.endswith("rootfile"))
            opf_path = rootfile.attrib["full-path"]
            opf = ElementTree.fromstring(archive.read(opf_path))
            manifest = {e.attrib["id"]: e.attrib for e in opf.iter() if e.tag.endswith("}item")}
            result = []
            for itemref in (e for e in opf.iter() if e.tag.endswith("}itemref")):
                item = manifest.get(itemref.attrib.get("idref"), {})
                if "nav" in item.get("properties", "").split() or itemref.attrib.get("linear") == "no":
                    continue
                href = unquote(item.get("href", "")).split("#")[0]
                path = posixpath.normpath(posixpath.join(posixpath.dirname(opf_path), href))
                soup = BeautifulSoup(archive.read(path), "html.parser")
                for node in soup(["script", "style", "nav", "head"]):
                    node.decompose()
                heading = soup.find(["h1", "h2", "h3"])
                title = heading.get_text(" ", strip=True) if heading else f"第{len(result) + 1}章"
                if heading:
                    heading.decompose()
                text = soup.get_text("\n", strip=True)
                if text.strip():
                    result.append({"title": title[:200], "text": text})
            if not result:
                raise ValueError("EPUB 中没有可读取的正文")
            if len(result) > 1000 or sum(len(c["text"]) for c in result) > MAX_TEXT:
                raise ValueError("书籍超过 1000 章或 200 万字，请分卷导入")
            return result, "epub"
    except (zipfile.BadZipFile, KeyError, StopIteration, ElementTree.ParseError) as exc:
        raise ValueError("EPUB 文件损坏或缺少有效目录") from exc


def source_text(data, filename):
    """Decode the original source with the same import rules, never as binary UTF-8."""
    if filename.lower().endswith(".txt"):
        _, codec = parse(data, filename)
        return data.decode(codec).replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    chapters, _ = parse(data, filename)
    return "\n\n".join(c["title"] + "\n" + c["text"] for c in chapters)


def director_segments(text):
    """Separate quoted speech and narrative without dropping or rewriting characters."""
    result = []
    for part in re.split(r'(“[^”]*”|「[^」]*」|『[^』]*』|"[^"\n]+")', text):
        if part:
            result.extend(segments(part))
    return result
