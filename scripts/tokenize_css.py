"""One-shot: tokenize hardcoded oklch colors and add the light theme."""
import re
from collections import Counter
from pathlib import Path

path = Path("frontend/src/style.css")
css = path.read_text(encoding="utf-8")

M = {
    "oklch(0.15 0.006 110)":        ("--bg",             "oklch(0.15 0.006 110)",   "oklch(0.972 0.009 110)"),
    "oklch(0.195 0.008 110)":       ("--panel",          "oklch(0.195 0.008 110)",  "oklch(0.947 0.011 110)"),
    "oklch(0.235 0.01 110)":        ("--raised",         "oklch(0.235 0.01 110)",   "oklch(0.916 0.013 110)"),
    "oklch(0.32 0.009 110)":        ("--line",           "oklch(0.32 0.009 110)",   "oklch(0.868 0.016 110)"),
    "oklch(0.74 0.014 110)":        ("--muted",          "oklch(0.74 0.014 110)",   "oklch(0.42 0.022 110)"),
    "oklch(0.95 0.008 110)":        ("--text",           "oklch(0.95 0.008 110)",   "oklch(0.24 0.018 110)"),
    "oklch(0.205 0.009 110)":       ("--button-bg",      "oklch(0.205 0.009 110)",  "oklch(0.94 0.012 110)"),
    "oklch(0.28 0.025 110)":        ("--active-bg",      "oklch(0.28 0.025 110)",   "oklch(0.893 0.032 110)"),
    "oklch(0.29 0.025 110)":        ("--hover-bg",       "oklch(0.29 0.025 110)",   "oklch(0.9 0.028 110)"),
    "oklch(0.32 0.024 110)":        ("--line-soft",      "oklch(0.32 0.024 110)",   "oklch(0.84 0.022 110)"),
    "oklch(0.36 0.01 110)":         ("--track",          "oklch(0.36 0.01 110)",    "oklch(0.862 0.018 110)"),
    "oklch(0.42 0.01 110)":         ("--scroll",         "oklch(0.42 0.01 110)",    "oklch(0.72 0.02 110)"),
    "oklch(0.55 0.012 110)":        ("--scroll-hover",   "oklch(0.55 0.012 110)",   "oklch(0.6 0.024 110)"),
    "oklch(0.21 0.012 110 / 0.55)": ("--wave-bg",        "oklch(0.21 0.012 110 / 0.55)", "oklch(0.9 0.02 110 / 0.7)"),
    "oklch(0.16 0.01 110 / 0.85)":  ("--overlay-strong", "oklch(0.16 0.01 110 / 0.85)",  "oklch(0.972 0.009 110 / 0.92)"),
    "oklch(0.91 0.13 110)":         ("--lime",           "oklch(0.91 0.13 110)",    "oklch(0.83 0.15 110)"),
    "oklch(0.91 0.13 110 / 0.1)":   ("--lime-tint",      "oklch(0.91 0.13 110 / 0.1)", "oklch(0.55 0.14 110 / 0.12)"),
    "oklch(0.21 0.018 110)":        ("--on-lime",        "oklch(0.21 0.018 110)",   "oklch(0.25 0.03 110)"),
    "oklch(0.95 0.1 110)":          ("--lime-hover",     "oklch(0.95 0.1 110)",     "oklch(0.88 0.16 110)"),
    "oklch(0.95 0.15 110)":         ("--lime-strong",    "oklch(0.95 0.15 110)",    "oklch(0.72 0.16 110)"),
    "oklch(0.32 0.048 110)":        ("--lime-dim",       "oklch(0.32 0.048 110)",   "oklch(0.9 0.07 110)"),
    "oklch(0.5 0.08 110 / 0.4)":    ("--lime-line-a",    "oklch(0.5 0.08 110 / 0.4)", "oklch(0.5 0.13 110 / 0.4)"),
    "oklch(0.5 0.08 110 / 0.5)":    ("--lime-line-b",    "oklch(0.5 0.08 110 / 0.5)", "oklch(0.5 0.13 110 / 0.55)"),
    "oklch(0.27 0.04 110 / 0.4)":   ("--lime-active-a",  "oklch(0.27 0.04 110 / 0.4)", "oklch(0.88 0.07 110 / 0.6)"),
    "oklch(0.27 0.04 110 / 0.45)":  ("--lime-active-b",  "oklch(0.27 0.04 110 / 0.45)", "oklch(0.88 0.07 110 / 0.75)"),
    "oklch(0.77 0.1 175)":          ("--mint",           "oklch(0.77 0.1 175)",     "oklch(0.55 0.11 175)"),
    "oklch(0.5 0.08 175 / 0.6)":    ("--mint-glow",      "oklch(0.5 0.08 175 / 0.6)", "oklch(0.55 0.11 175 / 0.3)"),
    "oklch(0.82 0.12 75)":          ("--warn",           "oklch(0.82 0.12 75)",     "oklch(0.55 0.13 75)"),
    "oklch(0.27 0.04 75 / 0.4)":    ("--warn-bg",        "oklch(0.27 0.04 75 / 0.4)", "oklch(0.93 0.08 75 / 0.55)"),
    "oklch(0.5 0.08 75 / 0.5)":     ("--warn-glow",      "oklch(0.5 0.08 75 / 0.5)", "oklch(0.55 0.13 75 / 0.3)"),
    "oklch(0.78 0.12 25)":          ("--red",            "oklch(0.78 0.12 25)",     "oklch(0.55 0.19 25)"),
    "oklch(0.23 0.035 25)":         ("--danger-bg",      "oklch(0.23 0.035 25)",    "oklch(0.955 0.02 25)"),
    "oklch(0.27 0.04 25 / 0.45)":   ("--danger-dim",     "oklch(0.27 0.04 25 / 0.45)", "oklch(0.92 0.055 25 / 0.6)"),
    "oklch(0.27 0.04 25 / 0.5)":    ("--danger-dim",     "oklch(0.27 0.04 25 / 0.5)",  "oklch(0.92 0.055 25 / 0.65)"),
    "oklch(0.3 0.065 25)":          ("--danger-hover",   "oklch(0.3 0.065 25)",     "oklch(0.9 0.06 25)"),
    "oklch(0.43 0.065 25)":         ("--danger-line",    "oklch(0.43 0.065 25)",    "oklch(0.83 0.1 25)"),
    "oklch(0.45 0.08 25 / 0.5)":    ("--danger-glow",    "oklch(0.45 0.08 25 / 0.5)", "oklch(0.55 0.19 25 / 0.3)"),
    "oklch(0.45 0.08 25 / 0.6)":    ("--danger-glow-2",  "oklch(0.45 0.08 25 / 0.6)", "oklch(0.55 0.19 25 / 0.4)"),
}

