import { useState } from "react";
import {
  AudioLines,
  Play,
  Search,
  RotateCcw,
  Heart,
} from "lucide-react";
import { Badge, Button, Empty, Heading } from "../components/ui";
import { baseSegment } from "../constants";
import { t, tf } from "../i18n";
import { api } from "../api";
import type { Common } from "../api";

export function Voices(
  p: Common & { favorites: string[]; setFavorites: (v: string[]) => void },
) {
  const [query, setQuery] = useState(""),
    [onlyFav, setOnlyFav] = useState(false),
    [selected, setSelected] = useState(""),
    [text, setText] = useState(
      t("暮色落进海面的时候，他收到了一封没有署名的信。"),
    );
  const v = p.voices.find((v) => v.id === selected) || p.voices[0];
  const filtered = p.voices.filter(
    (v) =>
      (v.name + v.description).toLowerCase().includes(query.toLowerCase()) &&
      (!onlyFav || p.favorites.includes(v.id)),
  );
  return (
    <>
      <Heading title={t("为故事挑选声音")} sub={t("同一段文字，听见不同的表达。")}>
        <Button
          disabled={p.busy}
          onClick={() =>
            p.run(async () => {
              const r = await api("/voices/refresh", "POST");
              p.reload();
              p.notify(tf("已获取 {count} 个音色", { count: r.count }));
            })
          }
        >
          <RotateCcw size={16} />
          {t("同步音色")}
        </Button>
      </Heading>
      <div className="filters">
        <Button
          className={!onlyFav ? "active" : ""}
          onClick={() => setOnlyFav(false)}
        >
          {t("全部音色")}
        </Button>
        <Button
          className={onlyFav ? "active" : ""}
          onClick={() => setOnlyFav(true)}
        >
          <Heart size={15} />
          {t("已收藏")}
        </Button>
        <div className="search">
          <Search size={16} />
          <input
            aria-label={t("搜索音色")}
            placeholder={t("搜索声音与特征")}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
      </div>
      <div className="two-columns">
        <section className="voice-list">
          {filtered.map((voice) => (
            <div
              className={"voice-row " + (v?.id === voice.id ? "selected" : "")}
              key={voice.id}
            >
              <div className="soundprint">
                <AudioLines size={26} />
              </div>
              <button
                className="voice-choice"
                onClick={() => setSelected(voice.id)}
              >
                <h3>{voice.name}</h3>
                <p>{voice.description || voice.id}</p>
              </button>
              <Button
                title={t("收藏音色")}
                onClick={() =>
                  p.run(async () =>
                    p.setFavorites(
                      await api("/voices/favorite", "POST", {
                        voice: voice.id,
                      }),
                    ),
                  )
                }
              >
                <Heart
                  size={16}
                  fill={
                    p.favorites.includes(voice.id) ? "currentColor" : "none"
                  }
                />
              </Button>
              <Button
                title={t("试听音色")}
                disabled={p.busy}
                onClick={() =>
                  p.run(() =>
                    p.preview({ ...baseSegment(text), voice: voice.id }),
                  )
                }
              >
                <Play size={17} />
              </Button>
            </div>
          ))}
          {!filtered.length && (
            <Empty
              title={t("没有匹配的音色")}
              description={t("同步服务商音色，或在设置中填写自定义音色 ID。")}
            />
          )}
        </section>
        <aside className="panel voice-detail">
          <div className="voice-art">
            <AudioLines size={90} strokeWidth={1} />
          </div>
          <h2>{v?.name || t("选择一个声音")}</h2>
          <Badge kind="ok">
            {p.supportsEmotion
              ? t("支持情绪与语速")
              : t("支持语速 · 默认情绪")}
          </Badge>
          <label>
            {t("试听文本")} <small>{text.length}/300</small>
            <textarea
              maxLength={300}
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
          </label>
          <Button
            primary
            disabled={!v || !text.trim() || p.busy}
            onClick={() =>
              p.run(() => p.preview({ ...baseSegment(text), voice: v.id }))
            }
          >
            <Play size={16} />
            {t("试听声音")}
          </Button>
          {p.book && (
            <Button
              disabled={!v || p.busy}
              onClick={() =>
                p.run(async () => {
                  await api("/books/" + p.bookId, "PUT", { voice: v.id });
                  p.reload();
                  p.notify(t("已应用到本书，已有章节音频将标记为待更新。"));
                })
              }
            >
              {tf("应用到《{title}》", { title: p.book.title })}
            </Button>
          )}
          <small>{t("短试听会使用当前语音服务并可能计费。")}</small>
        </aside>
      </div>
    </>
  );
}
