import { useState, useEffect, useRef} from "react";
import {
  Clapperboard,
  Play,
  LoaderCircle,
  RotateCcw,
  RefreshCw,
  Save,
  Sparkles,
} from "lucide-react";
import { Select } from "../components/Select";
import { PronunciationPopup, highlightCorrections } from "../components/Pronounce";
import { Badge, Button, Empty, Heading } from "../components/ui";
import { baseSegment, collectSpeakers, emotions, formatTime } from "../constants";
import { ChapterDetail, DictEntry, Segment, api } from "../api";
import type { Common } from "../api";
import { t, tf } from "../i18n";

type JobListing = {
  jobs: { id: string; chapter_id: string; kind: string; status: string }[];
};

export function Director(
  p: Common & {
    fixTarget?: { chapterId: string; index: number } | null;
    clearFixTarget?: () => void;
  },
) {
  const [detail, setDetail] = useState<ChapterDetail | null>(null),
    [index, setIndex] = useState(0),
    [dirty, setDirty] = useState(false),
    [switching, setSwitching] = useState(false);
  useEffect(() => {
    // Keep the whole workspace mounted while switching chapters: only the
    // script body fades out and back in with the new content.
    if (!p.chapterId) return; // book switch clears the chapter first
    let alive = true;
    setIndex(0);
    setSwitching(true);
    api<ChapterDetail>("/chapters/" + p.chapterId)
      .then((d) => {
        if (!alive) return;
        setDetail(d);
        setDirty(false);
        setSwitching(false);
      })
      .catch((e) => {
        if (!alive) return;
        setSwitching(false);
        p.clearFixTarget?.();
        p.notify(e.message);
      });
    return () => {
      alive = false;
    };
  }, [p.chapterId]);
  const [analysisId, setAnalysisId] = useState(""),
    [analyzing, setAnalyzing] = useState(false);
  const [restructureId, setRestructureId] = useState(""),
    [restructuring, setRestructuring] = useState(false);
  const [regen, setRegen] = useState<number | null>(null);
  // ≤768px panes (DESIGN.md: 章节、正文、参数分步标签) — the three-column
  // layout stacks on phones, and the inspector would otherwise sit after the
  // whole chapter text. Desktop ignores this state entirely (CSS).
  const [pane, setPane] = useState<"chapters" | "script" | "params">("script");
  // Pronunciation dictionary for this book: words highlighted in the script
  // rows, editable by swiping text (selection popup).
  const [dictEntries, setDictEntries] = useState<DictEntry[]>([]);
  const [dictVersion, setDictVersion] = useState(0);
  const [pronouncePop, setPronouncePop] = useState<{
    word: string;
    chapterId: string;
    anchor: { top: number; bottom: number; left: number };
  } | null>(null);
  useEffect(() => {
    let alive = true;
    api<DictEntry[]>(`/books/${p.book!.id}/dict`)
      .then((d) => {
        if (alive) setDictEntries([...d].sort((a, b) => b.word.length - a.word.length));
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [p.book?.id, dictVersion]);
  // Swipe-to-fix: a non-empty text selection inside a script row opens the
  // pronunciation popup anchored above the selection.
  const onScriptMouseUp = () => {
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed || !sel.rangeCount) return;
    // Strip ALL whitespace (a selection spanning rows joins them with newlines)
    // and reject punctuation-only picks; slice by code points, not UTF-16 units.
    const word = [...sel.toString().replace(/\s+/g, "")].slice(0, 60).join("");
    if (!word || !/[一-龥A-Za-z0-9]/.test(word)) return;
    const range = sel.getRangeAt(0);
    const startNode = range.startContainer;
    const el = startNode?.nodeType === 3 ? startNode.parentElement : (startNode as Element);
    const row = el?.closest?.(".script-segment") as HTMLElement | null;
    if (!row) return;
    const rect = range.getBoundingClientRect();
    setPronouncePop({
      word,
      chapterId: p.chapterId,
      anchor: { top: rect.top, bottom: rect.bottom, left: rect.left + rect.width / 2 },
    });
  };
  // Manually started pollers must stop when the user moves to another
  // chapter: neither their notifications nor their results may land on the
  // chapter now being edited.
  const chapterRef = useRef(p.chapterId);
  chapterRef.current = p.chapterId;
  const suggestionRef = useRef<HTMLDivElement>(null);
  // The regen poller has a chapter guard but interval timers survive
  // unmount — without this cleanup it would keep polling for up to three
  // minutes after the user leaves the page entirely.
  const regenTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(
    () => () => {
      if (regenTimer.current) clearInterval(regenTimer.current);
    },
    [],
  );
  const pollRegen = (jobId: string, forChapter: string) => {
    if (regenTimer.current) clearInterval(regenTimer.current);
    let ticks = 0;
    const timer = setInterval(async () => {
      if (chapterRef.current !== forChapter) {
        clearInterval(timer);
        regenTimer.current = null;
        setRegen(null);
        return;
      }
      if (++ticks > 150) {
        clearInterval(timer);
        regenTimer.current = null;
        setRegen(null);
        p.notify(t("片段重生成仍在处理，可从任务队列继续查看。"));
        return;
      }
      try {
        const j = await api("/jobs/" + jobId);
        if (["succeeded", "failed", "needs_review", "cancelled"].includes(j.status)) {
          clearInterval(timer);
          regenTimer.current = null;
          setRegen(null);
          if (chapterRef.current !== forChapter) return;
          if (j.status === "succeeded") {
            const d = await api<ChapterDetail>("/chapters/" + forChapter);
            setDetail(d);
            p.notify(t("该片段音频已就地更新。"));
          } else {
            p.notify(j.error || t("片段重生成未完成"));
          }
        }
      } catch {}
    }, 1200);
    regenTimer.current = timer;
  };
  useEffect(() => {
    setAnalysisId("");
    setAnalyzing(false);
    setRestructureId("");
    setRestructuring(false);
    setRegen(null);
  }, [p.chapterId]);
  // A listening mark jumped here: once the chapter detail exists, select the
  // targeted segment, bring it into view and consume the target.
  useEffect(() => {
    if (!p.fixTarget || p.fixTarget.chapterId !== p.chapterId || !detail) return;
    setIndex(Math.max(0, Math.min(p.fixTarget.index, detail.segments.length - 1)));
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    setTimeout(() => {
      document
        .querySelector(".script-segment.active")
        ?.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "center" });
    }, 150);
    p.clearFixTarget?.();
  }, [p.fixTarget, p.chapterId, detail]);
  // One shared poller for the analyze and restructure jobs. It discovers
  // pending jobs of either kind with a single /jobs request per tick and
  // hands each finished job to its own success/stop handlers.
  useEffect(() => {
    let alive = true;
    const configs = [
      {
        kind: "analyze" as const,
        id: analysisId,
        setId: setAnalysisId,
        setActive: setAnalyzing,
        stoppedLabel: t("分析已取消"),
        onSuccess: async () => {
          const next = await api<ChapterDetail>("/chapters/" + p.chapterId);
          if (!alive) return;
          setDetail(next);
          setIndex(0);
          p.notify(t("角色与朗读建议已就绪，请核对后采纳。"));
          const reduced = window.matchMedia(
            "(prefers-reduced-motion: reduce)",
          ).matches;
          setTimeout(
            () =>
              suggestionRef.current?.scrollIntoView({
                behavior: reduced ? "auto" : "smooth",
                block: "start",
              }),
            120,
          );
        },
      },
      {
        kind: "restructure" as const,
        id: restructureId,
        setId: setRestructureId,
        setActive: setRestructuring,
        stoppedLabel: t("优化分段已取消"),
        onSuccess: async () => {
          const next = await api<ChapterDetail>("/chapters/" + p.chapterId);
          if (!alive) return;
          setDetail(next);
          setIndex((cur) => Math.min(cur, Math.max(0, next.segments.length - 1)));
          p.notify(t("AI 已重新切分章节，可在下方面板预览后再决定是否采纳。"));
        },
      },
    ];
    const poll = async () => {
      let discovery: JobListing | null = null;
      for (const cfg of configs) {
        try {
          let id = cfg.id;
          if (!id) {
            const listing: JobListing = discovery ?? (await api("/jobs"));
            discovery = listing;
            id =
              listing.jobs.find(
                (j) =>
                  j.chapter_id === p.chapterId &&
                  j.kind === cfg.kind &&
                  ["queued", "running"].includes(j.status),
              )?.id ?? "";
            if (id && alive) cfg.setId(id);
          }
          if (!id) continue;
          const job = await api("/jobs/" + id);
          if (!alive) return;
          const active = ["queued", "running"].includes(job.status);
          cfg.setActive(active);
          if (!active) {
            if (job.status === "succeeded" && chapterRef.current === p.chapterId) {
              await cfg.onSuccess();
            } else if (job.status !== "succeeded") p.notify(job.error || cfg.stoppedLabel);
            if (alive) cfg.setId("");
          }
        } catch {}
      }
    };
    poll();
    const timer = setInterval(poll, 1500);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [p.chapterId, analysisId, restructureId]);
  // Unsaved-edit protection: block in-app navigation with a confirm, and a
  // beforeunload dialog for refresh/close. Cleared when saved or discarded.
  useEffect(() => {
    p.setNavGuard(
      dirty
        ? () =>
            window.confirm(
              t("有尚未保存的调整，离开将丢失这些修改。确定要离开吗？"),
            )
        : null,
    );
    return () => p.setNavGuard(null);
  }, [dirty]);
  useEffect(() => {
    if (!dirty) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty]);
  const load = async () => {
    setDetail(await api("/chapters/" + p.chapterId));
    setDirty(false);
  };
  const change = (key: keyof Segment, value: string | number) => {
    if (!detail) return;
    setDetail({
      ...detail,
      segments: detail.segments.map((s, i) =>
        i === index ? { ...s, [key]: value } : s,
      ),
    });
    setDirty(true);
  };
  const save = async () => {
    if (!detail) return;
    const d = await api("/chapters/" + detail.id, "PUT", {
      revision: detail.revision,
      title: detail.title,
      segments: detail.segments,
    });
    setDetail(d);
    setDirty(false);
    p.reload();
    p.notify(t("已保存。旧音频保留，可重新生成更新版本。"));
  };
  if (!detail)
    return (
      <div className="loading">
        <LoaderCircle className="spin" />
        {t("正在打开章节")}
      </div>
    );
  const s = detail.segments[index];
  // While switching chapters the previous script stays visible but dimmed;
  // the heading already shows the target chapter's title.
  const headTitle =
    p.book!.chapters.find((c) => c.id === p.chapterId)?.title || detail.title;
  return (
    <>
      <Heading
        title={headTitle}
        sub={tf("{book} / 朗读脚本 · 版本 {revision}", {
          book: p.book!.title,
          revision: detail.revision,
        })}
      >
        <Button
          disabled={p.busy}
          onClick={() => {
            if (dirty && !window.confirm(t("有尚未保存的调整，重新载入将丢弃这些修改。确定继续吗？"))) return;
            p.run(load);
          }}
        >
          <RotateCcw size={15} />
          {t("重新载入")}
        </Button>
        <Button
          disabled={!dirty || p.busy || analyzing}
          onClick={() => p.run(save)}
        >
          <Save size={16} />
          {t("保存")}
        </Button>
        <Button
          primary
          disabled={dirty || p.busy}
          onClick={() => p.confirmGenerate([p.chapterId])}
        >
          {t("生成本章")}
        </Button>
      </Heading>
      {dirty && (
        <div className="notice">
          {t("有尚未保存的调整。保存后再生成；切换章节前请先保存。")}
        </div>
      )}
      <div className="director-panes" role="tablist" aria-label={t("工作区视图")}>
        {(
          [
            ["chapters", t("章节列表")],
            ["script", t("朗读脚本")],
            ["params", t("朗读设置")],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            role="tab"
            aria-selected={pane === id}
            className={"director-pane-tab" + (pane === id ? " active" : "")}
            onClick={() => setPane(id)}
          >
            {label}
          </button>
        ))}
      </div>
      <div className={`director-layout pane-${pane}`}>
        <aside className="panel chapter-nav pane-chapters">
          <h3>{t("章节列表")}</h3>
          <div className="chapter-items">
            {p.book!.chapters.map((c) => (
              <button
                disabled={dirty}
                className={
                  (c.id === p.chapterId ? "active " : "") +
                  (switching && c.id === p.chapterId ? "switching" : "")
                }
                key={c.id}
                onClick={() => {
                  p.setChapterId(c.id);
                  setPane("script");
                }}
              >
                <small>{String(c.position).padStart(2, "0")}</small>
                <span>{c.title}</span>
              </button>
            ))}
          </div>
        </aside>
        <section
          className={
            "script-panel panel pane-script" + (switching ? " switching" : "")
          }
        >
          <div className="script-header">
            <h3>
              {t("朗读脚本")}
              <small className="script-hint">{t("划选正文词语可修正读音")}</small>
            </h3>
            <div className="script-header-actions">
              <Button
                className="small"
                disabled={dirty || p.busy || restructuring}
                onClick={() =>
                  p.run(async () => {
                    const r = await api(
                      `/chapters/${p.chapterId}/restructure`,
                      "POST",
                    );
                    setRestructureId(r.id);
                    setRestructuring(true);
                    p.notify(t("AI 正在按语义重新切分段落，完成后可在下方预览。"));
                  })
                }
              >
                {restructuring ? (
                  <LoaderCircle className="spin" size={15} />
                ) : (
                  <Sparkles size={15} />
                )}
                {restructuring ? t("优化中…") : t("AI 优化分段")}
              </Button>
              <Button
                className="small"
                disabled={dirty || p.busy || analyzing}
                onClick={() =>
                  p.run(async () => {
                    const analysis = await api(
                      `/chapters/${p.chapterId}/analyze`,
                      "POST",
                    );
                    setAnalysisId(analysis.id);
                    setAnalyzing(true);
                    p.notify(t("正在分析本章段落与对话，完成后将在此显示建议。"));
                  })
                }
              >
                {analyzing ? (
                  <LoaderCircle className="spin" size={15} />
                ) : (
                  <Clapperboard size={15} />
                )}
                {analyzing ? t("分析角色与对白…") : t("AI 分析本章")}
              </Button>
            </div>
          </div>
          {restructuring && (
            <div className="notice inline-notice" role="status">
              <LoaderCircle className="spin" size={14} />
              {t("AI 正在按语义重新切分段落，原文不会改动。")}
            </div>
          )}
          {analyzing && (
            <div className="notice inline-notice" role="status">
              <LoaderCircle className="spin" size={14} />
              {t("AI 正在逐段分析说话者、音色、语速与停顿，可在右侧查看。")}
            </div>
          )}
          <div
            className="script-body"
            key={detail.id}
            onMouseUp={onScriptMouseUp}
          >
            {detail.restructure && !restructuring && (
            <div className="restructure-preview">
              <header>
                <Badge kind="lime">{t("AI 建议的分段")}</Badge>
                <small>
                  {t("已按对白/叙述细分并标注每个单元的说话者，原文逐字符未改动；采纳后 AI 分析可精确到每个角色的每句话。")}
                </small>
              </header>
              <ol className="restructure-list">
                {detail.restructure.segments.slice(0, 80).map((s, i) => (
                  <li key={i}>
                    <span className="restructure-num">{String(i + 1).padStart(2, "0")}</span>
                    <span className="restructure-text">
                      {s.text.trim() ? s.text : t("（空段）")}
                    </span>
                    <Badge kind={s.speaker === "旁白" ? "" : "mint"}>
                      {t(s.speaker || "旁白")}
                    </Badge>
                  </li>
                ))}
              </ol>
              {detail.restructure.segments.length > 80 && (
                <small className="restructure-overflow">
                  {tf("仅显示前 80 段，共 {total} 段。", {
                    total: detail.restructure.segments.length,
                  })}
                </small>
              )}
              <div className="restructure-actions">
                <Button
                  primary
                  disabled={dirty || p.busy}
                  onClick={() =>
                    p.run(async () => {
                      await api(`/chapters/${detail.id}`, "PUT", {
                        title: detail.title,
                        revision: detail.revision,
                        segments: detail.restructure!.segments.map((s) => ({
                          text: s.text,
                          voice: s.voice || "",
                          emotion: s.emotion || "neutral",
                          speed: s.speed || 1.0,
                          pause: s.pause || 250,
                          speaker: s.speaker || "旁白",
                        })),
                      });
                      const d = await api<ChapterDetail>(
                        "/chapters/" + detail.id,
                      );
                      setDetail(d);
                      setDirty(false);
                      p.notify(t("已按 AI 建议重新分段。"));
                    })
                  }
                >
                  <Sparkles size={15} />
                  {t("采纳 AI 分段并替换现有脚本")}
                </Button>
                <Button
                  className="subtle"
                  onClick={() =>
                    p.run(async () => {
                      await api(
                        `/chapters/${detail.id}/dismiss-restructure`,
                        "POST",
                      );
                      const d = await api<ChapterDetail>(
                        "/chapters/" + detail.id,
                      );
                      setDetail(d);
                      p.notify(t("已忽略本次 AI 分段建议。"));
                    })
                  }
                >
                  {t("忽略本次建议")}
                </Button>
              </div>
            </div>
          )}
          <label className="chapter-title-field">
            {t("章节标题")}
            <input
              value={detail.title}
              disabled={analyzing || restructuring}
              onChange={(e) => {
                setDetail({ ...detail, title: e.target.value });
                setDirty(true);
              }}
              maxLength={200}
            />
          </label>
          {detail.segments.length ? (
            detail.segments.map((seg, i) => {
              const suggestion = detail.suggestion?.segments.find(
                (v) => v.index === i,
              );
              const speakerKey = seg.speaker || "旁白";
              const isDialogue = speakerKey !== "旁白";
              return (
                <div
                  className={"script-segment " + (i === index ? "active" : "")}
                  key={i}
                  data-index={i}
                  role="button"
                  tabIndex={0}
                  style={{ animationDelay: `${Math.min(i * 14, 240)}ms` }}
                  onClick={() => setIndex(i)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      setIndex(i);
                    }
                  }}
                >
                  <div>
                    <span className="muted">
                      {String(i + 1).padStart(2, "0")}
                    </span>
                    <Badge kind={isDialogue ? "mint" : ""}>{t(speakerKey)}</Badge>
                    <Badge>{t(emotions[seg.emotion])}</Badge>
                    {seg.voice && (
                      <Badge kind="lime">
                        {p.voices.find((v) => v.id === seg.voice)?.name ||
                          seg.voice}
                      </Badge>
                    )}
                    <span className="segment-speed">{seg.speed}×</span>
                  </div>
                  {suggestion?.voice_hint && (
                    <small className="voice-hint">
                      {tf("AI 音色建议：{hint}", { hint: suggestion.voice_hint })}
                    </small>
                  )}
                  <p>
                    {seg.text
                      ? highlightCorrections(seg.text, dictEntries)
                      : t("空片段")}
                  </p>
                </div>
              );
            })
          ) : (
            <Empty title={t("本章没有正文")} description={t("添加文字后即可制作。")}>
              <Button
                onClick={() => {
                  setDetail({ ...detail, segments: [baseSegment("")] });
                  setDirty(true);
                }}
              >
                {t("添加正文")}
              </Button>
            </Empty>
          )}
          <details className="original">
            <summary>{t("查看导入原文")}</summary>
            <p>{detail.source}</p>
          </details>
          </div>
        </section>
        <aside className="panel inspector pane-params">
          <h3>
            {t("朗读设置")} <small>{tf("片段 {n}", { n: index + 1 })}</small>
          </h3>
          {s && (
            <>
              <label>
                {t("朗读文本")}
                <textarea
                  value={s.text}
                  maxLength={1200}
                  disabled={analyzing || restructuring}
                  title={
                    analyzing || restructuring
                      ? t("AI 任务处理中，暂时不能编辑")
                      : undefined
                  }
                  onChange={(e) => change("text", e.target.value)}
                />
              </label>
              <label>
                {t("说话者")}
                <input
                  value={s.speaker || ""}
                  maxLength={60}
                  placeholder={t("旁白、角色名或描述")}
                  onChange={(e) => change("speaker", e.target.value)}
                />
              </label>
              <label>
                {t("音色")}
                <Select
                  aria-label={t("片段音色")}
                  value={s.voice}
                  onChange={(e) => change("voice", e.target.value)}
                >
                  <option value="">{t("跟随书籍设置")}</option>
                  {p.voices.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.name}
                    </option>
                  ))}
                </Select>
              </label>
              <label>
                {t("情绪")}
                <Select
                  aria-label={t("片段情绪")}
                  value={s.emotion}
                  onChange={(e) => change("emotion", e.target.value)}
                >
                  {Object.entries(emotions).map(([k, v]) => (
                    <option key={k} value={k}>
                      {t(v)}
                    </option>
                  ))}
                </Select>
              </label>
              {!p.supportsEmotion && (
                <small>{t("兼容接口不支持情绪参数，仅保留该项的语速与音量倾向。")}</small>
              )}
              <label>
                {t("合成语速")} <b>{s.speed.toFixed(2)}×</b>
                <input
                  type="range"
                  min=".6"
                  max="1.4"
                  step=".05"
                  value={s.speed}
                  onChange={(e) => change("speed", +e.target.value)}
                />
              </label>
              <label>
                {t("句尾停顿（毫秒）")}
                <input
                  type="number"
                  min="0"
                  max="3000"
                  step="50"
                  value={s.pause}
                  onChange={(e) => change("pause", +e.target.value)}
                />
              </label>
              <Button
                disabled={p.busy || !s.text.trim()}
                onClick={() =>
                  p.run(() =>
                    p.preview({
                      ...s,
                      voice: s.voice || p.book!.voice || p.settings?.tts.voice || "",
                      text: s.text.slice(0, 300),
                    }),
                  )
                }
              >
                <Play size={16} />
                {t("试听前 300 字")}
              </Button>
              {detail.active_audio && (
                <>
                  <Button
                    disabled={dirty || p.busy || regen !== null}
                    title={dirty ? t("请先保存修改，再重生成音频") : undefined}
                    onClick={() =>
                      p.run(async () => {
                        const j = await api(
                          `/chapters/${detail.id}/regen-segment`,
                          "POST",
                          { index },
                        );
                        setRegen(index);
                        pollRegen(j.id, p.chapterId);
                      })
                    }
                  >
                    <RefreshCw
                      size={16}
                      className={regen === index ? "spin" : undefined}
                    />
                    {regen === index ? t("正在重生成…") : t("重生成此段音频")}
                  </Button>
                  <small className="subtle">
                    {t("只重新合成这一段并就地拼接，几秒完成；改动文本后需先保存。")}
                  </small>
                </>
              )}
            </>
          )}
          {detail.suggestion && (
            <div className="suggestion" ref={suggestionRef}>
              <header className="suggestion-head">
                <Badge kind="lime">{t("AI 角色与朗读方案")}</Badge>
                <small>
                  {tf(
                    "已识别 {n} 个段落或对白。采纳后可逐段修改音色，再保存生成。",
                    { n: detail.suggestion.segments.length },
                  )}
                </small>
              </header>
              <div className="ai-suggestion-list">
                {detail.suggestion.segments.map((v, i) => (
                  <article key={i}>
                    <header>
                      <strong>{t(v.speaker || "旁白")}</strong>
                      <span className="muted">
                        {tf("片段 {n}", { n: String(i + 1).padStart(2, "0") })}
                      </span>
                    </header>
                    <p className="segment-text">{v.text}</p>
                    <div className="actions">
                      <Badge kind={v.voice ? "lime" : ""}>
                        {v.voice
                          ? p.voices.find((x) => x.id === v.voice)?.name ||
                            v.voice
                          : t("音色待指定")}
                      </Badge>
                      <Badge>{t(emotions[v.emotion])}</Badge>
                      <Badge>{tf("语速 {speed}×", { speed: v.speed.toFixed(2) })}</Badge>
                      <Badge>{tf("停顿 {pause}ms", { pause: v.pause })}</Badge>
                    </div>
                    {(v.voice_hint || v.reason) && (
                      <small className="ai-reason">
                        {v.voice_hint ? tf("音色建议：{hint}", { hint: v.voice_hint }) : ""}
                        {v.voice_hint && v.reason ? " · " : ""}
                        {v.reason}
                      </small>
                    )}
                  </article>
                ))}
              </div>
              <div className="suggestion-actions">
                <Button
                  primary
                  onClick={() => {
                    setDetail({
                      ...detail,
                      segments: detail.suggestion!.segments.map((v) => ({
                        text: v.text,
                        speaker: v.speaker || "旁白",
                        voice: v.voice || "",
                        emotion: v.emotion,
                        speed: v.speed,
                        pause: v.pause,
                      })),
                      suggestion: null,
                    });
                    setIndex(0);
                    setDirty(true);
                  }}
                >
                  <Clapperboard size={15} />
                  {t("采纳角色、音色与朗读建议")}
                </Button>
                <small className="muted">
                  {t("采纳后会替换当前片段；旧音频仍可试听。")}
                </small>
              </div>
            </div>
          )}
          {(() => {
            const speakers = collectSpeakers(detail);
            if (!speakers.length) return null;
            return (
              <div className="speaker-map">
                <h3>
                  {t("角色音色")} <small>{t("本章统一调整")}</small>
                </h3>
                {speakers.map((sp) => (
                  <div className="speaker-row" key={sp.name}>
                    <div className="speaker-meta">
                      <strong>{sp.name}</strong>
                      <small>{sp.hint || "—"}</small>
                      <Badge>{tf("{count} 段", { count: sp.count })}</Badge>
                    </div>
                    <Select
                      aria-label={tf("为{speaker}选择音色", { speaker: sp.name })}
                      value={sp.voice}
                      onChange={(e) => {
                        const voice = e.target.value;
                        setDetail({
                          ...detail,
                          segments: detail.segments.map((seg) =>
                            seg.speaker === sp.name ? { ...seg, voice } : seg,
                          ),
                        });
                        setDirty(true);
                      }}
                    >
                      <option value="">{t("跟随书籍设置")}</option>
                      {p.voices.map((v) => (
                        <option key={v.id} value={v.id}>
                          {v.name}
                        </option>
                      ))}
                    </Select>
                  </div>
                ))}
                <small className="subtle">
                  {t("在此一键为某个角色统一指定音色；切换后需重新合成音频。")}
                </small>
              </div>
            );
          })()}
          {detail.versions.length > 0 && (
            <div className="versions">
              <h3>{t("音频版本")}</h3>
              {detail.versions.map((v) => (
                <div className="version-row" key={v.id}>
                  <small>
                    {tf("版本 {revision} · {duration}", {
                      revision: v.revision,
                      duration: formatTime(v.duration),
                    })}
                  </small>
                  <Button
                    title={tf("试听版本{revision}", { revision: v.revision })}
                    onClick={() => p.run(() => p.playAudio(v.id, detail.title))}
                  >
                    <Play size={14} />
                  </Button>
                </div>
              ))}
            </div>
          )}
        </aside>
      </div>
      <PronunciationPopup
        key={pronouncePop ? pronouncePop.word + pronouncePop.chapterId : "none"}
        {...p}
        popup={pronouncePop}
        onClose={() => setPronouncePop(null)}
        onSaved={() => setDictVersion((v) => v + 1)}
      />
    </>
  );
}
