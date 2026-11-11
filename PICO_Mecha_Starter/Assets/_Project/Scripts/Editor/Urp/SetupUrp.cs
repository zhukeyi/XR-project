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

                int extracted = ExtractEmbeddedMaterials();
                int converted = ConvertAllMaterials();
                var asset = CreatePipelineAsset();
                ApplyGlobals(asset);

                AssetDatabase.SaveAssets();
                AssetDatabase.Refresh();

                Debug.Log("[SetupUrp] 完成：提取材质 " + extracted + " 个，转换 " + converted
                          + " 个，管线 " + asset.name);
                EditorApplication.Exit(0);
            }
            catch (System.Exception e)
            {
                Debug.LogError("[SetupUrp] 异常: " + e);
                EditorApplication.Exit(1);
            }
        }

        // ---------------- ① 提取 FBX 内嵌材质 ----------------

        static int ExtractEmbeddedMaterials()
        {
            var fbx = AssetDatabase.LoadAssetAtPath<GameObject>(FbxPath);
            if (fbx == null)
            {
                Debug.LogWarning("[SetupUrp] 找不到 FBX：" + FbxPath + "，跳过提取");
                return 0;
            }

            int n = 0;
            var seen = new System.Collections.Generic.HashSet<int>();

            foreach (var r in fbx.GetComponentsInChildren<Renderer>(true))
            {
                foreach (var m in r.sharedMaterials)
                {
                    if (m == null) continue;
                    if (!seen.Add(m.GetInstanceID())) continue;
                    // 已经是外部资产（不在 .fbx 包内）就跳过
                    if (AssetDatabase.Contains(m)) continue;

                    string path = MaterialDir + "/" + SafeName(m.name) + ".mat";
                    if (File.Exists(path)) continue;

                    var err = AssetDatabase.ExtractAsset(m, path);
                    if (!string.IsNullOrEmpty(err))
                        Debug.LogWarning("[SetupUrp] 提取失败 " + m.name + "：" + err);
                    else
                    {
                        n++;
                        Debug.Log("[SetupUrp] 已提取材质 → " + path);
                    }
                }
            }

            if (n > 0) AssetDatabase.Refresh();
            return n;
        }

        // ---------------- ② Standard → URP/Lit ----------------

        static int ConvertAllMaterials()
        {
            var urpLit = Shader.Find("Universal Render Pipeline/Lit");
            if (urpLit == null)
            {
                Debug.LogError("[SetupUrp] 找不到 Universal Render Pipeline/Lit shader，URP 可能未正确安装");
                return 0;
            }

            int n = 0;
            foreach (var guid in AssetDatabase.FindAssets("t:Material", new[] { MaterialDir }))
            {
                var path = AssetDatabase.GUIDToAssetPath(guid);
                var m = AssetDatabase.LoadAssetAtPath<Material>(path);
                if (m == null || m.shader == urpLit) continue;

                // 保留原颜色/贴图/金属度，只换 shader 并做属性名映射
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
                n++;
            }

            Debug.Log("[SetupUrp] 材质转换 " + n + " 个");
            return n;
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
            a.supportsSoftShadows = false;
        }

        static void ApplyGlobals(UniversalRenderPipelineAsset asset)
        {
            // 两处都要设，否则 Quality 档位会覆盖回 Built-in
            GraphicsSettings.defaultRenderPipeline = asset;
            QualitySettings.renderPipeline = asset;
            Debug.Log("[SetupUrp] 已挂载管线到 GraphicsSettings + QualitySettings");
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
