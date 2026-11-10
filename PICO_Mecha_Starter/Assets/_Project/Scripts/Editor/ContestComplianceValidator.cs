using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using SteelRidge.Core;
using UnityEditor;
using UnityEditor.Build;
using UnityEngine;
using UnityEngine.Rendering;
using Object = UnityEngine.Object;

namespace SteelRidge.EditorTools
{
    /// <summary>
    /// 比赛合规自检。把 PICO OpenXR 赛道的硬性要求 + 90Hz 性能预算编成可执行检查。
    /// 每一项给出 PASS / WARN / FAIL / SKIP，FAIL 不允许提交。
    /// 菜单：Steel Ridge/合规/运行比赛合规自检
    /// </summary>
    public static class ContestComplianceValidator
    {
        // ── 性能预算（源自技术方案 v2.0） ──
        const int TriBudget = 900_000;
        const int DrawCallBudget = 200;
        const int MaterialBudget = 40;
        const int HoloPanelBudget = 5;
        const int DynamicRtBudget = 1;

        enum St { Pass, Warn, Fail, Skip }

        class Row
        {
            public string Group;
            public string Item;
            public St Status;
            public string Detail;
        }

        [MenuItem("Steel Ridge/合规/运行比赛合规自检", false, 20)]
        public static void Run()
        {
            var rows = new List<Row>();

            CheckPlatform(rows);
            CheckScene(rows);
            CheckXr(rows);
            CheckPlatformAbstraction(rows);

            Report(rows);
        }

        // ═════════════════════ 平台抽象层 ═════════════════════

