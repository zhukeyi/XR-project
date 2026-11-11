# 里程碑分解：从当前成果到「可参赛的 OpenXR 沉浸体验」

> 编写日期：2026-11-10
> 基线：`SteelSpine.apk`（IL2CPP/ARM64，16 MB）已在 PICO OS 6 模拟器跑通并截图取证
> 对照文档：`PICO_OpenXR_机甲参赛技术方案_Unity版.md` v2.1 §10–§13、`制作流程与协作方式.md` §3、`Docs/PICO模拟器能力边界与用法.md` §6.8
>
> **2026-11-11 更新：M1 已通过。** 本文档 §1 的三句判断（写在 11-10）已成历史——当天夜里把 OpenXR 底座接上了，
> 且**在模拟器上跑出了真沉浸式会话**（双眼 1920×1920×2、相机位姿由 OpenXR 驱动）。实测证据与踩坑记录见 §10，
> 后续 M2 起的排期不变，但 §2 状态表中 4 项 ❌ 已转 ✅。

---

## 1 结论（先行）

**当前成果完成的是「资产 + 出包」两件事，OpenXR 沉浸这一层一行代码都还没有。**

具体讲三句：

1. **已经能做的事**：把 `mecha_render` 的机体几何转成 Unity 能吃的 FBX，用脚本无头生成场景、打成 IL2CPP/ARM64 APK、装进 PICO OS 6 模拟器、渲染出直立机体并截图。这条链**可复现、可回归**。
2. **还没有的事**：XR 会话（OpenXR）、6DoF 头显姿态、手柄输入、双眼立体、座舱空间、任何交互。所以现在这个 APK 在 OS 6 里是**平面窗口**，不是沉浸式。
3. **真实的进度判断**：原排期把 11/06–11/09 定为「环境锁版：PICO SDK 导入、空 APK 上模拟器」。其中**「空 APK 上模拟器」已超额完成**（我们上的是真资产，不是空场景），但**「PICO SDK 导入」这一格是空的**。所以 S2「灰盒座舱与驾驶」按原计划 11/10 已经该开工，实际还差一道 M1 底座。

**因此第一个里程碑不是「做座舱」，而是「把 XR 底座接上并验证模拟器能跑 OpenXR」。这件事不通，后面所有工作都建在沙上。**

---

## 2 现状：已验证到什么程度

| 能力 | 状态 | 证据 |
|---|---|---|
| 机体资产（244 分件 / 4,000 三角 / 11 材质） | ✅ | `mecha_render/out/pico/mecha_parts.fbx`（716 KB），Blender 回读一致 |
| FBX → Unity 导入 | ✅ | `Assets/_Project/Models/mecha_parts.fbx`，包围盒 W 6.51 / H 18.20 / D 9.59 m |
| 无头场景生成 | ✅ | `SMOKE_00_Boot.unity`，`BuildAndroidApk.BuildScene()` |
| Android 打包链路 | ✅ | IL2CPP + ARM64 + GLES3，`Result: Success`，0 error |
| APK 上模拟器 | ✅ | 安装 Success，冷启动 311–1227 ms，见 `Docs/参照/unity_android/01_...png` |
| 脚本编译门禁 | ✅ | `Tools/compile-check.sh`，28 脚本 0 error |
| 输入抽象层（8 通道 + 能力位 + 降级） | ✅ 代码已写 | `Core/Inputs/InputRouter.cs`、`InputSources.cs` |
| **OpenXR 会话 / 6DoF 头显** | ✅ 2026-11-11 | 会话状态到 `FOCUSED`；`HMD pose (0,1.65,0)` 与 `Cam world (0,1.65,0)` 相等（场景里相机初始为原点） |
| **双眼立体渲染** | ✅ 2026-11-11 | 启动报告 `SinglePassInstanced`；运行时 `SinglePassMultiview`；`Eye tex 1920×1920 vol=2` |
| **手柄真实输入** | ⚠️ 部分 | 旧版 `InputDevices` 能枚举 HMD 且位姿有效；**手柄位姿无数据**（模拟器无手柄，且 interaction profile 落到 `hand_interaction_ext`）→ 手柄必须走 Input System，见 §10.4 |
| 座舱空间 / 座舱内构 | ❌ | 场景里只有机体 + 相机 + 两盏灯 |
| 任何交互（抓杆/面板/光剑） | ❌ | 无 |
| **HUD / UI 底座** | ✅ 2026-11-11 | world-space Canvas 在立体渲染下正常显示（IMGUI 不可用，见 §10.3） |
| URP | ❌ | 工程是 Built-in（`m_CustomRenderPipeline: {fileID: 0}`），与方案 v2.1 声明的 URP 14 不符 |