for literal, (token, _d, _l) in M.items():
    css = css.replace(literal, f"var({token})")

# var(--lime) as text/border sits on the page background — the light theme
# needs the darker ink variant there; fill usages keep --lime.
css = css.replace("color: var(--lime)", "color: var(--lime-ink)")

DARK = {
    "--text": "oklch(0.95 0.008 110)",
    "--button-bg": "oklch(0.205 0.009 110)",
    "--active-bg": "oklch(0.28 0.025 110)",
    "--hover-bg": "oklch(0.29 0.025 110)",
    "--line-soft": "oklch(0.32 0.024 110)",
    "--track": "oklch(0.36 0.01 110)",
    "--scroll": "oklch(0.42 0.01 110)",
    "--scroll-hover": "oklch(0.55 0.012 110)",
    "--wave-bg": "oklch(0.21 0.012 110 / 0.55)",
    "--overlay-strong": "oklch(0.16 0.01 110 / 0.85)",
    "--on-lime": "oklch(0.21 0.018 110)",
    "--lime-ink": "oklch(0.91 0.13 110)",
    "--lime-hover": "oklch(0.95 0.1 110)",
    "--lime-strong": "oklch(0.95 0.15 110)",
    "--lime-tint": "oklch(0.91 0.13 110 / 0.1)",
    "--lime-dim": "oklch(0.32 0.048 110)",
    "--lime-line-a": "oklch(0.5 0.08 110 / 0.4)",
    "--lime-line-b": "oklch(0.5 0.08 110 / 0.5)",
    "--lime-active-a": "oklch(0.27 0.04 110 / 0.4)",
    "--lime-active-b": "oklch(0.27 0.04 110 / 0.45)",
    "--mint-glow": "oklch(0.5 0.08 175 / 0.6)",
    "--warn-bg": "oklch(0.27 0.04 75 / 0.4)",
    "--warn-glow": "oklch(0.5 0.08 75 / 0.5)",
    "--danger-bg": "oklch(0.23 0.035 25)",
    "--danger-dim": "oklch(0.27 0.04 25 / 0.5)",
    "--danger-hover": "oklch(0.3 0.065 25)",
    "--danger-line": "oklch(0.43 0.065 25)",
    "--danger-glow": "oklch(0.45 0.08 25 / 0.5)",
    "--danger-glow-2": "oklch(0.45 0.08 25 / 0.6)",
}
LIGHT = {
    "--text": "oklch(0.24 0.018 110)",
    "--button-bg": "oklch(0.94 0.012 110)",
    "--active-bg": "oklch(0.893 0.032 110)",
    "--hover-bg": "oklch(0.9 0.028 110)",
    "--line-soft": "oklch(0.84 0.022 110)",
    "--track": "oklch(0.862 0.018 110)",
    "--scroll": "oklch(0.72 0.02 110)",
    "--scroll-hover": "oklch(0.6 0.024 110)",
    "--wave-bg": "oklch(0.9 0.02 110 / 0.7)",
    "--overlay-strong": "oklch(0.972 0.009 110 / 0.92)",
    "--on-lime": "oklch(0.25 0.03 110)",
    "--lime-ink": "oklch(0.48 0.13 110)",
    "--lime-hover": "oklch(0.88 0.16 110)",
    "--lime-strong": "oklch(0.72 0.16 110)",
    "--lime-tint": "oklch(0.55 0.14 110 / 0.12)",
    "--lime-dim": "oklch(0.9 0.07 110)",
    "--lime-line-a": "oklch(0.5 0.13 110 / 0.4)",
    "--lime-line-b": "oklch(0.5 0.13 110 / 0.55)",
    "--lime-active-a": "oklch(0.88 0.07 110 / 0.6)",
    "--lime-active-b": "oklch(0.88 0.07 110 / 0.75)",
    "--mint-glow": "oklch(0.55 0.11 175 / 0.3)",
    "--warn-bg": "oklch(0.93 0.08 75 / 0.55)",
    "--warn-glow": "oklch(0.55 0.13 75 / 0.3)",
    "--danger-bg": "oklch(0.955 0.02 25)",
    "--danger-dim": "oklch(0.92 0.055 25 / 0.65)",
    "--danger-hover": "oklch(0.9 0.06 25)",
    "--danger-line": "oklch(0.83 0.1 25)",
    "--danger-glow": "oklch(0.55 0.19 25 / 0.3)",
    "--danger-glow-2": "oklch(0.55 0.19 25 / 0.4)",
}

