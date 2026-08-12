#!/usr/bin/env bash
# 构建「公考助手」Windows 桌面版，产出 dist/gongkao-win.zip（便携版）
# 和 dist/gongkao-setup.exe（安装版），外加 dist/win.json（应用内更新比对用）。
#
# 在这台 Linux 上就能出 Windows 包（electron-builder 跨平台构建）。
# 用法：./build_win.sh            两个都打
#       ./build_win.sh zip        只打便携版（快，验收用这个）
set -e

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$HERE/../.."
DIST="$ROOT/dist"

# ⚠️ 三个环境坑，缺一个都会失败，且报错都不指向真正的原因：
# ① VS Code 终端默认设着 ELECTRON_RUN_AS_NODE=1，会让 electron 退化成普通 node。
# ② Node 24 的 fetch 默认不读 proxy 环境变量，而 github 直连不通 —— 下不到 Electron 二进制。
# ③ electron-builder 在 Linux 上要靠 wine 给 exe 写图标和版本信息（rcedit）。
export NODE_USE_ENV_PROXY=1
unset ELECTRON_RUN_AS_NODE
command -v wine >/dev/null 2>&1 || echo "⚠️  没装 wine：exe 的图标和版本信息可能写不进去"

echo "[1/4] 版本号（唯一来源：main.js 的 SHELL_VER）"
VER="$(sed -n "s/^const SHELL_VER = '\(.*\)'.*/\1/p" "$HERE/main.js")"
[ -n "$VER" ] || { echo "没从 main.js 里读出 SHELL_VER"; exit 1; }
CODE="$(echo "$VER" | tr -d '.')"                      # 6.0 → 60，供网页比对版本用
# package.json 的 version 必须是 semver，且要和壳里的版本号一致 ——
# 不同步的话，安装包的版本号和网页看到的版本号会对不上。
node -e "
  const fs=require('fs'),p='$HERE/package.json',d=JSON.parse(fs.readFileSync(p,'utf8'));
  d.version='$VER'.split('.').length===2?'$VER.0':'$VER';
  fs.writeFileSync(p,JSON.stringify(d,null,2)+'\n');
  console.log('  package.json version =',d.version);
"

echo "[2/4] 应用图标（.ico，多尺寸）"
"$ROOT/.venv/bin/python3" - <<PY
from PIL import Image
im = Image.open("$ROOT/static/icon-512.png").convert("RGBA")
im.save("$HERE/build/icon.ico", format="ICO",
        sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
print("  build/icon.ico 就绪")
PY

echo "[3/4] electron-builder 打包"
rm -rf "$HERE/out"
( cd "$HERE" && ./node_modules/.bin/electron-builder --win ${1:-} )

echo "[4/4] 复制到 dist/ + 写 win.json"
mkdir -p "$DIST"
[ -f "$HERE/out/gongkao-win.zip" ] && cp "$HERE/out/gongkao-win.zip" "$DIST/gongkao-win.zip"
[ -f "$HERE/out/gongkao-setup.exe" ] && cp "$HERE/out/gongkao-setup.exe" "$DIST/gongkao-setup.exe"
NOTES="${WIN_NOTES:-首个 Windows 版：原生窗口 + 托盘 + 系统通知，出错有兜底页和详细日志。}"
cat > "$DIST/win.json" <<META
{
  "version_code": $CODE,
  "version_name": "$VER",
  "notes": "$NOTES"
}
META

echo "==== 完成 ===="
ls -lh "$DIST"/gongkao-win.zip "$DIST"/gongkao-setup.exe 2>/dev/null || true
cat "$DIST/win.json"