**一个容易被忽略的好消息**：输入层不是从零开始。`IInputSource` 已经把转向、俯仰、油门、扳机、握持、助推、菜单、面板选择归成 8 个抽象通道，并带能力位与优先级降级。换设备时改的是「谁供这个通道」，不是 gameplay。这意味着接 OpenXR 的成本主要在**一个适配类**，而不是整个输入系统重写。

---

## 3 与既有排期的对齐与偏差

| 原阶段 | 原定周次 | 现状 | 偏差 |
|---|---|---|---|
| S1 规格 | 11/06–11/08 | 已完成（交互规格、契约、性能预算） | 无 |
| 环境锁版（§12 第一行） | 11/06–11/09 | 打包链路 ✅ / **PICO SDK ❌** | **这一格空着** |
| S2 白盒（门 2） | 11/09–11/16 | 未开工（缺 XR 底座） | **起步晚约 2 天** |
| S3 垂直切片（门 3） | 11/17–11/23 | 未开始 | 取决于 M1 结论 |
| S4 全流程（门 4） | 11/24–11/30 | 未开始 | 同上 |
| S5 量产 | 12/01–12/07 | 未开始 | 同上 |
| S6 打磨（门 5） | 12/08–12/12 | 未开始 | 同上 |
| S7 提交 | 12/13–12/18 | 未开始 | 同上 |

**偏差的性质要说清**：不是「做了但慢了」，而是「该做的那件事换了内容」——我们花 11/09–11/10 打通了 Unity 出包链路（原计划里假设它现成可用），代价是 PICO SDK 这一步往后挪。这个交换本身是划算的：出包链路不做，SDK 装上也没法验证。

---

## 4 差距分解：OpenXR 沉浸需要补的六层

从「平面窗口里的一个 3D 模型」到「戴着 PICO 坐进座舱」，缺的是下面六层。**顺序不能乱**，因为每层是下一层的验证前提。

### L1 XR 运行时层（最底层，不通则全停）

| 项 | 内容 |
|---|---|
| 缺什么 | XR Plug-in Management + OpenXR Plugin + PICO 的 OpenXR feature；XR 配置文件（`ProjectSettings/XRPackageSettings.asset` 等） |
| 产出 | 编辑器里 Play 能看到双眼分屏；APK 在设备/模拟器上进入 **immersive 会话**（不是一个窗口） |
| 验收 | ① `XRSettings.isDeviceActive == true`；② `Camera.stereoTargetEye` 生效；③ 头转动时画面跟随；④ 截图是双眼（或至少全屏无窗口边框） |
| 工时估算 | 8–14 h（含一次失败返工） |
| 头号风险 | **模拟器是否支持 OpenXR 会话，未验证**。若不支持，只能靠真机或借机，排期要重排 |

### L2 相机与空间层

| 项 | 内容 |
|---|---|
| 缺什么 | XR Origin（Camera Offset + Main Camera）、Tracking Origin 模式、座舱锚点与机体的父子关系 |
| 产出 | `XR Origin` 在 `SeatAnchorWorldY = 11.55` 落位；机体在座舱外、舱内可见 |
| 验收 | ① 眼高固定 11.55 m（不随身高漂移）；② 头转动 ±60° 不穿出舱体；③ 舱门开合 0–95° 不穿模 |
| 工时估算 | 10–16 h |
| 依赖 | 契约 §3 的 `CockpitCenterY 11.40 / CockpitFloorY 10.40 / CockpitCeilingY 12.40` |

