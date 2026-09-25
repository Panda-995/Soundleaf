import { useState, useEffect } from "react";
import {
  Upload,
  Clapperboard,
  Headphones,
  Download,
  Play,
  ArrowUpRight,
  LoaderCircle,
} from "lucide-react";
import { Badge, Button, Cover, Heading } from "../components/ui";
import { formatTime, statusText } from "../constants";
import { Book, api } from "../api";
import type { Common } from "../api";
import { t, tf } from "../i18n";

function ChapterSplitPreview({
  book,
  proposed,
  onCancel,
  onApply,
}: {
  book: Book;
  proposed: { title: string; text: string }[];
  onCancel: () => void;
  onApply: () => Promise<void>;
}) {
  const [index, setIndex] = useState(0),
    [saving, setSaving] = useState(false),
    [ack, setAck] = useState(false),
    [error, setError] = useState("");
  return (
    <div className="split-preview">
      <div className="notice">
        {tf("识别出 {count} 章，完整保留 {chars} 字。标题和正文均来自原文件。", {
          count: proposed.length,
          chars: proposed.reduce((n, c) => n + c.text.length, 0).toLocaleString(),
        })}
      </div>
      <div className="split-layout">
        <aside className="split-list">
          {proposed.map((c, i) => (
            <button
              key={i}
              aria-pressed={index === i}
              className={i === index ? "active" : ""}
              onClick={() => setIndex(i)}
            >
              <small>{i + 1}</small>
              <span>{c.title}</span>
              <em>{tf("{count} 字", { count: c.text.length })}</em>
            </button>
          ))}
        </aside>
        <section className="split-editor">
          <h3>{proposed[index]?.title}</h3>
          <label>
            {t("原文预览")}
            <textarea readOnly value={proposed[index]?.text || ""} />
          </label>
        </section>
      </div>
      <label className="checkbox-label">
        <input
          type="checkbox"
          checked={ack}
          onChange={(e) => setAck(e.target.checked)}
        />
        {t("我已核对，将替换现有章节，并删除本书旧音频、导出包和任务记录。")}
      </label>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="split-actions">
        <Button onClick={onCancel}>{t("保留现有章节")}</Button>
        <Button
          primary
          disabled={!ack || saving}
          onClick={async () => {
            setSaving(true);
            try {
              await onApply();
            } catch (e) {
              setError((e as Error).message);
            } finally {
              setSaving(false);
            }
          }}
        >
          {saving ? t("正在应用…") : tf("确认分章 · {title}", { title: book.title })}
        </Button>
      </div>
    </div>
  );
}
function ChapterAnalysis(p: Common) {
  const [job, setJob] = useState<any>(null),
    [starting, setStarting] = useState(false);
  const b = p.book!;
  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const data = await api("/jobs");
        // Jobs already applied are skipped: their payload still carries a
        // preview that would otherwise resurrect after applying.
        const applied: string[] = JSON.parse(
          sessionStorage.getItem("soundleaf-applied-chapters") || "[]",
        );
        const latest = data.jobs.find(
          (j: any) =>
            j.book_id === b.id &&
            j.kind === "analyze_chapters" &&
            !applied.includes(j.id),
        );
        if (latest) {
          const full = await api("/jobs/" + latest.id);
          if (alive) setJob(full);
        } else if (alive) setJob(null);
      } catch {}
    };
    load();
    const timer = setInterval(load, 2000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [b.id]);
  const active =
    job && ["queued", "running", "needs_review"].includes(job.status);
  const preview = () =>
    p.setModal({
      title: t("AI 分章预览"),
      content: (
        <ChapterSplitPreview
          book={b}
          proposed={job.proposed}
          onCancel={() => p.setModal(null)}
          onApply={async () => {
            await api(`/books/${b.id}/apply-chapters`, "POST", {
              job_id: job.id,
            });
            const applied: string[] = JSON.parse(
              sessionStorage.getItem("soundleaf-applied-chapters") || "[]",
            );
            applied.push(job.id);
            sessionStorage.setItem(
              "soundleaf-applied-chapters",
              JSON.stringify(applied),
            );
            setJob(null);
            p.setChapterId("");
            p.setModal(null);
            p.reload();
            p.notify(t("分章已应用，正文完整保留。"));
          }}
        />
      ),
    });
  return (
    <section className="analysis-toolbar" aria-label={t("AI 章节识别")}>
      <div className="analysis-info">
        <h3>
          <Clapperboard size={18} />
          {t("AI 章节识别")}
        </h3>
        <p>{t("根据原文中的章节标题判断边界，完成后先预览再应用。")}</p>
        {job && (
          <small role="status">
            <span
              className={
                "status-pill " +
                (job.status === "succeeded"
                  ? "ok"
                  : ["failed", "needs_review"].includes(job.status)
                    ? "warn"
                    : job.status === "running" || job.status === "queued"
                      ? "active"
                      : "")
              }
            >
              {t(statusText[job.status])}
            </span>
            <span className="stage">· {job.stage}</span>
            {job.total ? (
              <span className="stage">
                · {job.done}/{job.total}
              </span>
            ) : null}
            {job.error ? <span className="stage">· {job.error}</span> : null}
          </small>
        )}
      </div>
      <div className="actions">
        {job?.status === "succeeded" && job.proposed?.length > 0 && (
          <Button primary onClick={preview}>
            {tf("查看分章预览（{count} 章）", { count: job.proposed.length })}
          </Button>
        )}
        <Button
          disabled={!!active || starting}
          onClick={async () => {
            setStarting(true);
            await p.run(async () => {
              const r = await api(`/books/${b.id}/analyze-chapters`, "POST");
              setJob(await api("/jobs/" + r.id));
              p.notify(t("AI 正在识别原文标题，可留在此页查看结果。"));
            });
            setStarting(false);
          }}
        >
          {active ? (
            <>
              <LoaderCircle className="spin" size={15} />
              {t("分析处理中…")}
            </>
          ) : (
            <>
              <Clapperboard size={15} />
              {job?.status === "succeeded" ? t("重新识别章节") : t("AI 识别章节")}
            </>
          )}
        </Button>
      </div>
    </section>
  );
}

