import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import {
  BookOpen,
  AudioLines,
  Play,
  Pause,
  SkipBack,
  SkipForward,
  Volume2,
  ArrowUpRight,
  ChevronRight,
  X,
  LoaderCircle,
  Menu,
  LogOut,
  Sun,
  Moon,
} from "lucide-react";
import "./style.css";
import { Select } from "./components/Select";
import { PasswordDialog } from "./components/PasswordChange";
import { usePlayer } from "./player";
import { Button, Badge, Empty, Logo } from "./components/ui";
import { navItems, formatTime, estimateDuration, APP_VERSION } from "./constants";
import { getLang, setLang, subscribeLang, t, tf, type Lang } from "./i18n";
import { Languages } from "lucide-react";
import { api, type Book, type BookSummary, type SettingsShape, type Segment, type Voice, type AudioMeta } from "./api";
import { Library } from "./pages/Library";
import { ImportPage } from "./pages/Import";
import { ChaptersPage } from "./pages/Chapters";
import { CastPage } from "./pages/Cast";
import { Director } from "./pages/Director";
import { Voices } from "./pages/Voices";
import { Jobs } from "./pages/Queue";
import { Listen } from "./pages/Listen";
import { ExportPage } from "./pages/Export";
import { SettingsPage } from "./pages/Settings";

// Login waveform: fixed heights (%) so every render and screenshot is
// identical; --i only staggers the breathing animation delay.
const AUTH_WAVE = [38, 66, 47, 84, 56, 96, 44, 72, 88, 40, 63, 79, 52, 34];

