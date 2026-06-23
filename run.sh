#!/usr/bin/env bash
# 启动「公考·成语词语积累」服务
cd "$(dirname "$0")" || exit 1
export NO_PROXY='*'          # 本机/局域网访问不走代理
PORT="${1:-8011}"
exec .venv/bin/python3 app.py --host 0.0.0.0 --port "$PORT"
