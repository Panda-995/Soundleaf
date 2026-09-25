import { useState } from "react";
import { Badge, Button } from "./ui";
import type { BookMeta } from "../api";
import { t, tf } from "../i18n";

export type BookAiPhase = "input" | "running" | "result" | "cover" | "error";

type Props = {
  phase: BookAiPhase;
  defaults: { title: string; author: string; intro: string };
  meta?: BookMeta | null;
  error?: string;
  imageModel: boolean;
  onClose: () => void;
  onBackground: () => void;
  onStart: (title: string) => Promise<unknown>;
  onApply: (v: { title: string; author: string; intro: string }) => Promise<unknown>;
  onGenerateCover: (v: {
    title: string;
    author: string;
    intro: string;
    mood: string;
    tags: string[];
  }) => Promise<unknown>;
  onRetry: () => void;
};

/** Content of the AI book-analysis dialog. Form state lives HERE, not in the
 * parent: the dialog element is stored once per phase in app state, so every
 * keystroke routed through the parent would re-create the input mid-IME and
 * shred pinyin composition ("lliliuliula…"). Local state round-trips in one
 * render, which keeps IME composition intact. */
export function BookAiModal(p: Props) {
  const [title, setTitle] = useState(p.defaults.title);
  const [author, setAuthor] = useState(p.defaults.author);
  const [intro, setIntro] = useState(p.defaults.intro);
  const [pending, setPending] = useState(false);
  // Handlers resolve when the request settles (success OR failure), so a
  // failed call re-enables the buttons instead of bricking the dialog.
  const guard = (fn: () => Promise<unknown>) => () => {
    if (pending) return;
    setPending(true);
    fn().finally(() => setPending(false));
  };

  if (p.phase === "input") {
    return (
      <>
        <p>{t("根据书名和开头片段，让 AI 推断作者、简介与封面设计。书名可以自由修改后再分析。")}</p>
        <label>
          {t("书名")}
          <input
            value={title}
            maxLength={200}
            onChange={(e) => setTitle(e.target.value)}
          />
        </label>
        <div className="modal-actions">
          <Button onClick={p.onClose}>{t("关闭")}</Button>
          <Button
            primary
            disabled={pending || !title.trim()}
            onClick={guard(() => p.onStart(title))}
          >
            {t("开始分析")}
          </Button>
        </div>
      </>
    );
  }
  if (p.phase === "running") {
    return (
      <>
        <p>{t("正在根据书名和开头片段推断作者、简介与封面设计…")}</p>
        <p className="muted">{t("通常需要几十秒，取决于 AI 服务速度。")}</p>
        <Button onClick={p.onBackground}>后台等待</Button>
      </>
    );
  }
  if (p.phase === "cover") {
    return (
      <>
        <p>{t("AI 正在绘制封面，完成后自动应用到书籍…")}</p>
        <p className="muted">{t("生成一张插画通常需要十几秒到一分钟。")}</p>
        <Button onClick={p.onBackground}>后台等待</Button>
      </>
    );
  }
  if (p.phase === "error") {
    return (
      <>
        <p className="error">{p.error}</p>
        <div className="modal-actions">
          <Button onClick={p.onClose}>关闭</Button>
          <Button primary onClick={p.onRetry}>
            {t("重新分析")}
          </Button>
        </div>
      </>
    );
  }
  return (
    <>
      {p.meta?.tags?.length ? (
        <div className="ai-tags">
          {p.meta.tags.map((t) => (
            <Badge key={t}>{t}</Badge>
          ))}
        </div>
      ) : null}
      <label>
        {t("书名")}
        <input value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} />
      </label>
      <label>
        {t("作者")}
        <input value={author} maxLength={60} onChange={(e) => setAuthor(e.target.value)} />
      </label>
      <label>
        {t("简介")}
        <textarea
          value={intro}
          rows={4}
          maxLength={500}
          onChange={(e) => setIntro(e.target.value)}
        />
      </label>
      <p className="muted">{t("应用时会把书名、作者与简介写入书籍资料。")}</p>
      <div className="modal-actions">
        <Button onClick={p.onClose}>{t("关闭")}</Button>
        <Button
          disabled={pending}
          onClick={guard(() => p.onApply({ title, author, intro }))}
        >
          {t("仅应用资料")}
        </Button>
        <Button
          primary
          disabled={pending || !p.imageModel}
          title={p.imageModel ? undefined : t("先在设置 → AI 分析中填写生图模型")}
          onClick={guard(() =>
            p.onGenerateCover({
              title,
              author,
              intro,
              mood: p.meta?.mood || "",
              tags: p.meta?.tags || [],
            }),
          )}
        >
          {p.imageModel ? t("AI 生成封面并应用") : t("生成封面（未配置生图模型）")}
        </Button>
      </div>
    </>
  );
}
