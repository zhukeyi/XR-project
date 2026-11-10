using System.Collections.Generic;
using System.IO;
using System.Text;
using SteelRidge.Core.Audio;
using SteelRidge.Core.Holo;
using SteelRidge.Core.Inputs;
using SteelRidge.Core.Perf;
using SteelRidge.Core.Platform;
using SteelRidge.Core.Render;
using SteelRidge.Core.Spatial;
using UnityEditor;
using UnityEngine;

namespace SteelRidge.EditorTools
{
    /// <summary>
    /// 平台抽象审计。回答四个必须能被追问的问题：
    /// 1) 同一套内容在 96° VR 和 43° AR 上各自是什么样（面板落位）；
    /// 2) 没有 6DoF 手柄时哪些操作会消失、由谁接管（输入降级）；
    /// 3) AR 侧要砍到多少面（性能双档）；
    /// 4) 哪些东西在 AR 上根本不能存在（显示语义、遮挡、地面）。
    /// 全部输出为可粘贴进方案的 Markdown。
    /// </summary>
    public static class PlatformAudit
    {
        const string ReportDir = "Docs";
        const string ReportPath = "Docs/平台抽象审计报告.md";

        [MenuItem("Steel Ridge/平台/① 能力矩阵审计（VR + AR 三档）", false, 40)]
        public static void AuditCapabilities()
        {
            var sb = new StringBuilder();
            sb.AppendLine("## 能力矩阵");
            sb.AppendLine();
            sb.AppendLine("| 档案 | 显示 | 位移 | 尺度 | 视场(H×V) | PPD | 输入 | 遮挡 | 光照估计 |");
            sb.AppendLine("|---|---|---|---|---|---|---|---|---|");

            foreach (var caps in AllProfiles())
            {
                sb.AppendLine($"| {caps.Name} | {caps.Display} | {caps.Translation} | {caps.Scale} | " +
                              $"{caps.FovHorizontal:0}°×{caps.FovVertical:0}° | {caps.PixelsPerDegree:0} | " +
                              $"{caps.Inputs} | {(caps.SupportsOcclusion ? "有" : "无")} | " +
                              $"{(caps.SupportsLightEstimation ? "有" : "无")} |");
            }

            sb.AppendLine();
            sb.AppendLine("## 档案自检");

            int bad = 0;
            foreach (var p in ProfileAssets())
            {
                var issues = p.Validate();
                if (issues.Count == 0)
                {
                    sb.AppendLine($"- [PASS] {p.displayName}");
                    continue;
                }

                bad += issues.Count;
                foreach (var i in issues)
                    sb.AppendLine($"- [FAIL] {i}");
            }

            if (bad == 0) sb.AppendLine("- 全部通过");

            Emit(sb.ToString(), "能力矩阵审计");
        }

        [MenuItem("Steel Ridge/平台/② 全息面板落位审计（五块面板 × 四档）", false, 41)]
        public static void AuditPanels()
        {
            var deck = HoloDeck.CreateDefault();
            var deckIssues = deck.Validate();

            var sb = new StringBuilder();
            sb.AppendLine("## 面板组自检");
            if (deckIssues.Count == 0) sb.AppendLine("- [PASS] 契约默认五块面板内部一致");
            else foreach (var i in deckIssues) sb.AppendLine($"- [FAIL] {i}");

            sb.AppendLine();
            sb.AppendLine("## 分档落位");

            var compact = HoloDeck.CreateCompact();

            foreach (var caps in AllProfiles())
            {
                var zone = SafeZoneResolver.From(caps);
                sb.AppendLine();
                sb.AppendLine($"### {caps.Name}（安全区 {zone}）");

                int fit, overflow;
                sb.AppendLine($"**五块版（{deck.name}）**");
                foreach (var line in HoloPanelLayout.AuditAll(deck.panels, caps, out fit, out overflow))
                    sb.AppendLine("- " + line);
                sb.AppendLine($"- 结论：{fit} 块原样可用，{overflow} 块需压回或隐藏");

                if (zone.Tier != SafeZoneTier.Wide)
                {
                    sb.AppendLine();
                    sb.AppendLine($"**三块版（{compact.name}，窄视场自动切换）**");
                    foreach (var line in HoloPanelLayout.AuditAll(compact.panels, caps, out fit, out overflow))
                        sb.AppendLine("- " + line);
                    sb.AppendLine($"- 结论：{fit} 块原样可用，{overflow} 块需压回或隐藏");
                }

                var anchors = SafeZoneResolver.Anchors(zone);
                sb.AppendLine($"- HUD 锚点：{anchors.Length} 个（中心 + 四角），中心 yaw {anchors[0].x:0}° pitch {anchors[0].y:0}°");
            }

            Emit(sb.ToString(), "面板落位审计");
        }