        /// <summary>
        /// 抽象层合规。这一组检查的是"换设备时要改的东西是否已经被隔离"，
        /// 而不是"画面好不好看" —— 后者只有评审能给分。
        /// </summary>
        static void CheckPlatformAbstraction(List<Row> rows)
        {
            const string g = "平台抽象";

            var bootstrap = Object.FindAnyObjectByType<SteelRidge.Core.Platform.PlatformBootstrap>();
            rows.Add(Make(g, "场景存在 PlatformBootstrap",
                bootstrap != null ? St.Pass : St.Warn,
                bootstrap != null ? bootstrap.name : "缺少装配根：各抽象子系统都不会生效，等于白写"));

            // 厂商命名空间泄漏扫描。PICO 与 Rokid 同一条判据：
            // 抽象层的意义是"换设备改档案不改代码"，一旦 gameplay 里出现厂商命名空间，
            // 这句话就不成立了。所以两类都必须是 FAIL 级，而不是"提示一下"。
            var leaks = ScanVendorNamespaceLeaks();

            rows.Add(Make(g, "无 PICO / Rokid 专有命名空间引用",
                leaks.Count == 0 ? St.Pass : St.Fail,
                leaks.Count == 0 ? "全部走 OpenXR / XR 通用接口" : "泄漏：" + string.Join("、", leaks)));

            // 性能双档
            var vr = SteelRidge.Core.Perf.PerfBudgetPlanner.From(SteelRidge.Core.Platform.BuiltinCapabilities.PicoVR);
            var ar = SteelRidge.Core.Perf.PerfBudgetPlanner.From(SteelRidge.Core.Platform.BuiltinCapabilities.RokidArStudio);

            rows.Add(Make(g, "VR 预算与合规常量一致（90 万面 / 200 DC）",
                vr.Triangles == TriBudget && vr.DrawCalls == DrawCallBudget ? St.Pass : St.Warn,
                $"{vr.Triangles:N0} 面 / {vr.DrawCalls} DC"));

            rows.Add(Make(g, "AR 预算显著更严且已单独定义",
                ar.Triangles < vr.Triangles && ar.DrawCalls < vr.DrawCalls ? St.Pass : St.Fail,
                $"{ar.Triangles:N0} 面 / {ar.DrawCalls} DC（VR 的 {ar.Triangles * 100f / vr.Triangles:0}%）"));

            // 显示语义
            var arDisplay = SteelRidge.Core.Render.DisplayConstraints.From(
                SteelRidge.Core.Platform.BuiltinCapabilities.RokidArStudio);

            rows.Add(Make(g, "AR 禁用全屏后处理与黑板",
                !arDisplay.AllowFullScreenPostFx && !arDisplay.AllowBlackBackground ? St.Pass : St.Fail,
                arDisplay.ToString()));

            // 资产
            int profileCount = AssetDatabase.FindAssets("t:PlatformProfile").Length;
            rows.Add(Make(g, "已生成平台档案资产",
                profileCount >= 2 ? St.Pass : St.Warn,
                profileCount == 0
                    ? "未生成，运行时只能按设备名猜（菜单：Steel Ridge/平台/生成四档档案资产）"
                    : $"{profileCount} 个"));

            int deckCount = AssetDatabase.FindAssets("t:HoloDeck").Length;
            rows.Add(Make(g, "已生成全息面板组资产",
                deckCount >= 1 ? St.Pass : St.Warn,
                deckCount == 0 ? "使用代码内默认五块面板（可接受，但评审时不好指认）" : $"{deckCount} 个"));

            // ── 尺度可观测性（SLAM Handbook §11.3.3：纯旋转下尺度不可观测）──
            var glasses = SteelRidge.Core.Platform.BuiltinCapabilities.RokidGlasses2025;
            rows.Add(Make(g, "3DoF AR 未虚报真实世界尺度",
                glasses.HasWorldScale == false ? St.Pass : St.Fail,
                glasses.HasWorldScale
                    ? "Rokid Glasses 预设声明了 WorldMetric：纯旋转下尺度不可观测，所有米级断言无效"
                    : $"HeadRelative｜地面退回静态、面板距离按角度口径（{glasses.LengthUnit}）"));

            // ── 跟踪质量验收（§18.8 第 3/4/5/9 项）──
            var monitor = Object.FindAnyObjectByType<SteelRidge.Core.Spatial.TrackingQualityMonitor>();
            rows.Add(Make(g, "场景存在跟踪质量监控器",
                monitor != null ? St.Pass : St.Warn,
                monitor != null
                    ? $"来源 {monitor.SourceName}｜{monitor.Acceptance}"
                    : "缺 TrackingQualityMonitor：无法回答「漂了怎么办」，验收只有帧预算没有跟踪指标"));

            int arProfiles = 0, arCalibrated = 0;
            foreach (var guid in AssetDatabase.FindAssets("t:PlatformProfile"))
            {
                var p = AssetDatabase.LoadAssetAtPath<SteelRidge.Core.Platform.PlatformProfile>(
                    AssetDatabase.GUIDToAssetPath(guid));
                if (p == null || p.displayMode != SteelRidge.Core.Platform.DisplayMode.AdditiveAR) continue;
                arProfiles++;
                if (p.arPixelRegistrationError > 0f) arCalibrated++;
            }

            rows.Add(Make(g, "AR 档案已记录像素配准实测值",
                arProfiles == 0 ? St.Warn : (arCalibrated == arProfiles ? St.Pass : St.Warn),
                arProfiles == 0
                    ? "未找到 AR 档案资产（先跑菜单：生成四档档案资产）"
                    : $"{arCalibrated} / {arProfiles} 个 AR 档案已标定" +
                      (arCalibrated == arProfiles
                          ? ""
                          : "（未标定的档案在审计报告里是 N/A，不能当作 0；菜单：记录 AR 像素配准误差）")));
        }

        /// <summary>
        /// 扫描厂商命名空间泄漏。返回 "文件名（命中词）" 列表。
        /// 只扫 Assets/_Project/Scripts 下的 .cs —— 适配器与宿主脚本若需要引用厂商 SDK，
        /// 应放在 Scripts 之外的独立程序集，这样"哪一行依赖要删"在编译期就是确定的。
        ///
        /// 匹配前必须先剥注释与字符串字面量。踩过的坑：本方法的同名词表与 SpatialAudio 里
        /// "PicoSpatialAudio 在 OpenXR 侧不可用"这句注释，都会被朴素 Contains 判成泄漏 ——
        /// 一个 FAIL 级门禁如果会误报自己，它迟早会被当成噪音关掉。
        /// </summary>
        static List<string> ScanVendorNamespaceLeaks()
        {
            var tokens = new[]
            {
                // PICO
                "using Pico.", "using ByteDance", "PicoSpatialAudio", "Unity.XR.PXR", "Unity.XR.PICO",
                // Rokid（UXR SDK）
                "using Rokid.", "using Rokid;", "Rokid.UXR", "Unity.XR.Rokid", "OpenXR.Features.Rokid"
            };

            var leaks = new List<string>();
            foreach (var guid in AssetDatabase.FindAssets("t:MonoScript"))
            {
                string path = AssetDatabase.GUIDToAssetPath(guid);
                if (!path.StartsWith("Assets/_Project/Scripts/") || !path.EndsWith(".cs")) continue;

                string text;
                try { text = File.ReadAllText(path); } catch { continue; }

                string code = StripCommentsAndLiterals(text);

                var hit = new List<string>();
                foreach (var t in tokens)
                    if (code.Contains(t)) hit.Add(t);

                if (hit.Count > 0)
                    leaks.Add($"{Path.GetFileName(path)}（{string.Join("/", hit)}）");
            }

            return leaks;
        }