### L3 输入层

| 项 | 内容 |
|---|---|
| 缺什么 | `OpenXRControllerSource` 现在用的是**旧版** `UnityEngine.XR.InputDevices` + `CommonUsages`；Unity OpenXR 插件推荐走 Input System 的 action |
| 产出 | 一个 `XrInputSource`（Input System 实现），供满 8 个通道；`InputRouter` 优先级调成 XR → 键鼠 → 注视 |
| 验收 | ① 8 通道全部有供给（不是 MISSING）；② 扳机/握持/摇杆在设备上可读；③ 设备无手柄时自动降级到键鼠且只告警一次 |
| 工时估算 | 6–10 h（**只改一个类**，这是抽象层的回报） |
| 风险 | 若坚持用 PICO 专有 SDK 的输入 API，会破坏「标准 OpenXR 可迁移」原则，并让 `Core` 层被污染——**不建议** |

### L4 座舱与全息层

| 项 | 内容 |
|---|---|
| 缺什么 | 座舱内构（Unicorn 实测出 14 项语义件：三显示器、油门块、扶手、双脚踏、球壳、滑轨…）、全息材质、World Space Canvas |
| 产出 | 可读的座舱：中央主屏 + 两侧屏 + 环幕；字号满足 §5.3 的可读性硬指标 |
| 验收 | ① 0.6 m 处主屏文字视角 ≥0.6°；② 全息面板 90 Hz 下不掉帧；③ 三块屏不遮挡前方 30 m 视野 |
| 工时估算 | 40–60 h（**最大的一块，建议外包**，`建模外包内容清单.md` A3 已是最全规格） |

### L5 流程与战斗层

| 项 | 内容 |
|---|---|
| 缺什么 | `SortieFlow` 状态机（Boot→Boarding→Cockpit→Sortie→Debrief）、波次、CIC 预警、光剑扫掠判定 |
| 产出 | 12 分钟闭环：仰视→登机→启动→顶升→起飞→战斗→返航→结算 |
| 验收 | 门 3「陌生人能独立完成一次击杀」；门 4「无网络从头玩到结算不中断」 |
| 工时估算 | 45–70 h（若按 §13 降级方案砍到单波次，可压到 25–40 h） |

### L6 性能与舒适层

| 项 | 内容 |
|---|---|
| 缺什么 | 合批（244 分件 = 244 draw call，必须压）、LOD、三档画质、FFR、舒适性红线（加速度限值、视野收窄） |
| 产出 | 90 Hz 稳定；三档画质可切 |
| 验收 | 门 5「90Hz 稳定、零阻断缺陷」 |
| 工时估算 | 15–25 h |
| **注意** | **这条在模拟器上无法验收**（GPU 指标恒 0、上限 60 FPS）。必须在真机或借机上做，或接受「未验证」并在材料里如实标注 |

---

## 5 里程碑 M0–M6

命名 M 是为了和既有 S 阶段区分：M 是**技术门**，S 是**制作阶段**。一个 S 可能跨多个 M。

| 里程碑 | 日期 | 核心产出 | 验收门 | 工时估算 | 主要风险 |
|---|---|---|---:|---:|---|
| **M0 基线** | 已完成（11/10） | `SteelSpine.apk` + 机体资产 + 出包脚本 | 模拟器能看见直立机体 | — | 已过 |
| **M1 XR 底座** | 11/11–11/13 | XR Origin 场景 + OpenXR 会话 APK + `XrInputSource` | ① 模拟器/真机进入 immersive；② 8 通道全供给；③ 头转动画面跟随 | 14–24 | **模拟器是否支持 OpenXR（未知）**；PICO SDK 获取 |
| **M2 座舱空间** | 11/14–11/17 | 座舱盒体 + 14 项内构 + SeatAnchor + 舱门 | 眼高 11.55 固定；转动不穿帮；舱门 0–95° | 10–16 | 座舱资产若外包未到，先用盒体占位 |
| **M3 交互** | 11/18–11/21 | 抓杆 / 节流阀 / 面板射线 / 光剑扫掠 | 门 2「连玩 5 分钟不晕不穿模」 | 20–30 | 手柄射线在模拟器上**无法可靠自动化测试**，只能人工 |
| **M4 流程闭环** | 11/22–11/28 | `SortieFlow` 全状态 + 一波敌人 + CIC | 门 3 + 门 4 | 25–40（降级） | 范围最容易失控的一段 |
| **M5 性能与舒适** | 11/29–12/05 | 合批 + LOD + 三档 + FFR | 门 5（90 Hz） | 15–25 | **模拟器不可验**，需真机 |
| **M6 提交件** | 12/06–12/12 | 离线包 + 仓库 + 许可证 + 演示视频 | 提交包可复现 | 8–12 | 视频必须真机拍 |

