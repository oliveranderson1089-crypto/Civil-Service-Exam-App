#!/usr/bin/env bash
# 打印当前 Cloudflare 隧道的公网网址（把它填进手机 APP 的「设置服务器地址」）。
LOG="$HOME/gongkao-app/cloudflared.log"
url=$(grep -hoE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" 2>/dev/null | tail -1)
if [ -n "$url" ]; then
  echo "$url"
else
  echo "（隧道尚未就绪。稍候几秒再试，或看： systemctl --user status gongkao-tunnel）"
fi
