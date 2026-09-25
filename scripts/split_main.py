"""One-shot structural split of frontend/src/main.tsx into modules."""
import re
from pathlib import Path

src = Path("frontend/src/main.tsx")
text = src.read_text(encoding="utf-8")
lines = text.splitlines(keep_annotations := False)

LUCIDE = [
    "BookOpen", "Upload", "ListMusic", "Clapperboard", "AudioLines", "ListTodo",
    "Headphones", "Download", "Settings", "Play", "Pause", "SkipBack",
    "SkipForward", "Volume2", "Search", "Plus", "ArrowUpRight", "ChevronRight",
    "Check", "X", "LoaderCircle", "RotateCcw", "Heart", "Menu", "LogOut",
    "Folder", "Mic2", "Save", "ArrowUp", "ArrowDown", "Scissors", "Merge",
    "Trash2", "CircleAlert", "Sparkles", "Sun", "Moon",
]
UI = ["Button", "Cover", "Badge", "Logo", "Heading", "Empty", "Wave"]
CONSTANTS = ["navItems", "emotions", "statusText", "formatTime", "baseSegment", "collectSpeakers"]
API = ["api", "Segment", "Chapter", "Book", "Voice", "AudioMeta", "ChapterDetail", "Common"]


def find(pattern):
    for i, line in enumerate(lines):
        if re.match(pattern, line):
            return i
    raise SystemExit(f"boundary not found: {pattern}")


def block(start_pat, end_pat):
    a = find(start_pat)
    b = find(end_pat)
    return "\n".join(lines[a:b]).rstrip() + "\n"


def used(chunk, names):
    return [n for n in names if re.search(rf"\b{re.escape(n)}\b", chunk)]


def make_module(chunk, path, export_name=None, rel=""):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    if export_name:
        chunk = re.sub(rf"^function {export_name}\(", f"export function {export_name}(", chunk, count=1, flags=re.M)
    head = []
    react_hooks = used(chunk, ["useState", "useEffect", "useRef", "useMemo", "useCallback"])
    if react_hooks or "ReactNode" in chunk or re.search(r"\bReact\.", chunk):
        parts = []
        if "ReactNode" in chunk:
            parts.append("type ReactNode")
        head.append(f'import {{ {", ".join(react_hooks + parts)} }} from "react";')
    icons = used(chunk, LUCIDE)
    if icons:
        head.append('import {\n  ' + ",\n  ".join(icons) + ',\n} from "lucide-react";')
    if re.search(r"\bSelect\b", chunk):
        head.append(f'import {{ Select }} from "{rel}components/Select";')
    ui_used = used(chunk, [u for u in UI if not (export_name and u == export_name)])
    if ui_used:
        head.append(f'import {{ {", ".join(sorted(ui_used))} }} from "{rel}components/ui";')
    const_used = used(chunk, CONSTANTS)
    if const_used:
        head.append(f'import {{ {", ".join(sorted(const_used))} }} from "{rel}constants";')
    api_used = used(chunk, [a for a in API if a != "Common"])
    if api_used:
        head.append(f'import {{ {", ".join(sorted(api_used))} }} from "{rel}api";')
    if re.search(r"\bCommon\b", chunk):
        head.append(f'import type {{ Common }} from "{rel}api";')
    out = "\n".join(head) + "\n\n" + chunk
    Path(path).write_text(out, encoding="utf-8")
    print(f"{path}: {len(out.splitlines())} lines")


# ---- api.ts ----
api_body = block(r"^type Segment", r"^const navItems") + "\n\n" + block(r"^async function api", r"^function Button")
common_type = block(r"^type Common", r"^function Library")
Path("frontend/src/api.ts").write_text(api_body + "\n" + common_type, encoding="utf-8")
print("frontend/src/api.ts written")

# ---- constants.ts ----
const_body = block(r"^const navItems", r"^async function api")
icons = used(const_body, LUCIDE)
head = 'import {\n  ' + ",\n  ".join(icons) + ',\n} from "lucide-react";\n' + 'import type { Segment, ChapterDetail } from "./api";\n\n'
Path("frontend/src/constants.ts").write_text(head + const_body, encoding="utf-8")
print("frontend/src/constants.ts written")

