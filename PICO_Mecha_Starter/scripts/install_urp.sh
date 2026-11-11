#!/usr/bin/env bash
# ============================================================================
#  install_urp.sh — 一键装 URP 14 + 材质统一 + 重新出包
#
#  2026-11-11 改版：主路径从「registry 下载」换成「本机内置包」
#
#  为什么
#    本机出口被 GeoIP 分发到 Unity 中国镜像（packages.unity.com → 8.233.179.0），
#    该索引只有 45 个版本、最高 10.10.1，14.0.x 的单版本查询与 tarball 全 404。
#    Oracle 服务器（217.142.246.70）解析到**同一个 IP**，索引同样 45/最高 10.10.1
#    —— 所以「走服务器中转」这条路本身就不成立，不是代理没开的问题。
#
#    真正的解法：Unity 安装包自带 BuiltInPackages，里面有 URP / Core / ShaderGraph /
#    URP-Config 的完整源码包，UPM 会直接链接内置包，**完全不经过 registry**。
#    只要 manifest 里写的版本号与内置版本号一致，解析就是离线完成的。
#
#  内置版本（Unity 2022.3.62f3 实测）
#    com.unity.render-pipelines.universal        14.0.12
#    com.unity.render-pipelines.core             14.0.12
#    com.unity.shadergraph                       14.0.12
#    com.unity.render-pipelines.universal-config 14.0.10
#    （URP 还依赖 registry 上的 burst 1.8.9 / mathematics 1.2.1，那两个包镜像上有，能下）
#
#  用法
#    ./scripts/install_urp.sh              # 内置包优先，一条命令装完 + 出包
#    ./scripts/install_urp.sh --probe-only # 只探测（内置包 / registry 各是什么情况）
#    ./scripts/install_urp.sh --registry   # 强制走 registry（换到能拿到 14.x 的线路时用）
#    ./scripts/install_urp.sh --proxy http://127.0.0.1:7890
#
#  退出码
#    0 成功   2 两条来源都拿不到 URP   3 manifest 已写但解析失败
#    4 出包失败   5 材质没有统一到 URP/Lit
# ============================================================================
set -uo pipefail

PROJ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNITY="/Applications/Unity/Unity.app/Contents/MacOS/Unity"
BUILTIN="/Applications/Unity/Unity.app/Contents/Resources/PackageManager/BuiltInPackages"
LOG_DIR="$PROJ/Logs"
MANIFEST="$PROJ/Packages/manifest.json"
REG="https://packages.unity.com"
PKG="com.unity.render-pipelines.universal"

JDK="/Users/zhukeyi/.local/jdk/jdk11/Contents/Home"
SDK="/Users/zhukeyi/Library/Android/sdk"
NDK="$SDK/ndk/23.1.7779620"

PROXY=""
PROBE_ONLY=0
FORCE_REGISTRY=0
MODE=""

while [ $# -gt 0 ]; do
  case "$1" in
    --proxy)       PROXY="$2"; shift 2 ;;
    --probe-only)  PROBE_ONLY=1; shift ;;
    --registry)    FORCE_REGISTRY=1; shift ;;
    -h|--help)     sed -n '2,40p' "$0"; exit 0 ;;
    *) echo "未知参数: $1"; exit 1 ;;
  esac
done

mkdir -p "$LOG_DIR"

c()    { printf "\033[%sm%s\033[0m\n" "$1" "$2"; }
ok()   { c "32" "  OK   $*"; }
bad()  { c "31" "  FAIL $*"; }
warn() { c "33" "  WARN $*"; }
step() { echo; c "36" "==> $*"; }

# macOS 自带 bash 3.2 不支持空数组展开（配 set -u 会报 unbound variable），用包装函数
curlx() {
  if [ -n "$PROXY" ]; then curl -x "$PROXY" "$@"; else curl "$@"; fi
}

pkgver() {  # $1 = 包目录名；读 package.json 的 version
  python3 -c "import json;print(json.load(open('$BUILTIN/$1/package.json'))['version'])" 2>/dev/null
}

# ---------------------------------------------------------------- 1. 探测来源
step "1/6 探测 URP 14 的来源"

