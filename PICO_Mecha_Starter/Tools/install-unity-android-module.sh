#!/usr/bin/env bash
# Tools/install-unity-android-module.sh — 把 Unity 的 Android 支持包装进已装的编辑器
#
# 背景
#   本机 Unity 2022.3.62f3 是手动安装的（Hub 里登记为 manual:true），
#   `unity install-modules` 会直接拒绝：「Module installation is only supported for
#   editors installed with Unity Hub.」
#   而官方模块包所在的 CDN（download.unity3d.com）在本机出口不可达（504 / 证书过期）。
#   所以：由人工用浏览器或其他网络下好 .pkg，本脚本负责解包并落位，不需要 sudo。
#
# 用法
#   Tools/install-unity-android-module.sh ~/Downloads/UnitySetup-Android-Support-for-Editor-2022.3.62f3.pkg
#   Unity 装在别处时：UNITY_APP=/path/to/Unity.app Tools/install-unity-android-module.sh <pkg>
#
# 做的事
#   1. 校验 pkg 是真正的 xar 包（防止把 504 的 HTML 错误页当包）
#   2. pkgutil --expand-full 解开
#   3. 找到 AndroidPlayer 目录，复制到 PlaybackEngines/
#   4. 列出结果，确认 Unity 能看到 Android 构建目标
set -euo pipefail

PKG="${1:?用法: install-unity-android-module.sh <UnitySetup-Android-Support-*.pkg>}"
UNITY_APP="${UNITY_APP:-/Applications/Unity/Unity.app}"
PE="$UNITY_APP/Contents/PlaybackEngines"
WORK="${WORK:-/tmp/unity-android-pkg}"

[ -f "$PKG" ] || { echo "找不到包: $PKG"; exit 1; }
[ -d "$PE" ] || { echo "找不到 PlaybackEngines: $PE"; exit 1; }

SIZE=$(wc -c < "$PKG" | tr -d ' ')
echo "包大小: $SIZE 字节"
if [ "$SIZE" -lt 100000000 ]; then
  echo "✗ 文件过小（<100 MB），多半是下载失败留下的 HTML 错误页："
  head -c 200 "$PKG"; echo
  exit 1
fi
if ! file "$PKG" | grep -q "xar"; then
  echo "✗ 不是 xar 包："; file "$PKG"; exit 1
fi

echo "== 解包 =="
rm -rf "$WORK"
pkgutil --expand-full "$PKG" "$WORK"

echo "== 定位 AndroidPlayer =="
AP="$(find "$WORK" -type d -name AndroidPlayer -maxdepth 8 | head -1)"
[ -n "$AP" ] || { echo "✗ 包里没找到 AndroidPlayer"; find "$WORK" -maxdepth 3 -type d | head -20; exit 1; }
echo "   $AP"
du -sh "$AP" 2>/dev/null || true

echo "== 落位到 PlaybackEngines =="
rm -rf "$PE/AndroidPlayer"
cp -R "$AP" "$PE/AndroidPlayer"

echo "== 结果 =="
ls -1 "$PE"
if [ -d "$PE/AndroidPlayer" ]; then
  echo "✓ AndroidPlayer 已就位"
  ls -1 "$PE/AndroidPlayer" | head -12
else
  echo "✗ 复制失败"; exit 1
fi

echo
echo "下一步：把 SDK / JDK 路径写进 Unity 偏好（否则构建会报找不到工具链）"
echo "  Unity -batchmode -quit -projectPath <项目> \\"
echo "        -executeMethod SteelSpine.EditorTools.SetAndroidToolchain.Apply"