        [MenuItem("Steel Ridge/平台/③ 输入降级审计（有/无 6DoF 手柄）", false, 42)]
        public static void AuditInputs()
        {
            var sb = new StringBuilder();
            sb.AppendLine("## 输入降级");

            foreach (var caps in AllProfiles())
            {
                var router = BuildRouter(caps);
                sb.AppendLine();
                sb.AppendLine($"### {caps.Name}");
                foreach (var line in router.Audit())
                    sb.AppendLine("- " + line);

                var lost = new List<string>();
                for (int ch = 0; ch <= (int)InputChannel.PanelSelect; ch++)
                {
                    if (!router.TryRead((InputChannel)ch, out _, out _))
                        lost.Add(((InputChannel)ch).ToString());
                }
                sb.AppendLine(lost.Count == 0
                    ? "- 结论：八个通道全部有供给侧"
                    : $"- 结论：{lost.Count} 个通道无供给侧 → {string.Join("，", lost)}（需在 gameplay 侧禁用或改设计）");
            }

            Emit(sb.ToString(), "输入降级审计");
        }

        [MenuItem("Steel Ridge/平台/④ 性能与显示双档审计", false, 43)]
        public static void AuditPerfAndDisplay()
        {
            var sb = new StringBuilder();
            var budgets = new List<FrameBudget>();

            foreach (var caps in AllProfiles())
                budgets.Add(PerfBudgetPlanner.From(caps));

            sb.AppendLine("## 性能双档");
            foreach (var l in PerfBudgetPlanner.CompareTable(budgets))
                sb.AppendLine(l);

            sb.AppendLine();
            sb.AppendLine("共用 LOD 断点：" + string.Join(" / ", PerfBudgetPlanner.SharedLodHeights));
            sb.AppendLine();

            sb.AppendLine("## 显示语义");
            sb.AppendLine();
            sb.AppendLine("| 档案 | 混合 | 允许黑板 | 允许后处理 | 允许 bloom | 自发光上限 | 壳体半透明 | 清屏 alpha |");
            sb.AppendLine("|---|---|---|---|---|---|---|---|");

            foreach (var caps in AllProfiles())
            {
                var c = DisplayConstraints.From(caps);
                sb.AppendLine($"| {caps.Name} | {c.Blend} | {(c.AllowBlackBackground ? "是" : "否")} | " +
                              $"{(c.AllowFullScreenPostFx ? "是" : "否")} | {(c.AllowBloom ? "是" : "否")} | " +
                              $"{c.MaxEmissiveIntensity:0.0} | {(c.ShellMustBeTransparent ? "是" : "否")} | {c.ClearAlpha:0.0} |");
            }

            sb.AppendLine();
            sb.AppendLine("## 遮挡与地面");

            // 场景里若有 GroundAnchor，读它自己的配置；没有则按代码常量给默认值，并标注清楚。
            var groundAnchor = Object.FindAnyObjectByType<GroundAnchor>();

            foreach (var caps in AllProfiles())
            {
                var occ = OcclusionResolver.Resolve(caps, false);
                float eye = groundAnchor != null
                    ? groundAnchor.EyeHeightFor(caps)
                    : caps.Translation == TranslationSupport.RoomScale
                        ? GroundAnchor.DefaultStandingEyeHeight
                        : GroundAnchor.DefaultSeatedEyeHeight;

                string ground = !caps.HasWorldScale
                    ? $"眼高假设静态地面（3DoF，尺度不可观测；眼高 {eye:0.00} m 为假设值）"
                    : caps.IsAdditive || caps.Translation == TranslationSupport.RoomScale
                        ? $"平面检测（等宿主推送，探针 = 眼位 − {eye:0.00} m）"
                        : $"虚拟静态地面（眼高 {eye:0.00} m）";
                string follow = caps.Translation == TranslationSupport.None ? "Locked（全补偿）"
                    : caps.Translation == TranslationSupport.SeatedClamp ? $"SeatedClamp（半径 {caps.MaxTranslationMeters:0.00} m）"
                    : "FollowHorizontal（舱随人走）";

                sb.AppendLine($"- {caps.Name}：遮挡 {occ}｜地面 {ground}｜视角 {follow}");
            }

            if (groundAnchor == null)
                sb.AppendLine("- 注：场景内无 GroundAnchor 实例，眼高取代码默认值（坐姿 1.15 / 站姿 1.65 m）");

            AppendGroundConfidenceSection(sb);

            Emit(sb.ToString(), "性能与显示审计");
        }