> 与原排期相比，M1–M3 相当于把 S2 拆成三段，因为原 S2 的「灰盒座舱 + 移动 + 抓杆」隐含前提是 XR 已通，而实际没有。

---

## 6 四个必须你拍板的决策

### D1 渲染管线：Built-in 还是 URP

| 选项 | 优点 | 缺点 |
|---|---|---|
| **A 保持 Built-in** | 现状零改动，50 个材质全部可用；出包已验证 | 无 FFR、无 URP 后处理（全息辉光要手写）；与方案 v2.1 §6.1 声明的「URP 14」冲突 |
| **B 转 URP 14** | FFR / MSAA / 后处理齐备；方案文档不用改 | 全部材质要重做或升级；转完要重新验一次出包；+6–10 h |

**建议 B**，但要**在 M1 之前决定**——因为 URP + OpenXR 的 Single Pass Instanced 配置方式与 Built-in 不同，转管线最好和 XR 底座一次做完，避免做两遍。

### D2 图形 API：GLES3 还是 Vulkan

现状为了模拟器（SwiftShader）只留了 GLES3。PICO 真机 Vulkan 性能更好。
**建议**：保留「GLES3（模拟器）+ Vulkan（真机）」两套切换，由 `QualityProfile` 决定，不要只留一个。

### D3 PICO SDK 走哪条路（见 §7）

### D4 座舱内构自研还是外包

按此前测算：座舱 40–60 h 是视觉权重 45% 且执行难度最高的一块。
**建议外包**，但需要一个前提：**先把契约里的 14 项内构规格写成可报价的清单**（`建模外包内容清单.md` A3 目前仍是旧口径）。

---

## 7 头号风险：PICO OpenXR SDK 能不能拿到

这是 M1 的硬前提，且我实测过三条路：

| 路径 | 实测结果 | 可行性 |
|---|---|---|
| `github.com/Pico-Developer/...` | **curl 返回 000**（连接被挡） | ✗ 本机不可达 |
| `registry.npmjs.org/com.unity.xr.picoxr` | 包存在，但 **2.3.6 / 2.4.3 已于 2025-03-06 被 unpublished** | ✗ 不可作为安装源 |
| `developer-cn.picoxr.com` | 站点 200，但文档与 SDK 下载页是 JS 渲染 + 需登录 PDC 账号 | ⚠ 需要你登录后手动下载 tgz |
| Unity 官方注册表 `com.unity.xr.openxr` | **200，可拉** | ✓ |

**结论：Unity 官方的 OpenXR 核心插件我能直接装；PICO 的扩展包大概率需要你从开发者平台下载一个 `.tgz` 或 `.unitypackage` 给我。**

**这也意味着一个降级路径是可行的**：先只用 Unity 官方 `com.unity.xr.openxr`（Khronos 标准），不装 PICO 扩展包。这样能验证「OpenXR 会话 + 6DoF + 手柄」这条主线；PICO 专有能力（手势、透视、空间锚点）再按需补。**建议 M1 就按这条路走**，不必等 PICO 包。

---

## 8 本周执行清单（11/11–11/16）

