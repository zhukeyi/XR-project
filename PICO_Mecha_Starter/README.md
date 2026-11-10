# Steel Ridge Starter · 《钢脊：立于大地》

PICO Space Program 2026 · OpenXR 赛道（最佳沉浸内容创作）  
阶段：**S1 规格交付** —— 契约锁定 + 可运行白盒 + 比赛合规自检

---

## 1. 这是什么

三件不依赖任何外部美术资源的东西。它们的共同目的：**让美术没到位时，交互和流程也能全速推进。**

| 交付物 | 解决的问题 |
|---|---|
| `Contracts/尺寸与接口契约表.md` + `contract.json` | 代码、白盒、外包三方共用一份坐标。美术换模型时程序零改动 |
| 白盒生成器（菜单可执行） | 18.2 m 机体 + 座舱内构 + 地面序章，一条菜单命令生成，改契约即重建 |
| 比赛合规自检器 | 把 PICO 赛道硬性要求 + 90Hz 性能预算编成 33 条检查定义（实跑 30–31 条，互斥项互斥，见 §7），FAIL 不允许提交 |
| 平台抽象层（§5） | 同一份 gameplay 在 96° 不透明 VR 与 43° 加色 AR 上都能跑，换设备改档案不改代码 |

> 白盒**不是最终美术**。它只保证三件事：尺寸对、挂点对、交互距离对。视觉风格在 S3 之后由真模型替换。

---

## 2. 目录结构

```
PICO_Mecha_Starter/
├── README.md
├── .gitignore
├── Contracts/
│   ├── 尺寸与接口契约表.md          人读版（发给建模方）
│   └── contract.json               机读版（导出后生成）
├── Docs/
│   └── 合规自检报告.md              自检器生成
├── Tools/
│   ├── compile-check.sh             无 Unity 授权时的完整类型编译校验（28 脚本，当前 0 error）
│   ├── pico-setup.command           初始化 PICO CLI + 拉起模拟器（需在终端手动跑）
│   └── install-unity-6000.0.59f2.command  仅在改投 Spatial 赛道时才用（6.0 线已 EOL）
└── Assets/_Project/
    ├── Config/
    │   ├── MechaContract.asset     ← 唯一事实来源（首次运行自动创建）
    │   ├── Platforms/              平台档案 PICO_4_VR / Rokid_ARStudio / Rokid_Glasses / Editor_Flat
    │   └── contract.json
    ├── Scenes/Blockout/
    │   ├── Blockout_00_Ground.unity     地面序章（1.7 m 眼高 / 25 m 机位）
    │   └── Blockout_01_Cockpit.unity    座舱内构（相机即 SeatAnchor）
    ├── Art/Blockout/                6 个白盒材质（自动生成）
    └── Scripts/
        ├── Core/
        │   ├── MechaContract.cs            尺寸契约（运行时，不引用 UnityEditor）
        │   ├── Platform/                   能力档案 / 注册表 / 装配根 / 验收门槛
        │   ├── Spatial/                    地面锚定 / 视点策略 / 遮挡策略 / 跟踪质量 / 厂商地面源适配（RokidUxrGroundProvider）
        │   ├── Render/                     显示语义（不透明 vs 加色）
        │   ├── Perf/                       性能双档 + LOD 共用曲线
        │   ├── Inputs/                     抽象通道 + 降级表
        │   ├── Holo/                      面板角度定义 / 安全区 / 运行时装载
        │   └── Audio/                      空间音频后端抽象
        └── Editor/
            ├── SteelRidgeBlockout.cs        白盒生成
            ├── ProjectBootstrap.cs          工程一键配置
            ├── ContestComplianceValidator.cs 比赛合规自检
            ├── PlatformAudit.cs             平台抽象五组审计 + 生成档案资产
            ├── PixelRegistrationRecorder.cs AR 像素配准误差记录（唯一需人工标定的验收项）
            └── MechaContractExport.cs       契约导出 JSON
```

