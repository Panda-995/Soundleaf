# 声页 · 架构与维护指南

> 2026-09 更新：前端已从 3441 行单文件拆分为模块化结构，后端结构未变。
> 本文档说明各模块职责、数据流向与常见维护场景的操作路径。

## 总体形态

```
浏览器 (React + Vite, hash 路由)
  │  fetch /api/*  (携带 X-Soundleaf 头 + 会话 Cookie)
  ▼
FastAPI 单进程 (app/main.py)
  ├── SQLite (data/studio.sqlite3, WAL)  ← store.py：唯一 DB 访问层
  ├── Worker 线程 (worker.py)：唯一消费任务队列的地方
  ├── FFmpeg 子进程 (audio.py)：转码 / 拼接 / 峰值提取
  ├── 本地引擎 (local_tts.py)：sherpa-onnx CPU 合成 + 模型下载器（可选，离线）
  └── httpx (providers.py)：MiniMax TTS / 兼容接口 / AI 分析
        ▼
data/ 目录：studio.sqlite3 · secret.key · sources/ audio/ cache/ exports/ covers/ tmp/ clones/ local-models/
```

**三条铁律**（改动前先读）：

1. 单进程单 worker——不要加 uvicorn workers、不要开第二个容器共用数据目录。
2. 所有 AI/合成调用都是异步任务（jobs 表），HTTP 请求只负责入队；网络不确定时进入"结果待确认"，绝不自动重发可能已计费的请求。
3. AI 输出永不直接采用：分段拼接逐字符校验、分析逐项降级、音色经书级角色表绑定，最后在合成端再兜底一次。

## 前端结构 (frontend/src/)

| 文件 | 行数 | 职责 |
| --- | --- | --- |
| `main.tsx` | ~820 | App 根：登录页（封面+波形品牌场景）/会话/路由/书籍选择/主题/Toast/Modal，组装各页面 |
| `api.ts` | ~165 | `api()` fetch 封装、全部类型（Segment/Book/BookSummary/SettingsShape 等；书列表的 `chapters` 是数量、书籍详情是数组，分别用 BookSummary / Book 表达） |
| `player.ts` | ~150 | `usePlayer`：播放器状态、playAudio 竞态守卫、进度保存、audio 元素接线 |
| `constants.ts` | ~125 | 导航项、情绪表、状态文案、formatTime、时长预估、segmentIndexAt、baseSegment、collectSpeakers |
| `i18n.ts` + `locales/` | ~730 | 极简 zh/en 国际化：中文原文作词典键，`t()`/`tf()` 在 zh 模式原样返回（渲染字节不变）；四份词典 core/groupA/B/C 合并约 500 词条；语言存 localStorage，侧栏底切换 |
| `components/ui.tsx` | ~210 | Button/Cover/Badge/Logo/Heading/Empty/Wave（波形已降采样至 ≤600 根） |
| `components/Select.tsx` | ~110 | Radix 下拉（Portal 挂载后解析最近的 dialog，解决 top-layer 遮挡） |
| `components/Pronounce.tsx` | ~165 | 读音修正：划选正文弹窗 + 词典词高亮渲染 |
| `components/BookAiModal.tsx` | ~150 | 书架 AI 分析弹窗内容（多阶段表单，状态局部化保证输入法安全） |
| `components/PasswordChange.tsx` | ~115 | 改密表单（设置页「账户」标签复用）+ 首次登录强制改密弹窗（不可关闭，Escape 被阻止——安全流程例外） |
| `components/About.tsx` | ~90 | 设置「关于」标签：项目介绍、合规入口（外链 `/privacy-policy.html` 隐私政策与个人信息"双清单"，绿联上架要求）、开发者信息 |
| `pages/*.tsx` | 10 个 | Library / Import / Chapters(含分章预览) / Cast(角色库) / Director / Voices / Queue / Listen / Export / Settings |

**复杂度洼地**：拆分后最大的文件是 `pages/Director.tsx`（~910 行：脚本编辑器 + 片段参数 + 一条共享的 analyze/restructure 轮询 + 片段重生成轮询 + 划选读音修正）。新增轮询类能力时优先扩展它的共享轮询模式，不要再复制 effect。

**数据流**：App 顶层持有 `books/settings/voices/book/chapterId`，通过 `common` prop bag 下发（run/notify/go/reload/busy/playAudio/confirmGenerate 等）。页面内局部状态不外抛。

