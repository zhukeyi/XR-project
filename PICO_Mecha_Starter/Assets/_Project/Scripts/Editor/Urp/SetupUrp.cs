// SetupUrp.cs — 把工程从 Built-in 切到 URP 14
//
// 为什么整个文件包在 #if URP_14_OR_NEWER 里
//   URP 包不存在时，任何引用 UnityEngine.Rendering.Universal 的代码都会让整个工程编译失败。
//   同目录的 SteelSpine.Editor.Urp.asmdef 用 versionDefines 在「包存在且 >= 14.0.0」时
//   自动定义 URP_14_OR_NEWER，因此 URP 未装时本文件等价于空文件，工程照常编译。
//
// 它做三件事，顺序不能换
//   ① 把 FBX 内嵌材质**提取**为外部 .mat（AssetDatabase.ExtractAsset），
//      否则每次 BuildScene 重建场景都会退回内嵌材质，转换结果白做；
//   ② 把这些 .mat 从 Standard 转到 Universal Render Pipeline/Lit；
//   ③ 创建 URP Asset + Renderer Data，挂到 GraphicsSettings 与 QualitySettings。
//
// 用法
//   Unity -batchmode -quit -projectPath <proj> \
//         -executeMethod SteelSpine.EditorTools.Urp.SetupUrp.Run -logFile -
//
// 注意
//   URP Asset 必须同时设 GraphicsSettings.defaultRenderPipeline 与 QualitySettings.renderPipeline，
//   只设前者时，Quality 档位会覆盖回 Built-in，表现为「切换没生效」。

#if URP_14_OR_NEWER

using System.IO;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;

namespace SteelSpine.EditorTools.Urp
{
    public static class SetupUrp
    {
        const string SettingsDir = "Assets/_Project/Settings";
        const string AssetPath = SettingsDir + "/URP_Asset.asset";
        const string RendererPath = SettingsDir + "/URP_Renderer.asset";
        const string MaterialDir = "Assets/_Project/Materials";
        const string FbxPath = "Assets/_Project/Models/mecha_parts.fbx";

        public static void Run()
        {
            try
            {
                EnsureFolder("Assets/_Project", "Settings");
                EnsureFolder("Assets/_Project", "Materials");

                int converted = EnsureUrpMaterials();
                var asset = CreatePipelineAsset();
                ApplyGlobals(asset);

                AssetDatabase.SaveAssets();
                AssetDatabase.Refresh();

                Debug.Log("[SetupUrp] 完成：转换材质 " + converted + " 个，管线 " + asset.name);
                EditorApplication.Exit(0);
            }
            catch (System.Exception e)
            {
                Debug.LogError("[SetupUrp] 异常: " + e);
                EditorApplication.Exit(1);
            }
        }

        // ---------------- ① 材质统一到 URP/Lit ----------------

        /// <summary>
        /// 把「外部 .mat」与「模型内嵌材质」两路一起过一遍，凡不是 URP/Lit 的就地转换。
        ///
        /// 为什么不再提取内嵌材质为外部 .mat（2026-11-11 改）
        ///   原版走 AssetDatabase.ExtractAsset，但实测 242 个 Renderer 的 11 个材质
        ///   全部满足 AssetDatabase.Contains(m) == true（内嵌子资产也算"已在资产库内"），
        ///   于是被 continue 静默跳过 —— 返回 0、零条日志，看起来像"模型没有材质"，实为误判。
        ///   更要紧的是：URP 成为默认管线后，模型重新导入时导入器**直接生成 URP/Lit 内嵌材质**
        ///   （实测 ArmorBlue/FrameDark 等 11 个全部如此），提取这一步本就没有必要。
        ///   外部 .mat 的价值只剩「可版本化管理调参」，留给 M2 做材质分级时再启用。
        /// </summary>
        static int EnsureUrpMaterials()
        {
            var urpLit = Shader.Find("Universal Render Pipeline/Lit");
            if (urpLit == null)
            {
                Debug.LogError("[SetupUrp] 找不到 Universal Render Pipeline/Lit shader，URP 可能未正确安装");
                return 0;
            }

            var targets = new System.Collections.Generic.List<Material>();
            var seen = new System.Collections.Generic.HashSet<int>();

            // ① 外部 .mat
            foreach (var guid in AssetDatabase.FindAssets("t:Material", new[] { MaterialDir }))
            {
                var m = AssetDatabase.LoadAssetAtPath<Material>(AssetDatabase.GUIDToAssetPath(guid));
                if (m != null && seen.Add(m.GetInstanceID())) targets.Add(m);
            }
            int external = targets.Count;

            // ② 模型内嵌材质
            var fbx = AssetDatabase.LoadAssetAtPath<GameObject>(FbxPath);
            int embedded = 0;
            if (fbx == null)
            {
                Debug.LogWarning("[SetupUrp] 找不到 FBX：" + FbxPath + "，只处理外部材质");
            }
            else
            {
                foreach (var r in fbx.GetComponentsInChildren<Renderer>(true))
                {
                    foreach (var m in r.sharedMaterials)
                    {
                        if (m == null) continue;
                        if (seen.Add(m.GetInstanceID())) { targets.Add(m); embedded++; }
                    }
                }
            }

            Debug.Log("[SetupUrp] 待检查材质：外部 " + external + " 个 + 内嵌 " + embedded + " 个");

            int ok = 0, converted = 0, failed = 0;
            foreach (var m in targets)
            {
                if (m.shader == urpLit) { ok++; continue; }
                try
                {
                    ConvertOne(m, urpLit);
                    converted++;
                    Debug.Log("[SetupUrp] 已转 URP/Lit：" + m.name + "（原 " + (m.shader != null ? m.shader.name : "null") + "）");
                }
                catch (System.Exception e)
                {
                    failed++;
                    Debug.LogWarning("[SetupUrp] 转换失败 " + m.name + "：" + e.Message);
                }
            }

            Debug.Log("[SetupUrp] 材质检查结果：已是 URP/Lit " + ok + " 个，本次转换 " + converted
                      + " 个，失败 " + failed + " 个");
            return converted;
        }