---

## 3. 接入步骤（5 步）

### 3.1 建工程

Unity Hub → 新建 **Unity 2022.3 LTS（2022.3.62f3）** 项目，模板选 **3D（URP）**（2022.3 模板名为 `3D (URP)`，Unity 6 才叫 `Universal 3D`）。

> **为什么不用 Unity 6**：OpenXR 赛道对引擎的硬性下限是 2022.3.15f1+，2022.3.62f3 已满足。PICO 把 6000.0.59f2 写成「指定版本」**只针对 Spatial 模式**，本套走标准 OpenXR，不需要。另外 2022.3 线（止于 2025-05-07）与 6.0 线（止于 2026-10-16）**都已 EOL**，EOL 不构成差异项；若日后要升级，直接取 6.3 LTS。
>
> 本套 28 个脚本由 `Tools/compile-check.sh` 在 2022.3.62f3 自带的 mono + Roslyn + NetStandard 2.1 上做类型完整编译，当前 0 error。换引擎版本等于把「已验证」退回「待验证」。
>
> 若确实要改投 **Spatial 赛道**，才需要 Unity 6000.0.59f2（`Tools/install-unity-6000.0.59f2.command` 可一键装，注意该版本所在 6.0 线已 EOL）。

### 3.2 拷文件

把本目录的 `Assets/_Project` 整个拷进工程的 `Assets/` 下，并把 `Contracts/` 拷到工程根目录（与 `Assets/` 同级）。

### 3.3 工程配置（菜单）

```
Steel Ridge ▸ 工程 ▸ 一键配置（Android + IL2CPP + Vulkan + Linear）
```

会设置：Android 平台 / IL2CPP / ARM64 单架构 / Vulkan / Linear / 包名 `com.steelridge.ground` / 关闭 INTERNET 权限 / minSdk 29 / ASTC / MSAA 4x / Single Pass Instanced。

### 3.4 生成白盒（菜单）

```
Steel Ridge ▸ 白盒 ▸ 重建全部（地面序章 + 座舱内构）
```

先跑契约自检，不一致会**中止并弹窗告诉你哪一项不对**。通过则生成两个场景。

### 3.5 手动补两项（脚本改不了）

1. 导入 **PICO Unity OpenXR SDK**（v1.4.0 或更新）→ `Project Settings ▸ XR Plug-in Management ▸ Android` 勾选 **OpenXR**，并在 OpenXR 的 Feature 列表勾选 **PICO**。
2. `Project Settings ▸ XR Plug-in Management ▸ Project Validation` → 点 **Fix All**。

完成后跑：

```
Steel Ridge ▸ 合规 ▸ 运行比赛合规自检
```

预期结果：`FAIL 0`。WARN 项（如全息面板数量）在 S3 之后再收敛。

---

## 4. 菜单索引

| 菜单 | 作用 | 何时用 |
|---|---|---|
| `工程 ▸ 一键配置` | 应用比赛要求的构型 | 新工程第一步 |
| `工程 ▸ 打印当前配置` | Console 打印体检表 | 怀疑设置被改坏时 |
| `工程 ▸ 打开契约资产` | 定位 MechaContract.asset | 改尺寸前 |
| `白盒 ▸ 重建全部` | 重建两个白盒场景 | 每次改契约后 |
| `白盒 ▸ 只重建当前场景内的机体` | 只重建 MECH_ROOT | 在自建场景里迭代 |
| `白盒 ▸ 删除场景内的机体` | 清场 | 换场景时 |
| `契约 ▸ 导出 JSON` | 生成 contract.json | 发外包前 |
| `合规 ▸ 运行比赛合规自检` | 33 条检查定义（实跑 30–31）+ 写报告 | 每次提交前 / 每阶段门 |
| `平台 ▸ 生成四档档案资产` | 生成 4 个 PlatformProfile | 第一次接触 AR / 换设备前 |
| `平台 ▸ ① 能力矩阵审计` | 四档能力对比 + 档案自检 | 定性能预算时 |
| `平台 ▸ ② 全息面板落位审计` | 五块面板 × 四档，标出出画的 | 改面板角度前 |
| `平台 ▸ ③ 输入降级审计` | 八个通道由谁供、谁消失 | 去手柄化设计时 |
| `平台 ▸ ④ 性能与显示双档审计` | 预算表 + 显示语义表 + 地面置信度阈值 | 写方案第 4 章时 |
| `平台 ▸ ⑤ 跟踪质量验收` | 四项指标定义 / 门槛 / 标定规程 | 被问「漂了怎么办」时 |
| `平台 ▸ 记录 AR 像素配准误差` | 标定结果写回档案（唯一不能自动测的一项） | 每次换设备后 |
| `平台 ▸ 导出完整审计报告` | 汇总成 `Docs/平台抽象审计报告.md` | 提交材料前 |

