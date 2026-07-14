#!/usr/bin/env bash
# 桌面版朗读引擎（可选，装不装都不影响应用启动）。
#
# 为什么要装：WebKitGTK 没有 speechSynthesis，桌面版只能借系统 TTS。系统自带的
# speech-dispatcher(espeak) 是机械音，读长文很难受。装完这两个就能在
# 「账户 → 🔊 朗读音色」里切：
#   piper —— 离线神经语音，不联网，起声快（默认）
#   edge  —— 微软在线，音质最自然，要联网
#
# 装到 ~/.local 下，不碰系统 Python，也不进 .deb（这俩加起来 90MB，没必要塞进包）。
set -e

PIPER_DIR="$HOME/.local/piper"
VOICE=zh_CN-huayan-medium

echo "== 1/2 Piper（离线）=="
if [ -x "$PIPER_DIR/piper/piper" ]; then
  echo "已装，跳过"
else
  mkdir -p "$PIPER_DIR/models"
  cd "$PIPER_DIR"
  curl -fL -o piper.tar.gz \
    https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_x86_64.tar.gz
  tar xzf piper.tar.gz && rm piper.tar.gz
  B=https://huggingface.co/rhasspy/piper-voices/resolve/main/zh/zh_CN/huayan/medium
  curl -fL -o "models/$VOICE.onnx"      "$B/$VOICE.onnx"
  curl -fL -o "models/$VOICE.onnx.json" "$B/$VOICE.onnx.json"
fi

echo "== 2/2 edge-tts（在线）=="
if [ -x "$HOME/.local/tts-venv/bin/edge-tts" ]; then
  echo "已装，跳过"
else
  # 独立 venv：系统 Python 是 PEP 668 管理的，不能直接 pip install
  command -v python3 >/dev/null || { echo "缺 python3"; exit 1; }
  python3 -m venv "$HOME/.local/tts-venv" 2>/dev/null || {
    echo "缺 python3-venv，请先： sudo apt install -y python3-venv"; exit 1; }
  "$HOME/.local/tts-venv/bin/pip" install -q edge-tts
fi

# 放音：piper 出 raw PCM 走 aplay，edge 出 mp3 走 GStreamer（GTK 自带，不用另装 mpg123）
command -v aplay >/dev/null || echo "⚠️ 缺 aplay（sudo apt install alsa-utils），piper 放不出声"
command -v gst-launch-1.0 >/dev/null || echo "⚠️ 缺 gst-launch-1.0，edge 放不出声"

echo "✅ 完成。重开桌面版 →「账户 → 🔊 朗读音色」里切换。"