BUILTIN_URP=""
if [ -d "$BUILTIN/$PKG" ]; then
  BUILTIN_URP="$(pkgver "$PKG")"
  echo "     内置包目录: $BUILTIN"
  ok "内置 $PKG = $BUILTIN_URP"
  for p in com.unity.render-pipelines.core com.unity.shadergraph com.unity.render-pipelines.universal-config; do
    v="$(pkgver "$p")"
    if [ -n "$v" ]; then ok "内置 $p = $v"; else warn "内置缺 $p"; fi
  done
else
  warn "本机 Unity 没有内置 $PKG"
fi

REG_URP=""
if [ "$FORCE_REGISTRY" = "1" ] || [ -z "$BUILTIN_URP" ]; then
  echo "     探测 registry..."
  BODY=$(curlx -s --max-time 25 "$REG/$PKG" 2>/dev/null || true)
  if [ -n "$BODY" ]; then
    REG_URP=$(printf '%s' "$BODY" | python3 -c '
import json,sys
try: d=json.load(sys.stdin)
except Exception: print(""); raise SystemExit
vs=[v for v in d.get("versions",{}) if v.startswith("14.0.")]
def key(v):
    try: return tuple(int(x) for x in v.split("."))
    except Exception: return (0,)
vs.sort(key=key)
print(vs[-1] if vs else "")
' 2>/dev/null || true)
    printf '     索引版本数 %s｜14.0.x 最高 %s\n' \
      "$(printf '%s' "$BODY" | python3 -c 'import json,sys;print(len(json.load(sys.stdin).get("versions",{})))' 2>/dev/null)" \
      "${REG_URP:--}"
  else
    warn "registry 无响应"
  fi
  [ -n "$REG_URP" ] && ok "registry $PKG = $REG_URP" || warn "registry 没有 14.0.x（已知：镜像只有 10.10.1）"
fi

if [ "$FORCE_REGISTRY" = "1" ] && [ -n "$REG_URP" ]; then
  MODE="registry"
elif [ -n "$BUILTIN_URP" ]; then
  MODE="builtin"
elif [ -n "$REG_URP" ]; then
  MODE="registry"
else
  bad "两条来源都拿不到 URP 14"
  echo "     内置包: $([ -d "$BUILTIN/$PKG" ] && echo 有 || echo 无)"
  echo "     registry: 见上（本机与 Oracle 服务器解析到同一镜像 8.233.179.0，索引最高 10.10.1）"
  echo "     可选：把 URP 14.x 的 tgz 放到 Packages/ 下改用 file: 引用"
  exit 2
fi

ok "选定来源: $MODE"
[ "$PROBE_ONLY" = "1" ] && { echo; ok "--probe-only 结束，工程未改动"; exit 0; }

# ---------------------------------------------------------------- 2. 写 manifest
step "2/6 写入 manifest.json"

if [ "$MODE" = "builtin" ]; then
  URP_V="$BUILTIN_URP"
  CORE_V="$(pkgver com.unity.render-pipelines.core)"
  SG_V="$(pkgver com.unity.shadergraph)"
  CFG_V="$(pkgver com.unity.render-pipelines.universal-config)"
else
  URP_V="$REG_URP"; CORE_V="$REG_URP"; SG_V="$REG_URP"; CFG_V=""
fi

cp -p "$MANIFEST" "$MANIFEST.bak-$(date +%Y%m%d-%H%M%S)"
python3 - "$MANIFEST" "$PKG" "$URP_V" "$CORE_V" "$SG_V" "$CFG_V" <<'PY'
import json,sys,collections
p,pkg,urp,core,sg,cfg=sys.argv[1:7]
d=json.load(open(p),object_pairs_hook=collections.OrderedDict)
dep=d.setdefault("dependencies",collections.OrderedDict())
dep[pkg]=urp
if core: dep["com.unity.render-pipelines.core"]=core
if sg:   dep["com.unity.shadergraph"]=sg
if cfg:  dep["com.unity.render-pipelines.universal-config"]=cfg
d["dependencies"]=collections.OrderedDict(sorted(dep.items()))
json.dump(d,open(p,"w"),indent=2,ensure_ascii=False)
open(p,"a").write("\n")
print("     URP=%s core=%s shadergraph=%s config=%s" % (urp,core,sg,cfg or "-"))
PY
ok "manifest 已更新（备份见 Packages/manifest.json.bak-*）"

# ---------------------------------------------------------------- 3. 解析
step "3/6 Unity 解析依赖（内置包是本地链接，不联网）"

export JAVA_HOME="$JDK"
export ANDROID_SDK_ROOT="$SDK"
export ANDROID_HOME="$SDK"
export ANDROID_NDK_ROOT="$NDK"
if [ -n "$PROXY" ]; then
  export HTTP_PROXY="$PROXY" HTTPS_PROXY="$PROXY" http_proxy="$PROXY" https_proxy="$PROXY"
fi

RESOLVE_LOG="$LOG_DIR/urp_resolve.log"
"$UNITY" -batchmode -quit -projectPath "$PROJ" -buildTarget Android \
  -logFile "$RESOLVE_LOG" >/dev/null 2>&1

CACHE_DIR=$(ls -d "$PROJ/Library/PackageCache/${PKG}"@* 2>/dev/null | head -1)
if [ -z "$CACHE_DIR" ]; then
  bad "解析后仍未在 Library/PackageCache 找到 $PKG"
  echo "     日志尾部："
  grep -iE "error|Cannot|failed|resolve" "$RESOLVE_LOG" 2>/dev/null | tail -12 | sed 's/^/       /'
  exit 3
fi
ok "包已落地：$(basename "$CACHE_DIR")"

# ---------------------------------------------------------------- 4. 材质 + 管线
step "4/6 材质统一到 URP/Lit + 创建/挂载管线资产"

SETUP_LOG="$LOG_DIR/urp_setup.log"
"$UNITY" -batchmode -quit -projectPath "$PROJ" -buildTarget Android \
  -executeMethod SteelSpine.EditorTools.Urp.SetupUrp.Run \
  -logFile "$SETUP_LOG" >/dev/null 2>&1

grep -E "\[SetupUrp\]" "$SETUP_LOG" | sed 's/^/     /'

SUMMARY=$(grep "材质检查结果" "$SETUP_LOG" | tail -1)
if [ -z "$SUMMARY" ]; then
  bad "SetupUrp 没有输出检查结果，编译可能失败"
  grep "error CS" "$SETUP_LOG" | sort -u | tail -10 | sed 's/^/       /'
  exit 5
fi

FAILED=$(printf '%s' "$SUMMARY" | sed -n 's/.*失败 \([0-9]*\) 个.*/\1/p')
[ "${FAILED:-99}" = "0" ] || { bad "有 $FAILED 个材质转换失败"; exit 5; }
ok "材质全部为 URP/Lit"

URP_ASSET=$(find "$PROJ/Assets" -name "URP_Asset.asset" 2>/dev/null | head -1)
[ -n "$URP_ASSET" ] && ok "管线资产 $(basename "$URP_ASSET")" || { bad "未找到 URP_Asset.asset"; exit 5; }

# ---------------------------------------------------------------- 5. 出包
step "5/6 重新出包"
"$PROJ/scripts/build_xr.sh" 2>&1 | tail -8

APK="$PROJ/out/android/SteelSpineXR.apk"
if [ -f "$APK" ]; then
  ok "APK $(ls -lh "$APK" | awk '{print $5}')  $(date -r "$APK" '+%H:%M:%S')"
else
  bad "APK 未生成"; exit 4
fi

# ---------------------------------------------------------------- 6. 后续
step "6/6 完成"
cat <<EOF
     装到模拟器看效果：
       adb install -r "$APK"
       adb shell am force-stop com.steelspine.smoke
       adb shell monkey -p com.steelspine.smoke -c android.intent.category.LAUNCHER 1
       adb exec-out screencap -p > Docs/参照/openxr/M1_02_URP.png

     回滚：
       cp "$MANIFEST".bak-* "$MANIFEST"
       git checkout -- Assets/_Project/Settings ProjectSettings/GraphicsSettings.asset \\
                       ProjectSettings/QualitySettings.asset
EOF
exit 0