        /// <summary>
        /// 单个材质 Standard → URP/Lit，保留颜色/贴图/金属度，并补一点自发光。
        /// 属性名映射是这段的关键：Standard 用 _Color/_MainTex/_Glossiness，
        /// URP/Lit 用 _BaseColor/_BaseMap/_Smoothness，直接换 shader 会丢色。
        /// </summary>
        static void ConvertOne(Material m, Shader urpLit)
        {
            Color baseColor = Color.white;
            if (m.HasProperty("_Color")) baseColor = m.GetColor("_Color");
            else if (m.HasProperty("_BaseColor")) baseColor = m.GetColor("_BaseColor");

            Texture tex = null;
            if (m.HasProperty("_MainTex")) tex = m.GetTexture("_MainTex");
            else if (m.HasProperty("_BaseMap")) tex = m.GetTexture("_BaseMap");

            float smooth = m.HasProperty("_Glossiness") ? m.GetFloat("_Glossiness") : 0.35f;
            float metal = m.HasProperty("_Metallic") ? m.GetFloat("_Metallic") : 0.55f;

            m.shader = urpLit;
            m.SetColor("_BaseColor", baseColor);
            if (tex != null) m.SetTexture("_BaseMap", tex);
            m.SetFloat("_Smoothness", smooth);
            m.SetFloat("_Metallic", metal);

            // 全息座舱的基础自发光：暗部不死黑，机甲边缘有微光
            m.EnableKeyword("_EMISSION");
            m.SetColor("_EmissionColor", baseColor * 0.18f);
            m.globalIlluminationFlags = MaterialGlobalIlluminationFlags.RealtimeEmissive;

            EditorUtility.SetDirty(m);
        }

        // ---------------- ③ 创建并挂载管线 ----------------

        static UniversalRenderPipelineAsset CreatePipelineAsset()
        {
            var existing = AssetDatabase.LoadAssetAtPath<UniversalRenderPipelineAsset>(AssetPath);
            if (existing != null)
            {
                TuneAsset(existing);
                EditorUtility.SetDirty(existing);
                return existing;
            }

            var rendererData = ScriptableObject.CreateInstance<UniversalRendererData>();
            rendererData.name = "URP_Renderer";
            AssetDatabase.CreateAsset(rendererData, RendererPath);

            var asset = UniversalRenderPipelineAsset.Create(rendererData);
            asset.name = "URP_Asset";
            AssetDatabase.CreateAsset(asset, AssetPath);

            TuneAsset(asset);
            EditorUtility.SetDirty(asset);
            return asset;
        }

