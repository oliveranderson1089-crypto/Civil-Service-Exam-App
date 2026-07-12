#!/usr/bin/env bash
# 构建「公考助手」桌面版 .deb —— 原生 GTK + 系统 WebKit2GTK（不依赖 Chrome、不打包引擎）。
# 一个真·原生窗口加载网页版；用系统 python3(自带 gi) 运行。
set -e

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$HERE/.."
DIST="$ROOT/dist"
VER="${DEB_VERSION:-3.2}"
CODE="$(echo "$VER" | tr -d '.')"                      # 3.2 → 32，供网页比对版本用
NOTES="${DEB_NOTES:-新增自动检查更新与更新提示；支持下载文件（更新包存到「下载」文件夹）。}"
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
# 壳里的版本号必须与包版本一致（网页据此判断有没有新版桌面客户端）
sed -i "s/^DESKTOP_VER = .*/DESKTOP_VER = \"$VER\"/" "$BUILD/usr/bin/$PKG"
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

# 版本元数据：桌面版启动时问 /api/desktop/version，据此提示「下载更新」
cat > "$DIST/deb.json" <<META
{
  "version_code": $CODE,
  "version_name": "$VER",
  "notes": "$NOTES"
}
META

echo "==== 完成 ===="
dpkg-deb --info "$DIST/gongkao.deb" | grep -E "Package|Version|Installed-Size|Depends"
ls -lh "$DIST/gongkao.deb"
