# 声页 · 小说有声化工作室

逐章制作、试听和导出有声书。首版已实现实际前后端，使用深色录音工作室界面，可通过 Docker 从源码构建部署。

## 功能

- TXT / 未加密 EPUB 上传、自动分章，导入时支持编辑、拆分、合并、排序和排除章节，保留原始文件。
- 逐章或批量生成；编辑片段的文本、音色、语速、情绪和停顿；复用未变化片段，保留旧音频版本。
- 读音词典：在 AI 导演页划选正文中的词，直接修正多音字、人名、地名的读音，修正过的词在脚本中高亮；合成时自动应用，原文不改。
- 书架 AI 分析：书名支持自定义，按书名推断作者、简介与封面设计；可用生图模型（OpenAI 兼容 /images/generations）生成插画书封并自动应用。
- 生成前显示所选章节数、字数与预计成品时长；AI 书籍资料先编辑再应用，不自动改写。
- M4B 导出：单文件章节有声书（AAC + 章节导航 + 书名/作者/封面元数据），也可逐章 MP3/WAV 打 ZIP。
- 合成时自动拆分混合片段：引号内对白使用角色音色，引号外的叙述回到旁白音色；语音服务的瞬时拒绝（如 MiniMax 1002/限流）自动重试，失败报错定位到具体片段。
- 书籍级角色库管理页：登记全书角色、台词量与示例，一键绑定/更换音色并批量重生成受影响章节。
- 片段级重生成：改完某一句，只重合成那一段并就地拼接进章节音频，几秒完成，其余片段不动。
- 响度归一化：每段合成后自动对齐统一响度目标，不同角色/旁白/情绪的音量听感一致。
- 听书端：全局键盘快捷键（空格播放、J/K/L 前后 10 秒、←→ 5 秒）。
- 界面中英双语，侧栏底部一键切换，偏好记忆在本地。
- AI 情绪、语速和停顿建议，手动采纳，不自动改写原文；提供 21 种情绪风格（含妩媚、娇喘、耳语、结巴等），合成端映射为服务商支持的情绪、语速、音高与音量组合，结巴以合成期文本变换实现，兼容接口自动降级。
- AI 优化分段：本地先按引号边界把整章细分为对白/叙述单元，AI 仅标注每个单元的说话者并合并相邻同角色单元——同一段里多个角色的对话也会各自成段；旁白恒为旁白音色，角色恒为角色音色；原文逐字符校验，长章节不会超时。
- MiniMax 音色同步、收藏、短试听；兼容 `/audio/speech` 的服务可填写实际音色 ID。
- 真实波形、倍速、音量、段落定位、问题标记、记住播放进度。
- 每章 MP3/WAV 下载、按章排序的 ZIP 导出；持久化队列、暂停、取消和重试。
- 单账户、单容器、单数据目录，无需 GPU、特权模式或 Docker socket。

十个页面：书架、导入、章节工作台、角色库、AI 导演、音色库、任务队列、试听、导出、设置。

## Docker 部署

公共镜像发布在 GHCR，提供 amd64 / arm64 双架构：

```sh
docker run -d --name soundleaf -p 8780:8780 \
  -v /path/to/data:/data \
  ghcr.io/panda-995/soundleaf:latest
```

容器默认以 root 启动，入口脚本会把数据目录属主调整为 1000:1000 后降权运行；用 compose 并指定 `user` 时按指定身份直接运行。也可以继续从源码构建：

### 1. 准备目录与配置

复制 `.env.example` 为 `.env`，按需修改：

```dotenv
WEB_PORT=8780
DATA_PATH=./data
APP_UID=1000
APP_GID=1000
TZ=Asia/Shanghai
COOKIE_SECURE=false
```

| 配置 | 说明 |
| --- | --- |
| `WEB_PORT` | 宿主机端口，例如 18880；容器内固定 8780 |
| `DATA_PATH` | 宿主机普通可写文件夹，例如 /volume1/docker/soundleaf，映射到 /data |
| `APP_UID` / `APP_GID` | 默认 1000:1000，可以改为有目录权限的 NAS 普通账户 UID/GID |
| `COOKIE_SECURE` | HTTPS 反向代理访问时设 true；直接 HTTP 访问保持 false |

Linux 下以用于本项目的普通账户操作：

```sh
cp .env.example .env
mkdir -p data
id -u
id -g
```

将 `.env` 中 UID/GID 改成上面普通账户的实际数字，确保 `DATA_PATH` 文件夹允许该账户读写。NAS 可通过文件管理器授予对应账户该文件夹的读写权限。无需 `chmod 777`，无需 root 或特权容器。

**先创建并授权映射目录，再启动。** 如果 Docker 自动创建了仅 root 可写的目录，应用会因无法保存数据库而启动失败；修正目录所有者或 ACL 即可。

### 2. 构建启动

```sh
docker compose up -d --build
docker compose ps
```

访问 `http://服务器IP:8780`，使用默认账户 admin / admin 登录；首次登录会立即要求修改密码。如果更改了 WEB_PORT，请使用对应端口。