---

## 5. 平台抽象层（VR / AR 双轨）

目的很直接：**别让一句"以后要上 AR"变成 S3 的重构。** 抽象不是提前做 AR，而是把"AR 会打碎的那个假设"提到接口层面。

### 5.1 八个抽象，各自替掉一个假设

| 抽象 | 替掉的假设 | VR 实现 | AR 实现 | 文件 |
|---|---|---|---|---|
| `PlatformCapabilities` | "设备就是 PICO 4" | 96°×62° / 6DoF / 不透明 | 43°×28° / 手势 / 加色 | `Core/Platform/PlatformProfile.cs` |
| `IGroundProvider` | "地面在 y=0" | 静态平面 | 平面检测（宿主推送）+ 眼高兜底 | `Core/Spatial/GroundAnchor.cs` + `RokidUxrGroundProvider.cs`（厂商推送适配） |
| `ViewpointPolicy` | "玩家被钉在座椅上" | Locked / SeatedClamp ±0.15 m | FollowHorizontal（舱随人走） | `Core/Spatial/ViewpointPolicy.cs` |
| `OcclusionPolicy` | "舱壁挡住一切" | ShellOpaque | DepthSoft，无深度则退为提示面 | `Core/Spatial/OcclusionPolicy.cs` |
| `DisplayConstraints` | "黑 = 暗场" | 允许黑板 / 允许 bloom | 黑 = 透明，禁全屏后处理 | `Core/Render/DisplayPolicy.cs` |
| `IInputSource` + `InputRouter` | "有 6DoF 手柄四键" | Stick/Grab/Trigger | 手势 pinch / 射线 / 注视停留 | `Core/Inputs/` |
| `ISpatialAudioBackend` | "有 PicoSpatialAudio" | 可接专用后端 | Unity Spatializer | `Core/Audio/SpatialAudio.cs` |
| `ITrackingStateSource` | "跟踪永远可用" | 未接入即 N/A（不伪造满分） | 宿主上报 Normal/Degraded/Lost | `Core/Spatial/TrackingQuality.cs` |

另有两个"内容侧"的抽象：`HoloPanelDef` 把面板从**米数坐标**改成**相对眼位的角度 + 距离**（否则 96° 里 ±25° 很舒服的侧窗，到 43° 直接出画），`PerfBudgetPlanner` 把预算做成双档但**共用一条 LOD 曲线**（各画一条必然不一致）。

还有一个不是抽象、但必须建模的**能力维度**：`ScaleGrounding`（真实世界尺度是否可观测）。依据是纯旋转（3DoF）下尺度不可观测 —— 不是"精度差"，是这个量不存在。所以 3DoF AR 上地面退回静态 + 眼高假设，面板距离按角度口径，所有米级断言在验收报告里都不成立。`GroundAnchor.EyeHeightAssumed` 就是这件事的对外标记。

**厂商地面源怎么接**：Rokid UXR 的平面检测走 `RokidUxrGroundProvider`（`Core/Spatial/`），它把宿主推送的平面包成 `IGroundProvider`：

