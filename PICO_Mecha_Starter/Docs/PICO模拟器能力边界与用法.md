# PICO 模拟器能力边界与用法

日期：2026-11-08  
取证方式：**官方文档原文 + 本机 `pico-cli 0.6.1` 实测**（不是二手转述）  
适用方案：《PICO_OpenXR_机甲参赛技术方案_Unity版.md》v2.1（OpenXR 赛道，目标 PICO Space Pro / PICO OS 6）

---

## 1 结论先行

### 1.1 三句话

1. **它是一台跑完整 PICO OS 6 的 Android 虚拟机**（官方原文：「运行完整的 PICO OS 6 系统镜像」，基于 Android AVD），不是 Unity 编辑器里的 Play 模式预览。装进去的是真 APK，走的是真 adb。
2. **它能把「构建 → 安装 → 启动 → 不崩 → 出截图 → 出日志」整条链闭环在你自己的电脑上**，而这一半恰好是能被脚本自动化的部分——我可以用 `pico-cli` 把它全部跑成命令。
3. **但它最高约 60 FPS、GPU 指标恒为 0、手柄射线与手势无法可靠自动化**（官方明列的差异）。「跑不跑得动、晕不晕、好不好玩」必须在真机判定。

### 1.2 一个常被忽略的关键事实

**Live Preview（实时预览）在 OpenXR 模式下不可用。**

官方「各开发模式支持的功能」表里，Live Preview 一行是：Unity XR 模式 ✅ / **Unity OpenXR 模式 `-`** / PICO Spatial 模式 `-`。而且它**仅支持 Windows**。

本项目走 OpenXR 赛道，因此 **Live Preview 这条路对我们关闭，模拟器（PICO Emulator）是唯一的电脑端运行环境**。这不是取舍，是没有第二个选项。

### 1.3 它不能替代什么（一张表先讲清）

| 维度 | 模拟器能给 | 只能真机 |
|---|---|---|
| 功能逻辑 | ✅ 完整闭环 | — |
| 打包链路 | ✅ APK 安装启动、权限、Manifest | — |
| 画面构图 | ✅ 截图 / 录屏（1–1800 s，MP4） | 立体 UI 最终效果 |
| 帧率与性能 | ❌ 上限约 60 FPS、GPU 指标恒为 0 | ✅ 唯一可信来源 |
| 手柄射线 / 手势 | ⚠️ 人工可点，**无法可靠自动化** | ✅ |
| 晕动与舒适 | ❌ | ✅ |
| 触觉、空间音频方位 | ❌ | ✅ |
| 眼动 / 面部 / 物体追踪 | ❌ | ✅ |

---

## 2 它到底是什么

### 2.1 形态与定位

| 项 | 值 |
|---|---|
| 本质 | 基于 **Android AVD** 的虚拟设备，跑完整 **PICO OS 6** 系统镜像 |
| adb | **完全适用**（官方原文：「the full capabilities of adb are equally applicable to it」） |
| 模拟能力 | 头部运动、**有限的手势**、空间建图环境 |
| 版本 | PICO Emulator **v0.8.4 beta**（2025-09-24 更新）；配套 PDC v1.4.8 |
| 首次启动 | macOS ≤ 60 s，Windows ≤ 180 s（之后显著加快） |
| 单实例占用 | **约 6 GB 内存 + 6 vCPU** |
| 下载 | 镜像体积大，慢网络下约 10 分钟；**磁盘至少预留 32 GB** |

### 2.2 为什么它对本项目特别重要

官方 FAQ 的原文是决定性的：

> **「PICO OS 6 仅能在 PICO Space Pro 和新的 PICO 模拟器上运行。旧款 PICO 设备和旧版 PICO 模拟器只能运行 PICO OS 5。」**

而我们方案的目标设备正是 **PICO Space Pro / PICO OS 6**，硬件 2026 年才全球发布。所以：

> **模拟器不是「没有真机时的降级替代」，而是当前唯一能跑目标 OS 的环境。**

这一点改变了它的价值判断——它验证的不是「差不多能跑」，而是**目标系统上的真实行为**（OS 6 的窗口管理、多应用渲染、系统级输入切换）。

### 2.3 三种「预览」的区别（最容易混淆）