        [MenuItem("Steel Ridge/平台/⑤ 跟踪质量验收（§18.8 四项指标）", false, 44)]
        public static void AuditTracking()
        {
            var sb = new StringBuilder();
            AppendTrackingSection(sb);
            Emit(sb.ToString(), "跟踪质量验收");
        }

        [MenuItem("Steel Ridge/平台/导出完整审计报告（Markdown）", false, 45)]
        public static void ExportFullReport()
        {
            var sb = new StringBuilder();
            sb.AppendLine("# 平台抽象层审计报告");
            sb.AppendLine();
            sb.AppendLine($"> 生成时间：{System.DateTime.Now:yyyy-MM-dd HH:mm}");
            sb.AppendLine("> 说明：本报告由代码生成，数值来自 PlatformProfile / 内置预设，实测后须替换折算值。");
            sb.AppendLine();

            var chapter1 = new StringBuilder();
            AuditCapabilitiesSilent(chapter1);
            sb.Append(chapter1);

            var chapter2 = new StringBuilder();
            AuditPanelsSilent(chapter2);
            sb.Append(chapter2);

            var chapter3 = new StringBuilder();
            AuditInputsSilent(chapter3);
            sb.Append(chapter3);

            var chapter4 = new StringBuilder();
            AuditPerfSilent(chapter4);
            sb.Append(chapter4);

            var chapter5 = new StringBuilder();
            AppendTrackingSection(chapter5, true);
            sb.Append(chapter5);

            var chapter6 = new StringBuilder();
            AppendMigrationNotes(chapter6);
            sb.Append(chapter6);

            Directory.CreateDirectory(ReportDir);
            File.WriteAllText(ReportPath, sb.ToString(), new UTF8Encoding(false));
            AssetDatabase.Refresh();

            Debug.Log($"[SteelRidge] 审计报告已写入 {ReportPath}\n{sb.ToString().Substring(0, Mathf.Min(1200, sb.Length))}…");
        }

        [MenuItem("Steel Ridge/平台/生成四档档案资产（平台 + 面板组）", false, 46)]
        public static void GenerateProfileAssets()
        {
            const string dir = "Assets/_Project/Config/Platforms";
            const string deckDir = "Assets/_Project/Config/Holo";
            Directory.CreateDirectory(dir);
            Directory.CreateDirectory(deckDir);

            CreateAsset(Build(PicoVR(), "PICO_4_VR"), dir);
            CreateAsset(Build(RokidStudio(), "Rokid_ARStudio"), dir);
            CreateAsset(Build(RokidGlasses(), "Rokid_Glasses"), dir);
            CreateAsset(Build(DebugFlat(), "Editor_Flat"), dir);

            CreateDeckAsset(HoloDeck.CreateDefault(), deckDir, "HoloDeck_Default");
            CreateDeckAsset(HoloDeck.CreateCompact(), deckDir, "HoloDeck_Compact");

            AssetDatabase.SaveAssets();
            AssetDatabase.Refresh();
            Debug.Log($"[SteelRidge] 档案资产已生成：{dir}（4 个）＋ {deckDir}（2 个面板组）");
        }