        /// <summary>
        /// VR 取向的参数：MSAA 4x、关 HDR（省带宽）、关闭开销大的阴影级联。
        /// 这些值是 M2 起步基线，后面按真机帧率再调。
        /// 注意 supportsSoftShadows 不在这里设 —— 它是 internal set，见 ApplyGlobals 的说明。
        /// </summary>
        static void TuneAsset(UniversalRenderPipelineAsset a)
        {
            a.msaaSampleCount = 4;
            a.renderScale = 1.0f;
            a.supportsHDR = false;
            a.supportsCameraDepthTexture = false;
            a.supportsCameraOpaqueTexture = false;
            a.shadowDistance = 25f;
            a.shadowCascadeCount = 1;
        }

        static void ApplyGlobals(UniversalRenderPipelineAsset asset)
        {
            // 两处都要设，否则 Quality 档位会覆盖回 Built-in
            GraphicsSettings.defaultRenderPipeline = asset;
            QualitySettings.renderPipeline = asset;

            // URP 14 的 supportsSoftShadows 是「public get + internal set」，
            // 外部程序集赋值会直接 CS0200 编译失败（实测）。
            // 只能改底层序列化字段 m_SoftShadowsSupported。
            // 为什么非要关：MSAA 4x 与 PCF 软阴影叠加在移动 GPU 上实测吃掉 3–4 ms，
            // 而座舱内景的阴影只有机甲自遮挡一路，硬阴影视觉差异极小。
            var so = new SerializedObject(asset);
            var soft = so.FindProperty("m_SoftShadowsSupported");
            if (soft != null)
            {
                soft.boolValue = false;
                so.ApplyModifiedPropertiesWithoutUndo();
                Debug.Log("[SetupUrp] 软阴影已关闭（m_SoftShadowsSupported=false）");
            }
            else
            {
                Debug.LogWarning("[SetupUrp] 未找到 m_SoftShadowsSupported 字段，软阴影保持默认开");
            }

            Debug.Log("[SetupUrp] 已挂载管线到 GraphicsSettings + QualitySettings");
        }

        // ---------------- 诊断（只读，不改工程） ----------------

        /// <summary>
        /// 探针：把 FBX 里的 Renderer / 材质真实情况打出来。
        /// 为什么要它：ExtractEmbeddedMaterials 返回 0 且有 0 条日志，
        /// 说明循环体一次都没进 —— 但「renderer 为 0」还是「sharedMaterials 为空」
        /// 是两种完全不同的病因，必须实测而不是猜。
        /// </summary>
        public static void Probe()
        {
            var fbx = AssetDatabase.LoadAssetAtPath<GameObject>(FbxPath);
            Debug.Log("[Probe] fbx null? " + (fbx == null) + "  path=" + FbxPath);
            if (fbx == null) { EditorApplication.Exit(2); return; }

            var rs = fbx.GetComponentsInChildren<Renderer>(true);
            Debug.Log("[Probe] Renderer 数量 = " + rs.Length);

            int nullMat = 0;
            var names = new System.Collections.Generic.List<string>();
            foreach (var r in rs)
            {
                var ms = r.sharedMaterials;
                Debug.Log("[Probe]   " + r.name + " | mats=" + ms.Length);
                foreach (var m in ms)
                {
                    if (m == null) { nullMat++; continue; }
                    string key = m.name + "|shader=" + (m.shader != null ? m.shader.name : "null")
                               + "|inAsset=" + AssetDatabase.Contains(m);
                    if (!names.Contains(key)) names.Add(key);
                }
            }
            Debug.Log("[Probe] null 材质槽 = " + nullMat);
            foreach (var k in names) Debug.Log("[Probe] MAT " + k);

            // 子资产路径：材质若真是内嵌子资产，这里能列出
            var all = AssetDatabase.LoadAllAssetsAtPath(FbxPath);
            Debug.Log("[Probe] LoadAllAssetsAtPath 数量 = " + all.Length);
            foreach (var o in all)
                if (o is Material) Debug.Log("[Probe] SUBMAT " + o.name + " type=" + o.GetType().Name);
            foreach (var o in all)
                if (o is Mesh) Debug.Log("[Probe] SUBMESH " + o.name);

            EditorApplication.Exit(0);
        }

        // ---------------- 工具 ----------------

        static void EnsureFolder(string parent, string child)
        {
            if (!AssetDatabase.IsValidFolder(parent + "/" + child))
                AssetDatabase.CreateFolder(parent, child);
        }

        static string SafeName(string raw)
        {
            if (string.IsNullOrEmpty(raw)) return "Material";
            var sb = new System.Text.StringBuilder(raw.Length);
            foreach (var c in raw)
                sb.Append(char.IsLetterOrDigit(c) || c == '_' || c == '-' ? c : '_');
            return sb.ToString();
        }
    }
}
#endif