| 日 | 动作 | 完成判据 |
|---|---|---|
| 11/11 上午 | 装 `com.unity.xr.management` + `com.unity.xr.openxr` + `com.unity.xr.interaction.toolkit`（版本对齐 2022.3） | `Packages/manifest.json` 出现三行；编译 0 error |
| 11/11 下午 | 建 XR 场景：XR Origin + Camera Offset，把 `MECH_YAW` 挂在 Origin 下 | 编辑器 Play 出现双眼分屏 |
| 11/12 上午 | **决定性验证：出 APK 上模拟器，看是否进 immersive** | 截图全屏无窗口边框，或明确报错原因 |
| 11/12 下午 | 若模拟器不支持 → 立即改道：找真机 / 借机 / 降级为「平面大屏演示」并改方案 | 结论写进 `Docs/`，排期随之调整 |
| 11/13 | 写 `XrInputSource`（Input System），接进 `InputRouter` | 8 通道全供给，日志无 MISSING |
| 11/14–11/16 | 座舱盒体 + SeatAnchor + 舱门；眼高固定验证 | 门 2 的一半：不穿模、眼高正确 |

**11/12 的验证是整个项目的分水岭**：它决定我们后面是在「真沉浸式」上加功能，还是在「平面大屏」上做演示。这一条必须在 48 小时内出结论，不能拖。

---

## 9 工时账与降级触发线

从 11/11 到 12/18 共 38 天。按每天 4 小时有效工作计，约 **152 h**。

| 项 | 工时 |
|---|---:|
| M1–M3（底座 + 座舱 + 交互） | 44–70 h |
| M4 流程（降级版） | 25–40 h |
| M5 性能与舒适 | 15–25 h |
| M6 提交件 | 8–12 h |
| 测试 / 返工（按 30% 计） | 28–44 h |
| **合计** | **120–191 h** |

**结论：上界已经超过 152 h。** 所以 P0 范围必须现在就砍到 `技术方案 §13 降级方案` 的口径，不能等到 12 月再说。具体三条硬线：

1. **M4 之前砍掉第二波敌人与多阶段首领**（原 P0 写了「两段战斗波次」，压缩为一波）。
2. **全息面板减到 3 块**，动态 RenderTexture 只保留中央。
3. **语音降到 8 条核心提示**，其余用字幕与音效。

**触发线**：若 M1 到 11/13 仍未跑通 immersive，则直接切到「平面大屏 + 座舱全景」的降级演示形态，把节省下来的 30–40 h 全部投入流程闭环与视频——**这仍然是一个完整的参赛作品，只是一个不戴头显也能打动评委的版本**。

> **该触发线未触发（2026-11-11）**：M1 已于 11-11 凌晨跑通真沉浸式（见 §10.1），因此**保留完整沉浸式路线**，不降级。
> 三条 P0 砍项仍建议执行——它们砍的是内容体量，与沉浸形态无关，省下来的时间正好补 M1 这一格的消耗。

---

## 10 M1 实测记录（2026-11-11）

### 10.1 验收证据链

四条验收条件全部拿到运行时证据，不是"看起来像"：

| 验收条件 | 证据 | 来源 |
|---|---|---|
| ① 以 immersive 会话启动 | `OpenXRSession::HandleSessionStateChangedEvent` 走完 `IDLE → READY → SYNCHRONIZED → VISIBLE → FOCUSED` | logcat（Unity tag） |
| ①' 由系统合成器接管 | `PxrMetric: ... LayerCnt=1 Pkg=com.steelspine.smoke FrmId=...`，`APxrRuntime: PXRSDK_PM ENGINE FPS` | logcat（PICO tag） |
| ② 双眼立体 | 启动报告 `Stereo Rendering Mode: SinglePassInstanced`；运行时 `XRSettings.stereoRenderingMode = SinglePassMultiview`；`XRSettings.eyeTextureDesc = 1920×1920 vol=2` | logcat + 屏内 HUD |
| ③ 头显姿态由 OpenXR 驱动 | `HMD pose (0.00,1.65,0.00)` 与 `Cam world (0.00,1.65,0.00)` 完全相等，而场景里相机 `localPosition` 与 XR Origin 都是原点 | 屏内 HUD |
| ④ 能看见 3D 内容 | 截图：直立机体居中、地面向远处延伸、地平线落在 1.65 m 眼高的正确位置 | `/tmp/xr5.png` |