        /// <summary>
        /// 去掉 // 与 /* */ 注释、字符串与字符字面量的内容，只留可执行代码。
        /// 目的不是美化，是让"注释里提到厂商名"不算泄漏、也不遮蔽真实泄漏。
        /// 已知边界：不处理 @"" 逐字字符串（本项目未使用；若引入需补一个分支）。
        /// </summary>
        static string StripCommentsAndLiterals(string src)
        {
            var sb = new StringBuilder(src.Length);
            bool inLine = false, inBlock = false, inStr = false, inChar = false;

            for (int i = 0; i < src.Length; i++)
            {
                char c = src[i];
                char n = i + 1 < src.Length ? src[i + 1] : '\0';

                if (inLine) { if (c == '\n') { inLine = false; sb.Append(c); } continue; }
                if (inBlock) { if (c == '*' && n == '/') { inBlock = false; i++; } continue; }
                if (inStr)
                {
                    if (c == '\\') { i++; continue; }
                    if (c == '"') { inStr = false; sb.Append('"'); }
                    continue;
                }
                if (inChar)
                {
                    if (c == '\\') { i++; continue; }
                    if (c == '\'') { inChar = false; sb.Append('\''); }
                    continue;
                }

                if (c == '/' && n == '/') { inLine = true; i++; continue; }
                if (c == '/' && n == '*') { inBlock = true; i++; continue; }
                if (c == '"') { inStr = true; continue; }
                if (c == '\'') { inChar = true; continue; }

                sb.Append(c);
            }

            return sb.ToString();
        }

        // ═════════════════════ 工程配置 ═════════════════════

        static void CheckPlatform(List<Row> rows)
        {
            const string g = "工程配置";

            rows.Add(Make(g, "Build Target = Android",
                EditorUserBuildSettings.activeBuildTarget == BuildTarget.Android ? St.Pass : St.Fail,
                EditorUserBuildSettings.activeBuildTarget.ToString()));

            var backend = PlayerSettings.GetScriptingBackend(NamedBuildTarget.Android);
            rows.Add(Make(g, "Scripting Backend = IL2CPP",
                backend == ScriptingImplementation.IL2CPP ? St.Pass : St.Fail, backend.ToString()));

            var arch = PlayerSettings.Android.targetArchitectures;
            rows.Add(Make(g, "架构含 ARM64 且不含 ARMv7",
                arch == AndroidArchitecture.ARM64 ? St.Pass : St.Fail, arch.ToString()));

            var apis = PlayerSettings.GetGraphicsAPIs(BuildTarget.Android);
            bool vulkan = apis.Length > 0 && apis[0] == GraphicsDeviceType.Vulkan;
            rows.Add(Make(g, "首选 Graphics API = Vulkan", vulkan ? St.Pass : St.Fail,
                string.Join(", ", apis)));

            rows.Add(Make(g, "Color Space = Linear",
                PlayerSettings.colorSpace == ColorSpace.Linear ? St.Pass : St.Fail,
                PlayerSettings.colorSpace.ToString()));

            // 立体渲染路径（属性名在不同版本可能变化，用反射读）
            string stereo = ReadStaticProperty(typeof(PlayerSettings), "stereoRenderingPath");
            rows.Add(Make(g, "立体渲染 = Single Pass Instanced",
                stereo == null ? St.Skip
                : (stereo.Contains("Instanced") || stereo == "SinglePass") ? St.Pass : St.Fail,
                stereo ?? "无法读取，请在 XR 设置中手动确认"));

            string pkg = PlayerSettings.GetApplicationIdentifier(NamedBuildTarget.Android);
            bool pkgOk = !string.IsNullOrEmpty(pkg)
                         && !pkg.StartsWith("com.DefaultCompany", StringComparison.Ordinal)
                         && !pkg.StartsWith("com.Company", StringComparison.Ordinal)
                         && pkg.Count(c => c == '.') >= 2;
            rows.Add(Make(g, "包名非默认值", pkgOk ? St.Pass : St.Fail, pkg));

            rows.Add(Make(g, "INTERNET 权限关闭（离线 Demo）",
                PlayerSettings.Android.forceInternetPermission ? St.Warn : St.Pass,
                PlayerSettings.Android.forceInternetPermission ? "已开启，评委可能质疑数据外传" : "已关闭"));

            int minSdk = (int)PlayerSettings.Android.minSdkVersion;
            rows.Add(Make(g, "minSdkVersion ≥ 29",
                minSdk >= 29 ? St.Pass : St.Warn, minSdk.ToString()));

            string astc = ReadStaticProperty(typeof(EditorUserBuildSettings), "androidBuildSubtarget");
            rows.Add(Make(g, "纹理压缩 = ASTC",
                astc == null ? St.Skip : astc == "ASTC" ? St.Pass : St.Warn, astc ?? "无法读取"));

            int msaa = QualitySettings.antiAliasing;
            rows.Add(Make(g, "MSAA ≥ 4x", msaa >= 4 ? St.Pass : St.Warn, msaa + "x"));
        }

