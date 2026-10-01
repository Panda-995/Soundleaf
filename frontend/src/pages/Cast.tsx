import { useEffect, useState } from "react";
import { AudioLines, Eraser, RefreshCw, TriangleAlert } from "lucide-react";
import { Select } from "../components/Select";
import { Button, Empty, Heading } from "../components/ui";
import { api, type Common } from "../api";
import { t, tf } from "../i18n";

type CastMember = {
  speaker: string;
  lines: number;
  sample: string;
  voice: string;
  bound: boolean;
};
type CastChapter = {
  id: string;
  title: string;
  position: number;
  has_audio: boolean;
  speakers: string[];
};
type CastData = {
  cast: CastMember[];
  narrator_voice: string;
  narration_lines: number;
  chapters: CastChapter[];
};

export function CastPage(p: Common) {
  const book = p.book!;
  const [data, setData] = useState<CastData | null>(null);
  useEffect(() => {
    let alive = true;
    setData(null);
    api<CastData>(`/books/${book.id}/cast`)
      .then((d) => {
        if (alive) setData(d);
      })
      .catch((e) => p.notify(e.message));
    return () => {
      alive = false;
    };
    // p.book identity changes after every reload, which refreshes the data.
  }, [p.book]);
  if (!data)
    return (
      <div className="loading">
        <RefreshCw className="spin" /> {t("正在读取角色表")}
      </div>
    );
  const affected = (member: CastMember) =>
    data.chapters.filter((c) => c.has_audio && c.speakers.includes(member.speaker));
  const setVoice = (speaker: string, voice: string) =>
    p.run(async () => {
      await api(`/books/${book.id}/cast`, "PUT", { speaker, voice });
      const d = await api<CastData>(`/books/${book.id}/cast`);
      setData(d);
      const n = d.chapters.filter(
        (c) => c.has_audio && c.speakers.includes(speaker),
      ).length;
      p.notify(
        n
          ? tf("「{speaker}」已绑定新音色，{count} 个已生成章节可重新生成以应用。", {
              speaker,
              count: n,
            })
          : tf("「{speaker}」已绑定新音色。", { speaker }),
      );
    });
  const setNarrator = (voice: string) =>
    p.run(async () => {
      await api(`/books/${book.id}`, "PUT", { voice });
      const d = await api<CastData>(`/books/${book.id}/cast`);
      setData(d);
      const n = d.chapters.filter((c) => c.has_audio).length;
      p.notify(
        n
          ? tf("旁白音色已更新，{count} 个已生成章节可重新生成以应用。", { count: n })
          : t("旁白音色已更新。"),
      );
    });
  const narratorVoice = data.narrator_voice || p.settings?.tts?.voice || "";
  // Voice bindings that the current engine's catalogue cannot resolve — they
  // appear after switching speech services and would fail generation with
  // 未知音色. Offer a one-click reset instead of a dead end.
  const staleBindings = [
    ...new Set(
      [data.narrator_voice, ...data.cast.map((m) => m.voice)].filter(
        (v) => v && !p.voices.some((x) => x.id === v),
      ),
    ),
  ];
  return (
    <>
      <Heading
        title={t("角色库")}
        sub={t("一本书的声音档案。绑定立即生效，重生成相关章节后听到新声音。")}
      />
      {staleBindings.length > 0 && (
        <section className="panel cast-stale" role="alert">
          <TriangleAlert size={19} />
          <div>
            <strong>
              {tf("{count} 个音色绑定来自其他语音服务，当前引擎无法合成。", {
                count: staleBindings.length,
              })}
            </strong>
            <p>
              {t(
                "可以逐个重新绑定，或一键清除全部绑定后从默认音色开始；已生成音频保持可播放并标记待更新。",
              )}
            </p>
          </div>
          <Button
            disabled={p.busy}
            onClick={() =>
              p.run(async () => {
                await api(`/books/${book.id}/reset-voices`, "POST");
                const d = await api<CastData>(`/books/${book.id}/cast`);
                setData(d);
                p.reload();
                p.notify(t("已清除全部音色绑定，请为角色重新选择音色。"));
              })
            }
          >
            <Eraser size={15} />
            {t("清除全部音色绑定")}
          </Button>
        </section>
      )}
      {data.cast.length ? (
        <div className="cast-list">
          <section className="panel cast-row item-in">
            <div className="cast-info">
              <strong>
                <AudioLines size={15} /> {t("旁白")}
              </strong>
              <small>{tf("{count} 段叙述 · 使用书籍默认音色", { count: data.narration_lines })}</small>
            </div>
            <div className="cast-actions">
              <Select
                aria-label={t("旁白音色")}
                value={narratorVoice}
                onChange={(e) => setNarrator(e.target.value)}
              >
                <option value="">{t("跟随语音服务默认")}</option>
                {p.voices.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.name}
                  </option>
                ))}
              </Select>
            </div>
          </section>
          {data.cast.map((m, i) => {
            const affectedCount = affected(m).length;
            return (
              <section
                className="panel cast-row item-in"
                key={m.speaker}
                style={{ animationDelay: `${Math.min((i + 1) * 45, 270)}ms` }}
              >
                <div className="cast-info">
                  <strong>{m.speaker}</strong>
                  <small>
                    {tf("{count} 段台词", { count: m.lines })}{m.bound ? t(" · 已绑定") : t(" · 暂用章节多数票")}
                  </small>
                  {m.sample && <p>{m.sample}</p>}
                </div>
                <div className="cast-actions">
                  <Select
                    aria-label={tf("为{speaker}选择音色", { speaker: m.speaker })}
                    value={m.voice}
                    onChange={(e) => setVoice(m.speaker, e.target.value)}
                  >
                    <option value="">{t("跟随章节多数票")}</option>
                    {p.voices.map((v) => (
                      <option key={v.id} value={v.id}>
                        {v.name}
                      </option>
                    ))}
                  </Select>
                  {affectedCount > 0 && (
                    <Button
                      className="small"
                      onClick={() =>
                        p.confirmGenerate(
                          affected(m).map((c) => c.id),
                        )
                      }
                    >
                      <RefreshCw size={14} />
                      {tf("重生成 {count} 章", { count: affectedCount })}
                    </Button>
                  )}
                </div>
              </section>
            );
          })}
        </div>
      ) : (
        <Empty
          title={t("还没有识别到角色")}
          description={t(
            "在 AI 导演页对章节执行 AI 分析并采纳后，出现的角色会自动登记在这里。",
          )}
        >
          <Button onClick={() => p.go("director")}>{t("打开 AI 导演")}</Button>
        </Empty>
      )}
    </>
  );
}
