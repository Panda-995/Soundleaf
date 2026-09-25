import { useEffect, useRef, useState, type ReactNode } from "react";
import { X } from "lucide-react";
import { Button } from "./ui";
import { api, type Common, type DictEntry } from "../api";
import { t, tf } from "../i18n";

/** Split segment text so dictionary words render with a correction marker.
 * Entries must be longest-word-first (same order the synthesizer applies). */
export function highlightCorrections(
  text: string,
  entries: DictEntry[],
): ReactNode[] {
  if (!entries.length) return [text];
  const parts: ReactNode[] = [];
  let plain = "";
  let i = 0;
  outer: while (i < text.length) {
    for (const entry of entries) {
      if (entry.word && text.startsWith(entry.word, i)) {
        if (plain) parts.push(plain);
        parts.push(
          <span key={i} className="dict-word" title={tf("读音修正：{reading}", { reading: entry.replacement })}>
            {entry.word}
          </span>,
        );
        i += entry.word.length;
        plain = "";
        continue outer;
      }
    }
    plain += text[i];
    i += 1;
  }
  if (plain) parts.push(plain);
  return parts;
}

type PopupState = {
  word: string;
  chapterId: string;
  anchor: { top: number; bottom: number; left: number };
};

/** Selection popup on the script text: swipe a word, fix its pronunciation.
 * The script keeps the original writing; the correction is applied when the
 * segment is synthesized (book-level dictionary). */
export function PronunciationPopup(
  p: Common & {
    popup: PopupState | null;
    onClose: () => void;
    onSaved?: () => void;
  },
) {
  const [entries, setEntries] = useState<DictEntry[]>([]);
  const [replacement, setReplacement] = useState("");
  const boxRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let alive = true;
    api<DictEntry[]>(`/books/${p.book!.id}/dict`)
      .then((d) => {
        if (alive) setEntries(d);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);
  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) p.onClose();
    };
    // isComposing: Esc cancels the IME draft — it must not close this popup.
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !e.isComposing) p.onClose();
    };
    // The anchor is a viewport snapshot; any scroll leaves it pointing at
    // unrelated text, so closing is safer than drifting.
    const scroll = () => p.onClose();
    window.addEventListener("mousedown", close);
    window.addEventListener("keydown", key);
    window.addEventListener("scroll", scroll, true);
    return () => {
      window.removeEventListener("mousedown", close);
      window.removeEventListener("keydown", key);
      window.removeEventListener("scroll", scroll, true);
    };
  }, [p.onClose]);
  if (!p.popup) return null;
  // Flip above/below the selection so the popup never leaves the viewport.
  const placeAbove = p.popup.anchor.top > 300;
  const style = {
    top: placeAbove ? p.popup.anchor.top - 6 : p.popup.anchor.bottom + 6,
    left: p.popup.anchor.left,
    transform: placeAbove ? "translate(-50%, -100%)" : "translate(-50%, 0)",
  };
  const existing = entries.find((e) => e.word === p.popup!.word);
  const save = () =>
    p.run(async () => {
      const result = await api<{ affected: number }>(
        `/books/${p.book!.id}/dict`,
        "PUT",
        { word: p.popup!.word, replacement },
      );
      p.onClose();
      p.reload();
      p.onSaved?.();
      p.notify(
        result.affected
          ? tf("「{word}」读音已修正，{count} 处待重生成。", { word: p.popup!.word, count: result.affected })
          : tf("「{word}」读音已修正，重新生成后生效。", { word: p.popup!.word }),
      );
    });
  const remove = () =>
    p.run(async () => {
      await api(`/books/${p.book!.id}/dict`, "PUT", {
        word: p.popup!.word,
        replacement: "",
      });
      setEntries(entries.filter((e) => e.word !== p.popup!.word));
      p.onClose();
      p.reload();
      p.onSaved?.();
      p.notify(tf("已删除「{word}」的读音修正。", { word: p.popup!.word }));
    });
  return (
    <div ref={boxRef} className="pronounce-pop" style={style}>
      <div className="pronounce-head">
        <strong>{p.popup.word}</strong>
        <Button title={t("关闭")} onClick={p.onClose}>
          <X size={14} />
        </Button>
      </div>
      {existing && (
        <p className="pronounce-current">{tf("当前修正为「{reading}」", { reading: existing.replacement })}</p>
      )}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (replacement.trim()) save();
        }}
      >
        <input
          autoFocus
          value={replacement}
          required
          maxLength={120}
          aria-label={t("读音替换写法")}
          placeholder={t("合成时读作…（同音或更清晰的写法）")}
          onChange={(e) => setReplacement(e.target.value)}
        />
        <div className="pronounce-actions">
          {existing && (
            <Button className="small subtle" onClick={remove}>
              {t("删除修正")}
            </Button>
          )}
          <Button type="submit" primary className="small" disabled={p.busy}>
            {t("修正读音")}
          </Button>
        </div>
      </form>
    </div>
  );
}
