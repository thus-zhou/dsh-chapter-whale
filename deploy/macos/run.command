#!/bin/sh
# 手动前台启动（不经 launchd）：Ctrl-C 或 SIGTERM 会走服务的停认领流程。
set -eu

ROOT="${CHAPTER_WHALE_ROOT:-/Users/Shared/chapter-whale}"
CODE="${CHAPTER_WHALE_CODE:-/opt/chapter-whale}"

if [ ! -d "$CODE/backend/integration" ]; then
  echo "找不到安装目录：$CODE/backend/integration（用 CHAPTER_WHALE_CODE 指定）" >&2
  exit 64
fi

if [ ! -d "$ROOT" ]; then
  echo "数据卷不存在：$ROOT（先创建，或用 CHAPTER_WHALE_ROOT 指定）" >&2
  exit 65
fi

if [ ! -w "$ROOT" ]; then
  echo "数据卷不可写：$ROOT" >&2
  exit 66
fi

export PYTHONPATH="$CODE/backend"
export PYTHONUTF8=1
export PYTHONUNBUFFERED=1

# launchd 与 Finder 的 PATH 很短；解释器不在 PATH 里时报 69 而不是让 shell 报 127。
if ! command -v python3 >/dev/null 2>&1; then
  echo "找不到 python3：先安装 3.11+，或在 plist 的 ProgramArguments/PATH 里写绝对路径" >&2
  exit 69
fi

exec python3 -B -X utf8 -m integration.resident_service start --root "$ROOT" ${@+"$@"}
