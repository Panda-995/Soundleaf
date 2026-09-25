import { useState, useRef } from "react";
import {
  Upload,
  ChevronRight,
  LoaderCircle,
  ArrowUp,
  ArrowDown,
  Scissors,
  Merge,
  Trash2,
  CircleAlert,
} from "lucide-react";
import { Select } from "../components/Select";
import { Badge, Button, Heading } from "../components/ui";
import { api } from "../api";
import type { Common } from "../api";
import { t, tf } from "../i18n";

export function ImportPage({
  run,
  notify,
  busy,
  onCreated,
}: Common & { onCreated: (id: string) => void }) {
  const [draft, setDraft] = useState<any>(null),
    [index, setIndex] = useState(0),
    [encoding, setEncoding] = useState("auto"),
    [title, setTitle] = useState(""),
    [author, setAuthor] = useState("");
  const fileRef = useRef<HTMLInputElement>(null),
    textRef = useRef<HTMLTextAreaElement>(null);
  const update = (key: string, value: string) =>
    setDraft({
      ...draft,
      chapters: draft.chapters.map((c: any, i: number) =>
        i === index ? { ...c, [key]: value } : c,
      ),
    });
  const move = (delta: number) => {
    const chapters = [...draft.chapters],
      next = index + delta;
    if (next < 0 || next >= chapters.length) return;
    [chapters[index], chapters[next]] = [chapters[next], chapters[index]];
    setDraft({ ...draft, chapters });
    setIndex(next);
  };
  return (
    <>
      <Heading title={t("导入小说")} sub={t("先把章节理清，再让故事开口。")} />
      <div className="steps">
        <span className={!draft ? "active" : ""}>{t("01　上传文件")}</span>
        <span className={draft ? "active" : ""}>{t("02　校对分章")}</span>
        <span>{t("03　创建有声书")}</span>
      </div>
      {!draft ? (
        <div className="import-start panel">
          <div className="upload-emblem">
            <Upload size={38} />
          </div>
          <h2>{t("把小说带进工作室")}</h2>
          <p>{t("支持 TXT、无加密 EPUB · 单文件最大 50MB")}</p>
          <label className="file-input">
            {t("选择小说文件")}
            <input
              ref={fileRef}
              type="file"
              accept=".txt,.epub"
              disabled={busy}
              onChange={(e) => {
                const f = e.target.files?.[0];
                e.target.value = "";
                if (!f) return;
                run(async () => {
                  const data = new FormData();
                  data.append("file", f);
                  const result = await api(
                    "/imports?encoding=" + encoding,
                    "POST",
                    data,
                  );
                  setDraft(result);
                  setTitle(result.name);
                  setIndex(0);
                });
              }}
            />
          </label>
          <label className="encoding">
            {t("文本编码")}
            <Select
              aria-label={t("文本编码")}
              value={encoding}
              onChange={(e) => setEncoding(e.target.value)}
            >
              <option value="auto">{t("自动识别")}</option>
              <option value="utf-8-sig">UTF-8</option>
              <option value="gb18030">GB18030</option>
              <option value="utf-16">UTF-16</option>
            </Select>
          </label>
          {busy && (
            <p>
              <LoaderCircle size={16} className="spin" /> {t("正在解析，请稍候")}
            </p>
          )}
        </div>
      ) : (
        <>
          <div className="import-layout">
            <aside className="panel chapter-nav">
              <div className="section-heading">
                <h3>{t("章节目录")}</h3>
                <Badge>{tf("{count} 章", { count: draft.chapters.length })}</Badge>
              </div>
              <div className="chapter-items">
                {draft.chapters.map((c: any, i: number) => (
                  <button
                    key={i}
                    className={i === index ? "active" : ""}
                    onClick={() => setIndex(i)}
                  >
                    <small>{String(i + 1).padStart(2, "0")}</small>
                    <span>{c.title}</span>
                    {!c.text.trim() && <CircleAlert size={14} />}
                  </button>
                ))}
              </div>
            </aside>
            <section className="panel import-editor">
              <div className="form-row">
                <label>
                  {t("书名")}
                  <input
                    value={title}
                    maxLength={200}
                    onChange={(e) => setTitle(e.target.value)}
                  />
                </label>
                <label>
                  {t("作者")}
                  <input
                    value={author}
                    maxLength={100}
                    onChange={(e) => setAuthor(e.target.value)}
                    placeholder={t("可选")}
                  />
                </label>
              </div>
              <label>
                {t("章节标题")}
                <input
                  value={draft.chapters[index].title}
                  maxLength={200}
                  onChange={(e) => update("title", e.target.value)}
                />
              </label>
              <div className="editor-tools">
                <Button
                  title={t("上移章节")}
                  disabled={!index}
                  onClick={() => move(-1)}
                >
                  <ArrowUp size={16} />
                </Button>
                <Button
                  title={t("下移章节")}
                  disabled={index === draft.chapters.length - 1}
                  onClick={() => move(1)}
                >
                  <ArrowDown size={16} />
                </Button>
                <Button
                  onClick={() => {
                    const p = textRef.current?.selectionStart || 0,
                      c = draft.chapters[index];
                    if (p <= 0 || p >= c.text.length) {
                      notify(t("将光标放在正文中需要拆分的位置"));
                      return;
                    }
                    const chapters = [...draft.chapters];
                    chapters.splice(
                      index,
                      1,
                      { ...c, text: c.text.slice(0, p) },
                      { title: c.title + t("（续）"), text: c.text.slice(p) },
                    );
                    setDraft({ ...draft, chapters });
                  }}
                >
                  <Scissors size={15} />
                  {t("从光标拆分")}
                </Button>
                <Button
                  disabled={index === draft.chapters.length - 1}
                  onClick={() => {
                    const chapters = [...draft.chapters];
                    chapters[index] = {
                      ...chapters[index],
                      text:
                        chapters[index].text + "\n" + chapters[index + 1].text,
                    };
                    chapters.splice(index + 1, 1);
                    setDraft({ ...draft, chapters });
                  }}
                >
                  <Merge size={15} />
                  {t("合并下一章")}
                </Button>
                <Button
                  title={t("排除此章节")}
                  disabled={draft.chapters.length === 1}
                  onClick={() => {
                    const chapters = draft.chapters.filter(
                      (_: any, i: number) => i !== index,
                    );
                    setDraft({ ...draft, chapters });
                    setIndex(Math.min(index, chapters.length - 1));
                  }}
                >
                  <Trash2 size={15} />
                </Button>
              </div>
              <textarea
                ref={textRef}
                className="novel-text"
                aria-label={t("章节正文")}
                value={draft.chapters[index].text}
                onChange={(e) => update("text", e.target.value)}
              />
              <small>
                {tf("原始文件会保留。当前识别编码：{encoding} · {count} 字", {
                  encoding: draft.encoding,
                  count: draft.chapters[index].text.length,
                })}
              </small>
            </section>
          </div>
          <div className="bottom-actions">
            <Button className="subtle" onClick={() => setDraft(null)}>{t("重新上传")}</Button>
            <Button
              primary
              disabled={busy || !title.trim()}
              onClick={() =>
                run(async () => {
                  const result = await api("/imports/confirm", "POST", {
                    id: draft.id,
                    title,
                    author,
                    chapters: draft.chapters,
                  });
                  notify(t("小说已导入"));
                  onCreated(result.id);
                })
              }
            >
              {t("确认分章并创建")}
              <ChevronRight size={17} />
            </Button>
          </div>
        </>
      )}
    </>
  );
}
