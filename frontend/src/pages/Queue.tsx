import { useState, useEffect } from "react";
import {
  ListMusic,
  Play,
  Pause,
  Check,
  X,
  LoaderCircle,
} from "lucide-react";
import { Badge, Button, Empty, Heading } from "../components/ui";
import { statusText } from "../constants";
import { t, tf } from "../i18n";
import { api } from "../api";
import type { Common } from "../api";

type QueueJob = {
  id: string;
  kind: string;
  book_id: string | null;
  chapter_id: string | null;
  status: string;
  stage: string;
  done: number;
  total: number;
  error: string;
  chapter_title: string | null;
  book_title: string | null;
};

export function Jobs(p: Common) {
  // Null until the first load returns: avoids flashing the empty state.
  const [data, setData] = useState<{
    jobs: QueueJob[];
    paused: boolean;
  } | null>(null);
  useEffect(() => {
    let alive = true;
    const load = () =>
      api<{ jobs: QueueJob[]; paused: boolean }>("/jobs")
        .then((d) => {
          if (alive) setData(d);
        })
        .catch((e) => {
          if (alive) p.notify(e.message);
        });
    load();
    const t = setInterval(load, 2000);
    return () => {
      alive = false;
      clearInterval(t);
      p.reload();
    };
  }, []);
  const active = data?.jobs.find((j) => j.status === "running");
  if (!data)
    return (
      <div className="loading">
        <LoaderCircle className="spin" />
        {t("正在读取队列")}
      </div>
    );
  return (
    <>
      <Heading title={t("任务队列")} sub={t("关闭页面后，任务仍会继续。")}>
        <Button
          onClick={() =>
            p.run(async () => {
              await api("/queue", "POST", { paused: !data.paused });
              setData({ ...data, paused: !data.paused });
            })
          }
        >
          {data.paused ? <Play size={16} /> : <Pause size={16} />}{" "}
          {data.paused ? t("恢复队列") : t("暂停队列")}
        </Button>
      </Heading>
      {data.paused && (
        <div className="notice">
          {t("已暂停领取新任务。当前正在处理的任务会继续到结束。")}
        </div>
      )}
      {active && (
        <section className="active-job panel">
          <div>
            <Badge kind="lime" live>{t("正在制作")}</Badge>
            <h2>{active.chapter_title || t("短试听")}</h2>
            <p>
              {active.book_title || t("音色测试")} · {active.stage}
            </p>
          </div>
          <div className="job-meter">
            <span>
              {tf("{done} / {total} 片段", {
                done: active.done,
                total: active.total || "—",
              })}
            </span>
            <div className="progress">
              <i
                style={{
                  width: `${active.total ? (active.done / active.total) * 100 : 0}%`,
                }}
              />
            </div>
          </div>
        </section>
      )}
      {data.jobs.length ? (
        <div className="job-list">
          {data.jobs.map((j, i) => (
            <article
              className="job-row item-in"
              key={j.id}
              style={{ animationDelay: `${Math.min(i * 35, 210)}ms` }}
            >
              <div className="job-icon">
                {j.status === "running" ? (
                  <LoaderCircle className="spin" />
                ) : j.status === "succeeded" ? (
                  <Check />
                ) : (
                  <ListMusic />
                )}
              </div>
              <div className="job-description">
                <h3>
                  {j.chapter_title ||
                    (
                      {
                        preview: t("音色试听"),
                        export: t("批量导出"),
                        analyze: t("AI 分析"),
                        analyze_chapters: t("AI 章节识别"),
                      } as Record<string, string>
                    )[j.kind] ||
                    t("章节生成")}
                </h3>
                <p>
                  {j.book_title} · {j.stage}{" "}
                  {j.total > 0 ? `· ${j.done}/${j.total}` : ""}
                </p>
                {j.error && <p className="error">{j.error}</p>}
              </div>
              <Badge
                kind={
                  j.status === "succeeded"
                    ? "ok"
                    : j.status === "failed"
                      ? "fail"
                      : ["needs_review", "cancelled"].includes(j.status)
                        ? "warn"
                        : j.status === "running" || j.status === "queued"
                          ? "active"
                          : ""
                }
              >
                {t(statusText[j.status])}
              </Badge>
              <div className="actions">
                {["failed", "needs_review", "cancelled"].includes(j.status) && (
                  <Button
                    className="small"
                    onClick={() =>
                      p.setModal({
                        title: t("确认重试"),
                        content: (
                          <>
                            <p>
                              {t(
                                "重试使用原任务的模型与文本快照。如果服务配置已修改，请取消此任务并从章节页重新生成。",
                              )}
                            </p>
                            <div className="notice">
                              {t(
                                "结果待确认的请求可能已经计费，重试前请检查服务商记录。",
                              )}
                            </div>
                            <Button
                              primary
                              onClick={() =>
                                p.run(async () => {
                                  await api(`/jobs/${j.id}/retry`, "POST");
                                  p.setModal(null);
                                })
                              }
                            >
                              {t("确认重试")}
                            </Button>
                          </>
                        ),
                      })
                    }
                  >
                    {t("重试")}
                  </Button>
                )}
                {["queued", "running", "needs_review"].includes(j.status) && (
                  <Button
                    title={t("取消任务")}
                    onClick={() => {
                      const cancel = () =>
                        p.run(async () => {
                          await api(`/jobs/${j.id}/cancel`, "POST");
                        });
                      // A running task may already be mid-request to the
                      // voice service; make stopping it a deliberate choice.
                      if (j.status === "running")
                        p.setModal({
                          title: t("取消正在处理的任务？"),
                          content: (
                            <>
                              <p>
                                {t(
                                  "任务会在安全边界停止；已经提交给语音服务的请求可能仍会完成并产生费用。",
                                )}
                              </p>
                              <div className="modal-actions">
                                <Button onClick={() => p.setModal(null)}>
                                  {t("继续处理")}
                                </Button>
                                <Button
                                  className="danger"
                                  onClick={() => {
                                    p.setModal(null);
                                    cancel();
                                  }}
                                >
                                  {t("确认取消")}
                                </Button>
                              </div>
                            </>
                          ),
                        });
                      else cancel();
                    }}
                  >
                    <X size={16} />
                  </Button>
                )}
                {j.status === "succeeded" &&
                  ["preview", "generate"].includes(j.kind) && (
                    <Button
                      title={t("试听任务成品")}
                      onClick={() =>
                        p.run(async () => {
                          const result = await api("/jobs/" + j.id);
                          if (result.audio_id)
                            await p.playAudio(
                              result.audio_id,
                              j.chapter_title || t("音色试听"),
                              j.book_id || "",
                            );
                        })
                      }
                    >
                      <Play size={16} />
                    </Button>
                  )}
              </div>
            </article>
          ))}
        </div>
      ) : (
        <Empty
          title={t("还没有制作任务")}
          description={t("选定章节或试听一个音色后，可以在这里查看进度。")}
        >
          <Button onClick={() => p.go("chapters")}>
            {t("打开章节工作台")}
          </Button>
        </Empty>
      )}
    </>
  );
}