```csharp
// 宿主每帧/每检测到新平面时调用，无需反射、无需引用 Rokid 程序集
provider.Submit(centerPose.position,          // center
                centerPose.rotation * Vector3.up, // normal
                new Vector2(extent.x, extent.z) * 0.5f, // halfExtent
                confidence);                  // 宿主给的置信度，缺省 0.8
```

映射关系与三个坑都写在类注释里：`extent` 是**全尺寸**须除 2；时间戳不传（内部按 `Time.unscaledTime` 记，宿主的帧时间与 Unity 时钟不同源）；**3DoF 设备不要接**——`HasWorldScale` 为 false 时 `GroundAnchor` 已经不走平面路径，接了只会产生"看起来很准"的假数据。

这个文件里刻意**不出现 `using Rokid.`**：宿主回调侧负责翻译，适配器本身只认 Unity 类型。这样合规自检的泄漏扫描（FAIL 级）不需要为它开口子，也保证将来换任何一家 AR 眼镜只改一行装配。

### 5.2 落位是算出来的，不是估的

用 `HoloPanelLayout` 对两组面板逐块求解（可用角已扣 2° 边距）：

| 面板组 | PICO 4（96°×62°） | Rokid AR Studio（43°×28°） | Rokid Glasses（23°×20°） |
|---|---|---|---|
| 五块版 `HoloDeck_Default` | **5 / 5 可用** | **1 / 5 可用**（仅中央 HUD） | 0 / 5 |
| 三块版 `HoloDeck_Compact` | 3 / 3 | **3 / 3 可用** | 0 / 3 |

两条结论：

1. **43° 设备上不能"把五块压回视场"，只能减块**。五块硬压的结果是全部挤在中央互相遮挡，读起来比三块更差。所以 `HoloDeckRuntime` 在安全区为 Narrow/Standard 时自动切 `compactDeck`，压回只是兜底。
2. **30° 单绿眼镜（23°×20°）连三块都放不下**，最小可读面板的横向半宽就有 12°。这不是调参能解决的，是形态上限 —— 所以那一档只作"能力下限"参照，不作为交付目标。

### 5.3 怎么落地

1. 菜单 `平台 ▸ 生成四档档案资产（平台 + 面板组）` → `Config/Platforms/` 下 4 个档案、`Config/Holo/` 下 2 个面板组；
2. 场景里放一个空物体挂 `PlatformBootstrap`，把档案、`CockpitRoot`、`Viewpoint`、`HoloDeckRuntime` 拖进去（`HoloDeckRuntime` 的 `deck` 填五块版、`compactDeck` 填三块版）；
3. 跑 `平台 ▸ 导出完整审计报告`，看 `Docs/平台抽象审计报告.md`。

`PlatformBootstrap` 的装配顺序是固定的：能力 → 空间 → 显示 → 音频 → 输入 → 面板 → 预算 → 跟踪质量。顺序不是审美：面板要读能力，显示要在相机清屏前定，预算必须最后采样，跟踪监控只观测不参与装配决策。

### 5.4 四条纪律

1. **gameplay 只读 `PlatformCapabilities`**，不读 `SystemInfo`、不读设备型号、不 `using Pico.*` / `using Rokid.`。这条有检查器兜底：合规自检里「无 PICO / Rokid 专有命名空间引用」是 FAIL 级，扫描前会先剥掉注释与字符串字面量（否则扫的是自己的词表）。
2. **禁止 gameplay 依赖全屏后处理**。加色叠加下 bloom 会把亮部糊成一片，而且 AR 侧必须能一键关掉全部 Volume。
3. **未解析就是未解析**。地面检测没结果时返回 `Unresolved` + 眼高兜底，绝不返回 y=0 —— 那会让机甲的脚出现在用户头顶。
4. **无数据就是 N/A，不是满分**。跟踪来源未接入时 `NullTrackingStateSource` 恒返回 false，报告里写 `[N/A]`。一个假的 100% 比没有指标更危险 —— 它会让评审以为问题已解决。