        static void CreateDeckAsset(HoloDeck d, string dir, string assetName)
        {
            d.name = assetName;
            string path = $"{dir}/{assetName}.asset";
            var existing = AssetDatabase.LoadAssetAtPath<HoloDeck>(path);
            if (existing != null)
            {
                EditorUtility.CopySerialized(d, existing);
                Object.DestroyImmediate(d);
                return;
            }
            AssetDatabase.CreateAsset(d, path);
        }

        // ═════════════════════ 内部 ═════════════════════

        static void CreateAsset(PlatformProfile p, string dir)
        {
            string path = $"{dir}/{p.name}.asset";
            var existing = AssetDatabase.LoadAssetAtPath<PlatformProfile>(path);
            if (existing != null)
            {
                EditorUtility.CopySerialized(p, existing);
                Object.DestroyImmediate(p);
                return;
            }
            AssetDatabase.CreateAsset(p, path);
        }

        static void Emit(string markdown, string title)
        {
            Debug.Log($"[SteelRidge] {title}\n{markdown}");

            Directory.CreateDirectory(ReportDir);
            string path = $"{ReportDir}/{title}.md";
            File.WriteAllText(path, $"# {title}\n\n" + markdown, new UTF8Encoding(false));
            AssetDatabase.Refresh();
            Debug.Log($"[SteelRidge] 已写入 {path}");
        }

        // ── 静默版（写进完整报告，不各自落文件） ──

        static void AuditCapabilitiesSilent(StringBuilder sb)
        {
            sb.AppendLine("## 1 能力矩阵");
            sb.AppendLine();
            sb.AppendLine("| 档案 | 显示 | 位移 | 尺度 | 视场(H×V) | PPD | 遮挡 | 光照估计 |");
            sb.AppendLine("|---|---|---|---|---|---|---|---|");
            foreach (var c in AllProfiles())
                sb.AppendLine($"| {c.Name} | {c.Display} | {c.Translation} | {c.Scale} | {c.FovHorizontal:0}°×{c.FovVertical:0}° | {c.PixelsPerDegree:0} | {(c.SupportsOcclusion ? "有" : "无")} | {(c.SupportsLightEstimation ? "有" : "无")} |");
            sb.AppendLine();
        }

        static void AuditPanelsSilent(StringBuilder sb)
        {
            var deck = HoloDeck.CreateDefault();
            var compact = HoloDeck.CreateCompact();
            sb.AppendLine("## 2 面板落位");
            sb.AppendLine();
            sb.AppendLine("### 2.1 五块版（VR 用）");
            sb.AppendLine();
            AppendPanelTable(sb, deck, BuiltinCapabilities.PicoVR, BuiltinCapabilities.RokidArStudio);

            sb.AppendLine("### 2.2 三块版（43° AR 用）");
            sb.AppendLine();
            AppendPanelTable(sb, compact, BuiltinCapabilities.PicoVR, BuiltinCapabilities.RokidArStudio);
            sb.AppendLine();
        }

        static void AppendPanelTable(StringBuilder sb, HoloDeck deck, in PlatformCapabilities vr, in PlatformCapabilities ar)
        {
            sb.AppendLine("| 面板 | 优先级 | yaw | pitch | 距离 | 横向半宽 | 纵向半宽 | 96° VR | 43° AR |");
            sb.AppendLine("|---|---|---|---|---|---|---|---|---|");

            foreach (var p in deck.panels)
            {
                var v = HoloPanelLayout.Solve(p, vr);
                var a = HoloPanelLayout.Solve(p, ar);
                sb.AppendLine($"| {p.id} | {p.priority} | {p.yaw:0}° | {p.pitch:0}° | {p.distance:0.00} m | " +
                              $"{v.AngularHalfWidthH:0.#}° | {v.AngularHalfWidthV:0.#}° | " +
                              $"{(v.Fits ? "可用" : "出画")} | {(a.Fits ? "可用" : "需压回/隐藏")} |");
            }

            sb.AppendLine();
        }

        static void AuditInputsSilent(StringBuilder sb)
        {
            sb.AppendLine("## 3 输入降级");
            sb.AppendLine();
            foreach (var caps in AllProfiles())
            {
                var router = BuildRouter(caps);
                sb.AppendLine($"### {caps.Name}");
                foreach (var l in router.Audit()) sb.AppendLine("- " + l);
                sb.AppendLine();
            }
        }

