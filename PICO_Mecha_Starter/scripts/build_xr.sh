#!/usr/bin/env bash
# build_xr.sh — 出 OpenXR APK（M1/M2 全流程一条命令）
#
# 为什么需要这个脚本（踩坑记录，2026-11-11）
#   Unity 2022.3.62f3 在 batchmode 下**不读** EditorPrefs / AndroidExternalToolsSettings 的
#   JdkPath，会直接抛 "UnityException: JDK not found"，接着抛 "Android NDK not found"。
#   唯一可靠的做法是把四个环境变量传给 Unity 进程：
#       JAVA_HOME / ANDROID_SDK_ROOT / ANDROID_HOME / ANDROID_NDK_ROOT
#   其中 JAVA_HOME 必须指向 macOS JDK bundle 内的 Contents/Home（不是 bundle 根，
#   否则 java 可执行文件路径不对）。
#
# 还要注意
#   ① Unity 必须**非沙箱**运行：沙箱会拦 Unity 写 ~/Library/Application Support/Unity，
#      表现为构建在 Gradle 阶段被打断、日志里出现 file-delete 被拒。
#   ② StripControllerOnly.cs 会在 OnPostGenerateGradleAndroidProject 阶段删掉 manifest 里的
#      controller 元数据（callbackOrder=100，排在 PICO SDK 的 1 之后），
#      否则 PICO 系统会用 AppStartInterceptManager 拦住启动（要求先配对手柄）。
#
# 用法
#   ./scripts/build_xr.sh            # 完整构建
#   ./scripts/build_xr.sh --no-build # 只打印环境自检

set -euo pipefail

PROJ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNITY="/Applications/Unity/Unity.app/Contents/MacOS/Unity"
JAVA_HOME_DIR="/Users/zhukeyi/.local/jdk/jdk11/Contents/Home"
SDK="/Users/zhukeyi/Library/Android/sdk"
NDK="$SDK/ndk/23.1.7779620"
LOG="/tmp/unity_xr_build.log"
APK="$PROJ/out/android/SteelSpineXR.apk"

export JAVA_HOME="$JAVA_HOME_DIR"
export ANDROID_SDK_ROOT="$SDK"
export ANDROID_HOME="$SDK"
export ANDROID_NDK_ROOT="$NDK"

echo "JAVA_HOME         = $JAVA_HOME"
echo "ANDROID_SDK_ROOT  = $ANDROID_SDK_ROOT"
echo "ANDROID_NDK_ROOT  = $ANDROID_NDK_ROOT"

[ -x "$JAVA_HOME/bin/java" ] || { echo "!! JDK 不可执行: $JAVA_HOME/bin/java"; exit 1; }
[ -d "$SDK/platform-tools" ] || { echo "!! SDK 缺 platform-tools: $SDK"; exit 1; }
[ -d "$NDK" ] || { echo "!! NDK 不存在: $NDK"; exit 1; }

if [ "${1:-}" = "--no-build" ]; then
  echo "环境自检通过（未构建）"
  exit 0
fi

echo "--- 开始构建 ---"
"$UNITY" -batchmode -quit \
  -projectPath "$PROJ" \
  -buildTarget Android \
  -executeMethod SteelSpine.EditorTools.BuildXrApk.Run \
  -logFile "$LOG" || true

echo "--- 结果 ---"
grep -E "\[StripController\]|\[BuildXr\] 结果|Build Finished" "$LOG" | tail -5

if [ -f "$APK" ]; then
  ls -lh "$APK"
  echo "OK: $APK"
else
  echo "!! 未生成 APK，检查日志 $LOG"
  exit 1
fi