### 5.5 验收口径：被问「漂了怎么办」时给四个数字

不承诺「不漂」（没人做得到），改为报四项可测指标（依据 SLAM Handbook §18.8 度量清单第 3/4/5/9 项）：

| 指标 | 定义 | 数据来源 | 能否自测 |
|---|---|---|---|
| 跟踪可用率 | (正常 + 降级) 帧 / 有效帧 | 宿主 tracking state | 能 |
| 完好率 | 仅正常 帧 / 有效帧 | 同上 | 能 |
| 重定位成功率 | 恢复次数 / 超过宽限期的丢失次数 | 同上 | 能 |
| AR 像素配准误差 | 叠加图形与真实特征的位置偏差（px） | 人工标定 | 否，须一次标定 |

门槛分档：AR 一律比 VR 严（可用率 99% vs 98%、重定位 95% vs 90%）。理由是光学透视把图形叠在真实世界上，同样的抖动在 VR 里是「画面在晃」，在 AR 里是「世界在晃」，后者无法归因于内容。

完好率单列一档而不是折进可用率：VIO 在弱纹理、强逆光、纯旋转下必然降级，把降级算失败则可用率永远不达标；但降级帧多到一定比例就是产品问题，混进可用率会被平均掉。

两项应用内测不到，验收口径里必须写清楚：**运动到光子延迟**（需光电传感器 + 外部高速相机，应用无权访问显示管线末端）只能报帧时间并注明「不含显示与光子延迟」；**绝对定位精度**需动捕或全站仪，因此不承诺绝对值，只承诺重定位成功率与像素配准误差。

---

## 6. 白盒几何 ↔ 契约对应

白盒不是随手拉的立方体，每个块都对着一行契约数字：

| 白盒节点 | 契约来源 | 校验值 |
|---|---|---|
| `BLK_antenna_L/R` 顶 | 天线 17.60–18.20 | 总高 **18.20 m** |
| `BLK_ShoulderArmor_L/R` 外缘 | shoulderWidth 10.60 / 2 | 肩宽 **10.60 m** |
| `CockpitRoot` | chestSocketY 12.60 + (−1.20) | **11.40 m** |
| `CPT_Floor` 上表面 | 11.40 − 2.00/2 | **10.40 m** |
| `SeatAnchor` | 地板 + 1.15 | **11.55 m**（相机位） |
| `CPT_Dash` | 眼位 + (0.60+0.90)/2 = 0.75 | **0.60–0.90 m 区间内** |
| `CPT_HatchPanel` | 0.85 高 × 1.25 宽，铰链在左缘 | 开角 **0–95°** |
| `Pivot_StickBase` | 地板 + (0.30, 0.35, 0.55) | 推拉 **±25°** |
| `UpperArm_R` 链 | 肩 14.20 − 3.00 − 3.20 | 腕 **8.00 m** |

两个白盒场景的机位是刻意设的：

- **Ground 场景**：相机在 `(0, 1.70, 25)`，看向 11.40 m 的座舱 → 仰角 **21.2°**。这就是"高低屹立于大地之上"的那一眼。
- **Cockpit 场景**：相机直接钉在 `SeatAnchor` 上，FOV 95° → 所见即玩家所见。

---

## 7. 已知限制（不要当成 bug）

