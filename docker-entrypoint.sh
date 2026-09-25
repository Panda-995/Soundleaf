#!/bin/sh
set -e

# NAS 应用包（UGOS Pro UPK）以 root 启动容器，以便接管安装向导选择的
# 数据文件夹属主；随后降权到非特权账户运行。本地 compose 已指定
# APP_UID/APP_GID 时直接跳过接管逻辑。
if [ "$(id -u)" = "0" ]; then
    data="${DATA_DIR:-/data}"
    mkdir -p "$data"
    chown -R "${APP_UID:-1000}:${APP_GID:-1000}" "$data" 2>/dev/null || true
    set -- gosu "${APP_UID:-1000}:${APP_GID:-1000}" "$@"
fi

exec "$@"
