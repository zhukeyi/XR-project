#!/bin/bash
# 双击运行（或在 Terminal 里执行）：初始化 PICO CLI 并拉起模拟器。
#
# 为什么必须由你手动执行：
#   pico-cli 的 setup / emulator 会用 ps 校验进程身份来抢文件锁，
#   而自动化沙箱对 ps 返回 "operation not permitted"，
#   于是 CLI 报 "Cannot determine process identity before acquiring file lock" 并拒绝写入。
#   在你自己的 Terminal 里 ps 是正常的，所以下面的命令能跑通。

set -u
export PICO_CLI_NO_TELEMETRY=1

cd "$(dirname "$0")/.." || exit 1

echo "工程目录：$PWD"
echo

echo "════ 1/6 初始化 PICO 环境（Unity 路径 + 全局配置） ════"
pico-cli setup --platform unity --scope global --region cn --project "$PWD" --yes
echo

echo "════ 2/6 诊断模拟器依赖 ════"
pico-cli emulator doctor
echo

echo "════ 3/6 下载模拟器镜像（首次约 1–2 GB） ════"
pico-cli emulator install
echo

echo "════ 4/6 创建 AVD ════"
pico-cli emulator create || pico-cli emulator create --help
echo

echo "════ 5/6 启动（首次启动约 60 秒） ════"
pico-cli emulator start
echo

echo "════ 6/6 状态 ════"
pico-cli emulator status
pico-cli device list || true

echo
echo "全部完成。之后在 Unity 里出一版 APK，用下面这条装进去："
echo "  pico-cli app install <你的.apk>"
echo
read -n 1 -s -r -p "按任意键关闭这个窗口…"