| 现象 | 原因 | 处理 |
|---|---|---|
| 舱门外壳在 z=2.10，舱内前壁在 z=1.10 | 契约规定舱门在胸甲外表面，中间 1.0 m 是装甲厚度 | 有意为之，S3 做登机动画时按此走 |
| 机体看起来"方" | 白盒只验证尺寸，不做倒角与面线 | S3 用真模型替换 `ArtRoot` |
| 场景没有天空盒/后处理 | 空场景新建，避免依赖 URP 资源包 | 需要时手动加 Volume |
| 座椅、仪表都是方块 | 同上 | 交互件在 S3 按 `Pivot_*` 定位重做 |
| 自检器读不到 XR Loader | 反射依赖 XR Management 包，未装则返回 SKIP | 显示 SKIP 不是失败 |
| 自检报告的行数比「33」少 | 代码里是 **33 条检查定义**，其中两组互斥（`契约资产存在` / `契约自检`；`XR Loader 已启用` 的 SKIP 版 / 实装版），另 `面数分布（按根节点）` 仅在有可统计根节点时输出 | **实跑 30–31 条属正常**，不是漏检。看 FAIL 数，不看总行数 |
| AR 下地面长时间 `Unresolved` | 平面探针 = 眼位 − 眼高。AR 房间尺度用站姿眼高 1.65 m，坐姿用 1.15 m；若实际眼高与假设偏差超过 **0.220 m**，探针会落到地面之外，真实地面权重被先验压到 0 | 契约要求眼高偏差 ≤ 0.220 m（`DetectedPlaneProvider.EffectiveHeightCutoffMeters()` 扫出的临界值，同时就是这条假设的误差预算）。真机偏差大时改 `GroundAnchor.standingEyeHeight` |
| AR 下壳体仍是实心色块 | `OcclusionPolicy` 写的 alpha 只是请求，材质必须是 Transparent 工作模式才生效；代码只告警不改材质（自动改会顺手关掉深度写入与阴影） | 按告警里指向的 `AdditiveMaterialGuard` 列表做透明/加色变体 |

---

## 8. 门 1 验收清单（需要你确认的 6 件事）

打开 `Blockout_00_Ground.unity` 和 `Blockout_01_Cockpit.unity`，逐项看：

1. **18.2 m 是否够"巨物感"** —— 12 m 集装箱只到膝盖，40 m 龙门吊是两倍高；肩宽 10.60 m、站距 5.80 m 的重心是否稳。
2. **11.4 m 的座舱高度对不对** —— 站在 25 m 外要抬头 21° 才能看到舱门。
3. **座舱 1.6×2.0×2.2 m 会不会太挤** —— 这是真人坐进去的净空，含座椅后剩余活动空间有限。
4. **眼位 11.55 m 的视界** —— 主窗 ±35° 水平、+25/−15° 垂直，看出去是否被胸甲挡住太多。
5. **驾驶杆 0.55 m 前 / 0.35 m 高的位置** —— 坐着伸手能否自然握住（真实座椅到杆的距离）。
6. **三块全息面板的布局** —— 左 25° / 中 0° / 右 −25°，是否够 CIC 信息分层。

任一项要改，只改 `MechaContract.asset` 一个数字，重跑「重建全部」，白盒与 JSON 同步更新。

---

## 9. 下一步（S2 白盒交互）

按依赖顺序：

1. XR Rig 组装（`Root → Camera Offset → Main Camera / 双手`），相机挂到 `SeatAnchor` 做座椅锚定
2. ~~头部姿态限位（±0.15 m 位移钳制）~~ → **已由 `ViewpointPolicy` 覆盖**，S2 只需在场景里指定 `CockpitRoot` 与 `Viewpoint`
3. 右臂 IK：手柄位姿 → 腕目标 → 肘/肩解算，限位读 `Pivot_Elbow_R`；IK 是否启用读 `Caps.Has6DoFController`
4. 驾驶杆抓取（`Pivot_StickBase` ±25° → 推力/转向映射），输入一律经 `InputRouter.Read(InputChannel.Grip)`
5. 移动与转向（高低差、动量感、急停前倾）
6. 助推（FOV 拉伸 + 相机后坐 + 音效分层），音效走 `SpatialAudio.PlayAt`

S2 完成后再跑一次合规自检，看 Draw Call 与面数是否被 XR Rig 拖爆。`PerfBudgetEnforcer` 会在运行时每 5 秒采样一次，超预算只告警一次，不会刷屏。
