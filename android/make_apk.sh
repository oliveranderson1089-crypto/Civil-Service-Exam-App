#!/usr/bin/env bash
# 用 Gradle 构建「公考助手」APK，并生成 dist/gongkao.apk + dist/apk.json（应用内更新比对用）。
# 需要：~/.local/jdk17、~/android-sdk（build-tools;34.0.0、platforms;android-34）、
#       ~/.local/gradle-8.9（或项目内 ./gradlew）。
set -e

HERE="$(cd "$(dirname "$0")" && pwd)"
DIST="$HERE/../dist"
export JAVA_HOME="${JAVA_HOME:-$HOME/.local/jdk17}"
export ANDROID_SDK_ROOT="${ANDROID_SDK_ROOT:-$HOME/android-sdk}"
export PATH="$JAVA_HOME/bin:$PATH"

# 本机优先用已装的 gradle（依赖直连、不必下发行版）；没有再退 wrapper
if [ -x "$HOME/.local/gradle-8.9/bin/gradle" ]; then GRADLE="$HOME/.local/gradle-8.9/bin/gradle"
elif [ -x "$HERE/gradlew" ]; then GRADLE="$HERE/gradlew"
else GRADLE="gradle"; fi

echo "[1/3] Gradle 构建 release APK"
( cd "$HERE" && "$GRADLE" :app:assembleRelease --console=plain )

echo "[2/3] 复制到 dist/gongkao.apk"
mkdir -p "$DIST"
cp "$HERE/app/build/outputs/apk/release/app-release.apk" "$DIST/gongkao.apk"

echo "[3/3] 生成 dist/apk.json（版本取自 app/build.gradle）"
GB="$HERE/app/build.gradle"
VC=$(grep -oE 'versionCode +[0-9]+' "$GB" | grep -oE '[0-9]+')
VN=$(grep -oE "versionName +'[^']*'" "$GB" | cut -d"'" -f2)
NOTES="${APK_NOTES:-修复问题、优化体验。}"
printf '{\n  "version_code": %s,\n  "version_name": "%s",\n  "notes": "%s"\n}\n' \
  "$VC" "$VN" "$NOTES" > "$DIST/apk.json"
echo "apk.json -> $VN ($VC)"

echo "==== 完成 ===="
"$ANDROID_SDK_ROOT/build-tools/34.0.0/apksigner" verify --print-certs "$DIST/gongkao.apk" | head -1
ls -lh "$DIST/gongkao.apk"