        // ═════════════════════ 场景预算 ═════════════════════

        static void CheckScene(List<Row> rows)
        {
            const string g = "场景预算（当前打开的场景）";

            var lodGroups = Object.FindObjectsByType<LODGroup>(FindObjectsSortMode.None);
            var lod1Plus = new HashSet<Renderer>();
            foreach (var lg in lodGroups)
            {
                var lods = lg.GetLODs();
                for (int i = 1; i < lods.Length; i++)
                    foreach (var r in lods[i].renderers)
                        if (r != null) lod1Plus.Add(r);
            }

            var renderers = Object.FindObjectsByType<Renderer>(FindObjectsSortMode.None);
            long tris = 0;
            int drawCalls = 0;
            var materials = new HashSet<Material>();
            var perRoot = new Dictionary<string, long>();
            int holoPanels = 0;
            int shadowCasters = 0;

            foreach (var r in renderers)
            {
                if (r == null || !r.enabled || !r.gameObject.activeInHierarchy) continue;
                if (lod1Plus.Contains(r)) continue;                // LOD1+ 不参与渲染
                if (r is ParticleSystemRenderer) continue;

                Mesh m = null;
                var mf = r.GetComponent<MeshFilter>();
                if (mf != null) m = mf.sharedMesh;
                var smr = r as SkinnedMeshRenderer;
                if (smr != null) m = smr.sharedMesh;
                if (m == null) continue;

                long t = m.triangles.LongLength / 3L;
                tris += t;

                int sub = Mathf.Min(m.subMeshCount, Mathf.Max(1, r.sharedMaterials.Length));
                drawCalls += sub;

                foreach (var mat in r.sharedMaterials)
                    if (mat != null) materials.Add(mat);

                if (r.shadowCastingMode != ShadowCastingMode.Off) shadowCasters++;

                string rootName = TopRootName(r.transform);
                perRoot.TryGetValue(rootName, out long acc);
                perRoot[rootName] = acc + t;

                if (r.gameObject.name.IndexOf("HoloPanel", StringComparison.OrdinalIgnoreCase) >= 0)
                    holoPanels++;
            }

            rows.Add(Make(g, $"三角面 ≤ {TriBudget:N0}",
                tris <= TriBudget ? St.Pass : St.Fail, $"{tris:N0} 面"));

            rows.Add(Make(g, $"Draw Call 估算 ≤ {DrawCallBudget}",
                drawCalls <= DrawCallBudget ? St.Pass : drawCalls <= DrawCallBudget * 2 ? St.Warn : St.Fail,
                $"约 {drawCalls} 次（未计阴影与后处理 pass）"));

            rows.Add(Make(g, $"材质数 ≤ {MaterialBudget}",
                materials.Count <= MaterialBudget ? St.Pass : St.Warn, $"{materials.Count} 个"));

            rows.Add(Make(g, "阴影投射物体占比 < 40%",
                shadowCasters <= Mathf.Max(1, renderers.Length) * 0.4f ? St.Pass : St.Warn,
                $"{shadowCasters} / {renderers.Length}"));

            rows.Add(Make(g, $"全息面板 ≤ {HoloPanelBudget}",
                holoPanels == 0 ? St.Skip : holoPanels <= HoloPanelBudget ? St.Pass : St.Fail,
                holoPanels == 0 ? "场景内无 HoloPanel（未到 S3）" : $"{holoPanels} 块"));

            // 动态 RenderTexture（座舱中央那块）—— 按资产名粗筛
            string[] rtGuids = AssetDatabase.FindAssets("t:RenderTexture");
            rows.Add(Make(g, $"动态 RenderTexture ≤ {DynamicRtBudget}",
                rtGuids.Length <= DynamicRtBudget ? St.Pass : St.Warn,
                $"{rtGuids.Length} 个 RT 资产"));

            if (perRoot.Count > 0)
            {
                var sb = new StringBuilder();
                foreach (var kv in perRoot)
                    sb.Append($"{kv.Key}: {kv.Value:N0} 面　");
                rows.Add(Make(g, "面数分布（按根节点）", St.Skip, sb.ToString().TrimEnd()));
            }

            // 契约一致性：白盒是否与契约数值吻合
            var contract = AssetDatabase.LoadAssetAtPath<MechaContract>(MechaContract.AssetPath);
            if (contract == null)
            {
                rows.Add(Make(g, "契约资产存在", St.Skip, "尚未生成，运行「白盒/重建全部」即可创建"));
            }
            else
            {
                var issues = contract.Validate();
                rows.Add(Make(g, "契约自检", issues.Count == 0 ? St.Pass : St.Fail,
                    issues.Count == 0 ? "尺寸与挂点自洽" : string.Join("；", issues)));
            }
        }