        static void AuditPerfSilent(StringBuilder sb)
        {
            var budgets = new List<FrameBudget>();
            foreach (var caps in AllProfiles()) budgets.Add(PerfBudgetPlanner.From(caps));

            sb.AppendLine("## 4 性能双档");
            sb.AppendLine();
            foreach (var l in PerfBudgetPlanner.CompareTable(budgets)) sb.AppendLine(l);
            sb.AppendLine();
            AppendGroundConfidenceSection(sb);
        }

        /// <summary>
        /// 地面置信度阈值表。数值由 DetectedPlaneProvider 的实际权重函数扫出，
        /// 不在文档里手算 —— 否则代码改了报告不会跟着变。
        /// </summary>
        static void AppendGroundConfidenceSection(StringBuilder sb)
        {
            var dp = new DetectedPlaneProvider();
            float tiltCut = dp.EffectiveTiltCutoffDeg();
            float heightCut = dp.EffectiveHeightCutoffMeters();

            sb.AppendLine();
            sb.AppendLine("### 地面检测置信度阈值");
            sb.AppendLine();
            sb.AppendLine($"- 权重参数：宿主置信度 × 倾角（软 {dp.SoftTiltDeg:0}° / 硬 {dp.HardTiltDeg:0}°）" +
                          $" × 新鲜度（{dp.StaleSeconds:0.0} s 后线性衰减）" +
                          $" × 高度先验（容差 {dp.HeightToleranceMeters:0.00} m）；融合后低于 {dp.MinConfidence:0.00} 判为未解析");
            sb.AppendLine(tiltCut < 0f
                ? "- 有效倾角截止：容差内不跌破（异常）"
                : $"- 有效倾角截止：≈ {tiltCut:0.#}°（超过即权重低于 {dp.MinConfidence:0.00}，退回眼高兜底）");
            sb.AppendLine(heightCut < 0f
                ? "- 有效高度截止：容差内不跌破（异常）"
                : $"- 有效高度截止：≈ {heightCut:0.00} m（这是排除桌面的依据，倾角判据对此无效）");
            if (heightCut > 0f)
                sb.AppendLine($"- **该截止值同时是眼高假设的误差预算**：站姿眼高按 1.65 m 取值，" +
                              $"个体差异超过 ±{heightCut:0.00} m 时真实地面会被先验排除、退回兜底。" +
                              "超出此预算的场景应改用宿主提供的平面语义标签（floor/table 分类），而不是继续调容差。");
            sb.AppendLine();
            sb.AppendLine("| 场景 | 倾角 | 高度偏差 | 稳态权重 | 判定 |");
            sb.AppendLine("|---|---|---|---|---|");

            var cases = new[]
            {
                ("平整地面", 3f, 0.02f),
                ("地砖缝 / 轻微反光", 12f, 0.10f),
                ("斜坡 20°", 20f, 0.10f),
                ("斜坡 26°（旧硬门限在此处会掉回兜底）", 26f, 0.10f),
                ("楼梯斜梁 35°", 35f, 0.10f),
                ("矮几 / 台阶（水平但高 0.30 m）", 2f, 0.30f),
                ("桌面 / 台面（水平但高 0.45 m）", 2f, 0.45f),
                ("货架隔板（水平但高 0.40 m）", 2f, 0.40f),
                ("地面 + 眼高误差 0.10 m", 3f, 0.10f),
                ("地面 + 眼高误差 0.20 m", 3f, 0.20f),
                ("地面 + 眼高误差 0.30 m（超预算）", 3f, 0.30f)
            };

            foreach (var (name, tilt, dh) in cases)
            {
                float w = dp.SteadyWeight(0.8f, tilt, dh);
                sb.AppendLine($"| {name} | {tilt:0}° | {dh:0.00} m | {w:0.000} | {(w >= dp.MinConfidence ? "接受" : "拒，退回眼高兜底")} |");
            }

            sb.AppendLine();
            sb.AppendLine("旧实现是「法线偏差超过 25° 直接丢弃 + 取单一最优平面 + 位置取平面中心」，");
            sb.AppendLine("三个问题：边界跳变（26° 的斜坡会让座舱 y 突跳）、桌面被当地面（桌面也是水平的）、");
            sb.AppendLine("以及检测到半块地面时机甲跳到平面正中。现改为连续权重 + 多平面加权融合 + 探针投影。");
            sb.AppendLine();
        }

