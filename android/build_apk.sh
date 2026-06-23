#!/usr/bin/env bash
# 手动构建「公考积累」WebView 壳 APK（不依赖 Gradle）。
# 需要：~/.local/jdk17、~/android-sdk（build-tools;34.0.0、platforms;android-34）。
set -e

HERE="$(cd "$(dirname "$0")" && pwd)"
SDK="${ANDROID_SDK_ROOT:-$HOME/android-sdk}"
BT="$SDK/build-tools/34.0.0"
PLAT="$SDK/platforms/android-34/android.jar"
export JAVA_HOME="${JAVA_HOME:-$HOME/.local/jdk17}"
export PATH="$JAVA_HOME/bin:$PATH"   # apksigner/d8 的包装脚本要在 PATH 找到 java

OUT="$HERE/build"
DIST="$HERE/../dist"
KS="$HERE/debug.keystore"

echo "[1/7] 清理"
rm -rf "$OUT"; mkdir -p "$OUT/compiled" "$OUT/gen" "$OUT/classes" "$OUT/dex" "$DIST"

echo "[2/7] 编译资源 aapt2 compile"
"$BT/aapt2" compile --dir "$HERE/res" -o "$OUT/compiled/res.zip"

echo "[3/7] 链接资源+清单 aapt2 link"
"$BT/aapt2" link \
  -o "$OUT/base.apk" \
  -I "$PLAT" \
  --manifest "$HERE/AndroidManifest.xml" \
  --java "$OUT/gen" \
  "$OUT/compiled/res.zip"

echo "[4/7] 编译 Java javac"
SRCS=$(find "$HERE/java" "$OUT/gen" -name '*.java')
"$JAVA_HOME/bin/javac" -source 8 -target 8 -nowarn \
  -classpath "$PLAT" -d "$OUT/classes" $SRCS

echo "[5/7] 转 dex d8"
"$BT/d8" --lib "$PLAT" --min-api 21 --output "$OUT/dex" \
  $(find "$OUT/classes" -name '*.class')

echo "[6/7] 打包 dex + 对齐"
cp "$OUT/dex/classes.dex" "$OUT/classes.dex"
( cd "$OUT" && zip -q base.apk classes.dex )
"$BT/zipalign" -f -p 4 "$OUT/base.apk" "$OUT/aligned.apk"

echo "[7/7] 签名 apksigner"
if [ ! -f "$KS" ]; then
  "$JAVA_HOME/bin/keytool" -genkeypair -keystore "$KS" -alias gongkao \
    -keyalg RSA -keysize 2048 -validity 10000 \
    -storepass android -keypass android -dname "CN=Gongkao, O=Study, C=CN"
fi
"$BT/apksigner" sign --ks "$KS" --ks-pass pass:android --key-pass pass:android \
  --out "$DIST/gongkao.apk" "$OUT/aligned.apk"

echo "==== 完成 ===="
"$BT/apksigner" verify --print-certs "$DIST/gongkao.apk" | head -2
ls -lh "$DIST/gongkao.apk"