| 方式 | 本质 | 能否代表目标机 | OpenXR 可用 |
|---|---|---|---|
| Unity 编辑器 Play 模式 | 编辑器内模拟 XR（无 OS） | 否，连设备输入都是假的 | ✅（但只是开发期） |
| **Live Preview**（PDC） | 编辑器连真机实时串流 | 是，但**需要真机在手**，且仅 Windows | ❌ 表内为 `-` |
| **PICO Emulator** | 完整 OS 6 虚拟机 + 真 APK | **是目标 OS，不是目标硬件** | ✅ |

三者不能互相替代：Play 模式验证代码，Live Preview 验证真机表现，Emulator 验证 OS 行为与整链路。

---

## 3 能做什么（命令级，本机已验证可用）

`pico-cli emulator` 的官方定位写得很直白：**「This set of commands is designed for AI」**，全部支持 `--format json`。

### 3.1 生命周期

```bash
pico-cli emulator doctor          # 环境自检
pico-cli emulator setup           # 诊断前置条件并打印修复指引
pico-cli emulator install         # 下载镜像（不创建 AVD）
pico-cli emulator create --avd demo -y
pico-cli emulator start --avd demo --watch -y   # 启动，掉线自动重启
pico-cli emulator status
pico-cli emulator list
pico-cli emulator stop / delete / delete-image -y
pico-cli emulator dump-logs --out ./sim-logs    # 起不来时导模拟器自身日志
```

### 3.2 安装与运行

```bash
pico-cli app install ./app-debug.apk -r -g      # 覆盖安装 + 授权
pico-cli app launch <pkg> --activity .MainActivity
pico-cli app list / app info <pkg> --format json
pico-cli app stop / uninstall
```

官方提示：`app launch` 只等进程创建，不等 UI 就绪——做 UI 自动化前需自行轮询状态。

### 3.3 诊断（这是它比真机方便的地方）

```bash
pico-cli app watch-crash <pkg> --start --activity .MainActivity   # 一条命令拿崩溃栈
pico-cli log -n 200 -l E                     # 最近 200 行 error
pico-cli log -b crash                        # 只看 crash buffer
pico-cli log -f -C                           # 清空后持续跟随
pico-cli files push ./assets /sdcard/assets
pico-cli files pull /sdcard/out ./out
pico-cli capture screenshot -o ./shot.png
pico-cli capture record -t 30 -o ./demo.mp4  # 1–1800 秒
```

### 3.4 多设备与端口转发

```bash
pico-cli device list                         # 真机与模拟器会同时列出 emulator-5554/5556…
pico-cli app install ./app.apk -d emulator-5556   # 指定目标
pico-cli adb forward tcp:8080 tcp:8080
pico-cli adb reverse tcp:3000 tcp:3000       # ★ APK 可访问本机服务
pico-cli shell <cmd>                         # 等于 adb shell
```

`adb reverse` 这一条对我们有用：APK 内的遥测/调试面板可以直接连本机服务，不必反复导出文件。

---

## 4 硬边界（官方原文五条）

官方在 Caution 里明列「PICO emulator cannot be fully equivalent to a real device」：

| # | 限制 | 原文要点 | 对我们的后果 |
|---|---|---|---|
| 1 | **空间交互** | 无法可靠自动化测试需要真实空间操作的功能，**举例即为 3D 立体窗口、手柄射线、手势** | 抓杆、光剑扫掠、面板射线**不能脚本化回归**，只能人工点 |
| 2 | **性能诊断** | 可用于验证命令链与报告结构，但**不准确反映性能**；**GPU 指标恒为 0**；**最高约 60 FPS（若目标 90 FPS，测试会失败）** | 性能验收 100% 交给真机；模拟器上跑 Perf 报表只能验「字段有没有」 |
| 3 | **截图** | 常规场景为全彩，但特定立体 UI 的最终效果取决于真机渲染路径 | 截图可作构图证据，不能作视觉验收 |
| 4 | **用户体验** | 真实空间交互与佩戴体验必须在真机验证 | 晕动、舒适、沉浸感无法在电脑上判定 |
| 5 | **系统要求** | macOS 需 **14.0+ / 16 GB RAM / M1 Pro 起，不支持 Intel**；Windows 需 i5 + **GTX 1060 8 GB 显存**；建议预留 ≥ 12 GB 可用内存 | 见 §7 内存账 |

