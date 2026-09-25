# -*- coding: utf-8 -*-
"""声页 (Soundleaf) 图标生成脚本。

- 圆角外形取自 G:\下载文件\icon_template.svg 的平滑 squircle 路径（64 viewBox）。
- 背景白色 + 0.5 宽 8% 黑描边（模板蒙版内，只显示贴边内半侧）。
- 颜色由前端语义令牌 oklch 换算为 sRGB，浅色背景用 lime-ink / mint 深色墨。
- 输出 256x256 PNG（<100KB）与 SVG 源文件，另拼一张总览图。
"""
import io
import re
import struct
import zlib
from pathlib import Path

import resvg_py
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).parent
TEMPLATE = Path(r"G:\下载文件\icon_template.svg")

SQ = re.search(r'\bd="([^"]+)"', TEMPLATE.read_text(encoding="utf-8")).group(1)


# ---------- oklch -> sRGB ----------
def oklch_hex(L, C, H, alpha=None):
    h = __import__("math").radians(H)
    a, b = C * __import__("math").cos(h), C * __import__("math").sin(h)
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b
    l_, m_, s_ = l_**3, m_**3, s_**3
    r = +4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_
    g = -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_
    bb = -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_
    def enc(c):
        c = min(1.0, max(0.0, c))
        return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
    rgb = "".join(f"{round(enc(v) * 255):02X}" for v in (r, g, bb))
    return f"#{rgb}" + ("" if alpha is None else f'" fill-opacity="{alpha}' if False else "") , rgb


def oklch(L, C, H):
    _, rgb = oklch_hex(L, C, H)
    return "#" + rgb


INK = oklch(0.45, 0.13, 110)      # 亮色主题 --lime-ink 深墨绿（白底主色）
LIME = oklch(0.72, 0.16, 110)     # --lime-strong 亮黄绿（白底填充用）
MINT = oklch(0.46, 0.11, 175)     # 亮色主题 --mint 深青（音轨/选中）
MINT_BRIGHT = oklch(0.77, 0.10, 175)  # 暗色主题 --mint，仅作小点缀

SVG_TMPL = """<svg width="256" height="256" viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg">
<mask id="mask_{mid}" style="mask-type:alpha" maskUnits="userSpaceOnUse" x="0" y="0" width="64" height="64">
<path d="{sq}" fill="#fff"/>
</mask>
<g mask="url(#mask_{mid})">
<path d="{sq}" fill="#FFFFFF"/>
<path d="{sq}" fill="none" stroke="#000000" stroke-opacity="0.08" stroke-width="0.5"/>
{art}
</g>
</svg>
"""


def svg(mid, art):
    return SVG_TMPL.format(mid=mid, sq=SQ, art=art)


def render(name, art):
    s = svg(name, art)
    (ROOT / f"{name}.svg").write_text(s, encoding="utf-8")
    png = bytes(resvg_py.svg_to_bytes(svg_string=s, width=256, height=256))
    (ROOT / f"{name}.png").write_bytes(png)
    return len(png)


# ---------- 通用图元 ----------
def bars(items, color, w, opacity=None):
    op = f' stroke-opacity="{opacity}"' if opacity else ""
    return "".join(
        f'<line x1="{x}" y1="{y1}" x2="{x}" y2="{y2}" stroke="{color}" stroke-width="{w}" stroke-linecap="round"{op}/>'
        for x, y1, y2 in items
    )


def hlines(items, color, w, opacity=None):
    op = f' stroke-opacity="{opacity}"' if opacity else ""
    return "".join(
        f'<line x1="{x1}" y1="{y}" x2="{x2}" y2="{y}" stroke="{color}" stroke-width="{w}" stroke-linecap="round"{op}/>'
        for x1, x2, y in items
    )


ICONS = {}

# 1) 应用主图标：三条高低不同的声音竖线 + 开启的书（合页关系）
ICONS["icon-app"] = f'''
<path d="M14 41.6 C21.5 41.6 27.5 43 32 46.2 C36.5 43 42.5 41.6 50 41.6 L50 47.2 C42.5 47.2 36.5 48.4 32 51.8 C27.5 48.4 21.5 47.2 14 47.2 Z" fill="{INK}" fill-opacity="0.12" stroke="{INK}" stroke-width="2.4" stroke-linejoin="round"/>
{bars([(23.5, 24.5, 35), (32, 17, 42.8), (40.5, 21.5, 38)], INK, 4.2)}
<circle cx="47" cy="13.2" r="2.7" fill="{MINT}"/>
'''

# 2) 导入小说：文档 + 文本行 + 导入箭头徽标
ICONS["icon-import"] = f'''
<rect x="17.5" y="11.5" width="27" height="33" rx="4" fill="{INK}" fill-opacity="0.1" stroke="{INK}" stroke-width="2.6"/>
{hlines([(23, 38, 19.5), (23, 35.5, 25.5), (23, 38.5, 31.5)], INK, 2.6, 0.42)}
{hlines([(23, 31, 37.5)], MINT, 2.6)}
<circle cx="42.5" cy="43" r="9.5" fill="{INK}" stroke="#FFFFFF" stroke-width="2.2"/>
<line x1="42.5" y1="38.6" x2="42.5" y2="46.4" stroke="#FFFFFF" stroke-width="3" stroke-linecap="round"/>
<path d="M38.9 43.1 L42.5 46.9 L46.1 43.1" stroke="#FFFFFF" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
'''