export function ChaptersPage(p: Common) {
  const b = p.book!;
  const [selected, setSelected] = useState<string[]>([]);
  useEffect(() => setSelected([]), [b.id, b.chapters.length]);
  const toggle = (id: string) =>
    setSelected((v) =>
      v.includes(id) ? v.filter((x) => x !== id) : [...v, id],
    );
  return (
    <>
      <Heading
        title={b.title}
        sub={tf("{total} 章 · {done} 章已完成", {
          total: b.chapters.length,
          done: b.chapters.filter((c) => c.active_audio).length,
        })}
      >
        <Button onClick={() => p.go("listen")}>
          <Headphones size={17} />
          {t("试听")}
        </Button>
        <Button
          primary
          disabled={!selected.length || p.busy}
          onClick={() => p.confirmGenerate(selected)}
        >
          <Play size={16} />
          {tf("生成所选 {count}", { count: selected.length || "" })}
        </Button>
      </Heading>
      <ChapterAnalysis {...p} />
      <section className="book-banner">
        <Cover book={b} />
        <div>
          <Badge kind="lime">{t("章节工作台")}</Badge>
          <h2>{b.title}</h2>
          <p>{b.author || t("我的有声书")}</p>
          <div className="actions">
            <Badge>{t("支持角色配音")}</Badge>
            <span className="muted">
              {b.voice || p.settings?.tts.voice || t("未设置音色")}
            </span>
          </div>
        </div>
        <label className="cover-upload">
          <Upload size={16} />
          {t("更换封面")}
          <input
            type="file"
            accept="image/png,image/jpeg"
            onChange={(e) => {
              const f = e.target.files?.[0];
              e.target.value = "";
              if (f)
                p.run(async () => {
                  const d = new FormData();
                  d.append("file", f);
                  await api(`/books/${b.id}/cover`, "POST", d);
                  p.reload();
                });
            }}
          />
        </label>
      </section>
      <div className="section-heading">
        <h2>{t("章节列表")}</h2>
        <Button onClick={() => p.go("voices")}>
          {t("选择音色")}
          <ArrowUpRight size={15} />
        </Button>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>
                <input
                  type="checkbox"
                  aria-label={t("选择全部章节")}
                  checked={
                    !!b.chapters.length && selected.length === b.chapters.length
                  }
                  onChange={(e) =>
                    setSelected(
                      e.target.checked ? b.chapters.map((c) => c.id) : [],
                    )
                  }
                />
              </th>
              <th>{t("章节")}</th>
              <th>{t("字数")}</th>
              <th>{t("音频状态")}</th>
              <th>{t("时长")}</th>
              <th>{t("操作")}</th>
            </tr>
          </thead>
          <tbody>
            {b.chapters.map((c) => (
              <tr key={c.id}>
                <td>
                  <input
                    type="checkbox"
                    aria-label={tf("选择{title}", { title: c.title })}
                    checked={selected.includes(c.id)}
                    onChange={() => toggle(c.id)}
                  />
                </td>
                <td>
                  <small className="chapter-number">
                    {String(c.position).padStart(2, "0")}
                  </small>
                  {c.title}
                </td>
                <td className="muted">{c.characters.toLocaleString()}</td>
                <td>
                  <Badge
                    kind={
                      c.active_audio
                        ? c.revision === c.audio_revision && !c.stale_count
                          ? "ok"
                          : "warn"
                        : ""
                    }
                  >
                    {c.active_audio
                      ? c.revision === c.audio_revision
                        ? c.stale_count
                          ? tf("{count} 段待重生成", { count: c.stale_count })
                          : t("已完成")
                        : t("待更新")
                      : t("待生成")}
                  </Badge>
                </td>
                <td className="muted">
                  {c.active_audio ? formatTime(c.duration) : "—"}
                </td>
                <td>
                  <div className="actions">
                    <Button
                      className="small"
                      onClick={() => {
                        p.setChapterId(c.id);
                        p.go("director");
                      }}
                    >
                      {t("进入导演")}
                    </Button>
                    <Button
                      title={tf("试听{title}", { title: c.title })}
                      disabled={!c.active_audio}
                      onClick={() =>
                        p.run(() => p.playAudio(c.active_audio!, c.title))
                      }
                    >
                      <Play size={16} />
                    </Button>
                    {c.active_audio && (
                      <a
                        className="icon-link"
                        title={t("下载本章")}
                        aria-label={tf("下载{title}", { title: c.title })}
                        href={`/api/audio/${c.active_audio}?download=true`}
                      >
                        <Download size={16} />
                      </a>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="bottom-actions">
        <span className="muted">
          {tf("已选 {count} 章 · 支持仅重新生成修改过的片段", { count: selected.length })}
        </span>
        <Button onClick={() => p.go("export")}>
          <Download size={16} />
          {t("导出章节")}
        </Button>
      </div>
    </>
  );
}
