#!/bin/sh
# 容器入口：接管应用数据目录属主后以非 root 运行。NAS 共享文件夹可能
# 拒绝 chown（保留原属主或挂载层限制），此时依次改以可写的目录属主、
# （ALLOW_ROOT_DATA_FALLBACK=true 时）容器 root 继续运行，避免应用
# 因 /data 不可写而反复崩溃重启。
set -e

data_dir="${DATA_DIR:-/data}"
export DATA_DIR="$data_dir"
mkdir -p "$data_dir" || true

app_files="studio.sqlite3 studio.sqlite3-wal studio.sqlite3-shm secret.key"

# 数据目录必须能建子目录（Store 启动时要创建 sources/ 等六个子目录），
# 已有数据库与密钥必须可读写（SQLite 的 WAL/SHM 在库文件旁创建）。
can_write_data() {
  probe_sh='
    dir=$1
    [ -d "$dir" ] || exit 1
    probe=$(mktemp "$dir/.soundleaf-write-check.XXXXXX") || exit 1
    rm -f "$probe"
    sub="$dir/.soundleaf-probe"
    mkdir "$sub" 2>/dev/null || exit 1
    rmdir "$sub"
    for name in '"$app_files"'; do
      file="$dir/$name"
      [ ! -e "$file" ] || { [ -f "$file" ] && [ -r "$file" ] && [ -w "$file" ]; } || exit 1
    done
  '
  if [ "$1" = current ]; then
    sh -c "$probe_sh" sh "$data_dir"
  else
    gosu "$1" sh -c "$probe_sh" sh "$data_dir"
  fi
}

if [ "$(id -u)" = "0" ]; then
  # 只接管本应用的路径，不递归修改用户所选共享目录里的其他文件。
  for target in "$data_dir" "$data_dir"/sources "$data_dir"/audio \
    "$data_dir"/cache "$data_dir"/exports "$data_dir"/tmp "$data_dir"/covers \
    "$data_dir"/studio.sqlite3 "$data_dir"/studio.sqlite3-wal \
    "$data_dir"/studio.sqlite3-shm "$data_dir"/secret.key; do
    [ -e "$target" ] && chown "${APP_UID:-1000}:${APP_GID:-1000}" "$target" 2>/dev/null || true
  done
  if can_write_data "${APP_UID:-1000}:${APP_GID:-1000}"; then
    exec gosu "${APP_UID:-1000}:${APP_GID:-1000}" "$@"
  fi
  # chown 被拒绝时先尝试目录原属主，尽量保持非 root 运行。
  for candidate in "$data_dir" "$data_dir/studio.sqlite3"; do
    [ -e "$candidate" ] || continue
    owner=$(stat -c '%u:%g' "$candidate" 2>/dev/null || true)
    case "$owner" in
      ""|0:*|"${APP_UID:-1000}:${APP_GID:-1000}") continue ;;
    esac
    if can_write_data "$owner"; then
      echo "soundleaf: 数据目录拒绝 chown，改以其可写属主 $owner 运行。" >&2
      exec gosu "$owner" "$@"
    fi
  done
  if [ "${ALLOW_ROOT_DATA_FALLBACK:-false}" = true ] && can_write_data current; then
    echo "soundleaf: 数据目录对应用用户与目录属主均不可写，按 ALLOW_ROOT_DATA_FALLBACK 以容器 root 继续。" >&2
    exec "$@"
  fi
  echo "soundleaf: 无法在 $data_dir 写入（数据库/密钥/子目录）。请检查所选 NAS 文件夹的写权限与挂载模式；已有文件未被修改。" >&2
  exit 73
fi

if ! can_write_data current; then
  echo "soundleaf: 无法在 $data_dir 写入。请检查所选 NAS 文件夹对该运行身份的写权限与挂载模式。" >&2
  exit 73
fi
exec "$@"