```sh
docker compose logs --tail=100 soundleaf
docker compose down
```

更新源码后再次执行 `docker compose up -d --build`。停止或重建容器不会删除映射文件夹。

### NAS 图形化容器管理

先在项目目录执行 `docker build -t soundleaf:local .`，然后创建容器：

- 镜像：`soundleaf:local`。
- 容器端口：`8780/TCP`，宿主机端口自定。
- 文件夹：NAS 普通可写文件夹 → `/data`，读写映射。
- 运行用户：默认 `1000:1000`，或有该文件夹权限的普通 UID/GID。
- 不启用特权模式，不映射设备，不使用 host 网络。

### 绿联 UGOS Pro 一键安装

提供 amd64 / arm64 双架构 UPK 安装包，从 [Releases](https://github.com/Panda-995/Soundleaf/releases/latest) 下载后，在 UGOS Pro 应用中心手动安装：

1. 安装向导中选择数据文件夹（可留空使用应用内置目录），完成安装；
2. 浏览器访问 `http://NAS的IP:8780`，默认账户 admin / admin，首次登录强制修改密码；
3. 在“设置”页填写语音服务（MiniMax 或兼容接口）与 AI 分析服务，密钥加密保存在数据目录。

详见 [ugreen/README.md](ugreen/README.md)。

### 数据与备份

```text
/data/
  studio.sqlite3       账户、书籍、章节、任务、配置和播放进度
  secret.key           配置加密密钥，必须与数据库一同备份
  sources/             原始小说
  covers/              上传封面
  audio/               各版音频与短试听
  cache/               可复用片段
  exports/             导出包
  tmp/                 导入和处理中间文件
```

备份时停止容器，完整复制映射目录，再启动。恢复时完整还原并授予运行账户读写权限。不要丢失 secret.key；SQLite 的 WAL/SHM 文件也应一并保留。

首版不自动清理历史音频和导出包。长篇制作前请预留空间，不要在任务执行期间手动删除文件。

## 连接声音和 AI

1. 在“设置 → 语音服务”填写服务、基础地址、密钥、模型、音色 ID，保存后测试。
2. 在音色库同步声音，先做短试听。
3. 如需 AI 建议，在“AI 分析”中配置兼容 `/chat/completions` 的服务；不配置 AI 也能手动制作。
4. 导入小说、确认章节并生成，在试听页检查后下载。

MiniMax 默认基础地址为 `https://api.minimax.cn/v1`。模型和音色请填写账号实际支持的值。兼容模式要求支持 `/audio/speech`，不保证任意第三方服务直接兼容；该模式不发送情绪参数。连接测试不等于实际语音合成或音质验收。

局域网服务需勾选“允许局域网或本地 HTTP 服务”。**容器内 127.0.0.1 指向容器自己**；请填写实际可达的 NAS/LAN 地址或同一 Docker 网络内的服务名。

密钥仅由服务端加密保存，不回传浏览器；能读取整个数据目录的人也能得到解密密钥。云端分析与生成会把所选文本发送给配置的服务，可能产生费用，软件不附带付费额度。

## 本地开发

需要 Python 3.11+、Node.js 22 和 FFmpeg。

```sh
python -m venv .venv
# 激活虚拟环境后执行
pip install -r requirements.lock
pip install -e ".[dev]"
cd frontend
npm ci
npm run build
cd ..
python -m uvicorn app.main:app --host 127.0.0.1 --port 8780 --workers 1 --no-access-log
```

前端开发可单独运行 `npm run dev`，API 代理到 8780。默认数据目录为 ./data，可用 DATA_DIR 覆盖。FFmpeg 优先使用 FFMPEG_PATH，其次系统安装，最后使用开发依赖 imageio-ffmpeg。

**当前必须单进程、单副本运行**，不要增加 Uvicorn workers 或让多个容器共享一个数据目录。

## 验证和后续范围

本地后端测试、静态检查、前端生产构建以及浏览器完整流程已验证。详见 [开发进度与验证](docs/开发进度与验证.md)。

集成验证使用模拟服务与合成测试音频，未调用真实付费服务。CI（`.github/workflows/check.yml`）已覆盖单元测试、静态检查、前端构建、浏览器全流程（冒烟 + 双主题三视口审计）与多架构容器构建；推送 main 时 `docker-publish` 工作流会在 amd64 / arm64 原生 runner 上构建并发布 `ghcr.io/panda-995/soundleaf` 双架构镜像，绿联 UPK 通过手动运行 `Build UGOS Pro UPK` 工作流打包并上传到 Release。

首版为单人旁白制作。角色自动识别绑定、内置本地 TTS、配乐混音、M4B、多用户协作、自动清理和导入后的章节拆分合并留待后续版本。

实际应用源码在 app/ 与 frontend/，结构与维护指南见 [ARCHITECTURE.md](ARCHITECTURE.md)。[产品计划](docs/产品与开发计划.md)、[设计规范](DESIGN.md)、prototype/ 和 output/ui/ 保留原始设计资料。
