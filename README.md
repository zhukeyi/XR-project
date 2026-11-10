# XR-project · 《钢脊》PICO OpenXR 机甲座舱

PICO Space Program 2026 · OpenXR 赛道（最佳沉浸内容创作）参赛项目。
一句话定义：**玩家以驾驶员身份完整经历一次出击**——登机、启动、CIC 简报、弹射出击、驾驶/射击/近战、返航着舰、结算。

本仓库是两个开发模块的**唯一集成点**。模块各自迭代、各自可回滚，但对外的坐标与资产接口只有一份。

---

## 1. 仓库结构

| 路径 | 模块 | 职责 | 技术栈 |
|---|---|---|---|
| `mecha_render/` | **M1 资产与预渲染** | 程序化几何建模、造型度量、glTF 导出、宣传片渲染 | Python 3 + numpy/PIL；Blender 5.2 无头 |
| `PICO_Mecha_Starter/` | **M2 引擎内实时** | 座舱交互、战斗、性能预算、白盒与合规自检 | Unity 2022.3.62f3 + URP + PICO OpenXR SDK |
| `PICO_Mecha_Starter/Contracts/` | **接口层（唯一事实来源）** | 两模块共用的坐标与尺寸；由 M2 编辑器脚本从 `MechaContract.asset` 导出，不手工编辑 | Markdown / JSON |
| `docs/` | 设计与评审 | 技术方案、世界观、引擎决策、制作流程 | Markdown |
| `docs/pm/` | 项目管理 | 状态盘点、模块对齐、资产交付规格、版本与回滚策略 | Markdown |

契约存放在 M2 工程内、而非独立顶层目录，原因是 `MechaContractExport.cs` 会把 JSON 写到工程根的 `Contracts/`，目录一移动导出即断。**单一真源优先于目录美观。**


---

## 2. 两个模块的边界

**M1 只管"资产如何被造出来"，M2 只管"资产如何被用起来"。**

| 事项 | M1 负责 | M2 负责 |
|---|---|---|
| 几何、比例、枢轴命名 | ✅ | 只消费，不修改 |
| glTF/FBX 导出与坐标系 | ✅ | 只导入，不改 scale |
| 预渲染宣传片 | ✅ | — |
| 刚体绑定、VAT、材质实例化 | 提供源资产 | ✅ |
| 座舱交互、战斗、性能 | — | ✅ |
| 尺寸契约的数值定义 | 提出并论证 | 评审并落地 |

接口只有三样东西，其余一律不跨模块耦合：**① 尺寸与枢轴表（`PICO_Mecha_Starter/Contracts/`）② glTF 资产 ③ 命名约定**。

资产的交接规格单独成文：`docs/pm/02_资产交付规格_M1到M2.md`。

---

## 3 快速开始

### M1 资产与预渲染

```bash
cd mecha_render
python3 tools/s2_graybox.py          # 生成灰模并出图
python3 tools/export_gltf.py         # 导出 glTF（含节点层级与枢轴）
```

预渲染（无头，不需要打开 Blender 界面）：

```bash
/Applications/Blender.app/Contents/MacOS/Blender -b -P <script>.py
```

> Blender 5.2 的 EEVEE 标识符是 `BLENDER_EEVEE`；`CYCLES` 使用前需 `addon_utils.enable("cycles")`。
> 视频编码用 Blender 内置 FFmpeg（H.264/H.265/AV1），**无需系统 ffmpeg**。

### M2 引擎内实时

用 Unity **2022.3.62f3** 打开 `PICO_Mecha_Starter/`，目标平台 Android。
白盒生成、合规自检均为编辑器菜单命令，详见 `PICO_Mecha_Starter/README.md`。

---

## 4 版本与回滚

- 仓库版本：`v0.1` 起，语义化版本。当前 **v0.1**。
- 模块版本：`M1-vX.Y` / `M2-vX.Y` 记录在 `docs/pm/01_模块对齐与版本策略.md`，可独立前进。
- **产物不入库**：`out/`、`frames/`、`Library/` 全部由 `.gitignore` 排除。因此回滚永远是"回滚源 + 重新生成"，不存在"回滚一个坏产物"。
- **单模块回滚**：`git revert <sha> -- mecha_render/`，不要 `reset` 整仓。
- **接口变更**：改 `contracts/` 必须同时升契约版本号，并在提交信息里写 `contract: vX.Y -> vX.Z`。

---

## 5 当前状态（v0.1，2026-11-10）

| 项 | 状态 |
|---|---|
| M1 程序化几何 | 可生成、可出图、可导出带枢轴的 glTF |
| M1 尺度论证 | 已锁 7.930 m（四条约束交集），**尚未回写契约** |
| M1 预渲染管线 | 无头渲染验证通过，分镜/断点续渲待实现 |
| M2 接口契约 | v1.1 已发布，但数值仍为 18.20 m |
| M2 白盒与交互 | S1 规格交付完成（契约 + 白盒 + 合规自检） |
| **两模块对齐** | **未完成：M1 = 7.930 m，M2 = 18.20 m，相差 2.3 倍** |

详见 `docs/pm/00_项目状态_v0.1.md`。

---

## 6 不入库的内容

| 内容 | 原因 |
|---|---|
| `mecha_render/ref_assets/` | 含第三方高达模型，属他人在先权利表达，禁止进入公开仓库 |
| `mecha_render/out/`、`frames/` | 渲染产物，可由源重新生成 |
| `PICO_Mecha_Starter/Library/` | Unity 缓存，2.4 GB |
| `*.apk`、`*.mvfrm` | 构建产物与录屏 |

---

## 7 合规声明

本项目为原创作品：机体造型、配色、命名、剧情、UI、音效均为自研，不使用任何现有作品的名称、机体造型、角色、台詞、标志或音乐。对既有作品的参照限于"流程与镜头语言"等不受版权保护的通用语法。

仓库内不含第三方受版权保护的模型、贴图或音频。