def block(values):
    return "\n".join(f"  {k}: {v};" for k, v in values.items())

new_root = """:root {
  font-family: "PingFang SC", "Microsoft YaHei", system-ui, sans-serif;
  color: var(--text);
  background: var(--bg);
  font-synthesis: none;
  color-scheme: dark;
""" + block(DARK) + """
  --bg: oklch(0.15 0.006 110);
  --panel: oklch(0.195 0.008 110);
  --raised: oklch(0.235 0.01 110);
  --line: oklch(0.32 0.009 110);
  --muted: oklch(0.74 0.014 110);
  --lime: oklch(0.91 0.13 110);
  --mint: oklch(0.77 0.1 175);
  --warn: oklch(0.82 0.12 75);
  --red: oklch(0.78 0.12 25);
}
:root[data-theme="light"] {
  color-scheme: light;
""" + block(LIGHT) + """
  --bg: oklch(0.972 0.009 110);
  --panel: oklch(0.947 0.011 110);
  --raised: oklch(0.916 0.013 110);
  --line: oklch(0.868 0.016 110);
  --muted: oklch(0.42 0.022 110);
  --lime: oklch(0.83 0.15 110);
  --mint: oklch(0.55 0.11 175);
  --warn: oklch(0.55 0.13 75);
  --red: oklch(0.55 0.19 25);
}"""

css = re.compile(r":root \{[^}]*\}", re.S).sub(new_root, css, count=1)
path.write_text(css, encoding="utf-8")
print("remaining raw oklch:", Counter(re.findall(r"oklch\([0-9. /]+\)", css)).most_common())
