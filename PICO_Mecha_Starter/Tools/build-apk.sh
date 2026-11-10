#!/usr/bin/env bash
# Tools/build-apk.sh — 通用 APK 打包器（不依赖 Gradle，不依赖 Unity）
#
# 为什么手写这一套
#   本机 Unity 的 Android Build Support 尚未装（模块包所在的 CDN 出口不通），
#   而「构建 → 安装 → 启动 → 截图」这条链需要立刻能跑。用 aapt2 + javac + d8 +
#   zipalign + apksigner 五步即可产出可安装的 APK，且完全可复现、无守护进程。
#
# 目录约定（$APP 为一个应用根目录）
#   $APP/AndroidManifest.xml     必需
#   $APP/src/**/*.java           必需（递归收集）
#   $APP/res/**                  可选（aapt2 资源）
#   $APP/assets/**               可选（原样打进 assets/）
#
# 用法
#   Tools/build-apk.sh Tools/android-viewer                 # 只打包
#   Tools/build-apk.sh Tools/android-viewer --install       # 打包 + 装 + 启动
#   PKG_SUFFIX=-debug Tools/build-apk.sh <app>              # 换包名后缀
set -euo pipefail

APP="${1:?用法: build-apk.sh <appDir> [--install]}"
INSTALL="${2:-}"
HERE="$(cd "$(dirname "$0")" && pwd)"
APP="$(cd "$APP" && pwd)"
NAME="$(basename "$APP")"
OUT="$APP/build"

export ANDROID_HOME="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
export JAVA_HOME="${JAVA_HOME:-/Applications/Android Studio.app/Contents/jbr/Contents/Home}"
BT="$ANDROID_HOME/build-tools/35.0.0"
PLATFORM="$ANDROID_HOME/platforms/android-35/android.jar"
ADB="$ANDROID_HOME/platform-tools/adb"

for f in "$BT/aapt2" "$BT/d8" "$BT/zipalign" "$BT/apksigner" "$PLATFORM" \
         "$JAVA_HOME/bin/javac" "$JAVA_HOME/bin/keytool"; do
  [ -e "$f" ] || { echo "缺少依赖: $f"; exit 1; }
done
[ -f "$APP/AndroidManifest.xml" ] || { echo "缺少 AndroidManifest.xml"; exit 1; }

PKG="$(sed -n 's/.*package="\([^"]*\)".*/\1/p' "$APP/AndroidManifest.xml" | head -1)"
[ -n "$PKG" ] || { echo "无法从 manifest 解析 package"; exit 1; }
ACTIVITY="${ACTIVITY:-.MainActivity}"

rm -rf "$OUT"
mkdir -p "$OUT/classes" "$OUT/dex" "$OUT/gen"

echo "== 1/6 收集源码（包 ${PKG}）=="
SRCS=()
while IFS= read -r _f; do SRCS+=("$_f"); done < <(find "$APP/src" -name '*.java' 2>/dev/null || true)
[ "${#SRCS[@]}" -gt 0 ] || { echo "src 下没有 .java"; exit 1; }
echo "   ${#SRCS[@]} 个源文件"

echo "== 2/6 编译 Java =="
"$JAVA_HOME/bin/javac" -source 11 -target 11 -nowarn \
  -classpath "$PLATFORM" -d "$OUT/classes" "${SRCS[@]}" 2>&1 | grep -v '^Note:' || true

echo "== 3/6 dex =="
CLS=()
while IFS= read -r _f; do CLS+=("$_f"); done < <(find "$OUT/classes" -name '*.class')
"$BT/d8" --lib "$PLATFORM" --min-api 29 --output "$OUT/dex" "${CLS[@]}"

echo "== 4/6 链接资源 =="
LINK_ARGS=(-o "$OUT/base.apk" -I "$PLATFORM" --manifest "$APP/AndroidManifest.xml" --java "$OUT/gen")
if [ -d "$APP/res" ]; then
  "$BT/aapt2" compile --dir "$APP/res" -o "$OUT/res.zip"
  LINK_ARGS+=("$OUT/res.zip")
fi
if [ -d "$APP/assets" ]; then
  LINK_ARGS+=(-A "$APP/assets")
fi
"$BT/aapt2" link "${LINK_ARGS[@]}"

echo "== 5/6 打入 classes.dex + 对齐 =="
( cd "$OUT/dex" && zip -q -X "$OUT/base.apk" classes.dex )
"$BT/zipalign" -f 4 "$OUT/base.apk" "$OUT/aligned.apk"

echo "== 6/6 签名 =="
KS="${KEYSTORE:-$HOME/.android/debug-steelspine.keystore}"
if [ ! -f "$KS" ]; then
  mkdir -p "$(dirname "$KS")"
  "$JAVA_HOME/bin/keytool" -genkeypair -v -keystore "$KS" -storepass android \
    -keypass android -alias androiddebugkey -keyalg RSA -keysize 2048 -validity 10000 \
    -dname "CN=Steel Spine, O=Local, C=CN" >/dev/null 2>&1
  echo "   已生成调试签名 $KS"
fi
APK="$OUT/$NAME.apk"
"$BT/apksigner" sign --ks "$KS" --ks-pass pass:android --key-pass pass:android \
  --out "$APK" "$OUT/aligned.apk" >/dev/null 2>&1
"$BT/apksigner" verify --print-certs "$APK" | sed -n '1,2p'

ls -lh "$APK"
echo "APK: $APK"

if [ "$INSTALL" = "--install" ]; then
  echo "== 安装并启动 =="
  "$ADB" install -r -g "$APK"
  "$ADB" shell am start -W -n "$PKG/$ACTIVITY"
fi