**关于 `SinglePassInstanced` 与 `SinglePassMultiview` 的差异**：前者是 Unity 侧的渲染模式名，后者是运行时在 GLES3 上采用的具体实现（`GL_OVR_multiview` 一类的多视图扩展）。两者都是"一次绘制两张眼图"的单通道方案，对性能的意义相同，**不需要为这个差异做任何处理**。

### 10.2 坑一：Unity batchmode 不读 EditorPrefs 里的 JDK 路径

现象：`UnityException: JDK not found`，但 `~/.local/jdk/jdk11/Contents/Home/bin/java` 明明可执行。

排查过程与结论：

| 尝试 | 结果 |
|---|---|
| `defaults write` 写 `JdkPath` 到 `com.unity3d.UnityEditor5.x.plist` | ❌ 仍报 JDK not found |
| 在 Unity 进程内 `EditorPrefs.SetString("JdkPath", ...)` | ❌ 仍报 |
| 反射写 `AndroidExternalToolsSettings.jdkRootPath` | ❌ 该类型 `ScriptableObject.CreateInstance` 返回 null，asset 建不出来 |
| **给 Unity 进程传 `JAVA_HOME` 环境变量** | ✅ 通过，紧接着报 `Android NDK not found` |
| **再传 `ANDROID_SDK_ROOT` / `ANDROID_HOME` / `ANDROID_NDK_ROOT`** | ✅ 构建 Success |

**结论**：Unity 2022.3.62f3 在 batchmode 下走的是环境变量（或至少在 Tools 设置缺失时以环境变量兜底），`JAVA_HOME` 必须指向 macOS bundle 内的 `Contents/Home`，**不是 bundle 根**。

已固化为 `scripts/build_xr.sh`，一条命令完成"环境自检 + 构建 + 产物校验"：

```bash
./scripts/build_xr.sh          # 构建
./scripts/build_xr.sh --no-build   # 只做环境自检
```

另一个必须注意的点：**Unity 必须非沙箱运行**。沙箱会拦住 Unity 写 `~/Library/Application Support/Unity`，表现为构建在 Gradle 阶段无声中断、日志里只有 `file-delete` 被拒的记录。

### 10.3 坑二：IMGUI 在 XR 立体渲染下完全不显示

第一版 HUD 用的是 `OnGUI()`（IMGUI）。平面 APK 上正常，切到 OpenXR 后截图里**一个像素的文字都没有**，只有 3D 场景。

原因：IMGUI 走的是独立的 GUI 渲染通道，不参与 XR 的立体渲染，在 `SinglePassInstanced` 下被整体跳过。

**这条对后续排期有直接影响**：座舱里所有 UI（HUD、全息面板、按钮）只能走 **world-space Canvas**，不能用 IMGUI 快速搭原型。已改写 `Core/Render/XrStatus.cs` 为 world-space Canvas 实现，并作为 M4 座舱 UI 的底座：

- Canvas `renderMode = WorldSpace`，挂在相机下（head-locked），距眼 1.6 m
- 比例 `1 canvas unit = 1 mm`，便于用物理尺寸排版（HUD 宽 0.46 m，字高 19 mm）
- 必须有半透明底板，否则浅色文字压在白色地面上读不出来

### 10.4 结论：手柄输入必须重写为 Input System

`XrStatus` 是刻意做成"实验装置"的——它用**旧版** `UnityEngine.XR.InputDevices` 读设备。实测输出：

```
HMD pose  : (0.00,1.65,0.00)     ← 有效
L hand    : (0.00,0.00,0.00) trig=0 grip=0
R hand    : (0.00,1.65,0.00) trig=0 grip=0
```

- HMD：`isValid = true` 且位姿有效 → **旧 API 对头显可用**
- 手柄：`isValid = true` 但位姿恒为默认值、按键恒 0 → **旧 API 对手柄拿不到数据**

同时 logcat 给出原因：

```
SPR-OpenXRInteractionManager: Current interaction profile：/interaction_profiles/ext/hand_interaction_ext
SPR-OpenXRInteractionManager: Current controller type ：8
```

