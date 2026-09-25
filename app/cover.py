"""Generated cover artwork: an SVG book cover drawn from AI-suggested
palette and mood. Pure string rendering — no image libraries — served
directly as an <img> source by the cover endpoint."""

import re
from xml.sax.saxutils import escape

# escape() keeps quotes intact by default; every attribute position needs
# them escaped or a title containing '"' could inject attributes.
_ATTR = {'"': "&quot;"}


def _attr(value: str) -> str:
    return escape(value, _ATTR)


def _wrap_title(title: str, per_line: int = 8, max_lines: int = 3):
    clean = " ".join(title.split())
    lines = [clean[i : i + per_line] for i in range(0, min(len(clean), per_line * max_lines), per_line)]
    if len(clean) > per_line * max_lines:
        lines[-1] = lines[-1][:-1] + "…"
    return lines or ["未命名"]


def render_cover_svg(title: str, author: str, palette: list[str], mood: str = "") -> str:
    """A 2:3 cover: deep gradient wash, the 声页 sound-bars motif, the title
    in a serif stack and the author line. `palette` is [base, deep, accent];
    tokens are re-validated here so the renderer is safe on its own."""
    safe_palette = ["#" + c.lstrip("#").lower() for c in palette if re.fullmatch(r"#?[0-9a-fA-F]{6}", str(c))]
    base, deep, accent = (safe_palette + ["#22302b", "#101820", "#8fd3b6"])[:3]
    lines = _wrap_title(title)
    title_spans = "".join(
        f'<text x="64" y="{300 + i * 84}" class="t">{escape(line)}</text>'
        for i, line in enumerate(lines)
    )
    bars = "".join(
        f'<rect x="{64 + i * 26}" y="{760 - hgt}" width="10" height="{hgt}" rx="5" fill="{accent}" opacity="{0.55 + 0.15 * (i % 3)}"/>'
        for i, hgt in enumerate((46, 90, 64, 108, 58))
    )
    mood_text = (
        f'<text x="64" y="848" class="m">{escape(mood)}</text>' if mood else ""
    )
    author_text = (
        f'<text x="64" y="196" class="a">{escape(author)}</text>' if author else ""
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="600" height="900" '
        f'viewBox="0 0 600 900" role="img" aria-label="{_attr(title)} 封面">'
        f"<defs>"
        f'<linearGradient id="g" x1="0" y1="0" x2="1" y2="1.2">'
        f'<stop offset="0" stop-color="{base}"/><stop offset="1" stop-color="{deep}"/>'
        f"</linearGradient>"
        f"</defs>"
        f'<rect width="600" height="900" fill="url(#g)"/>'
        f'<circle cx="520" cy="120" r="150" fill="{accent}" opacity="0.14"/>'
        f'<circle cx="90" cy="820" r="190" fill="{accent}" opacity="0.10"/>'
        f'<style>.t{{font:600 58px "Songti SC","STSong","SimSun",serif;fill:#f6f7f2}}'
        f".a{{font:24px \"PingFang SC\",\"Microsoft YaHei\",sans-serif;fill:#f6f7f2;opacity:0.82}} "
        f'.m{{font:20px "PingFang SC","Microsoft YaHei",sans-serif;fill:#f6f7f2;opacity:0.6}}'
        f"</style>"
        f"{author_text}{title_spans}{bars}{mood_text}"
        f"</svg>"
    )