---

## 5 对本项目的具体影响

### 5.1 能在模拟器上闭环的环节（约 8 项）

| 环节 | 判据 |
|---|---|
| APK 打包链路 | 安装成功、启动无 `FATAL`、无缺权限报错 |
| Manifest / 权限 / 包名 | `app info --format json` 可核对 |
| 场景加载与资源引用 | 启动后进主场景不报 `NullReference` / 缺资源 |
| 座舱相机锚点 | 截图里能确认视点高度与朝向（`SeatAnchorWorldY = 11.55`） |
| 枢轴与门控逻辑 | 舱门开合、抓杆状态机的数值断言进日志 |
| 面板布局与遮挡 | 截图初判字号、位置、遮挡关系 |
| 崩溃回归 | `app watch-crash` 每次提交跑一次 |
| 提交材料素材 | `capture record` 直接出 MP4，可做评审预演片 |

### 5.2 必须真机的环节（6 项）

| 环节 | 原因 |
|---|---|
| 稳态帧时间 / 90 Hz | 模拟器上限 60 FPS |
| 热降频曲线 | 无功耗与散热约束 |
| FFR / ETFR 视觉质量 | 需真实双眼渲染与镜头畸变 |
| 手柄追踪延迟与触觉 | 宿主输入延迟不同，无振动 |
| 空间音频方位感 | 依赖真实双耳输出 |
| 晕动与舒适 | 60 Hz 宿主 + 无前庭输入，结论无效 |

### 5.3 我（AI）在模拟器上的能力边界

这一条必须诚实说清，因为它直接影响「能不能自动化验收」：

| 能做（可脚本化、可复现） | 不能做 |
|---|---|
| 建/启/停 AVD、装 APK、启动、抓日志 | 用手柄射线去点一个 3D 面板（官方明示不可靠） |
| 崩溃栈、error 日志、文件推拉 | 手势交互的自动验证 |
| 截图、录屏、生成对比图 | 判定「这个画面好不好看」 |
| 端口转发、adb shell 任意命令 | 判定帧率是否达标（GPU 指标恒 0） |
| 多实例并行、指定设备 | 判定晕动与舒适 |

**换句话说：模拟器把「工程正确性」变成了我可以自动跑的部分，把「体验正确性」留给了人和真机。**

---

## 6 本机环境：已装好并跑通（2026-11-08 21:52）

### 6.1 最终状态

| 项 | 状态 |
|---|---|
| `pico-cli` | **0.6.1 (public) darwin-arm64** ✓ |
| Android SDK | **Platform 35 + Sources 35 + platform-tools(adb 37.0.1)**，装在 `~/Library/Android/sdk` ✓ |
| PICO Emulator | **6.1.0**，装在 `~/Library/PICO/sdk/6.1/emulator`（镜像 2961 MB）✓ |
| AVD | **`demo`** 已创建，`~/.pico/avd/demo.avd` ✓ |
| 运行状态 | **已启动，`emulator-5554` adb online** ✓ |
| 设备身份 | `model=swan_arm64`、`product=swan`、`device=pico_spaceos_emulator_arm64`、**Android 16 / SDK 36**、`arm64-v8a` ✓ |
| 截图 | `pico-cli capture screenshot` 成功，得到 PICO OS 6 空间桌面（3D 房间 + Dock：浏览器/设置/播放器/文件 + 状态栏） ✓ |
| PICO Spatial Plugin | 官方 docotor 判为 **optional，未装**（只有 Android Studio 插件工作流才需要） |

`pico-cli emulator doctor` 现在是：Android SDK `[ok]`、存储布局 `[ok]`、模拟器 bundle `[ok]`，仅剩一条提示——

> `[warn] PICO_HOME: configured via ~/.pico/config.json, but is not exported in the current shell. Manual action: export PICO_HOME='/Users/zhukeyi/Library/PICO/sdk'`

这条只影响子进程环境继承，**不影响 CLI 自身运行**（实测 `status` / `device list` / `capture` 全部正常）。

### 6.2 实际执行的命令序列（可复现）