        static void AppendMigrationNotes(StringBuilder sb)
        {
            sb.AppendLine("## 6 迁移到 AR 时必须改的四件事");
            sb.AppendLine();
            sb.AppendLine("| # | 事项 | VR 做法 | AR 做法 | 代码入口 |");
            sb.AppendLine("|---|---|---|---|---|");
            sb.AppendLine("| 1 | 背景语义 | 黑 = 暗场 | 黑 = 透明，禁止黑板 | DisplayConstraints.AllowBlackBackground |");
            sb.AppendLine("| 2 | 遮挡 | 壳体几何挡住一切 | 深度软遮挡，无深度则退为提示面 | OcclusionPolicy.Apply |");
            sb.AppendLine("| 3 | 座舱锚定 | 钉在座椅，±0.15 m | 舱随人走 / 只跟水平 | ViewpointPolicy.Mode |");
            sb.AppendLine("| 4 | 交互 | 6DoF 手柄四键 | 手势 pinch / 射线 / 注视停留 / 语音 | InputRouter.Audit |");
            sb.AppendLine();
            sb.AppendLine("## 7 未解决项");
            sb.AppendLine();
            sb.AppendLine("- Rokid AR Studio 的 43°×28° 为 50° 对角按 16:10 折算，**实测后必须替换**；");
            sb.AppendLine("- 深度来源（IRealDepthSource）目前只有 NullDepthSource，真机需接 SDK；");
            sb.AppendLine("- 加色材质变体尚未制作，AdditiveMaterialGuard 现阶段只能报问题，不能修；");
            sb.AppendLine("- 跟踪状态来源（ITrackingStateSource）目前只有 NullTrackingStateSource，真机需接 SDK；");
            sb.AppendLine("- AR 像素配准误差尚未标定，验收报告里为 N/A，不能当作 0。");
        }