**新增页面**：在 `pages/` 建组件 → main.tsx 的 route 条件渲染区加一行 → `navItems` 加导航项。若需要播放器/确认生成等能力，从 `common` 取，不要自己再建实例。

**新增情绪/音色风格**：改 `app/providers.py` 的 `EMOTION_STYLES`（只允许服务商情绪枚举 + 轻微语速倾向，不要动音高/音量——那是"同角色换声"问题的根源），同步 `frontend/src/constants.ts` 的 `emotions` 标签表。

## 后端结构 (app/)

| 文件 | 职责 | 关键约定 |
| --- | --- | --- |
| `main.py` | 全部 HTTP 路由 + 会话/CSRF/大小限制/CSP 中间件 | 数据目录为空时预置默认账户 admin/admin；`/api/login` 与 `/api/bootstrap` 带 `must_change_password`（默认密码未改即 true，前端据此强制弹改密框；校验结果按用户缓存于进程内存）；`POST /api/account/password` 校验当前密码后更新（新密码 ≥8 位，与旧 `Login` 模型下限一致，登录接口因默认密码仅 5 位放宽到 ≥1），有独立失败限速并吊销其他设备的会话；写操作必须带 `X-Soundleaf: 1`；章节保存用 revision 乐观锁；同类任务入队去重全部包在 `BEGIN IMMEDIATE` 事务里（查重+插入原子）；generate 在计费前拒绝超 20 万字的章节；响应带 CSP（`default-src 'self'`，style 允许内联属性，媒体限 self/blob）；TTS provider 白名单 `minimax`/`compatible`/`local`，音色白名单（书籍旁白与 cast 绑定）对 local 走 `voice_catalog()` 活动目录 |
| `worker.py` | 任务消费、清理、音色解析 | `resolved_segment` 是音色唯一真相：无引号文本→强制旁白默认音色；角色→书级 cast → 章节多数票（`top_vote`）→ 段内值；缓存键含解析后音色（tts-v2）；regen 的停顿按书籍风格缩放，与整章生成同一公式；主循环有兜底 catch，状态写失败也不会杀死线程 |
| `providers.py` | 服务商调用与 AI 协议 | `request()` 无隐式重试（Rejected 仅 429/5xx 及 MiniMax 1002/1026/1027 退避；synthesize 显式 retries=2）；`EMOTION_STYLES` 禁止音高/音量偏移；restructure 的 `response_format` 降级仅在 400 时重试；`provider == "local"` 分支委托给 local_tts（情绪同样只保留语速倾向），`local_identity()` 给缓存键补充本地引擎文件身份，云端配置返回 `{}` 保持旧 digest 不变 |
| `local_tts.py` | 本地离线引擎（2026-10 新增） | sherpa-onnx CPU 推理（延迟导入，缺依赖时报可读错误）；模型目录 Kokoro v1.1 中英（int8 优先/完整版，103 内置音色）+ ZipVoice 克隆（int8 蒸馏 + vocos 24k vocoder）；模型按需下载到 `data/local-models/<id>/`，`meta.json` + verify 通配（含 espeak-ng-data 目录）标记完整下载；克隆音色存 `data/clones/<hash>.wav`（ffmpeg 转 24k 单声道）+ settings key `clones`（加密），id=音频内容+原文哈希 → 换参考音频自然产生新缓存身份；音色 ID 契约：`k:<sid>`（v1.1-zh：0-2 英女、3-57 中女、58-102 中男）、`c:<hash>`；旁白默认 `k:3`；`SOUNDPAGE_TTS_MIRROR` 环境变量可替换 GitHub releases 下载前缀 |
| `store.py` | SQLite + Fernet 加密设置 | 全部建表 `CREATE TABLE IF NOT EXISTS`（老数据目录自动迁移）；`store.file` 防路径穿越；`store.job(..., db=)` 可加入外部事务实现原子入队 |
| `importer.py` | TXT/EPUB 解析 | 章节标题正则、EPUB 加密/路径/体积防护（总量 200MB、单资源 30MB） |
| `audio.py` | FFmpeg 封装 | `metadata()` 峰值已归一化 ≤2400 点；`convert()` 超时可随时长缩放；`concatenate`/`splice_segment` 有 WAV 容量护栏（MAX_WAV_FRAMES ≈ 24 小时，超限报错而非产出损坏文件）；audioop 在 Python 3.13 有纯 Python 回退 |
| `security.py` | URL 校验 | 拒绝 userinfo/内网网段（allow_local 例外） |
| `cover.py` | SVG 封面渲染 | 按配色/氛围绘制 2:3 书封（无生图模型时的后备方案），供 cover 接口直接以 image/svg+xml 下发；AI 生图封面走 providers.generate_cover_image（PNG/JPG） |

