import { useEffect, useRef, useState } from "react";
import {
  AudioLines,
  Search,
  Plus,
  ArrowUpRight,
  Sparkles,
  Trash2,
} from "lucide-react";
import { BookAiModal, type BookAiPhase } from "../components/BookAiModal";
import { t, tf } from "../i18n";
import { Badge, Button, Cover, Empty, Heading } from "../components/ui";
import { api } from "../api";
import type { BookMeta, BookSummary, Common } from "../api";

type AiFlow = {
  phase: BookAiPhase;
  bookId: string;
  title: string;
  jobId?: string;
  meta?: BookMeta;
  error?: string;
};

export function Library({
  books,
  selectBook,
  go,
  run,
  notify,
  reload,
  setModal,
  settings,
}: Common & {
  books: BookSummary[];
  selectBook: (id: string, target?: string) => void;
}) {
  const [search, setSearch] = useState("");
  const [ai, setAi] = useState<AiFlow | null>(null);
  const filtered = books.filter(
    (b) => b.title.includes(search) || (b.author || "").includes(search),
  );
  const startAi = (bookId: string, title: string) =>
    setAi({ phase: "input", bookId, title });
  const closeAi = () => {
    setModal(null);
    setAi(null);
  };
  // Poll the analysis / cover job. If the user closed the dialog meanwhile
  // (X / Escape / 后台等待), finish silently with a toast instead of popping
  // the modal back open; if the page itself unmounted, say the job lives on.
  const unmountedRef = useRef(false);
  useEffect(() => {
    if ((ai?.phase !== "running" && ai?.phase !== "cover") || !ai.jobId) return;
    let alive = true;
    const timer = setInterval(async () => {
      try {
        const job = await api<{ status: string; error: string; meta?: BookMeta }>(
          "/jobs/" + ai.jobId,
        );
        if (!alive) return;
        const dialogOpen = !!document.querySelector("dialog[open]");
        if (job.status === "succeeded") {
          if (ai.phase === "running") {
            if (job.meta) setAi({ ...ai, phase: "result", meta: job.meta });
            else setAi({ ...ai, phase: "error", error: t("AI 没有返回书籍资料") });
          } else if (dialogOpen) {
            setModal(null);
            setAi(null);
            reload();
            notify(t("AI 封面已生成并应用到书籍。"));
          } else {
            setAi(null);
            reload();
            notify(t("AI 封面已生成并应用到书籍。"));
          }
        } else if (job.status !== "queued" && job.status !== "running") {
          const message =
            job.error ||
            (ai.phase === "cover" ? t("封面生成未完成") : t("分析未完成"));
          if (dialogOpen) setAi({ ...ai, phase: "error", error: message });
          else {
            setAi(null);
            notify(tf("AI 任务失败：{message}", { message }));
          }
        }
      } catch {}
    }, 1500);
    return () => {
      alive = false;
      clearInterval(timer);
      if (unmountedRef.current) {
        notify(t("AI 任务仍在后台运行，完成后可在任务队列查看结果。"));
      }
    };
  }, [ai?.phase, ai?.jobId]);
  // The dialog element is stored once per phase; form state lives inside
  // BookAiModal so keystrokes never round-trip through app state (which
  // shredded IME composition).
  useEffect(() => {
    if (!ai) return;
    setModal({
      title:
        ai.phase === "input"
          ? t("AI 分析书籍")
          : tf("AI 分析《{title}》", { title: ai.title }),
      content: (
        <BookAiModal
          key={ai.phase + (ai.jobId || "")}
          phase={ai.phase}
          defaults={{ title: ai.title, author: ai.meta?.author || "", intro: ai.meta?.intro || "" }}
          meta={ai.meta}
          error={ai.error}
          imageModel={!!settings?.ai?.image_model}
          onClose={closeAi}
          onBackground={() => setModal(null)}
          onStart={(title) =>
            run(async () => {
              const job = await api<{ id: string }>(
                `/books/${ai.bookId}/analyze-book`,
                "POST",
                { title },
              );
              setAi({ ...ai, phase: "running", jobId: job.id, title });
            })
          }
          onApply={(v) =>
            run(async () => {
              await api(`/books/${ai.bookId}/apply-meta`, "POST", v);
              closeAi();
              reload();
              notify(t("书籍资料已应用。"));
            })
          }
          onGenerateCover={(v) =>
            run(async () => {
              await api(`/books/${ai.bookId}/apply-meta`, "POST", {
                title: v.title,
                author: v.author,
                intro: v.intro,
              });
              const job = await api<{ id: string }>(
                `/books/${ai.bookId}/generate-cover`,
                "POST",
                { title: v.title, mood: v.mood, tags: v.tags },
              );
              setAi({ ...ai, phase: "cover", jobId: job.id });
            })
          }
          onRetry={() => setAi({ phase: "input", bookId: ai.bookId, title: ai.title })}
        />
      ),
    });
  }, [ai]);
  const askDelete = (b: BookSummary) => {
    setModal({
      title: tf("删除《{title}》？", { title: b.title }),
      content: (
        <>
          <p>
            {t(
              "将删除本书及其全部章节、音频、导出包、任务、播放进度和封面。原始上传文件也会被移除。共享语音缓存保留。 这项操作不可撤销。",
            )}
          </p>
          <div className="notice">
            {tf("{done} / {total} 章已完成 · 删除前请先确认导出或备份。", {
              done: b.completed,
              total: b.chapters,
            })}
          </div>
          <div className="modal-actions">
            <Button onClick={() => setModal(null)}>{t("取消")}</Button>
            <Button
              className="danger"
              onClick={() =>
                run(async () => {
                  const deleted = await api(`/books/${b.id}`, "DELETE");
                  setModal(null);
                  notify(
                    deleted.cleanup_pending
                      ? tf("已移除书籍，有 {count} 个文件因权限问题未清理", {
                          count: deleted.cleanup_pending,
                        })
                      : tf("已删除《{title}》", { title: b.title }),
                  );
                  reload();
                })
              }
            >
              <Trash2 size={16} />
              {t("确认删除")}
            </Button>
          </div>
        </>
      ),
    });
  };
  return (
    <>
      <Heading title={t("我的书架")} sub={t("把每一页，变成可以听见的故事。")}>
        <Button primary onClick={() => go("import")}>
          <Plus size={18} />
          {t("导入小说")}
        </Button>
      </Heading>
      {!books.length ? (
        <Empty
          title={t("第一本有声书，从这里开始")}
          description={t(
            "上传 TXT 或 EPUB，挑一个声音，让熟悉的故事有新的模样。",
          )}
        >
          <Button primary onClick={() => go("import")}>
            {t("导入第一本小说")}
            <ArrowUpRight size={17} />
          </Button>
          <Button onClick={() => go("settings")}>{t("配置语音服务")}</Button>
        </Empty>
      ) : (
        <>
          <section className="continue-book">
            <div className="cover-row">
              <Cover book={books[0]} />
              <div>
                <Badge kind="lime">{t("继续制作")}</Badge>
                <h2>{books[0].title}</h2>
                <p>
                  {tf("{author} · {count} 章", {
                    author: books[0].author || t("未填写作者"),
                    count: books[0].chapters,
                  })}
                </p>
                <div className="progress">
                  <i
                    style={{
                      width: `${(books[0].completed / Math.max(1, books[0].chapters)) * 100}%`,
                    }}
                  />
                </div>
                <small>
                  {tf("{done} / {total} 章已完成", {
                    done: books[0].completed,
                    total: books[0].chapters,
                  })}
                </small>
                {books[0].intro && <p className="continue-intro">{books[0].intro}</p>}
              </div>
            </div>
            <div className="continue-action">
              <AudioLines size={62} strokeWidth={0.9} />
              <Button primary onClick={() => selectBook(books[0].id)}>
                {t("继续制作")}
                <ArrowUpRight size={18} />
              </Button>
              <Button onClick={() => startAi(books[0].id, books[0].title)}>
                <Sparkles size={15} />
                {t("AI 分析")}
              </Button>
              <Button
                className="danger ghost"
                title={t("删除书籍")}
                onClick={(e) => {
                  e.stopPropagation();
                  askDelete(books[0]);
                }}
              >
                <Trash2 size={15} />
                {t("删除书籍")}
              </Button>
            </div>
          </section>
          <div className="section-heading">
            <h2>
              {t("全部作品")}{" "}
              <small>{books.length.toString().padStart(2, "0")}</small>
            </h2>
            <div className="search">
              <Search size={16} />
              <input
                aria-label={t("搜索书籍")}
                placeholder={t("搜索书名、作者")}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
          </div>
          <div className="book-grid">
            {filtered.map((b, i) => (
              <div
                className="book-card-wrap item-in"
                key={b.id}
                style={{ animationDelay: `${Math.min(i * 45, 300)}ms` }}
              >
                <button
                  className="book-card"
                  onClick={() => selectBook(b.id)}
                  aria-label={tf("打开《{title}》", { title: b.title })}
                >
                  <Cover book={b} />
                  <h3>{b.title}</h3>
                  <p>
                    {tf("{done} / {total} 章已完成", {
                      done: b.completed,
                      total: b.chapters,
                    })}
                  </p>
                  <div className="progress">
                    <i
                      style={{
                        width: `${(b.completed / Math.max(1, b.chapters)) * 100}%`,
                      }}
                    />
                  </div>
                </button>
                <button
                  className="book-card-menu ai"
                  title={t("AI 分析书籍资料")}
                  aria-label={tf("AI 分析《{title}》", { title: b.title })}
                  onClick={(e) => {
                    e.stopPropagation();
                    startAi(b.id, b.title);
                  }}
                >
                  <Sparkles size={14} />
                </button>
                <button
                  className="book-card-menu"
                  title={t("删除书籍")}
                  aria-label={tf("删除《{title}》", { title: b.title })}
                  onClick={(e) => {
                    e.stopPropagation();
                    askDelete(b);
                  }}
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
          </div>
          {!filtered.length && (
            <Empty
              title={t("没有找到这本书")}
              description={t("换一个关键词试试。")}
            />
          )}
        </>
      )}
    </>
  );
}