因为 §10.5 的 `controller` 标记被删掉，runtime 把交互 profile 落到了**手部追踪**而不是 PICO Touch 手柄。真机上手柄在场时会切回 `.../pico4_controller` 一类 profile，但旧 API 的 `CommonUsages` 映射在 OpenXR 下本来就不可靠。

**决策**：`Core/Inputs/InputSources.cs` 里的 `OpenXRControllerSource` 必须改写为 Input System 的 action（`<PICO4Controller>{LeftHand}/triggerPressed` 等），**不要再寄望旧 API**。这是 M3 的第一件事。上层 `IInputSource` / `InputRouter` 抽象（8 通道 + 能力位 + 优先级降级）不用动。

### 10.5 坑三：PICO 的 `controller` 元数据会拦住启动

装好 OpenXR APK 后点图标，进程根本不创建，只弹一个"需要使用手柄"对话框。系统拒绝理由在 logcat 里：

```
I AppStartInterceptManager: Intercepted for ControllerOnly: No controller paired. Pkg: com.steelspine.smoke
W ActivityTaskManager: addPendingControllerOnlyLaunchItem ...
```

来源是 PICO OpenXR SDK 的 `Editor/PICOModifyAndroidManifest.cs:AddPICOMetaData()`——除非把"手部追踪"设为 `HandsOnly`，否则它一定往 manifest 写：

```xml
<meta-data android:name="controller" android:value="1" />
```

而模拟器里 `pxrcontrollerservice` 两个手柄都是 `state=offline`、`bindstatus=0`，且**没有 `cmd` 接口**（`cmd pxrcontrollerservice` → `Failed transaction`），配对状态无法伪造。

解决办法（已落地为 `Assets/_Project/Scripts/Editor/StripControllerOnly.cs`）：实现 `IPostGenerateGradleAndroidProject`，`callbackOrder = 100`（排在 SDK 的 `1` 之后），在 manifest 生成后删掉这一行。这不是 hack——SDK 自己的 `HandsOnly` 分支做的就是 `DeleteAndroidMetaData("controller")`。

**代价**：无手柄时交互落空（见 §10.4）。M1 只验证渲染与位姿，不受影响；M3 之后按真机实际形态决定是否恢复。

### 10.6 模拟器侧的两个环境坑

| 现象 | 原因 | 处理 |
|---|---|---|
| `pico-cli emulator start` 报 `Cannot determine process identity before acquiring file lock` | 本机 `ps` 被系统权限拦截（`operation not permitted: ps`），pico-cli 拿不到自己的启动时间 | 绕过 pico-cli，直接跑 emulator 二进制，并把 AVD 克隆到可写目录：`HOME=/tmp/pico-run ANDROID_AVD_HOME=/tmp/pico-run/avd <sdk>/emulator -avd demo -sysdir <sdk>/system-images/system-images -gpu angle_indirect` |
| emulator 报 `filesystem error: in remove: Operation not permitted [.../hardware-qemu.ini.new]` | `~/.pico/avd` 在当前执行环境里不可写 | 同上，AVD 整目录 `cp -cR` 到 `/tmp/pico-run/avd`，`demo.ini` 的 `path` 指过去 |
| `adb: device offline` | 模拟器连跑十几小时后 adb 通道会掉 | 安装/启动脚本要带重试（`adb get-state` 轮询 + `install` 重试），不能假设一次成功 |

补充：模拟器本身是**完整的 PICO OS 6 环境**（360° 全景房间 + 桌面 + 设置），不是空壳。装上去的 VR 应用会被系统识别成 VR 应用（`pvr.app.type=vr`），这是"出包正确"的第一个信号。

---

## 附：与既有文档的关系

- 本文档不替代 `技术方案 v2.1`，而是把它的 §10（P0/P1/P2）与 §12（六周排期）**按已发生的实际情况重排**。
- 门 1–门 5 的定义沿用 `制作流程与协作方式.md §3`，M0–M6 是技术门，不改变制作门的判据。
- 模拟器能力边界沿用 `Docs/PICO模拟器能力边界与用法.md`，其中 §6.8 记录了 M0 的全部实测数据。