```bash
# 1. Android SDK（复用给 Unity 打包，不必装两套）
curl -L -o cmdline.zip https://dl.google.com/android/repository/commandlinetools-mac-11076708_latest.zip
unzip -q cmdline.zip && mv cmdline-tools ~/Library/Android/sdk/cmdline-tools/latest
yes | sdkmanager --sdk_root=$HOME/Library/Android/sdk --licenses
sdkmanager --sdk_root=$HOME/Library/Android/sdk "platform-tools" "platforms;android-35" "sources;android-35"

# 2. 模拟器镜像（2961 MB，7 分 52 秒，均速 6.3 MB/s，校验通过）
pico-cli emulator install

# 3. AVD 与启动
pico-cli emulator create --avd demo -y
pico-cli emulator start --avd demo
pico-cli emulator status        # → ADB online: yes, emulator-5554
pico-cli capture screenshot -o shot.png
```

### 6.3 两个必须记下来的环境坑

| # | 现象 | 根因 | 处理 |
|---|---|---|---|
| 1 | `pico-cli setup` / `emulator setup` 报 `Cannot determine process identity before acquiring file lock` | CLI 用 `ps -o lstart= -p <pid>` 判断持锁进程身份，而**本机宿主策略禁止执行 `/bin/ps`**（沙箱内外都禁） | 仅在**需要写状态锁**的命令（setup 系列）前置一个 `ps` 替身；`status / device / capture / log` 等运行期命令**不需要** |
| 2 | `pico-cli setup` 里 `git clone` 报 `Error in the HTTP2 framing layer` / `Empty reply from server` | 到 `github.com` 的连接不稳（`git` 走 HTTP/2 会失败；`curl -I github.com` 直接返 000，但仓库地址返 200） | `GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=http.version GIT_CONFIG_VALUE_0=HTTP/1.1`（非持久化，只对当次进程链生效）。首次 clone 成功，随后的增量 fetch 仍偶发失败 |

**`pico-cli setup` 至今未完成**（GitHub 增量 fetch 两次失败）。它装的是 **agent 插件 + 知识库**，与「跑模拟器」无关——模拟器全链路已可用。要用它的 agent 集成时再重试。

### 6.4 端到端链路已验证（打包 → 安装 → 启动 → 截图）

**结论：这条链在当前机器上已经跑通，可重复执行。**

| 环节 | 实测结果 |
|---|---|
| 打包 | `Tools/build-probe-apk.sh` → `SteelSpineProbe.apk`（12 KB，apksigner 签名，SHA-256 `2fc06118…e4224`） |
| 安装 | `adb install -r -g` → **Success**，增量安装 158 ms |
| 启动 | `am start -W` → **Status: ok，COLD，TotalTime 1229 ms** |
| 前台确认 | `pidof` = 14801；`topResumedActivity = com.steelspine.probe/.MainActivity` |
| 截图 | `pico-cli capture screenshot` → 3.3 MB PNG，画面为 PICO OS 6 空间房间 + 应用平面窗口 |

截图中的文字（由我们自己的代码渲染）为：

```
Steel Spine Probe
钢脊 HX-07 · 链路探针
包装名  com.steelspine.probe
设备    swan_arm64
系统    Android 16  (SDK 36)
ABI     arm64-v8a
```

工具链版本：`aapt2 / d8 / zipalign / apksigner` 来自 build-tools **35.0.0**，`javac / keytool` 来自 Android Studio 内置 JBR，编译目标 `android.jar` = **API 35**，`minSdk 29 / targetSdk 35`。

> **必须说清的边界**：这个 APK 是**手工打的纯 Android 应用**，不含 Unity。它证明的是「Android 打包工具链 + 模拟器 + adb 安装启动 + 截图取证」这条链可用，**不证明 Unity 的 Android 导出可用**——后者缺模块，见 §6.5。

### 6.5 Unity 的 Android 模块：已装（**此前的「缺失」结论是误判，已订正**）

**订正说明（2026-11-09 23:45）**

此前本节的结论是「缺 `AndroidPlayer`，需人工下载 0.68 GB 模块包」。**该结论错误**，原因是查错了目录：

