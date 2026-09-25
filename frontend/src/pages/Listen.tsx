import { useState, useEffect } from "react";
import {
  Download,
  Play,
  Pause,
  SkipBack,
  SkipForward,
  ArrowUpRight,
  CircleAlert,
} from "lucide-react";
import { Badge, Button, Cover, Empty, Heading, Wave } from "../components/ui";
import { emotions, formatTime, qualityLabels, segmentIndexAt } from "../constants";
import { AudioMeta, ChapterDetail, api } from "../api";
import type { Common } from "../api";
import { t, tf } from "../i18n";

export function Listen(
  p: Common & {
    audioMeta: AudioMeta | null;
    position: number;
    playing: boolean;
    togglePlay: () => void;
    seek: (v: number) => void;
    goFixSegment: (chapterId: string, index: number) => void;
  },
) {
  const [text, setText] = useState<ChapterDetail | null>(null);
  const [textState, setTextState] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  const [saved, setSaved] = useState<{ audio_id?: string; seconds?: number }>(
    {},
  );
  const b = p.book!;
  useEffect(() => {
    api("/books/" + b.id + "/progress")
      .then(setSaved)
      .catch(() => {});
  }, [b.id]);
  const textTarget = p.audioMeta?.chapter_id || p.chapterId;
  useEffect(() => {
    // Guard against slow responses: never let a stale chapter overwrite the
    // one the user is currently viewing.
    let alive = true;
    if (!textTarget) {
      setTextState("ready");
      return;
    }
    setTextState("loading");
    api("/chapters/" + textTarget)
      .then((d) => {
        if (!alive) return;
        setText(d);
        setTextState("ready");
      })
      .catch(() => {
        if (alive) setTextState("error");
      });
    return () => {
      alive = false;
    };
  }, [textTarget]);
  return (
    <>
      <Heading title={t("听见故事")} sub={t("听一章，修一段，让声音慢慢成形。")}>
        {saved.audio_id && (
          <Button
            onClick={() =>
              p.run(() =>
                p.playAudio(
                  saved.audio_id!,
                  t("继续上次播放"),
                  b.id,
                  saved.seconds || 0,
                ),
              )
            }
          >
            <Play size={16} />
            {t("继续上次播放")}
          </Button>
        )}
        <Button onClick={() => p.go("director")}>
          {t("返回导演")}
          <ArrowUpRight size={16} />
        </Button>
      </Heading>
      <div className="listen-layout">
        <aside className="panel listen-book">
          <Cover book={b} large />
          <h2>{b.title}</h2>
          <p>{b.author || t("我的有声书")}</p>
          <div className="chapter-items">
            {b.chapters.map((c) => (
              <button
                className={p.audioMeta?.chapter_id === c.id ? "active" : ""}
                disabled={!c.active_audio}
                key={c.id}
                onClick={() => {
                  p.setChapterId(c.id);
                  p.run(() => p.playAudio(c.active_audio!, c.title));
                }}
              >
                <span>{c.title}</span>
                <small>
                  {c.active_audio ? formatTime(c.duration) : t("未生成")}
                </small>
              </button>
            ))}
          </div>
        </aside>
        <section className="listen-stage">
          <h2>{text?.title || t("选择已生成的章节")}</h2>
          <Wave
            peaks={p.audioMeta?.peaks}
            position={p.audioMeta ? p.position / p.audioMeta.duration : 0}
            onSeek={(v) => p.audioMeta && p.seek(v * p.audioMeta.duration)}
          />
          <div className="wave-times">
            <time>{formatTime(p.position)}</time>
            <time>{formatTime(p.audioMeta?.duration)}</time>
          </div>
          <div className="listen-buttons">
            <Button
              title={t("后退15秒")}
              disabled={!p.audioMeta}
              onClick={() => p.seek(p.position - 15)}
            >
              <SkipBack />
            </Button>
            <Button
              className="big-play"
              disabled={!p.audioMeta}
              onClick={p.togglePlay}
              title={p.playing ? t("暂停") : t("播放")}
            >
              {p.playing ? <Pause /> : <Play />}
            </Button>
            <Button
              title={t("前进15秒")}
              disabled={!p.audioMeta}
              onClick={() => p.seek(p.position + 15)}
            >
              <SkipForward />
            </Button>
            <span className="row-divider" />
            <Button
              disabled={!text || !p.audioMeta}
              onClick={() =>
                p.setModal({
                  title: t("标记试听问题"),
                  content: (
                    <form
                      onSubmit={(e) => {
                        e.preventDefault();
                        const note = new FormData(e.currentTarget).get("note");
                        p.run(async () => {
                          const created = await api(
                            `/chapters/${text!.id}/marks`,
                            "POST",
                            { note, seconds: p.position },
                          );
                          // Append locally so the new mark is visible (and
                          // fixable) without refetching the chapter.
                          if (text)
                            setText({
                              ...text,
                              marks: [
                                {
                                  id: created.mark.id,
                                  seconds: created.mark.seconds,
                                  note: created.mark.note,
                                },
                                ...text.marks,
                              ],
                            });
                          p.setModal(null);
                          p.notify(t("问题已标记，可在章节中检查。"));
                        });
                      }}
                    >
                      <label>
                        {t("问题说明")}
                        <textarea
                          name="note"
                          required
                          maxLength={1000}
                          placeholder={t("例如：人名读音不正确")}
                        />
                      </label>
                      <Button type="submit" primary>
                        {t("保存标记")}
                      </Button>
                    </form>
                  ),
                })
              }
            >
              <CircleAlert size={16} />
              {t("标记问题")}
            </Button>
            {p.audioMeta && (
              <a className="button" href={`/api/audio/${p.audioMeta.id}?download=true`}>
                <Download size={16} />
                {t("下载本章")}
              </a>
            )}
          </div>
          <div className="reading-scroll">
          {text && p.audioMeta && (
            <div className="now-segment" role="status">
              {(() => {
                const current =
                  p.audioMeta.timeline.find(
                    (t) => p.position >= t.start && p.position < t.end,
                  ) ?? null;
                if (!current) {
                  return <small>{t("当前位置在片段之间")}</small>;
                }
                const seg = text.segments[current.index];
                if (!seg) return null;
                const speaker = seg.speaker || "旁白";
                const voiceName = seg.voice
                  ? p.voices.find((v) => v.id === seg.voice)?.name || seg.voice
                  : p.voices.find(
                      (v) =>
                        v.id === (p.book?.voice || p.settings?.tts?.voice),
                    )?.name || t("书籍默认音色");
                return (
                  <>
                    <strong>{t(speaker)}</strong>
                    <Badge kind={speaker !== "旁白" ? "mint" : ""}>{voiceName}</Badge>
                    <Badge>{t(emotions[seg.emotion] || "默认")}</Badge>
                    <span className="seg-speed">{seg.speed.toFixed(2)}×</span>
                  </>
                );
              })()}
            </div>
          )}
          <div className="reading-text">
            {text && p.audioMeta?.quality?.segments.length ? (
              <p className="quality-summary" role="status">
                {tf(
                  "巡检发现 {n} 段疑似异常（静音 / 时长异常 / 爆音），已用标记标出。",
                  { n: p.audioMeta.quality.segments.length },
                )}
              </p>
            ) : null}
            {text?.segments.map((s, i) => {
              const at = p.audioMeta?.timeline.find((t) => t.index === i);
              const issues =
                p.audioMeta?.quality?.segments.find((q) => q.index === i)?.issues ||
                [];
              const current = p.audioMeta?.timeline.some(
                (t) =>
                  t.index === i &&
                  p.position >= t.start &&
                  p.position < t.end,
              );
              return at ? (
                <button
                  className={current ? "current" : ""}
                  key={i}
                  aria-label={
                    issues.length
                      ? tf("跳转到第 {index} 段，存在质量标记", { index: i + 1 })
                      : tf("跳转到第 {index} 段", { index: i + 1 })
                  }
                  title={t("点击跳转到此段落")}
                  onClick={() => p.seek(at.start + 0.01)}
                >
                  {s.text}
                  {issues.length > 0 && (
                    <span className="quality-flag">
                      ⚠ {issues.map((x) => t(qualityLabels[x] || x)).join("、")}
                    </span>
                  )}
                </button>
              ) : (
                <p className={current ? "current" : ""} key={i}>
                  {s.text}
                </p>
              );
            })}
            {!text && textState === "loading" && (
              <p className="muted">{t("正在载入章节…")}</p>
            )}
            {!text && textState === "error" && (
              <Empty
                title={t("章节暂时载入失败")}
                description={t("请刷新页面重试；没有完成音频的章节可以从工作台生成。")}
              />
            )}
            {!text && textState === "ready" && (
              <Empty
                title={t("选择章节开始试听")}
                description={t("没有完成音频的章节可以从工作台生成。")}
              />
            )}
          </div>
          {text?.marks.length ? (
            <div className="panel marks">
              <h3>{t("试听标记")}</h3>
              {text.marks.map((m) => {
                // The fix loop: resolve the mark's position to a timeline
                // segment and jump straight to it in the director.
                const index =
                  p.audioMeta?.chapter_id === text.id
                    ? segmentIndexAt(p.audioMeta.timeline, m.seconds)
                    : null;
                return (
                  <div className="mark-row" key={m.id}>
                    <p>
                      {formatTime(m.seconds)} · {m.note}
                    </p>
                    {index !== null && (
                      <Button
                        className="small"
                        title={t("跳转到导演页的这个片段")}
                        onClick={() => p.goFixSegment(text.id, index)}
                      >
                        {t("去修复")}
                      </Button>
                    )}
                  </div>
                );
              })}
            </div>
          ) : null}
          </div>
        </section>
      </div>
    </>
  );
}
