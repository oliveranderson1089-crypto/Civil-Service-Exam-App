#!/usr/bin/env bash
# 构建「公考助手」桌面版 .deb —— 一个轻量壳：用 Chrome 应用窗口模式打开网页版，
# 提供独立窗口 + 启动器图标。几十 KB，不含 Electron，复用已装的 Chrome。
set -e

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$HERE/.."
DIST="$ROOT/dist"
VER="${DEB_VERSION:-2.7}"
PKG="gongkao-assistant"
BUILD="$HERE/build/$PKG"

echo "[1/4] 清理并铺目录"
rm -rf "$HERE/build"; mkdir -p "$DIST"
mkdir -p "$BUILD/DEBIAN" \
         "$BUILD/usr/bin" \
         "$BUILD/usr/share/applications" \
         "$BUILD/usr/share/icons/hicolor/512x512/apps" \
         "$BUILD/usr/share/icons/hicolor/256x256/apps" \
         "$BUILD/usr/share/icons/hicolor/192x192/apps"

echo "[2/4] 启动脚本 + 桌面项 + 图标"
cat > "$BUILD/usr/bin/$PKG" <<'LAUNCH'
#!/usr/bin/env bash
# 公考助手 桌面版：Chrome 应用窗口。
# 默认公网隧道；本机若在跑本地服务(8011)则优先用它(更快)。可用 GONGKAO_URL 覆盖。
URL="${GONGKAO_URL:-https://gk.gongkaopei2026.click}"
if [ -z "$GONGKAO_URL" ] && curl -s -o /dev/null --max-time 1 http://127.0.0.1:8011/ 2>/dev/null; then
  URL="http://127.0.0.1:8011"
fi
for B in google-chrome-stable google-chrome chromium chromium-browser; do
  command -v "$B" >/dev/null 2>&1 && CHROME="$B" && break
done
[ -z "$CHROME" ] && { echo "未找到 Chrome/Chromium"; exit 1; }
exec "$CHROME" --app="$URL" --class=Gongkao --name=gongkao-assistant \
  --user-data-dir="$HOME/.config/gongkao-assistant" "$@"
LAUNCH
chmod 755 "$BUILD/usr/bin/$PKG"

cat > "$BUILD/usr/share/applications/$PKG.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=公考助手
Name[en]=Gongkao Assistant
Comment=公务员考试积累与练习
Comment[en]=Civil service exam study
Exec=$PKG %U
Icon=$PKG
Terminal=false
Categories=Education;
StartupWMClass=Gongkao
DESK

cp "$ROOT/static/icon-512.png" "$BUILD/usr/share/icons/hicolor/512x512/apps/$PKG.png"
cp "$ROOT/static/icon-512.png" "$BUILD/usr/share/icons/hicolor/256x256/apps/$PKG.png"
cp "$ROOT/static/icon-192.png" "$BUILD/usr/share/icons/hicolor/192x192/apps/$PKG.png"

echo "[3/4] 控制信息"
INSTALLED_KB=$(du -sk "$BUILD" | cut -f1)
cat > "$BUILD/DEBIAN/control" <<CTRL
Package: $PKG
Version: $VER
Architecture: all
Maintainer: Gongkao <noreply@localhost>
Depends: google-chrome-stable | google-chrome | chromium | chromium-browser
Recommends: curl
Section: education
Priority: optional
Installed-Size: $INSTALLED_KB
Description: 公考助手 桌面版
 公务员考试积累与练习的桌面客户端。用 Chrome 应用窗口模式打开网页版，
 提供独立窗口与启动器图标；本机在跑服务时自动用 localhost，否则走公网。
CTRL

# 安装后刷新图标/桌面缓存
cat > "$BUILD/DEBIAN/postinst" <<'POST'
#!/bin/sh
set -e
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q /usr/share/applications || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -f /usr/share/icons/hicolor || true
exit 0
POST
chmod 755 "$BUILD/DEBIAN/postinst"

echo "[4/4] 打包"
dpkg-deb --build --root-owner-group "$BUILD" "$DIST/gongkao.deb" >/dev/null
echo "==== 完成 ===="
dpkg-deb --info "$DIST/gongkao.deb" | grep -E "Package|Version|Installed-Size|Depends"
ls -lh "$DIST/gongkao.deb"