| 查的地方 | 内容 | 是否模块目录 |
|---|---|---|
| `Unity.app/Contents/PlaybackEngines/` | 只有 `MacStandaloneSupport` | ✗ 这是内置平台的目录 |
| **`/Applications/Unity/PlaybackEngines/`** | **`AndroidPlayer`（2.1 GB / 670 个文件）** | ✓ **模块装在这里** |

模块由 `UnitySetup-Android-Support-for-Editor-2022.3.62f3.pkg` 安装，**落位时间 2026-04-18 18:05**，与 `~/Downloads` 里同名的 pkg 载荷**逐项一致（670 文件对 670 文件）**。pkg 内 `postinstall` 脚本的目标路径写明为 `/Applications/Unity/PlaybackEngines/AndroidPlayer`，`pkg-ref id="com.unity3d.AndroidPlayer"`。

**引擎自证（决定性验证）**

```
$ Unity -batchmode -quit -projectPath PICO_Mecha_Starter         -executeMethod SteelSpine.EditorTools.CheckAndroidSupport.Run
Unity 版本        : 2022.3.62f3
IsBuildTargetSupported(Android) : True
AndroidSdkRoot    : /Users/zhukeyi/Library/Android/sdk -> True
JdkPath           : ~/.local/jdk/jdk-17.0.21+9/Contents/Home -> True
AndroidNdkRoot    : .../ndk/23.1.7779620 -> False   （Mono 构建不需要）
GradleTemplates   : /Applications/Unity/PlaybackEngines/AndroidPlayer/Tools/GradleTemplates -> True
✓ Android 构建目标可用
```

**工具链依赖现状**

| 依赖 | 状态 |
|---|---|
| Unity 编辑器 | 2022.3.62f3（`/Applications/Unity/Unity.app`，手动安装） |
| Android 模块 `AndroidPlayer` | ✅ **已装**，2.1 GB，Gradle 模板/IL2CPP/bundletool 齐备 |
| Android SDK 35 | ✅ platform 35 + sources 35 + build-tools 35.0.0（`~/Library/Android/sdk`） |
| JDK 17 | ✅ `~/.local/jdk/jdk-17.0.21+9/Contents/Home`（Unity 2022.3 的 Gradle 不认 JDK 25） |
| NDK r23b | ⬜ 未装，Mono 构建不需要；IL2CPP 时用 `sdkmanager "ndk;23.1.7779620"` |

**工具链路径已写入 Unity 偏好**（`com.unity3d.UnityEditor5.x`）：`AndroidSdkRoot` / `JdkPath` / `AndroidNdkRoot` + `AndroidUseEmbedded* = false`。

> 注意：在 `-batchmode -quit` 里调 `EditorPrefs.SetString` **不会落盘**（实测下次会话读回 `(未设置)`），必须用 `defaults write` 或改用环境变量。这是踩过的坑。

**剩余未验证项**：尚未真正打出过 Android APK。`IsBuildTargetSupported = True` 只证明模块与工具链就位，不等于出包链路验证通过——后者要用 `-buildTarget Android` 实际构建一次。

### 6.6 内存实测

模拟器运行中，整机：`Pages free 4443`（≈69 MB）、`System-wide memory free percentage: 41%`、累计 pageout 46.9 万次。

> **结论：单独跑模拟器可接受（41% 可用），但同时开 Unity 会进入 swap。** 见 §7 的作业顺序。

### 6.7 机体在模拟器中的渲染验证（2026-11-09 16:55）

**结论：`mecha_model` 的机体几何能在 PICO OS 6 模拟器里被正确加载并渲染出来。**

做法：写了一个不依赖 Unity、不依赖引擎的 GLES 2.0 查看器，把几何以自定义二进制喂进去。

| 环节 | 实测 |
|---|---|
| 几何导出 | `mecha_render/tools/export_viewer_bin.py` → **244 分件 / 12,000 顶点 / 4,000 三角 / 342 KB** |
| 二进制布局 | 40 字节头 + 244×**60** 字节分件表 + 顶点区(6f/顶点) + 索引区；总长 **350,680 字节**（与预期逐字节相符） |
| APK | `Tools/android-viewer` → **76 KB**，GLES2 + `glDrawArrays` 逐件绘制 |
| 打包 | `Tools/build-apk.sh`（aapt2 + javac + d8 + zipalign + apksigner，无 Gradle） |
| 运行 | 安装 Success、冷启动 **0.4–1.2 s**（多次实测）、进程存活、`glErr=0` |
| 截图 | 机体**头到脚完整入画**，白/蓝/红分区可辨，右手侧可见武器 |