# ---- components/ui.tsx ----
ui_body = block(r"^function Button", r"^function App")
make_module(ui_body, "frontend/src/components/ui.tsx")

# ---- pages ----
make_module(block(r"^function Library", r"^function ImportPage"), "frontend/src/pages/Library.tsx", "Library", "../")
make_module(block(r"^function ImportPage", r"^function ChapterSplitPreview"), "frontend/src/pages/Import.tsx", "ImportPage", "../")
chapters = block(r"^function ChapterSplitPreview", r"^function Director")
chapters = re.sub(r"^function ChaptersPage\(", "export function ChaptersPage(", chapters, count=1, flags=re.M)
head_lines = []
react_hooks = used(chapters, ["useState", "useEffect", "useRef"])
head_lines.append(f'import {{ {", ".join(react_hooks)} }} from "react";')
icons = used(chapters, LUCIDE)
if icons:
    head_lines.append('import {\n  ' + ",\n  ".join(icons) + ',\n} from "lucide-react";')
used_ui = used(chapters, UI)
if used_ui:
    head_lines.append(f'import {{ {", ".join(sorted(used_ui))} }} from "../components/ui";')
used_const = used(chapters, CONSTANTS)
if used_const:
    head_lines.append(f'import {{ {", ".join(sorted(used_const))} }} from "../constants";')
used_api = used(chapters, [a for a in API if a != "Common"])
if used_api:
    head_lines.append(f'import {{ {", ".join(sorted(used_api))} }} from "../api";')
head_lines.append('import type { Common } from "../api";')
Path("frontend/src/pages/Chapters.tsx").parent.mkdir(parents=True, exist_ok=True)
Path("frontend/src/pages/Chapters.tsx").write_text("\n".join(head_lines) + "\n\n" + chapters, encoding="utf-8")
print("frontend/src/pages/Chapters.tsx written")
make_module(block(r"^function Director", r"^function Voices"), "frontend/src/pages/Director.tsx", "Director", "../")
make_module(block(r"^function Voices", r"^function Jobs"), "frontend/src/pages/Voices.tsx", "Voices", "../")
make_module(block(r"^function Jobs", r"^function Listen"), "frontend/src/pages/Queue.tsx", "Jobs", "../")
make_module(block(r"^function Listen", r"^function ExportPage"), "frontend/src/pages/Listen.tsx", "Listen", "../")
make_module(block(r"^function ExportPage", r"^function SettingsPage"), "frontend/src/pages/Export.tsx", "ExportPage", "../")
make_module(block(r"^function SettingsPage", r"^type Common"), "frontend/src/pages/Settings.tsx", "SettingsPage", "../")

# ---- new main.tsx ----
app_body = block(r"^function App", r"^type Common")
main_icons = used(app_body, LUCIDE)
head = []
head.append('import { useEffect, useRef, useState, type ReactNode } from "react";')
head.append('import { createRoot } from "react-dom/client";')
head.append('import {\n  ' + ",\n  ".join(main_icons) + ',\n} from "lucide-react";')
head.append('import "./style.css";')
head.append('import { Select } from "./components/Select";')
head.append('import { Button, Badge, Empty, Logo } from "./components/ui";')
head.append('import { navItems, formatTime } from "./constants";')
head.append('import { api, type Book, type Segment } from "./api";')
head.append('import { Library } from "./pages/Library";')
head.append('import { ImportPage } from "./pages/Import";')
head.append('import { ChaptersPage } from "./pages/Chapters";')
head.append('import { Director } from "./pages/Director";')
head.append('import { Voices } from "./pages/Voices";')
head.append('import { Jobs } from "./pages/Queue";')
head.append('import { Listen } from "./pages/Listen";')
head.append('import { ExportPage } from "./pages/Export";')
head.append('import { SettingsPage } from "./pages/Settings";')
new_main = "\n".join(head) + "\n\n" + app_body + "\n\ncreateRoot(document.getElementById(\"root\")!).render(<App />);\n"
src.write_text(new_main, encoding="utf-8")
print(f"frontend/src/main.tsx: {len(new_main.splitlines())} lines")