        // ═════════════════════ XR 插件 ═════════════════════

        static void CheckXr(List<Row> rows)
        {
            const string g = "XR 插件";

            var loaders = ReadActiveLoaderNames();
            if (loaders == null)
            {
                rows.Add(Make(g, "XR Loader 已启用", St.Skip,
                    "无法自动读取，请到 Project Settings > XR Plug-in Management 勾选 OpenXR"));
                return;
            }

            bool openxr = false, pico = false;
            foreach (var n in loaders)
            {
                if (n.IndexOf("OpenXR", StringComparison.OrdinalIgnoreCase) >= 0) openxr = true;
                if (n.IndexOf("PICO", StringComparison.OrdinalIgnoreCase) >= 0 ||
                    n.IndexOf("Picoxr", StringComparison.OrdinalIgnoreCase) >= 0) pico = true;
            }

            rows.Add(Make(g, "OpenXR Loader 已启用", openxr ? St.Pass : St.Fail,
                loaders.Count == 0 ? "未启用任何 Loader" : string.Join(", ", loaders)));

            rows.Add(Make(g, "PICO / OpenXR 厂商插件", pico ? St.Pass : St.Warn,
                pico ? "已检测到 PICO 相关 Loader" : "未检测到 PICO Loader：请导入 PICO Unity OpenXR SDK 并在 OpenXR Feature 列表勾选 PICO"));
        }

        // ═════════════════════ 输出 ═════════════════════

        static void Report(List<Row> rows)
        {
            int pass = 0, warn = 0, fail = 0, skip = 0;
            var sb = new StringBuilder();
            sb.AppendLine("════════ PICO 比赛合规自检 ════════");
            sb.AppendLine($"Unity {Application.unityVersion}　场景：{UnityEngine.SceneManagement.SceneManager.GetActiveScene().name}");
            sb.AppendLine();

            string lastGroup = null;
            foreach (var r in rows)
            {
                if (r.Group != lastGroup)
                {
                    sb.AppendLine($"── {r.Group} ──");
                    lastGroup = r.Group;
                }

                string tag;
                switch (r.Status)
                {
                    case St.Pass: tag = "PASS"; pass++; break;
                    case St.Warn: tag = "WARN"; warn++; break;
                    case St.Fail: tag = "FAIL"; fail++; break;
                    default: tag = "SKIP"; skip++; break;
                }
                sb.AppendLine($"[{tag}] {r.Item}　→　{r.Detail}");
            }

            sb.AppendLine();
            sb.AppendLine($"合计：PASS {pass} / WARN {warn} / FAIL {fail} / SKIP {skip}");
            sb.AppendLine(fail > 0
                ? "结论：存在硬性不合规项，不可提交。"
                : warn > 0 ? "结论：硬性项通过，有优化建议，可提交但建议处理 WARN。"
                : "结论：全部通过。");

            if (fail > 0) Debug.LogError(sb.ToString());
            else if (warn > 0) Debug.LogWarning(sb.ToString());
            else Debug.Log(sb.ToString());

            WriteMarkdown(rows, pass, warn, fail, skip);

            EditorUtility.DisplayDialog("比赛合规自检",
                $"PASS {pass}　WARN {warn}　FAIL {fail}　SKIP {skip}\n\n" +
                (fail > 0 ? "存在 FAIL，不可提交。详情见 Console 与 Docs/合规自检报告.md"
                          : "硬性项已通过。详情见 Console 与 Docs/合规自检报告.md"),
                "好");
        }

