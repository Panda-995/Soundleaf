import { useCallback, useEffect, useState } from "react";
import { ArrowUpRight, CircleAlert, Download, Folder, MicVocal, Save, Trash2, X } from "lucide-react";
import { Select } from "../components/Select";
import { PasswordForm } from "../components/PasswordChange";
import { About } from "../components/About";
import { Button, Heading } from "../components/ui";
import { api, type Common, type LocalModel } from "../api";
import { t } from "../i18n";

function fmtSize(bytes: number) {
  return bytes >= 1024 ** 3 ? `${(bytes / 1024 ** 3).toFixed(1)} GB` : `${Math.round(bytes / 1024 ** 2)} MB`;
}

/** Model manager for the offline engine: lists the downloadable catalog and
 * polls while a download is running (the backend reports live progress). */
function LocalModels({ run }: { run: Common["run"] }) {
  const [models, setModels] = useState<LocalModel[]>([]);
  const [dependency, setDependency] = useState<string | null>(null);
  const load = useCallback(
    () =>
      api<{ models: LocalModel[]; dependency: string | null }>("/local/models").then((r) => {
        setModels(r.models);
        setDependency(r.dependency);
      }),
    [],
  );
  useEffect(() => {
    // Poll failures stay silent (last state remains, next tick self-heals);
    // user-initiated actions go through run() and surface errors as toasts.
    load().catch(() => {});
  }, [load]);
  useEffect(() => {
    if (!models.some((m) => m.state === "downloading")) return;
    const id = window.setInterval(() => load().catch(() => {}), 1500);
    return () => window.clearInterval(id);
  }, [models, load]);
  const stateLabel = (m: LocalModel) => {
    if (m.state === "ready") return t("已就绪");
    if (m.state === "downloading" && m.total) {
      return `${t("下载中")} ${Math.min(100, Math.round(((m.received || 0) / m.total) * 100))}%`;
    }
    if (m.state === "error") return `${t("下载失败")}：${m.error || ""}`;
    return fmtSize(m.size);
  };
  return (
    <div className="local-models">
      <h3>{t("本地模型")}</h3>
      <p className="muted">
        {t("模型下载到数据目录，一次下载永久可用；合成全程在本机 CPU 完成，文本不会发往云端。")}
      </p>
      {dependency && (
        <p className="notice">
          {t("本机缺少本地引擎依赖（sherpa-onnx）；官方 Docker 镜像已内置，自建环境需先安装。")}
        </p>
      )}
      {models.map((m) => (
        <div className={"model-row " + m.state} key={m.id}>
          <div className="model-info">
            <h4>{m.name}</h4>
            <p>{m.description}</p>
            <p className="muted">{stateLabel(m)}</p>
            {m.state === "downloading" && (
              <progress value={m.received || 0} max={m.total || m.size} aria-label={t("下载进度")} />
            )}
          </div>
          <div className="model-actions">
            {m.state !== "ready" && m.state !== "downloading" && (
              <Button disabled={!!dependency} onClick={() => run(() => api(`/local/models/${m.id}/download`).then(load))}>
                <Download size={16} />
                {t("下载")}
              </Button>
            )}
            {m.state === "downloading" && (
              <Button onClick={() => run(() => api(`/local/models/${m.id}/abort`).then(load))}>
                <X size={16} />
                {t("取消下载")}
              </Button>
            )}
            {m.state === "ready" && (
              <Button title={t("删除模型文件")} onClick={() => run(() => api(`/local/models/${m.id}`, "DELETE").then(load))}>
                <Trash2 size={16} />
              </Button>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

export function SettingsPage(p: Common) {
  // main.tsx only mounts this page once settings have loaded.
  const settings = p.settings!;
  const [tab, setTab] = useState("tts");
  const [draft, setDraft] = useState<any>({ ...settings.tts, api_key: "" });
  const local = tab === "tts" && draft.provider === "local";
  const [result, setResult] = useState("");
  useEffect(() => {
    if (["tts", "ai"].includes(tab)) setDraft({ ...settings[tab as "tts" | "ai"], api_key: "" });
    if (tab === "notify")
      setDraft({ enabled: false, kind: "ntfy", url: "", ...(settings.notify || {}) });
  }, [tab, p.settings]);
  useEffect(() => setResult(""), [tab]);
  const change = (key: string, value: string | boolean) =>
    setDraft({ ...draft, [key]: value });
  // Switching providers: to the local engine presets a valid built-in voice
  // so the saved configuration is usable immediately (the backend normalizes
  // this too); back to a cloud service restores the remembered connection so
  // nothing has to be retyped.
  const changeProvider = (value: string) =>
    setDraft((d: any) => {
      if (value === "local") {
        return { ...d, provider: value, ...(!/^[kc]:/.test(d.voice || "") ? { voice: "k:3" } : {}) };
      }
      if (d.provider === "local" && p.settings?.tts_cloud?.base_url) {
        const cloud = p.settings.tts_cloud;
        return {
          ...d,
          provider: value,
          base_url: cloud.base_url,
          model: cloud.model || d.model,
          voice: cloud.voice || d.voice,
          allow_local: !!cloud.allow_local,
        };
      }
      return { ...d, provider: value };
    });
  return (
    <>
      <Heading title={t("设置")} sub={t("连接声音，管理你的工作室。")} />
      <div className="tabs">
        {[
          ["tts", "语音服务"],
          ["ai", "AI 分析"],
          ["notify", "完成通知"],
          ["storage", "数据存储"],
          ["account", "账户"],
          ["about", "关于"],
        ].map(([id, label]) => (
          <button
            className={tab === id ? "active" : ""}
            onClick={() => setTab(id as string)}
            key={id}
          >
            {t(label)}
          </button>
        ))}
      </div>
      {tab === "about" ? (
        <About />
      ) : (
      <div className="two-columns">
        <section className="panel settings-panel">
          {tab === "notify" ? (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                p.run(async () => {
                  await api("/settings/notify", "PUT", draft);
                  setResult(t("通知设置已保存"));
                });
              }}
            >
              <h2>{t("生成完成通知")}</h2>
              <p>{t("本书全部章节生成完成后，推送一条通知到你的设备。")}</p>
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={!!draft.enabled}
                  onChange={(e) => change("enabled", e.target.checked)}
                />
                {t("启用完成通知")}
              </label>
              <label>
                {t("通知方式")}
                <Select
                  aria-label={t("通知方式")}
                  value={draft.kind}
                  onChange={(e) => change("kind", e.target.value)}
                >
                  <option value="ntfy">ntfy</option>
                  <option value="bark">Bark</option>
                  <option value="serverchan">Server酱</option>
                  <option value="webhook">Webhook</option>
                </Select>
              </label>
              <label>
                {t("推送地址")}
                <input
                  type="url"
                  required
                  value={draft.url}
                  onChange={(e) => change("url", e.target.value)}
                  placeholder={
                    draft.kind === "bark"
                      ? t("https://api.day.app/你的设备Key")
                      : draft.kind === "serverchan"
                        ? t("https://sctapi.ftqq.com/你的Key")
                        : draft.kind === "webhook"
                          ? t("https://你的服务器/接收地址")
                          : t("https://ntfy.sh/你的主题名")
                  }
                />
              </label>
              <div className="actions">
                <Button type="submit" primary disabled={p.busy}>
                  <Save size={16} />
                  {t("保存设置")}
                </Button>
                <Button
                  disabled={p.busy}
                  onClick={() =>
                    p.run(async () => {
                      await api("/settings/notify", "PUT", draft);
                      const r = await api("/settings/notify/test", "POST");
                      setResult(r.message);
                    })
                  }
                >
                  {t("发送测试通知")}
                </Button>
              </div>
              {result && (
                <p className="connection-result" role="status">
                  {result}
                </p>
              )}
              <div className="notice">
                {t("通知在本书最后一个生成任务完成后发送，包含全书完成进度。")}
              </div>
            </form>
          ) : tab === "account" ? (
            <>
              <h2>{t("修改密码")}</h2>
              <p>{t("修改登录声页时使用的密码，至少 8 位。")}</p>
              <PasswordForm onSaved={() => p.notify(t("密码已更新"))} />
            </>
          ) : tab === "storage" ? (
            <>
              <Folder size={32} className="accent" />
              <h2>{t("数据都在你的目录里")}</h2>
              <div className="summary-line">
                <span>{t("持久目录")}</span>
                <code>{settings.data_dir}</code>
              </div>
              <div className="summary-line">
                <span>{t("磁盘可用")}</span>
                <b>{(settings.free_bytes / 1024 ** 3).toFixed(1)} GB</b>
              </div>
              <p className="notice">
                {t(
                  "数据库、原小说、音频、导出和加密密钥均保存在此目录。备份时建议先停止容器，再完整复制整个目录。",
                )}
              </p>
              <p className="muted">
                {t(
                  "容器数据路径为 /data，可映射到 NAS 的普通可写文件夹。服务端口为 8780，可映射到其他主机端口。",
                )}
              </p>
            </>
          ) : (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                p.run(async () => {
                  const { has_key, ...body } = draft;
                  await api("/settings/" + tab, "PUT", body);
                  setResult(t("设置已保存"));
                  p.reload();
                });
              }}
            >
              <h2>{tab === "tts" ? t("语音合成服务") : t("AI 内容分析")}</h2>
              <p>
                {tab === "tts"
                  ? local
                    ? t("声音在本机离线生成，无需联网与 API 密钥。")
                    : t("声音由你选择的服务生成，NAS 无需 GPU。")
                  : t("AI 提出朗读节奏建议，原文始终保留。")}
              </p>
              {tab === "tts" && (
                <label>
                  {t("服务类型")}
                  <Select
                    aria-label={t("服务类型")}
                    value={draft.provider}
                    onChange={(e) => changeProvider(e.target.value)}
                  >
                    <option value="minimax">MiniMax</option>
                    <option value="compatible">{t("兼容 /audio/speech 接口")}</option>
                    <option value="local">{t("本地离线引擎（无需联网）")}</option>
                  </Select>
                </label>
              )}
              {local && <LocalModels run={p.run} />}
              {!local && (
                <>
                  <label>
                    {t("API 基础地址")}
                    <input
                      type="url"
                      required
                      value={draft.base_url}
                      onChange={(e) => change("base_url", e.target.value)}
                      placeholder={t("https://服务地址/v1")}
                    />
                  </label>
                  <label>
                    {t("API 密钥")}
                    <input
                      type="password"
                      autoComplete="new-password"
                      value={draft.api_key}
                      onChange={(e) => change("api_key", e.target.value)}
                      placeholder={
                        draft.has_key
                          ? t("已保存，留空保持不变")
                          : t("输入服务密钥；本地服务可留空")
                      }
                    />
                  </label>
                  <label>
                    {t("模型名称")}
                    <input
                      required
                      value={draft.model}
                      onChange={(e) => change("model", e.target.value)}
                      placeholder={tab === "tts" ? "speech-2.6-hd" : t("服务支持的模型名称")}
                    />
                  </label>
                </>
              )}
              {tab === "ai" && (
                <label>
                  {t("生图模型（可选，用于 AI 书封）")}
                  <input
                    value={draft.image_model || ""}
                    onChange={(e) => change("image_model", e.target.value)}
                    placeholder={t("服务支持的图片模型，如 seedream / gpt-image-1")}
                  />
                </label>
              )}
              {tab === "tts" && !local && (
                <label>
                  {t("默认音色 ID")}
                  <input
                    required
                    value={draft.voice}
                    onChange={(e) => change("voice", e.target.value)}
                    placeholder={t("填写实际 voice_id")}
                  />
                </label>
              )}
              {tab === "ai" || !local ? (
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={draft.allow_local}
                    onChange={(e) => change("allow_local", e.target.checked)}
                  />
                  {t("允许局域网或本地 HTTP 服务")}
                </label>
              ) : null}
              <div className="actions">
                <Button type="submit" primary disabled={p.busy}>
                  <Save size={16} />
                  {t("保存设置")}
                </Button>
                <Button
                  disabled={p.busy}
                  onClick={() =>
                    p.run(async () => {
                      const r = await api("/settings/" + tab + "/test", "POST");
                      setResult(r.message);
                      // 不 reload：测试不改变任何数据，重建 draft 会丢掉
                      // 用户填到一半的表单。
                    })
                  }
                >
                  {t("测试已保存的配置")}
                </Button>
              </div>
              {result && (
                <p className="connection-result" role="status">
                  <CircleAlert size={15} />
                  {result}
                </p>
              )}
              <div className="notice">
                {local
                  ? t("本地引擎暂不支持情绪调节（情绪会体现为轻微语速变化）；克隆音色在音色库页创建。")
                  : t("云端分析或合成会将所选文本发送到对应服务商。兼容语音接口仅支持音色和语速，情绪调整需使用支持该能力的引擎。")}
              </div>
            </form>
          )}
        </section>
        <aside>
          <div className="panel onboarding">
            <h3>{t("开始制作，只需三步")}</h3>
            <ol>
              <li>
                <span>1</span>
                <div>
                  <h3>{t("连接声音")}</h3>
                  <p>{t("保存服务配置，获取可用音色。")}</p>
                </div>
              </li>
              <li>
                <span>2</span>
                <div>
                  <h3>{t("听一小段")}</h3>
                  <p>{t("用短试听确认声音与节奏。")}</p>
                </div>
              </li>
              <li>
                <span>3</span>
                <div>
                  <h3>{t("生成章节")}</h3>
                  <p>{t("选定章节，逐章完成制作。")}</p>
                </div>
              </li>
            </ol>
            <Button onClick={() => p.go("voices")}>
              {t("去音色库试听")}
              <ArrowUpRight size={15} />
            </Button>
          </div>
          <div className="panel local-panel">
            <MicVocal size={28} />
            <h3>{t("轻量运行，持久保存")}</h3>
            <p>{t("普通容器权限 · 一个数据目录 · 一个 Web 端口")}</p>
          </div>
        </aside>
      </div>
      )}
    </>
  );
}