#### 三个把画面做黑了的真实 bug（都值得记）

| # | 现象 | 根因 | 修法 |
|---|---|---|---|
| 1 | `FATAL EXCEPTION: GLThread — IllegalArgumentException: Must use a native order direct Buffer` | 几何读进了堆上的 `ByteBuffer.wrap(byte[])`，GLES 的 `glVertexAttribPointer` 只接受 direct buffer | `ByteBuffer.allocateDirect(n).put(raw)` |
| 2 | 窗口纯色、无任何几何，且 `glErr=0` | **MVP 顺序错**：写成 P·R·T(含 -dist)，等于让模型绕世界原点公转；34° 偏航就把整机甩出视锥（手算 NDC x = **−1.15**，被裁） | 改成 **P · T(后退) · R · T(居中)**，即先居中再自转再后退；修后 NDC = (−0.14, −0.07, 0.97) |
| 3 | 顶点数据解析错位、画不出东西 | 分件记录步长按 44 字节算，实际是 32(名)+12(rgb)+16(4×u32) = **60 字节** | 统一为 60；文件总长可作校验（350,680 字节） |

另有两个环境侧发现：

- **GL 图层会被截图捕获**：把 `glClearColor` 临时改成亮绿后截图变绿，证明 `pico-cli capture screenshot` 拿得到 `GLSurfaceView` 的内容，不是空窗。
- **叠在 `GLSurfaceView` 之上的普通 View 不会出现在截图里**（文字层始终不可见），所以应用内的 HUD 必须画进 GL，或用系统窗口标题承载。

#### 必须说清的边界

| 项 | 说明 |
|---|---|
| 不是沉浸式 | 这是普通 2D 应用，在 OS 6 里以**平面窗口**呈现。真正的沉浸式需要 **OpenXR 会话**，只能从 Unity（缺 Android 模块）或 NDK 原生写 |
| 不能验性能 | 模拟器上限约 60 FPS、GPU 指标恒为 0。这次只能证明「画得对」，不能证明「跑得快」 |
| 未做贴图 | 用的是每件平色（源自 `r3d.Mat.rgb`），不是 PBR。贴图要等 UV 与 Substance |

---

### 6.8 Unity 导出 APK 全链路已跑通（2026-11-10）

**结论：`机体几何 → Unity 场景 → IL2CPP/ARM64 APK → 装进 PICO OS 6 模拟器 → 截图` 这条链已经打通并留下证据。**

| 环节 | 实测结果 |
|---|---|
| 场景生成 | `Assets/_Project/Scenes/Build/SMOKE_00_Boot.unity`，机体包围盒 **W 6.51 / H 18.20 / D 9.59 m** |
| 构建 | `BuildPipeline.BuildPlayer` → **Result: Success，0 error / 1 warning** |
| 产物 | `out/android/SteelSpine.apk`，**16 MB**，包名 `com.steelspine.smoke`，minSdk 29 / targetSdk 35 |
| 原生库 | `lib/arm64-v8a/libil2cpp.so`(24.6 MB) + `libunity.so`(14.6 MB) + `libmain.so` —— 确认 **IL2CPP + ARM64** |
| 安装 | `adb install -r -g` → **Success** |
| 启动 | `am start -W` → **Status ok / COLD / 311–1227 ms** |
| 画面 | 机体**直立、头到脚完整、白蓝红分区可辨**；`OnGUI` 文字由我们自己的代码渲染 |

证据图：`Docs/参照/unity_android/01_unity_apk_in_emulator.png`（另附故障态 `00_故障_躺倒姿态.png`）。

画面上的文字（自渲染）：

```
Steel Spine  |  Unity Android 链路验证
Unity 2022.3.62f3    后端 Player
屏幕 1920×1080    累计帧 29
设备 pico_swan_arm64    图形 OpenGLES3
已运行 8 s
```

#### 六个卡点（按被撞到的顺序，全部有据可查）