        static void WriteMarkdown(List<Row> rows, int pass, int warn, int fail, int skip)
        {
            var sb = new StringBuilder();
            sb.AppendLine("# 比赛合规自检报告");
            sb.AppendLine();
            sb.AppendLine($"> 自动生成，勿手工编辑。Unity {Application.unityVersion}");
            sb.AppendLine($"> 合计：PASS {pass} / WARN {warn} / FAIL {fail} / SKIP {skip}");
            sb.AppendLine();
            sb.AppendLine("| 组 | 检查项 | 结果 | 实测值 |");
            sb.AppendLine("|---|---|---|---|");
            foreach (var r in rows)
            {
                string tag = r.Status == St.Pass ? "PASS" : r.Status == St.Warn ? "WARN"
                           : r.Status == St.Fail ? "FAIL" : "SKIP";
                sb.AppendLine($"| {r.Group} | {r.Item} | {tag} | {r.Detail.Replace("|", "\\|")} |");
            }

            string dir = Path.Combine(Application.dataPath, "../Docs");
            if (!Directory.Exists(dir)) Directory.CreateDirectory(dir);
            File.WriteAllText(Path.Combine(dir, "合规自检报告.md"), sb.ToString());
        }

        // ═════════════════════ 反射辅助 ═════════════════════

        static Row Make(string g, string item, St st, string detail)
        {
            return new Row { Group = g, Item = item, Status = st, Detail = detail };
        }

        static string TopRootName(Transform t)
        {
            while (t.parent != null) t = t.parent;
            return t.name;
        }

        static string ReadStaticProperty(Type t, string prop)
        {
            var p = t.GetProperty(prop, BindingFlags.Public | BindingFlags.Static);
            if (p == null) return null;
            try
            {
                var v = p.GetValue(null);
                return v?.ToString();
            }
            catch { return null; }
        }

        /// <summary>读取当前构建目标已启用的 XR Loader 名称；读不到返回 null。</summary>
        static List<string> ReadActiveLoaderNames()
        {
            try
            {
                string[] guids = AssetDatabase.FindAssets("XRGeneralSettingsPerBuildTarget");
                foreach (var guid in guids)
                {
                    string path = AssetDatabase.GUIDToAssetPath(guid);
                    var perTarget = AssetDatabase.LoadAssetAtPath<ScriptableObject>(path);
                    if (perTarget == null) continue;

                    var m = perTarget.GetType().GetMethod("SettingsForBuildTarget",
                        BindingFlags.Public | BindingFlags.Instance);
                    if (m == null) continue;

                    var settings = m.Invoke(perTarget, new object[] { BuildTargetGroup.Android });
                    if (settings == null) continue;

                    var managerProp = settings.GetType().GetProperty("Manager",
                        BindingFlags.Public | BindingFlags.Instance);
                    var manager = managerProp?.GetValue(settings);
                    if (manager == null) continue;

                    var loadersProp = manager.GetType().GetProperty("activeLoaders",
                        BindingFlags.Public | BindingFlags.Instance);
                    if (loadersProp?.GetValue(manager) is IEnumerable list)
                    {
                        var names = new List<string>();
                        foreach (var l in list)
                            if (l != null) names.Add(l.GetType().Name);
                        return names;
                    }
                }
            }
            catch (Exception e)
            {
                Debug.Log($"[SteelRidge] XR Loader 自动检测失败：{e.Message}");
            }
            return null;
        }
    }
}
