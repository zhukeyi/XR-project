#!/bin/bash
# Unity 6000.0.59f2 离线安装（ARM64 Mac）
#
# ⚠️ 现状（2026-11-07 复核）：本脚本对应的 6000.0.59f2 目前**不需要装**。
#    - 本项目基准引擎是本机已装的 2022.3.62f3（OpenXR 赛道下限要求 2022.3.15f1+）。
#    - PICO 把 6000.0.59f2 列为「指定版本」只针对 **Spatial 模式**；只有改投 Spatial 赛道时才用它。
#    - Unity 6.0 LTS 支持已于 2026-10-16 结束，该线终版为 6000.0.85f2，故 59f2 已是旧补丁。
#    长期升级目标应为 Unity 6.3 LTS（支持至 2027-12），不是 6.0。
#    留着脚本是为了「改投 Spatial 赛道」这一条路径随时可走。
#
# 为什么要这个脚本：自动化环境里下载被出口代理劫持
# （download.unity3d.com 被解析到 es.n7-sparks.n7net.in，证书 2026-06-01 已过期，
#   返回 Elasticsearch 的 401），且 sudo 被禁用，装包必须要你的管理员密码。
# 所以下载 + 装包必须在你自己终端里跑。脚本负责：断点续传下载 → 校验大小与 MD5 → 拉起图形安装器。
#
# 用法：双击，或在终端执行
#   /Users/zhukeyi/WorkBuddy/2026-11-05-21-19-43/PICO_Mecha_Starter/Tools/install-unity-6000.0.59f2.command

set -u

VER="6000.0.59f2"
DIR="$HOME/Downloads/Unity-$VER"
EDITOR_URL="https://download.unity3d.com/download_unity/ef281c76c3c1/MacEditorInstallerArm64/Unity-$VER.pkg"
ANDROID_URL="https://download.unity3d.com/download_unity/ef281c76c3c1/MacEditorTargetInstaller/UnitySetup-Android-Support-for-Editor-$VER.pkg"
EDITOR_BYTES=4960440017
ANDROID_BYTES=674903654
EDITOR_MD5="ed04b4c010b5180e7758bf50767744a5"

mkdir -p "$DIR"
cd "$DIR" || exit 1

hr() { printf '%s\n' "────────────────────────────────────────"; }

fetch() {
  local url="$1" out="$2" want="$3"
  if [[ -f "$out" ]]; then
    local have
    have=$(stat -f%z "$out" 2>/dev/null || echo 0)
    if [[ "$have" == "$want" ]]; then
      echo "已存在且大小正确：$out"
      return 0
    fi
    echo "存在但大小不符（$have / $want），继续续传"
  fi

  echo "下载 $(basename "$out")（$((want / 1024 / 1024)) MB）"

  # 首选正常路径；失败则钉住 Akamai 真实 IP 重试（绕开被污染的 DNS）
  if ! curl -fL -C - --retry 5 --retry-delay 3 --connect-timeout 20 \
            -o "$out" "$url"; then
    echo "常规下载失败，尝试钉住 Akamai IP 重试…"
    local ok=1
    for ip in "${AKAMAI_IPS[@]}"; do
      echo "  → $ip"
      if curl -fL -C - --retry 3 --retry-delay 2 --connect-timeout 15 \
              --resolve "download.unity3d.com:443:$ip" \
              -o "$out" "$url"; then ok=0; break; fi
    done
    if [[ $ok -ne 0 ]]; then
      echo "下载失败：$url"
      return 1
    fi
  fi

  local got
  got=$(stat -f%z "$out" 2>/dev/null || echo 0)
  if [[ "$got" != "$want" ]]; then
    echo "大小校验失败：$got ≠ $want"
    return 1
  fi
  echo "大小正确：$got bytes"
}

# ───────────── 网络自检：先告诉你是哪一层出问题 ─────────────
preflight() {
  echo "网络自检：download.unity3d.com"
  local ip
  ip=$(dscacheutil -q host -a name download.unity3d.com 2>/dev/null | awk '/ip_address/{print $2; exit}')
  echo "  DNS 解析 → ${ip:-解析失败}"

  local cn
  cn=$(echo | openssl s_client -connect download.unity3d.com:443 \
        -servername download.unity3d.com 2>/dev/null \
        | openssl x509 -noout -subject 2>/dev/null | sed 's/^subject=//')
  echo "  证书持有者 → ${cn:-取不到}"

  if [[ -n "$cn" && "$cn" != *unity* ]]; then
    echo "  ⚠️ 证书 CN 不含 unity → 该域名被代理/DNS 劫持（典型症状：Hub 报 Validation failed）"
    echo "     建议：退出 Clash Verge（含 TUN 模式）后重跑本脚本，或给 unity3d.com 加 DIRECT 规则"
    echo "     本脚本仍会尝试钉 IP 下载，成不成功取决于劫持发生在哪一层"
  else
    echo "  DNS 与证书正常"
  fi
  echo
}

AKAMAI_IPS=(203.69.141.24 203.69.141.67)

hr
echo "Unity $VER 离线安装"
echo "下载目录：$DIR"
hr
preflight

echo
echo "【1/3】编辑器"
if ! fetch "$EDITOR_URL" "Unity-$VER.pkg" "$EDITOR_BYTES"; then
  echo
  echo "编辑器下载失败。两个可选方案："
  echo "  A. 在 Unity Hub 里装：Installs → Install Editor → Archive → 搜 $VER"
  echo "  B. 浏览器打开下面地址下载，再手动双击 pkg："
  echo "     $EDITOR_URL"
  read -n 1 -s -r -p "按任意键退出…"
  exit 1
fi

echo "校验 MD5…"
GOT_MD5=$(md5 -q "Unity-$VER.pkg")
if [[ "$GOT_MD5" != "$EDITOR_MD5" ]]; then
  echo "MD5 不匹配：$GOT_MD5 ≠ $EDITOR_MD5"
  echo "包可能损坏或被中间人替换，删掉重下。"
  read -n 1 -s -r -p "按任意键退出…"
  exit 1
fi
echo "MD5 正确：$GOT_MD5"

echo
echo "【2/3】安装编辑器（需要输入管理员密码）"
echo "会弹出图形安装器，点「继续 → 安装」，装到默认路径 /Applications/Unity/Hub/Editor/$VER"
open "Unity-$VER.pkg"
read -n 1 -s -r -p "安装器点完「完成」后，按任意键继续…"

echo
echo "【3/3】Android 模块"
if fetch "$ANDROID_URL" "UnitySetup-Android-Support-for-Editor-$VER.pkg" "$ANDROID_BYTES"; then
  echo "会弹出第二个安装器，装的是 Android Build Support（含 SDK & NDK / OpenJDK 需在 Hub 里补）"
  open "UnitySetup-Android-Support-for-Editor-$VER.pkg"
  read -n 1 -s -r -p "安装完成后，按任意键结束…"
else
  echo "Android 模块下载失败，可改用 Hub 补装：Installs → 该版本齿轮 → Add modules"
fi

hr
echo "收尾检查"
hr
echo "1. 许可证：Unity Hub → 设置 → Licenses → Add → Get a free personal license"
echo "   （没有许可证编辑器能开但打不出 APK，这是当前唯一硬阻塞）"
echo "2. SDK/NDK 子模块：Hub → Installs → $VER 右侧齿轮 → Add modules"
echo "   勾 Android SDK & NDK Tools + OpenJDK，否则 pico-cli 会报 ADB not found"
echo "3. 装完回报版本号，我接着写 S2 的 XR Rig 与右臂 IK"
echo
read -n 1 -s -r -p "按任意键关闭…"
