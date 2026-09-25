import { useState, useEffect } from "react";
import {
  Download,
  RotateCcw,
} from "lucide-react";
import { Select } from "../components/Select";
import { Badge, Button, Heading } from "../components/ui";
import { formatTime } from "../constants";
import { t, tf } from "../i18n";
import { api } from "../api";
import type { Common } from "../api";

export function ExportPage(p: Common) {
  const [selected, setSelected] = useState<string[]>([]),
    [format, setFormat] = useState("mp3"),
    [embed, setEmbed] = useState(true),
    [allowStale, setAllowStale] = useState(false),
    [history, setHistory] = useState<any[]>([]);
  const b = p.book!;
  useEffect(() => {
    api("/exports")
      .then(setHistory)
      .catch((e) => p.notify(e.message));
    setSelected([]);
  }, [b.id]);
  return (
    <>
      <Heading title={t("导出有声书")} sub={t("每章独立保存，也可以一次带走。")} />
      <div className="two-columns">
        <section>
          <div className="section-heading">
            <h2>{t("选择章节")}</h2>
            <Button
              className="small"
              onClick={() =>
                setSelected(
                  b.chapters.filter((c) => c.active_audio).map((c) => c.id),
                )
              }
            >
              {t("全选已完成")}
            </Button>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th />
                  <th>{t("章节")}</th>
                  <th>{t("音频版本")}</th>
                  <th>{t("时长")}</th>
                </tr>
              </thead>
              <tbody>
                {b.chapters.map((c) => (
                  <tr key={c.id}>
                    <td>
                      <input
                        type="checkbox"
                        aria-label={tf("导出{title}", { title: c.title })}
                        disabled={!c.active_audio}
                        checked={selected.includes(c.id)}
                        onChange={(e) =>
                          setSelected(
                            e.target.checked
                              ? [...selected, c.id]
                              : selected.filter((id) => id !== c.id),
                          )
                        }
                      />
                    </td>
                    <td>{c.title}</td>
                    <td>
                      <Badge
                        kind={
                          c.revision === c.audio_revision && !c.stale_count && !c.voice_stale
                            ? "ok"
                            : "warn"
                        }
                      >
                        {c.active_audio
                          ? `v${c.audio_revision}${c.revision !== c.audio_revision ? t(" · 待更新") : ""}${c.stale_count ? t(" · {count} 段待重生成").replace("{count}", String(c.stale_count)) : ""}${c.voice_stale ? t(" · 音色待更新") : ""}`
                          : t("未生成")}
                      </Badge>
                    </td>
                    <td>{c.active_audio ? formatTime(c.duration) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="notice">
            {t("未生成的章节不会包含在导出包中。单章也可从试听页直接下载。")}
            {b.chapters.some((c) => c.voice_stale || c.stale_count) ? " " + t("部分章节的音频待更新（脚本已修改或音色已更换），导出前请重新生成。") : ""}
          </div>
          <div className="section-heading">
            <h2>{t("导出历史")}</h2>
            <Button
              className="small"
              onClick={() =>
                p.run(async () => setHistory(await api("/exports")))
              }
            >
              <RotateCcw size={14} />
              {t("刷新")}
            </Button>
          </div>
          {history
            .filter((e) => e.book_id === b.id)
            .map((e) => (
              <div className="export-row" key={e.id}>
                <div>
                  <h3>{e.title}</h3>
                  <small>
                    {tf("{count} 章", { count: e.count })} ·{" "}
                    {e.format.toUpperCase()} ·{" "}
                    {new Date(e.created * 1000).toLocaleString()}
                  </small>
                </div>
                <a className="button" href={`/api/exports/${e.id}/download`}>
                  <Download size={16} />
                  {t("下载")}
                </a>
              </div>
            ))}
        </section>
        <aside className="panel export-settings">
          <h3>{t("导出设置")}</h3>
          <label>
            {t("音频格式")}
            <Select
              aria-label={t("导出音频格式")}
              value={format}
              onChange={(e) => setFormat(e.target.value)}
            >
              <option value="mp3">{t("MP3 · 逐章文件 + ZIP 打包")}</option>
              <option value="wav">{t("WAV · 逐章文件 + ZIP 打包")}</option>
              <option value="m4b">{t("M4B · 单文件章节有声书")}</option>
            </Select>
          </label>
          {format === "m4b" ? (
            <div className="summary-line">
              <span>{t("章节导航")}</span>
              <b>{t("播放器中显示章节列表")}</b>
            </div>
          ) : (
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={embed && format === "mp3"}
                disabled={format !== "mp3"}
                onChange={(e) => setEmbed(e.target.checked)}
              />
              {t("嵌入元数据（书名/作者/章节）与封面")}
            </label>
          )}
          {format === "mp3" && embed && (
            <div className="summary-line">
              <span>{t("封面嵌入")}</span>
              <b>{b.cover ? t("将嵌入当前封面") : t("未设置封面")}</b>
            </div>
          )}
          {format === "mp3" && embed && !b.cover && (
            <p className="muted">
              {t(
                "到书架上传封面后重新导出，MP3 会自动附带封面插图（元数据不受影响）。",
              )}
            </p>
          )}
          <div className="filename-preview">
            <small>{t("文件名示例")}</small>
            <code>
              {format === "m4b"
                ? `${b.title || t("有声书")}.m4b`
                : `0001_${b.chapters[0]?.title || t("第一章")}.${format}`}
            </code>
          </div>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={allowStale}
              onChange={(e) => setAllowStale(e.target.checked)}
            />
            {t("允许导出尚未更新的旧音频")}
          </label>
          <div className="summary-line">
            <span>{t("已选择")}</span>
            <b>{tf("{count} 章", { count: selected.length })}</b>
          </div>
          <Button
            primary
            disabled={!selected.length || p.busy}
            onClick={() =>
              p.run(async () => {
                await api(`/books/${b.id}/exports`, "POST", {
                  chapter_ids: selected,
                  format,
                  embed: format === "mp3" && embed,
                  allow_stale: allowStale,
                });
                p.notify(t("导出任务已加入队列，完成后从导出历史下载。"));
                p.go("queue");
              })
            }
          >
            <Download size={17} />
            {t("创建导出包")}
          </Button>
          <small>{t("导出会固定当前音频版本，后续修改不会改变这次包内容。")}</small>
        </aside>
      </div>
    </>
  );
}