        /// <summary>
        /// 跟踪质量与验收指标。这一节回答的是"漂了怎么办" ——
        /// 答案是给四个可测的数字，而不是承诺"不漂"。
        /// </summary>
        static void AppendTrackingSection(StringBuilder sb, bool numbered = false)
        {
            sb.AppendLine(numbered ? "## 5 跟踪质量与验收指标" : "## 跟踪质量与验收指标");
            sb.AppendLine();
            sb.AppendLine("> 四项指标取自 SLAM Handbook §18.8 度量清单的第 3/4/5/9 项。");
            sb.AppendLine("> 选它们而不是「定位精度」的理由：精度需外部真值（动捕系统），竞赛现场与客户现场都不具备；");
            sb.AppendLine("> 而这四项中三项可由应用侧自测，一项只需一次人工标定。");
            sb.AppendLine();

            sb.AppendLine("### 指标定义与数据来源");
            sb.AppendLine();
            sb.AppendLine("| # | 指标 | 定义 | 数据来源 | 能否应用内自测 |");
            sb.AppendLine("|---|---|---|---|---|");
            sb.AppendLine("| 3 | 跟踪可用率 | (正常 + 降级) 帧 / 有效帧 | 宿主 tracking state | 能 |");
            sb.AppendLine("| 4 | 重定位成功率 | 恢复次数 / 超过宽限期的丢失次数 | 同左 | 能 |");
            sb.AppendLine("| 5 | 帧时间 | CPU 单帧耗时（ms） | Time.unscaledDeltaTime | 能（不等同运动到光子延迟） |");
            sb.AppendLine("| 9 | AR 像素配准误差 | 叠加图形与真实特征的位置偏差（px） | 人工标定 | 否，须一次标定 |");
            sb.AppendLine();

            sb.AppendLine("### 各平台门槛");
            sb.AppendLine();
            sb.AppendLine("| 档案 | 跟踪可用率 | 完好率 | 重定位成功率 | 平均恢复 | 帧时间 | 像素配准上限 |");
            sb.AppendLine("|---|---|---|---|---|---|---|");
            foreach (var caps in AllProfiles())
            {
                var a = TrackingAcceptance.From(caps);
                sb.AppendLine($"| {caps.Name} | ≥{a.MinTrackingRobustness:P0} | ≥{a.MinUndegradedRatio:P0} | " +
                              $"≥{a.MinRelocalizationRobustness:P0} | ≤{a.MaxMeanRecoverySeconds:0.0} s | " +
                              $"≤{a.MaxFrameMs:0.0} ms | ≤{a.MaxArPixelRegistrationError:0.0} px |");
            }
            sb.AppendLine();
            sb.AppendLine("AR 门槛一律比 VR 严：光学透视是把图形叠在真实世界上，同样的抖动在 VR 里是「画面在晃」，");
            sb.AppendLine("在 AR 里是「世界在晃」，后者无法归因于内容，用户会直接判定设备不可用。");
            sb.AppendLine();

            sb.AppendLine("### 完好率为什么单列一档");
            sb.AppendLine();
            sb.AppendLine("VIO 在弱纹理、强逆光、纯旋转下必然降级。把降级算作失败，可用率永远不达标；");
            sb.AppendLine("但降级帧多到一定比例就是产品问题，混进可用率里会被平均掉。");
            sb.AppendLine("所以分两个数：可用率（含降级）回答「还能不能用」，完好率（仅正常）回答「好不好用」。");
            sb.AppendLine();

            sb.AppendLine("### AR 像素配准标定规程（一次，约 20 分钟）");
            sb.AppendLine();
            sb.AppendLine("1. 打印一张高对比度十字靶（十字交点即标定点），贴在平面墙上；");
            sb.AppendLine("2. 用卷尺记录靶心到地面的垂距，以及靶心到两侧墙角的两段水平距离，作为**独立于头显的**真值；");
            sb.AppendLine("3. 在应用里加载「标定场景」：在同样三个坐标处放三个纯色 1 px 线宽的十字；");
            sb.AppendLine("4. 戴上设备，站在距靶 1.5 m 处，头部保持不动，截图（设备自带截屏，不要拍屏）；");
            sb.AppendLine("5. 在截图里量虚拟十字与真实靶心的像素偏差，取三个点的均值，填入档案的 `arPixelRegistrationError`。");
            sb.AppendLine();
            sb.AppendLine("为什么必须截图量而不是目视：44 PPD 下 1.5 px 约 2′ 视角，肉眼无法分辨，但叠加在真实边缘上会显脏。");
            sb.AppendLine();

            sb.AppendLine("### 应用内测不到的两项，以及为什么");
            sb.AppendLine();
            sb.AppendLine("| 指标 | 为什么测不到 | 替代做法 |");
            sb.AppendLine("|---|---|---|");
            sb.AppendLine("| 运动到光子延迟（M2P） | 需光电传感器测屏幕响应 + 外部高速相机，应用无权访问显示管线末端 | 报帧时间，并注明「不含显示与光子延迟」；真机 M2P 向厂商索取规格书 |");
            sb.AppendLine("| 绝对定位精度（cm 级） | 需外部真值（动捕 / 全站仪） | 不承诺绝对值，只承诺「重定位成功率」与「像素配准误差」 |");
            sb.AppendLine();
            sb.AppendLine("这两条必须写进对外的验收口径里。用帧时间冒充延迟、用「不漂」冒充精度，是评审最容易一眼看穿的地方。");
            sb.AppendLine();

            sb.AppendLine("### 挂接方式");
            sb.AppendLine();
            sb.AppendLine("```csharp");
            sb.AppendLine("// 宿主侧：实现 ITrackingStateSource，把 SDK 的跟踪状态翻成 TrackingState");
            sb.AppendLine("var monitor = gameObject.AddComponent<TrackingQualityMonitor>();");
            sb.AppendLine("monitor.Configure(caps, profile.ToAcceptance(), new MySdkTrackingSource());");
            sb.AppendLine();
            sb.AppendLine("// 会话结束后取数");
            sb.AppendLine("foreach (var line in monitor.Evaluate()) Debug.Log(line);");
            sb.AppendLine("```");
            sb.AppendLine();
            sb.AppendLine("未接宿主时 `NullTrackingStateSource` 恒返回 false，报告里是 `[N/A]` 而不是 100% ——");
            sb.AppendLine("一个假的满分指标比没有指标更危险。");
            sb.AppendLine();
        }

