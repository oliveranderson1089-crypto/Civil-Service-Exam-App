#!/usr/bin/env bash
# 在这台 Linux 上试跑 Windows 壳（同一份代码，只是没有标题栏合一和托盘那些 Windows 专属件）。
# 用法：./run-dev.sh [http://127.0.0.1:8011]
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"

# ⚠️ 两个坑，缺一个都跑不起来：
# ① VS Code 的集成终端里 ELECTRON_RUN_AS_NODE=1 是**默认设着**的（它自己就是 Electron 应用）。
#    带着这个变量启动 electron，它会退化成一个普通 node —— 表现是
#    「TypeError: Cannot read properties of undefined (reading 'setPath')」，看着像代码错，其实是环境。
# ② 代理：本机服务是 127.0.0.1，走代理反而连不上。
exec env -u ELECTRON_RUN_AS_NODE -u HTTP_PROXY -u HTTPS_PROXY \
  "$HERE/node_modules/.bin/electron" "$HERE" --url="${1:-http://127.0.0.1:8011}"
