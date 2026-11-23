#!/bin/sh
# 容器入口：只做环境自检，然后把进程交给服务本体（exec 保证 SIGTERM 直达）。
set -eu

DATA_ROOT="${NOVEL_HELPER_ROOT:-/data}"

if [ ! -d "$DATA_ROOT" ]; then
  echo "数据卷不存在：$DATA_ROOT" >&2
  exit 64
fi

if ! touch "$DATA_ROOT/.entrypoint-probe" 2>/dev/null; then
  echo "数据卷不可写：$DATA_ROOT" >&2
  exit 65
fi
rm -f "$DATA_ROOT/.entrypoint-probe"

if [ -d /config ] && [ -n "$(ls -A /config 2>/dev/null)" ]; then
  echo "已挂载只读配置：$(ls /config | tr '\n' ' ')"
fi

# 缺配置不是致命错误：服务会以 degraded 状态只提供健康信息，不静默开调度。
exec python -B -X utf8 -m integration.resident_service start \
  --interval "${RESIDENT_INTERVAL:-30}" "$@"