| # | 现象 | 根因 | 处理 |
|---|---|---|---|
| 1 | `UnityException: Target architecture not specified` | **Unity 的 Mono 后端不支持 Android ARM64**；写 `ARM64` 后校验把架构重置为 None | 改 **IL2CPP + ARM64**（模拟器 `abilist` 只有 `arm64-v8a`，无 32 位，Mono/ARMv7 装不上） |
| 2 | `UnityException: JDK not found` | ① Unity 2022.3 只认 **JDK 11**（JDK 17 直接判 invalid）；② 传 `.../Contents/Home` 会被再拼一次 `Contents/Home` | 装 JDK 11；`JdkPath` 指向 **bundle 根**（`~/.local/jdk/jdk11`），由 Unity 自己补 `Contents/Home` |
| 3 | `UnsupportedClassVersionError`（SdkManagerCli / class 61） | 我们的 `cmdline-tools` 是 **13.0**（需 Java 17），而 Unity 用 JDK 11 调 `sdkmanager` | 装 **Command-line Tools 6.0**（`commandlinetools-mac-8092744`）到 `cmdline-tools/latest`，与 13.0 并存（13.0 移到 `cmdline-tools.j17`） |
| 4 | `UnityException: Android NDK not found`（目录明明存在） | **偏好键名是全大写缩写**：`AndroidSDKRoot` / `AndroidNDKRoot`，不是 `AndroidSdkRoot` / `AndroidNdkRoot`。从 `UnityEditor.Android.Extensions.dll` 的字符串表可查证 | 改键名，同时导出 `ANDROID_HOME` / `ANDROID_NDK_ROOT` 兜底 |
| 5 | 机体**躺倒在画面底部**，只见一小块 | FBX 的 `GlobalSettings` 声明 `UpAxis=Y`，但 Blender 侧 `bake_space_transform=False`，几何实际仍是 Z-up；Unity 用**根节点 -90°X 旋转**校正。两处代码把这个旋转抹掉了：`transform.rotation = identity` 与 `Turntable` 每帧写 `localRotation` | 改为「**外层 `MECH_YAW` 只做偏航 + 内层保留原姿态**」；`bakeAxisConversion` 保持 `False` |
| 6 | 取景算错（相机距 16.34，裁头） | `Renderer.bounds` 与顶点矩阵在批处理「刚实例化」时**滞后**，曾把深度 9.564 误读成高度 | 取景一律用确定常量（18.200 / 6.471 / 9.564，中心 y=9.10），运行时测量只作日志 |

#### 三个必须说清的边界

| 项 | 说明 |
|---|---|
| **不是 OpenXR 沉浸式** | 这是普通 Android 应用，在 OS 6 里以**平面窗口**呈现。真正沉浸式需要 PICO Unity OpenXR SDK + XR Plugin 管理，当前工程未装 |
| **不能判性能** | 画面显示「累计帧 29 / 已运行 8 s ≈ 3.6 fps」，是模拟器 **SwiftShader 软渲染 + 窗口节流**的结果，**不代表真机**。故已把 FPS 从 HUD 移除，只保留累计帧数（不构成性能声明） |
| **无法去掉 Unity 启动画面** | Personal 授权不允许关闭 Splash，冷启动后会先显示约 2–3 s |

#### 复现命令

```bash
export JAVA_HOME="$HOME/.local/jdk/jdk11/Contents/Home"
export ANDROID_HOME="$HOME/Library/Android/sdk"
export ANDROID_NDK_ROOT="$HOME/Library/Android/sdk/ndk/23.1.7779620"

Unity -batchmode -quit -projectPath PICO_Mecha_Starter -buildTarget Android \
      -executeMethod SteelSpine.EditorTools.BuildAndroidApk.Run -logFile -

adb install -r -g out/android/SteelSpine.apk
adb shell am start -W -n com.steelspine.smoke/com.unity3d.player.UnityPlayerActivity
pico-cli capture screenshot -o shot.png
```

> 注意：`Unity` 进程**必须在非沙箱环境执行**，否则它在退出时会尝试删除
> `~/Library/Application Support/Unity/CoreBusinessMetrics.db-{shm,wal}` 被策略拦截而失败。
> 另外 `Tools/install-unity-android-module.sh` 已无必要（模块本来就装着），保留仅作备用。

---

## 7 16 GB 内存的现实约束