**任务类型**：`generate`（章节合成；保存章节只会学习未绑定的新角色进 cast，不覆盖既有绑定）、`regen_segment`（片段级就地重合成：替换该段 PCM、平移时间轴、按 revision 提升；允许在编辑保存后对旧音频执行——这正是它的用途——切片基于音频自带 timeline，提升仍有 revision 守卫）、`preview`（片段试听，chapter_id 为空，24h 过期）、`analyze`（逐段角色/情绪建议）、`restructure`（AI 优化分段）、`analyze_chapters`（章节边界识别）、`analyze_book`（书名可自定义，推断作者/简介/封面设计，结果存 job payload.meta）、`generate_cover`（生图模型经 /images/generations 绘制书封并自动应用）、`export`（mp3/wav 打 ZIP，m4b 生成单文件章节有声书）。

**读音词典**：`dict` 表按书存储"词→替换写法"，`apply_pronunciation` 在送合成前应用（最长词优先），脚本原文不改；修改词条只会提升包含该词且有音频的章节 revision。UI 在 AI 导演页：划选正文词语弹出修正框（`components/Pronounce.tsx`），修正过的词在正文里虚线高亮。

**M4B 导出**：`audio.build_m4b` 用 concat demuxer 拼接章节 PCM → AAC 96k，FFMetadata 写章节标记，嵌入书名/作者与位图封面（SVG 封面 FFmpeg 无法解码，自动跳过）。下载文件名取真实后缀。

## 数据生命周期（worker.cleanup，每 6 小时）

- 终态任务（succeeded/failed/cancelled/needs_review）：保留 7 天后删除（payload 可达数 MB）。
- 未确认导入 + 其 source 文件：48 小时。
- 试听音频（chapter_id 为空的 audio 行 + wav/mp3）：24 小时。
- 过期会话：立即删。
- 正式章节音频版本：**暂不自动清理**（见路线图）。
- 合成缓存（cache/）：按容量 LRU 淘汰（`SOUNDPAGE_CACHE_GB`，默认 2GB，0 关闭）；最近 6 小时内写入的条目永不触碰（刚做完的书保持可低成本重生成）。条目是摘要寻址的纯备忘，删除只损失一次重合成。
- 合成缓存统一响度：`audio.normalize_loudness` 在写入缓存前把 RMS 拉到共享目标（峰值安全、静音跳过），跨角色/跨情绪听感一致。
- 段间微淡入淡出：`audio.concatenate` 对每个片段首尾做约 5ms 线性淡变（峰值安全），消除拼接接缝的咔哒声；片段级重生成的替换音频同样处理。

## 常见维护场景

- **"某角色声音变了/旁白串音"**：先查 `data/studio.sqlite3` 的 `cast` 表与生成任务 payload 的 segments（speaker/voice 分布），再用 `resolved_segment` 复现解析结果。生成端规则：无引号→旁白默认音色；有引号→cast → 章节多数票 → 段内值。
- **换 TTS 参数后想强制重合成**：升级 `worker.py` 缓存键版本号（`tts-v2` → `tts-v3`），不要手删缓存目录。注意：新增本地引擎时**没有**升版本——缓存 options 里的 `local_engines` 键只对 `provider=local` 出现，云端配置的 digest 保持字节不变（老缓存不会失效重计费）；本地引擎的模型变体/克隆内容变化由 `local_tts.signature` 与 `c:<hash>` 音色 ID 覆盖。
- **本地引擎相关**：模型状态/下载/删除走 `/api/local/models*`，克隆上传/删除走 `/api/voices/clone*`；保存 local 配置会清空 base_url/model（防串入缓存身份）并把无效默认音色归一为 `k:3`，同时把被替换的云端连接快照进 settings key `tts_cloud`（GET /api/settings 以 `tts_cloud` 透出、不含 api_key）——前端切回云服务时自动回填，无需重填；Kokoro 音色名目前是"中文女声 N"式通用标签（sid 名未随模型分发），选音色靠试听。
- **跨引擎音色绑定**：换语音服务后书籍里旧的音色引用（books.voice、cast 行、片段 voice 字段）会令生成报"未知音色"——这是有意的响亮失败（绝不静默换声）。恢复路径：角色库页会自动显示告警条（统计不在当前目录的绑定数），`POST /api/books/{id}/reset-voices` 一键清除全部引用（旁白置空、删 cast 行、片段 voice 清空、revision+1、清 suggestion、有声章节填满 stale_segments、cast_version+1 标记旧音频待更新），之后按当前引擎重新绑定即可。
- **改 AI 提示词**：分段/分析分别在 `providers.py` 的 `restructure_chapter` / `analyze`；改完必须跑 `tests/test_studio.py`（对 AI 输出协议有强断言）。
- **调试 AI 返回**：所有 AI 响应都经 `json_result`/`_coerce_json`（剥 think 块/围栏），失败信息以"AI 返回…"开头。

