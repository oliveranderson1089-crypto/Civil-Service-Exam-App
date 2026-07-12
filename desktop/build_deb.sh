#!/usr/bin/env bash
# 构建「公考助手」桌面版 .deb —— 原生 GTK + 系统 WebKit2GTK（不依赖 Chrome、不打包引擎）。
# 一个真·原生窗口加载网页版；用系统 python3(自带 gi) 运行。
set -e

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$HERE/.."
DIST="$ROOT/dist"
VER="${DEB_VERSION:-3.0}"
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

echo "[2/4] 原生启动器 + 桌面项 + 图标"
cp "$HERE/gongkao_native.py" "$BUILD/usr/bin/$PKG"
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
StartupWMClass=gongkao-assistant
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
Depends: python3, python3-gi, gir1.2-gtk-3.0, gir1.2-webkit2-4.1
Section: education
Priority: optional
Installed-Size: $INSTALLED_KB
Description: 公考助手 桌面版（原生 GTK）
 公务员考试积累与练习的桌面客户端。原生 GTK 窗口 + 系统 WebKit2GTK 加载网页版，
 不依赖 Chrome、不打包浏览器引擎；本机在跑服务时自动用 localhost，否则走公网。
CTRL

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