这是本机最硬的约束，必须提前规划：

```
系统 + 浏览器          ≈ 3–4 GB
Unity 编辑器（2022.3）  ≈ 5–7 GB
PICO Emulator         ≈ 6 GB + 6 vCPU
────────────────────────────────
合计                   ≈ 14–17 GB  → 16 GB 会 swap
```

而 CPU 只有 10 核（4 性能 + 6 能效），模拟器一开口就要 **6 vCPU**，同时跑 Unity 编译会明显变慢。

**建议的作业顺序（不要三者同时开）**：

1. Unity 里 Build（不启动 Play 模式）→ 得到 APK
2. 关闭 Unity（或至少不切平台）
3. 启动模拟器 → 装 APK → 截图 / 录屏 / 抓日志
4. 关闭模拟器 → 回 Unity 改代码

代价是每次回归多一次启停（约 60 s），收益是不进入 swap。若确实需要并行，**优先加内存而不是加机器**——16 GB 是官方最低线，不是舒适线。

---

## 8 建议的日常用法

| 频率 | 动作 | 产出 |
|---|---|---|
| 每次代码提交 | `app install` + `app watch-crash` | 崩溃回归结论 |
| 每天 | 截图 4 个固定机位 + 与上一版对比 | 构图回归 |
| 每个里程碑 | `capture record -t 30` 录一段 | 评审预演素材 |
| 门 1 / 门 2 验收 | 日志数值断言（枢轴角、眼高、门控状态） | 可核对的验收证据 |
| 每周 | 汇总「模拟器已验证 / 待真机验证」两栏 | 提交材料的测试说明 |

**纪律**：任何写进提交材料的性能数字，必须标注来源。「模拟器实测 60 FPS」这种表述会被评委问穿——正确写法是「模拟器验证功能闭环，性能待真机」。

---

## 9 三个待确认

| # | 问题 | 为什么重要 |
|---|---|---|
| 1 | **OS 6 模拟器对 Unity OpenXR APK 的实际兼容度** | 官方 OpenXR 教程把 Emulator 列为 Run Device，但未单独声明「OS 6 版模拟器已验证 OpenXR 应用」。这是装好后的第一个必测项 |
| 2 | 比赛评委用哪台设备 | 若用 PICO 4 Ultra（OS 5），模拟器（OS 6）与验收机不同版本，需要在 4 Ultra 上复验一遍 |
| 3 | Android Studio 版本要求的具体值 | `isRequiredVersion: false` 说明当前 2026.1 不符 PICO 期望，需查 Spatial Plugin 文档确认目标版本，再决定降/升 |

---

## 附：来源

| 事实 | 来源 | 取证日期 |
|---|---|---|
| 运行完整 PICO OS 6 镜像；模拟头部运动、有限手势、空间建图；Windows 8 GB 显存 / macOS M 系列；宿主机 60 Hz | PICO Space Pro & PICO OS 6 常见问题（官方 FAQ） | 2026-11-08 |
| OS 6 仅能在 Space Pro 与新模拟器运行，旧设备只跑 OS 5 | 同上 | 2026-11-08 |
| 基于 Android AVD、adb 全能力、6 GB/6 vCPU、≤60 s 启动、录屏 1–1800 s、32 GB 磁盘、全部 `--format json`、「designed for AI」 | PICO CLI · Run and debug applications using PICO Emulator | 2026-11-08 |
| 五条硬边界的原文（空间交互不可靠自动化、GPU 指标恒 0、最高约 60 FPS、立体 UI 截图、体验需真机） | 同上 Caution 段 | 2026-11-08 |
| macOS 14.0 / 16 GB / M1 Pro / 32 GB 磁盘 / 建议 12 GB 可用内存 | Install PICO Emulator（Spatial Toolkit） | 2026-11-08 |
| Live Preview 仅 Unity XR 模式支持、仅 Windows；OpenXR 模式为 `-` | Functionalities supported by each development mode | 2026-11-08 |
| Emulator v0.8.4 beta（2025-09-24）、PDC v1.4.8 | PICO Developer 下载页 | 2026-11-08 |
| 本机环境、doctor 结果、`~/.pico` 状态 | **本机实测** `pico-cli 0.6.1` | 2026-11-08 |
