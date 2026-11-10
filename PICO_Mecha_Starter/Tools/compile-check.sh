#!/usr/bin/env bash
# 编译校验（不需要 Unity 授权）
#
# 背景：本机 Unity 未激活（No valid Unity Editor license），无法用 -batchmode 触发真实编译。
# 但 Unity 自带 mono + Roslyn，配合它自己的 NetStandard 2.1 引用集，
# 足以对 Assets/_Project/Scripts 做一次**类型完整的编译**（不是语法检查）。
#
# 用法：Tools/compile-check.sh
# 退出码 0 = 编译通过。
set -uo pipefail

UNITY_APP="${UNITY_APP:-/Applications/Unity/Unity.app/Contents}"
MONO="$UNITY_APP/MonoBleedingEdge/bin/mono"
CSC="$UNITY_APP/MonoBleedingEdge/lib/mono/4.5/csc.exe"

if [[ ! -x "$MONO" || ! -f "$CSC" ]]; then
  echo "找不到 Unity 自带的 mono/csc：$UNITY_APP" >&2
  echo "可通过 UNITY_APP=/path/to/Unity.app/Contents 覆盖" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$(mktemp -d)/SteelRidge.dll"
REFS="$(mktemp)"

{
  echo "-nostdlib+"
  echo "-r:$UNITY_APP/NetStandard/ref/2.1.0/netstandard.dll"
  for f in "$UNITY_APP"/NetStandard/compat/2.1.0/shims/netfx/*.dll; do echo "-r:$f"; done
  # 引擎模块：排除 UnityEditor.* 模块，统一用 UnityEditor.dll，避免 MenuItem 等类型重复定义
  for f in "$UNITY_APP"/Managed/UnityEngine/*.dll; do
    case "$f" in *UnityEditor*) continue;; esac
    echo "-r:$f"
  done
  echo "-r:$UNITY_APP/Managed/UnityEditor.dll"
} > "$REFS"

SRCS=()
while IFS= read -r -d '' f; do SRCS+=("$f"); done \
  < <(find "$ROOT/Assets/_Project/Scripts" -name '*.cs' -print0)

echo "编译 $((${#SRCS[@]})) 个脚本…"

"$MONO" "$CSC" -nologo -target:library -langversion:9.0 \
  -define:UNITY_EDITOR,UNITY_2022_3_OR_NEWER,ENABLE_LEGACY_INPUT_MANAGER \
  -out:"$OUT" @"$REFS" "${SRCS[@]}" 2>&1 | grep -E "error|warning" || true

if [[ -f "$OUT" ]]; then
  echo "编译通过 → $OUT"
  exit 0
fi

echo "编译失败" >&2
exit 1