function App() {
  const [boot, setBoot] = useState<{
      authenticated: boolean;
      mustChangePassword: boolean;
    } | null>(null),
    [route, setRoute] = useState(location.hash.slice(1) || "library");
  const [theme, setTheme] = useState<"dark" | "light">(
    () =>
      (localStorage.getItem("soundleaf-theme") as "dark" | "light") || "dark",
  );
  const [lang, setLangLive] = useState<Lang>(getLang());
  useEffect(() => subscribeLang(() => setLangLive(getLang())), []);
  useEffect(() => {
    document.title = t("声页 · 有声书工作室");
  }, [lang, boot]);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("soundleaf-theme", theme);
    document
      .querySelector('meta[name="theme-color"]')
      ?.setAttribute("content", theme === "dark" ? "#101211" : "#f4f5ec");
  }, [theme]);
  const [books, setBooks] = useState<BookSummary[]>([]),
    [bookId, setBookId] = useState(
      localStorage.getItem("soundleaf-book") || "",
    ),
    [book, setBook] = useState<Book | null>(null),
    [chapterId, setChapterId] = useState("");
  const [settings, setSettings] = useState<SettingsShape | null>(null),
    [voices, setVoices] = useState<Voice[]>([]),
    [favorites, setFavorites] = useState<string[]>([]),
    [supportsEmotion, setSupportsEmotion] = useState(true),
    [refresh, setRefresh] = useState(0);
  const [toast, setToast] = useState(""),
    [busy, setBusy] = useState(false),
    [modal, setModal] = useState<{ title: string; content: ReactNode } | null>(
      null,
    ),
    [menu, setMenu] = useState(false);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [toastAssertive, setToastAssertive] = useState(false);
  const notify = (message: string, assertive = false) => {
    setToastAssertive(assertive);
    setToast(message);
  };
  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      // Failures are announced assertively; see the toast role below.
      notify((e as Error).message, true);
    } finally {
      setBusy(false);
    }
  };
  const player = usePlayer({
    notify,
    run,
    bookId,
    chapters: book?.chapters || [],
  });
  // Navigation guard: pages with unsaved work (director edits) register a
  // blocker through setNavGuard; every in-app navigation path funnels through
  // tryGo, which runs it and aborts when it returns false.
  const navGuardRef = useRef<(() => boolean) | null>(null);
  const setNavGuard = (guard: (() => boolean) | null) => {
    navGuardRef.current = guard;
  };
  // The last hash the guard allowed; history back/forward that the guard
  // rejects bounces back here (a hashchange cannot be prevented, only undone).
  const authorizedHashRef = useRef(location.hash || "#library");
  const tryGo = (target: string) => {
    if (navGuardRef.current && !navGuardRef.current()) return false;
    authorizedHashRef.current = "#" + target;
    location.hash = target;
    setMenu(false);
    return true;
  };
  // Global listening shortcuts (space / J K L / arrows) only when the page
  // body has focus — never while typing or inside controls.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (!target || target.tagName !== "BODY" || dialogRef.current?.open) return;
      const key = e.key;
      if (key === " " || key === "k" || key === "K") {
        e.preventDefault();
        player.togglePlay();
      } else if (key === "j" || key === "J") {
        e.preventDefault();
        player.seek(player.position - 10);
      } else if (key === "l" || key === "L") {
        e.preventDefault();
        player.seek(player.position + 10);
      } else if (e.key === "ArrowLeft") {
        e.preventDefault();
        player.seek(player.position - 5);
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        player.seek(player.position + 5);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  });
  const reload = () => setRefresh((x) => x + 1);
  const go = (target: string) => {
    tryGo(target);
  };
  const selectBook = (id: string, target = "chapters") => {
    // tryGo already navigated; do NOT call go() again — with the nav guard
    // active it would confirm twice for one book switch.
    if (!tryGo(target)) return;
    if (id !== bookId) {
      // The loaded audio belongs to the previous book; keep it from bleeding
      // into the new book's Listen page.
      setChapterId("");
      if (player.audioMeta) player.reset();
    }
    setBookId(id);
    localStorage.setItem("soundleaf-book", id);
    setMenu(false);
  };
  // Mark → fix loop: jump from a listening mark straight to the offending
  // segment in the director. fixTarget survives the navigation, is consumed
  // by the director once the chapter detail is loaded, and is then cleared.
  const [fixTarget, setFixTarget] = useState<{
    chapterId: string;
    index: number;
  } | null>(null);
  const goFixSegment = (chapterId: string, index: number) => {
    setChapterId(chapterId);
    setFixTarget({ chapterId, index });
    go("director");
  };
  useEffect(() => {
    api("/bootstrap")
      .then(setBoot)
      .catch((e) => notify(e.message));
    const listener = () => {
      // Hash navigations routed through tryGo pre-authorize their target:
      // running the guard again here would confirm twice.
      if (location.hash === authorizedHashRef.current) {
        setRoute(location.hash.slice(1) || "library");
        return;
      }
      const target = location.hash.slice(1) || "library";
      if (navGuardRef.current && !navGuardRef.current()) {
        // Browser back/forward cannot be prevented — undo the navigation.
        location.hash = authorizedHashRef.current;
        return;
      }
      authorizedHashRef.current = location.hash;
      setRoute(target);
    };
    window.addEventListener("hashchange", listener);
    return () => window.removeEventListener("hashchange", listener);
  }, []);
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(""), 6500);
    return () => clearTimeout(t);
  }, [toast]);
  useEffect(() => {
    if (modal) dialogRef.current?.showModal();
    else dialogRef.current?.close();
  }, [modal]);
  useEffect(() => {
    if (!boot?.authenticated) return;
    // Out-of-order refreshes must not let a stale response win: drop results
    // that arrive after a newer refresh started.
    let stale = false;
    Promise.all([api("/books"), api("/settings"), api("/voices")])
      .then(([bs, s, v]) => {
        if (stale) return;
        setBooks(bs);
        setSettings(s);
        setVoices(v.voices);
        setFavorites(v.favorites);
        setSupportsEmotion(v.emotion);
        if (!bs.some((b: Book) => b.id === bookId)) {
          const next = bs[0]?.id || "";
          setBookId(next);
          setChapterId("");
          setBook(null);
          localStorage.setItem("soundleaf-book", next);
          if (player.audioMeta) player.reset();
        }
      })
      .catch((e) => {
        if (!stale) notify(e.message);
      });
    return () => {
      stale = true;
    };
  }, [boot?.authenticated, refresh]);
  useEffect(() => {
    if (!boot?.authenticated || !bookId) return;
    let cancelled = false;
    api<Book>("/books/" + bookId)
      .then((b) => {
        if (cancelled) return;
        setBook(b);
        if (!chapterId || !b.chapters.some((c) => c.id === chapterId))
          setChapterId(b.chapters[0]?.id || "");
      })
      .catch((e) => notify(e.message));
    return () => {
      cancelled = true;
    };
  }, [bookId, refresh, boot?.authenticated]);
  async function preview(segment: Segment) {
    // book_id lets the server apply the book's pronunciation dictionary so
    // the audition sounds exactly like the final render.
    const job = await api("/preview", "POST", { ...segment, book_id: bookId });
    notify(t("试听已加入队列，生成完成后自动载入。"));
    go("queue");
    pollPreview(job.id);
  }
  const previewTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  function pollPreview(id: string) {
    // One preview poll at a time; failures must be visible, not silent.
    if (previewTimer.current) clearInterval(previewTimer.current);
    let ticks = 0;
    const timer = setInterval(async () => {
      try {
        const j = await api("/jobs/" + id);
        if (j.status === "succeeded") {
          clearInterval(timer);
          previewTimer.current = null;
          await player.playAudio(j.audio_id, t("音色试听"), "");
        } else if (["failed", "needs_review", "cancelled"].includes(j.status)) {
          clearInterval(timer);
          previewTimer.current = null;
          notify(j.error || t("试听已取消"));
        } else if (++ticks > 240) {
          clearInterval(timer);
          previewTimer.current = null;
          notify(t("试听仍在处理中，可从任务队列继续查看。"));
        }
      } catch (e) {
        clearInterval(timer);
        previewTimer.current = null;
        notify((e as Error).message || t("试听状态查询失败"));
      }
    }, 1500);
    previewTimer.current = timer;
  }
  function confirmGenerate(ids: string[]) {
    if (!book || !ids.length) {
      notify(t("请先选择章节"));
      return;
    }
    const count = book.chapters
      .filter((c) => ids.includes(c.id))
      .reduce((s, c) => s + c.characters, 0);
    const duration = estimateDuration(count);
    const summary = duration
      ? tf("将生成 {chapters} 章，共 {chars} 字，预计成品时长{duration}。", {
          chapters: ids.length,
          chars: count.toLocaleString(),
          duration,
        })
      : tf("将生成 {chapters} 章，共 {chars} 字。", {
          chapters: ids.length,
          chars: count.toLocaleString(),
        });
    setModal({
      title: t("开始生成所选章节"),
      content: (
        <>
          <p>{summary}</p>
          <div className="notice">
            {t("会调用当前配置的语音服务，可能产生费用。已完成片段可复用；音色或文本变化的片段会重新合成。")}
          </div>
          <div className="modal-actions">
            <Button onClick={() => setModal(null)}>{t("取消")}</Button>
            <Button
              primary
              onClick={() =>
                run(async () => {
                  await api(`/books/${book.id}/generate`, "POST", {
                    chapter_ids: ids,
                  });
                  setModal(null);
                  go("queue");
                  reload();
                })
              }
            >
              {t("确认生成")} <ChevronRight size={16} />
            </Button>
          </div>
        </>
      ),
    });
  }
  const common = {
    run,
    notify,
    go,
    reload,
    busy,
    book,
    bookId,
    chapterId,
    setChapterId,
    voices,
    settings,
    setModal,
    playAudio: player.playAudio,
    preview,
    supportsEmotion,
    confirmGenerate,
    setNavGuard,
  };
  if (!boot)
    return (
      <div className="boot">
        <LoaderCircle className="spin" /> {t("正在打开工作室")}
      </div>
    );
  if (!boot.authenticated)
    return (
      <div className="auth-scene">
        <div className="auth-art">
          <div className="brand">
            <AudioLines />
            声页<span>.</span>
          </div>
          <div className="auth-stage">
            <div className="auth-book" aria-hidden="true">
              <small>{t("有声书工作室")}</small>
              <strong>声页</strong>
              <div className="auth-book-bars">
                <span />
                <span />
                <span />
                <span />
                <span />
              </div>
            </div>
            <div className="auth-wave" aria-hidden="true">
              {AUTH_WAVE.map((h, i) => (
                <span key={i} style={{ "--h": h, "--i": i } as CSSProperties} />
              ))}
            </div>
          </div>
          <h1>
            {t("让每一页，")}
            <br />
            {t("都有自己的声音。")}
          </h1>
          <small>{t("你的小说，你的声音，你的工作室。")}</small>
        </div>
        <div className="auth-side">
          <div className="auth-controls">
            <button
              title={theme === "dark" ? t("切换到亮色模式") : t("切换到暗色模式")}
              aria-label={theme === "dark" ? t("切换到亮色模式") : t("切换到暗色模式")}
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            >
              {theme === "dark" ? <Sun size={14} /> : <Moon size={14} />}
              {theme === "dark" ? t("亮色模式") : t("暗色模式")}
            </button>
            <button
              title={lang === "zh" ? "Switch to English" : "切换到中文"}
              aria-label={lang === "zh" ? "Switch to English" : "切换到中文"}
              onClick={() => setLang(lang === "zh" ? "en" : "zh")}
            >
              <Languages size={14} />
              {lang === "zh" ? "English" : "中文"}
            </button>
          </div>
          <form
            className="auth-form"
            onSubmit={(e) => {
              e.preventDefault();
              const d = new FormData(e.currentTarget);
              run(async () => {
                const r = await api<{ must_change_password: boolean }>(
                  "/login",
                  "POST",
                  { name: d.get("name"), password: d.get("password") },
                );
                setBoot({
                  authenticated: true,
                  mustChangePassword: r.must_change_password,
                });
              });
            }}
          >
            <h2>{t("欢迎回来")}</h2>
            <p>{t("登录后，继续上次的创作。")}</p>
            <label>
              {t("用户名")}
              <input
                name="name"
                autoComplete="username"
                required
                maxLength={60}
              />
            </label>
            <label>
              {t("密码")}
              <input
                name="password"
                type="password"
                autoComplete="current-password"
                maxLength={200}
                required
              />
            </label>
            <Button primary type="submit" disabled={busy}>
              {busy ? <LoaderCircle className="spin" size={18} /> : null}
              {t("登录")}
              <ArrowUpRight size={18} />
            </Button>
            {toast && (
              <p role="alert" className="error">
                {toast}
              </p>
            )}
          </form>
        </div>
      </div>
    );
  return (
    <>
      <aside className={"sidebar " + (menu ? "open" : "")}>
        <a
          href="#library"
          className="brand"
          onClick={(e) => {
            if (!tryGo("library")) e.preventDefault();
          }}
        >
          <AudioLines />
          声页<span>.</span>
        </a>
        <p className="brand-caption">{t("让文字，被听见")}</p>
        <nav>
          {navItems.map(([id, label, Icon]) => (
            <a
              href={"#" + id}
              key={id}
              onClick={(e) => {
                if (!tryGo(id)) e.preventDefault();
                else setMenu(false);
              }}
              className={route === id ? "active" : ""}
              aria-current={route === id ? "page" : undefined}
            >
              <Icon size={19} />
              {t(label)}
            </a>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <span className="status-dot" />
            {t("我的本地工作室")}<small>声页 · {APP_VERSION}</small>
          <button
            title={theme === "dark" ? t("切换到亮色模式") : t("切换到暗色模式")}
            aria-label={theme === "dark" ? t("切换到亮色模式") : t("切换到暗色模式")}
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
          >
            {theme === "dark" ? <Sun size={14} /> : <Moon size={14} />}
            {theme === "dark" ? t("亮色模式") : t("暗色模式")}
          </button>
          <button
            title={lang === "zh" ? "Switch to English" : "切换到中文"}
            aria-label={lang === "zh" ? "Switch to English" : "切换到中文"}
            onClick={() => setLang(lang === "zh" ? "en" : "zh")}
          >
            <Languages size={14} />
            {lang === "zh" ? "English" : "中文"}
          </button>
          <button
            onClick={() =>
              run(async () => {
                await api("/logout", "POST");
                // A live preview poll would fire into the logged-out session
                // and trigger a misleading 401 toast.
                if (previewTimer.current) clearInterval(previewTimer.current);
                previewTimer.current = null;
                player.reset();
                setBoot({ authenticated: false, mustChangePassword: false });
              })
            }
          >
            <LogOut size={14} /> {t("退出登录")}
          </button>
        </div>
      </aside>
      <div className="shell">
        <header className="topbar">
          <Button
            className="mobile-toggle"
            title={t("打开导航")}
            onClick={() => setMenu(!menu)}
          >
            <Menu size={19} />
          </Button>
          <div className="top-center">
            {t(navItems.find((n) => n[0] === route)?.[1] || "")}
          </div>
          <div className="top-right">
            {busy && (
              <span
                className="top-busy"
                role="status"
                aria-live="polite"
                title={t("正在处理请求")}
              >
                <LoaderCircle className="spin" size={16} />
                <small>{t("处理中")}</small>
              </span>
            )}
            <a
              className="brand-logo"
              href="#library"
              aria-label={t("声页 · 返回书架")}
              onClick={(e) => {
                if (!tryGo("library")) e.preventDefault();
              }}
            >
              <Logo size={36} showText={true} />
              <span className="brand-tagline">{t("让每一页，都有声音")}</span>
            </a>
          </div>
        </header>
        <main>
          {["chapters", "cast", "director", "listen", "export"].includes(route) &&
            books.length > 0 && (
              <div className="book-switch">
                <BookOpen size={15} />
                <Select
                  aria-label={t("当前书籍")}
                  value={bookId}
                  onChange={(e) => selectBook(e.target.value, route)}
                >
                  {books.map((b) => (
                    <option value={b.id} key={b.id}>
                      {b.title}
                    </option>
                  ))}
                </Select>
              </div>
            )}
          {route === "library" && (
            <Library
              {...common}
              books={books}
              selectBook={selectBook}
              go={go}
            />
          )}
          {route === "import" && (
            <ImportPage
              {...common}
              onCreated={(id) => {
                selectBook(id);
                reload();
              }}
            />
          )}
          {route === "chapters" &&
            (book ? (
              <ChaptersPage {...common} />
            ) : (
              <Empty
                title={t("还没有小说")}
                description={t("导入第一本小说，开始制作。")}
              >
                <Button primary onClick={() => go("import")}>
                  {t("导入小说")}
                </Button>
              </Empty>
            ))}
          {route === "cast" &&
            (book ? (
              <CastPage {...common} />
            ) : (
              <Empty
                title={t("先选一本小说")}
                description={t("角色表按书籍管理，从书架选择作品。")}
              >
                <Button onClick={() => go("library")}>{t("打开书架")}</Button>
              </Empty>
            ))}
          {route === "director" &&
            (book ? (
              <Director
                {...common}
                fixTarget={fixTarget}
                clearFixTarget={() => setFixTarget(null)}
              />
            ) : (
              <Empty
                title={t("先选一本小说")}
                description={t("从书架进入章节工作台，再调整朗读。")}
              >
                <Button onClick={() => go("library")}>{t("打开书架")}</Button>
              </Empty>
            ))}
          {route === "voices" && (
            <Voices
              {...common}
              favorites={favorites}
              setFavorites={setFavorites}
            />
          )}
          {route === "queue" && <Jobs {...common} />}
          {route === "listen" &&
            (book ? (
              <Listen
                {...common}
                audioMeta={player.audioMeta}
                position={player.position}
                playing={player.playing}
                togglePlay={player.togglePlay}
                seek={player.seek}
                goFixSegment={goFixSegment}
              />
            ) : (
              <Empty
                title={t("这里等待你的第一段声音")}
                description={t("先导入小说，生成章节音频。")}
              >
                <Button primary onClick={() => go("import")}>
                  {t("导入小说")}
                </Button>
              </Empty>
            ))}
          {route === "export" &&
            (book ? (
              <ExportPage {...common} />
            ) : (
              <Empty
                title={t("还没有可导出的作品")}
                description={t("完成章节生成后，可以逐章下载或批量打包。")}
              />
            ))}
          {route === "settings" &&
            (settings ? (
              <SettingsPage {...common} />
            ) : (
              <Empty
                title={t("设置暂时读不到")}
                description={t("加载数据目录信息时出错，请重试。")}
              >
                <Button primary onClick={reload}>
                  {t("重新加载")}
                </Button>
              </Empty>
            ))}
        </main>
      </div>
      <footer className="transport">
        <div className="now-playing">
          <div className="transport-icon">
            <AudioLines size={24} />
          </div>
          <div>
            {player.audioLabel}
            <small>
              {player.audioMeta ? t("声页 · 章节音频") : t("生成后可试听和下载")}
            </small>
          </div>
        </div>
        <div className="transport-middle">
          <Button
            title={t("后退 15 秒")}
            disabled={!player.audioMeta}
            onClick={() => player.seek(player.position - 15)}
          >
            <SkipBack size={17} />
          </Button>
          <Button
            className={"round-play" + (player.playing ? " playing" : "")}
            disabled={!player.audioMeta}
            title={player.playing ? t("暂停") : t("播放")}
            onClick={player.togglePlay}
          >
            {player.playing ? <Pause size={20} /> : <Play size={20} />}
          </Button>
          <Button
            title={t("前进 15 秒")}
            disabled={!player.audioMeta}
            onClick={() => player.seek(player.position + 15)}
          >
            <SkipForward size={17} />
          </Button>
          <time>{formatTime(player.position)}</time>
          <input
            type="range"
            min={0}
            max={player.audioMeta?.duration || 1}
            step={0.1}
            value={player.position}
            disabled={!player.audioMeta}
            aria-label={t("播放进度")}
            onChange={(e) => player.seek(+e.target.value)}
          />
          <time>{formatTime(player.audioMeta?.duration)}</time>
        </div>
        <div className="transport-right">
          <Select
            aria-label={t("播放倍速")}
            value={player.rate}
            onChange={(e) => player.setRate(+e.target.value)}
          >
            {[0.75, 1, 1.25, 1.5, 2].map((v) => (
              <option key={v} value={v}>
                {v}×
              </option>
            ))}
          </Select>
          <Volume2 size={17} />
          <input
            type="range"
            min="0"
            max="1"
            step=".05"
            aria-label={t("音量")}
            value={player.volume}
            onChange={(e) => player.setVolume(+e.target.value)}
          />
        </div>
        <audio {...player.audioProps(player.audioMeta?.id)} />
      </footer>
      <dialog
        ref={dialogRef}
        aria-labelledby="studio-dialog-title"
        onCancel={() => setModal(null)}
        className={
          (modal?.title?.includes(t("分章")) ? "wide " : "") +
          (modal?.title?.startsWith(t("删除")) ? "danger" : "")
        }
      >
        <div className="dialog-head">
          <h2 id="studio-dialog-title">{modal?.title}</h2>
          <Button title={t("关闭")} onClick={() => setModal(null)}>
            <X size={20} />
          </Button>
        </div>
        <div className="dialog-content">{modal?.content}</div>
      </dialog>
      {boot.mustChangePassword && (
        <PasswordDialog
          onDone={() => {
            setBoot({ authenticated: true, mustChangePassword: false });
            notify(t("密码已更新"));
          }}
        />
      )}
      {toast && (
        <div
          className="toast"
          role={toastAssertive ? "alert" : "status"}
          aria-live={toastAssertive ? "assertive" : "polite"}
        >
          {toast}
          <button onClick={() => setToast("")} aria-label={t("关闭提示")}>
            <X size={16} />
          </button>
        </div>
      )}
    </>
  );
}


createRoot(document.getElementById("root")!).render(<App />);