## 验证清单（改动后必跑）

```sh
.venv/Scripts/python -m ruff check app tests
# basetemp 的父目录必须先存在（pytest 只创建最后一级；CI 同理先 mkdir）
mkdir -p .pytest_tmp && .venv/Scripts/python -m pytest tests/ -q --basetemp=".pytest_tmp/run"
cd frontend && npm run build && cd ..
# 集成回归（需两个终端）
.venv/Scripts/python tests/ui_fixture.py     # 终端 1：8781 应用 + 18781 模拟服务商
node scripts/browser-smoke.cjs               # 终端 2：12 项端到端
node scripts/ui-audit.cjs                    # 双主题 × 3 视口 + 焦点/触控/对比度
```

## 已知取舍与遗留

- 界面支持中英切换（侧栏底部）；服务端错误消息仍为中文原文（后端 i18n 未做，`e.message` 直显）。语言切换时已打开的弹窗/Toast 保留旧语言，重新打开即更新。
- `main.tsx` 仍持有全局 books/settings 与 `common` prop bag：播放器已抽出（player.ts），下一步可把 dirty 守卫上提消掉"切书丢编辑"。
- 正式章节音频版本无自动清理（cache/ 已有容量淘汰，音频版本保留全部历史供回放）。
- 孤儿对账（worker.sweep_orphans，随 6h cleanup 周期并在启动后首轮执行）：删除 audio/ 与 exports/ 中无 DB 行的文件（生成/重生成/导出在"写文件之后、INSERT 之前"失败或取消的残留）、清空 tmp/ 全部内容、回收 cache/*.norm 临时文件。cleanup 与任务消费同线程，扫描期间绝无任务在写。
- 登录/改密失败限速与默认密码校验缓存均记录为进程内存（重启即清，单用户场景可接受）。
- Jobs 页 2s 轮询在无任务时也在跑（自托管单用户可接受，可做退避）。
- 情绪标签表前后端各一份（`constants.ts` / `EMOTION_STYLES`），新增情绪需两处同步。
- SSRF 校验存在 DNS rebinding 时序窗：`validate_url` 解析一次、httpx 建连再解析一次。自托管单用户下暴露面小；彻底修复需要按校验过的 IP 建连（SNI/证书处理复杂），暂以文档记录。
- `preview` 与 `export` 入队无去重（短试听/导出允许重复提交，成本可控）；其余五类任务的查重+插入已原子化。
- 设置里的密钥一旦保存无法用空值清空（空值语义是"保留旧值"）。
- 关闭时 worker join 仅 5 秒，超时的 FFmpeg 子进程与 .tmp 文件由孤儿对账周期回收（见数据生命周期）。
- 通知 webhook（ntfy/Bark 等）按用户自配 URL 直发，不经 `validate_url`（自 SSRF 属预期）。
- 本地引擎（2026-10）：模型从 GitHub releases 下载（断点续传 + 5 次重试；同次下载内的中断会从已收字节继续，重开应用后重新下载），国内网络慢时启动前设 `SOUNDPAGE_TTS_MIRROR=<前缀>`（ghproxy 风格，拼在完整原始 URL 前，如 `https://ghfast.top`）；Kokoro 音色标签为通用编号名（模型包不含 sid→名字映射，待后续带真实试听后补充）；ZipVoice 的 `speed` 参数对 flow-matching 模型可能无效（sherpa-onnx 透传，不报错）；本地合成无情绪参数，情绪按兼容接口同款策略降级为语速。
- `_model_cwd` 会在本地合成期间临时修改进程 cwd（espeak-ng 的 Windows 绝对路径缺陷所致）：其正确性依赖"单 worker 线程 + 全工程绝对路径访问"两个不变量——新增后台线程或相对路径文件操作前必读 `app/local_tts.py` 的 docstring。