# 3) 多角色配音：两张交叠的声纹卡（黄绿旁白 + 青色角色）
ICONS["icon-voices"] = f'''
<rect x="11" y="14" width="28.5" height="20" rx="6.5" fill="{INK}" fill-opacity="0.12" stroke="{INK}" stroke-width="2.6"/>
{bars([(18, 21.5, 27.5), (23.5, 19.5, 29.5), (29, 21, 28)], INK, 2.7)}
<rect x="27.5" y="32" width="25.5" height="17.5" rx="6.5" fill="#FFFFFF" stroke="{MINT}" stroke-width="2.6"/>
{bars([(34.5, 39.5, 43.5), (39.5, 38, 45), (44.5, 40, 43)], MINT, 2.5)}
'''

# 4) 试听：播放圆钮 + 青色声波竖线
ICONS["icon-preview"] = f'''
<circle cx="24" cy="32" r="13.5" fill="{INK}"/>
<path d="M21.2 26.4 L21.2 37.6 L31.2 32 Z" fill="#FFFFFF" stroke="#FFFFFF" stroke-width="2.4" stroke-linejoin="round"/>
{bars([(43.5, 24, 40), (50, 19.5, 44.5), (56.5, 26.5, 37.5)], MINT, 3.4)}
'''

# 5) 片段修正：音轨上选中片段（青色选中 = 音轨强调色）
_fix_h = [9, 15, 21, 14, 25, 19, 26, 16, 22, 13, 8]
_fix_all = bars([(13 + i * 3.9, 32 - h / 2, 32 + h / 2) for i, h in enumerate(_fix_h)], INK, 2.5, 0.34)
_fix_sel = bars([(13 + 5 * 3.9, 32 - 19 / 2, 32 + 19 / 2), (13 + 6 * 3.9, 32 - 26 / 2, 32 + 26 / 2)], MINT, 2.5)
ICONS["icon-fix"] = f'''
{_fix_all}
<rect x="29.7" y="15.5" width="13" height="33" rx="4.5" fill="{MINT}" fill-opacity="0.1" stroke="{MINT}" stroke-width="2.4"/>
{_fix_sel}
'''

# 6) 导出音频：波形文件卡 + 下载箭头 + 托盘
ICONS["icon-export"] = f'''
<rect x="16.5" y="11" width="31" height="21" rx="5.5" fill="{INK}" fill-opacity="0.12" stroke="{INK}" stroke-width="2.6"/>
{bars([(23, 17.5, 25.5), (28, 15, 28), (38, 16, 27), (43, 18, 25)], INK, 2.4, 0.45)}
{bars([(33, 13, 30)], MINT, 2.4)}
<line x1="32" y1="37.5" x2="32" y2="50.5" stroke="{INK}" stroke-width="3.6" stroke-linecap="round"/>
<path d="M25.9 44.4 L32 50.8 L38.1 44.4" stroke="{INK}" stroke-width="3.6" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
<line x1="20.5" y1="56.5" x2="43.5" y2="56.5" stroke="{INK}" stroke-width="3.2" stroke-linecap="round" stroke-opacity="0.55"/>
'''

sizes = {}
for name, art in ICONS.items():
    sizes[name] = render(name, art)

# ---------- 总览拼图 ----------
LABELS = {
    "icon-app": "主图标 · 声页",
    "icon-import": "导入小说",
    "icon-voices": "多角色配音",
    "icon-preview": "试听播放",
    "icon-fix": "片段修正",
    "icon-export": "导出音频",
}
CELL, PAD, LABEL_H = 256, 36, 44
COLS, ROWS = 3, 2
sheet = Image.new("RGBA", (COLS * (CELL + PAD) + PAD, ROWS * (CELL + LABEL_H + PAD) + PAD), (243, 244, 240, 255))
draw = ImageDraw.Draw(sheet)
try:
    font = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 20)
except OSError:
    font = ImageFont.load_default()
for i, (name, art) in enumerate(ICONS.items()):
    img = Image.open(io.BytesIO((ROOT / f"{name}.png").read_bytes()))
    cx = PAD + (i % COLS) * (CELL + PAD)
    cy = PAD + (i // COLS) * (CELL + LABEL_H + PAD)
    sheet.paste(img, (cx, cy), img)
    label = LABELS[name]
    tw = draw.textlength(label, font=font)
    draw.text((cx + (CELL - tw) / 2, cy + CELL + 10), label, fill=(60, 64, 50), font=font)
sheet.convert("RGB").save(ROOT / "icons-preview.png")
sheet.convert("RGB").save(ROOT / "icons-preview.jpg", quality=90)

for name, sz in sizes.items():
    png_kb = (ROOT / f"{name}.png").stat().st_size / 1024
    print(f"{name}: png {png_kb:.1f} KB, svg {(ROOT / f'{name}.svg').stat().st_size / 1024:.1f} KB, rendered {sz} B")
print("colors:", dict(INK=INK, LIME=LIME, MINT=MINT, MINT_BRIGHT=MINT_BRIGHT))