        static InputRouter BuildRouter(in PlatformCapabilities caps)
        {
            var r = new InputRouter();
            r.Configure(caps);
            r.Add(new KeyboardDebugSource());

            if (caps.Has6DoFController)
            {
                var stick = new ControllerStickSource();
                stick.SetNode(UnityEngine.XR.XRNode.RightHand);
                r.Add(stick);
            }

            if (caps.HasHandTracking) r.Add(new HandPinchSource());

            if ((caps.Inputs & InputCapability.Gaze) != 0)
                r.Add(new GazeSource { DwellSeconds = caps.IsAdditive ? 1.0f : 1.4f });

            r.Tick(0f);
            return r;
        }

        static List<PlatformCapabilities> AllProfiles() => new List<PlatformCapabilities>
        {
            BuiltinCapabilities.DebugFlat,
            BuiltinCapabilities.PicoVR,
            BuiltinCapabilities.RokidArStudio,
            BuiltinCapabilities.RokidGlasses2025
        };

        static IEnumerable<PlatformProfile> ProfileAssets()
        {
            yield return Build(PicoVR(), "PICO_4_VR");
            yield return Build(RokidStudio(), "Rokid_ARStudio");
            yield return Build(RokidGlasses(), "Rokid_Glasses");
            yield return Build(DebugFlat(), "Editor_Flat");
        }

        // ── 预设构造（与 BuiltinCapabilities 对齐，但独立可编辑） ──

        static PlatformProfile Build(in PlatformCapabilities c, string assetName)
        {
            var p = ScriptableObject.CreateInstance<PlatformProfile>();
            p.name = assetName;
            p.displayName = c.Name;
            p.displayMode = c.Display;
            p.translation = c.Translation;
            p.scaleGrounding = c.Scale;
            p.inputs = c.Inputs;
            p.fovHorizontal = c.FovHorizontal;
            p.fovVertical = c.FovVertical;
            p.pixelsPerDegree = c.PixelsPerDegree;
            p.supportsPassthrough = c.SupportsPassthrough;
            p.supportsOcclusion = c.SupportsOcclusion;
            p.supportsLightEstimation = c.SupportsLightEstimation;
            p.maxTranslationMeters = c.MaxTranslationMeters;
            p.refreshHz = c.RefreshHz;

            var b = PerfBudgetPlanner.From(c);
            p.triangleBudget = b.Triangles;
            p.drawCallBudget = b.DrawCalls;
            p.materialBudget = b.Materials;
            p.maxHoloPanels = b.HoloPanels;
            p.maxDynamicRenderTextures = b.DynamicRenderTextures;

            p.forbidFullScreenPostFx = c.IsAdditive;
            p.cockpitShellMustBeTransparent = c.IsAdditive;
            p.safeMarginDeg = c.IsAdditive ? 4f : 6f;
            p.criticalHalfAngle = SafeZoneResolver.From(c).CriticalHalfAngle;

            var acc = TrackingAcceptance.From(c);
            p.minTrackingRobustness = acc.MinTrackingRobustness;
            p.minUndegradedRatio = acc.MinUndegradedRatio;
            p.minRelocalizationRobustness = acc.MinRelocalizationRobustness;
            p.maxMeanRecoverySeconds = acc.MaxMeanRecoverySeconds;
            p.arPixelRegistrationError = acc.ArPixelRegistrationError;
            p.maxArPixelRegistrationError = acc.MaxArPixelRegistrationError;

            return p;
        }

        static PlatformCapabilities PicoVR() => BuiltinCapabilities.PicoVR;
        static PlatformCapabilities RokidStudio() => BuiltinCapabilities.RokidArStudio;
        static PlatformCapabilities RokidGlasses() => BuiltinCapabilities.RokidGlasses2025;
        static PlatformCapabilities DebugFlat() => BuiltinCapabilities.DebugFlat;
    }
}
