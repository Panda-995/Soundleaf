# 声页 Soundleaf 绿联 UGOS Pro 应用包

此目录保存声页（Soundleaf）的绿联 UGOS Pro 打包配置，支持 `amd64` 与 `arm64`。应用包基于项目公开的多架构 Docker 镜像制作，应用 ID 为 `com.panda.soundleaf`，当前版本为 `1.1.0`（构建号 `0001`）。

## 应用信息

- 开发者：熊猫不是猫QAQ
- 发布者：熊猫不是猫QAQ
- 源码：https://github.com/Panda-995/Soundleaf
- 许可协议：https://github.com/Panda-995/Soundleaf/blob/main/LICENSE
- 隐私政策：https://github.com/Panda-995/Soundleaf/blob/main/frontend/public/privacy-policy.html
- 问题反馈：https://github.com/Panda-995/Soundleaf/issues

## 安装与数据文件夹

1. 从 Release 下载符合设备架构的 UPK，在 UGOS Pro 应用中心选择手动安装。
2. 在安装配置的“数据文件夹 / Data folder”中选择有读写权限的文件夹；选择共享文件夹时，先在 UGOS Pro 应用设置中授权本应用访问该目录。数据库、原始小说、音频成品与导出包都保存在此处。该选项可留空；留空使用应用内置的 `./data` 目录。
3. 建议为应用选择一个专用文件夹，不要与其他应用共用。安装向导允许随时改选文件夹。
4. 安装后浏览器输入 `http://NAS的IP:8780` 访问。默认账户 `admin / admin`，首次登录会强制修改密码；语音服务（MiniMax 或兼容接口）与 AI 分析服务在“设置”页填写，密钥加密保存在数据目录中。

升级时保持数据文件夹选项与原版一致即可；更换目录前先停用应用，把原数据目录的全部内容（包括 `studio.sqlite3`、`secret.key` 及 SQLite 的 WAL/SHM 文件）复制到新目录，确认应用拥有读写权限后再修改文件夹配置并启动。文件夹选择仅改变挂载位置，不会自动搬迁旧文件。`secret.key` 必须与数据库一同迁移，否则已保存的服务密钥无法解密。一个数据目录只供一个声页实例使用。

### Installation and data folder

Install the UPK for your NAS architecture. In the installation wizard, use **Data folder** to select a writable folder for the database, source novels, audiobook files and exports; authorize the app for shared folders in UGOS Pro settings. Leave the folder blank to use the app-internal `./data` directory. After installation, open `http://NAS-IP:8780`, sign in with `admin / admin` (a password change is forced on first login) and configure your speech and AI services in Settings. To move the data folder later, stop the app and copy the whole directory including `studio.sqlite3` and `secret.key`.

The Compose source contains Go template directives in YAML comments for UGOS Pro packaging. Use the UPK for this installation flow; for plain Docker deployments, use the repository's normal Compose file and set its host-side bind path.

## 构建方式

在 GitHub Actions 中手动运行 `Build UGOS Pro UPK` 工作流。工作流会分别拉取 `1.1.0-amd64`、`1.1.0-arm64` 不可变镜像，使用绿联官方 `ugcli` 校验项目并生成两个 UPK 安装包，同时生成 `SHA256SUMS-UPK`；指定 Release tag 时自动上传到对应 Release。

本地生成的镜像归档和 UPK 文件属于构建产物，不提交到 Git 仓库。
