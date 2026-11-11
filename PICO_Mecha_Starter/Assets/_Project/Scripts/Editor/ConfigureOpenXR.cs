// ConfigureOpenXR.cs — 一次性把工程的 OpenXR 底座配好（幂等，可反复跑）
//
// 为什么用脚本而不是点菜单
//   项目要在 CI / 无头环境可复现，点菜单无法脚本化；而且 XR 设置分散在
//   三个资产里（XRGeneralSettingsPerBuildTarget / OpenXR Package Settings / OpenXRFeature enable 位），
//   手点容易漏。
//
// 做的事（顺序有依赖，不能乱）
//   1. 创建 XRGeneralSettingsPerBuildTarget 与 Android 的 XRGeneralSettings
//   2. 给 Android 指定 OpenXR Loader（UnityEngine.XR.OpenXR.OpenXRLoader）
//   3. 刷新并启用 PICO 的两个必需 Feature：
//        com.unity.openxr.feature.pico      （PICO Support）
//        com.unity.openxr.pico.features     （PICO Extensions）
//   4. 把 Active Input Handling 设为 Both（Input System 需要；旧 Input 也保留，避免老脚本全挂）
//   5. 打印全部结果，便于核对
//
// 用法
//   Unity -batchmode -quit -projectPath <proj> -buildTarget Android \
//         -executeMethod SteelSpine.EditorTools.ConfigureOpenXR.Run -logFile -

using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.XR.Management;
using UnityEditor.XR.Management.Metadata;
using UnityEditor.XR.OpenXR.Features;
using UnityEngine;
using UnityEngine.XR.Management;
using UnityEngine.XR.OpenXR;
using UnityEngine.XR.OpenXR.Features;

namespace SteelSpine.EditorTools
{
    public static class ConfigureOpenXR
    {
        const string LoaderTypeName = "UnityEngine.XR.OpenXR.OpenXRLoader";
        const string SettingsDir = "Assets/XR/Settings";
        const string PerTargetAsset = SettingsDir + "/XRGeneralSettingsPerBuildTarget.asset";

        // PICO 插件里写死的两个 FeatureId（见 Runtime/PICOFeature.cs 与 Runtime/Features/OpenXRExtensions.cs）
        static readonly string[] PicoRequiredFeatures =
        {
            "com.unity.openxr.feature.pico",
            "com.unity.openxr.pico.features",
        };

        public static void Run()
        {
            EnsurePerTargetSettings();
            var general = GetOrCreateAndroidSettings();
            AssignLoader(general);
            EnablePicoFeatures();
            SetInputHandling();
            Report(general);
        }

        // ---- 1. XRGeneralSettingsPerBuildTarget ----

        static void EnsurePerTargetSettings()
        {
            if (!Directory.Exists(SettingsDir)) Directory.CreateDirectory(SettingsDir);

            if (EditorBuildSettings.TryGetConfigObject(XRGeneralSettings.settingsKey,
                    out XRGeneralSettingsPerBuildTarget existing) && existing != null)
            {
                Debug.Log("[OpenXR] 已有 XRGeneralSettingsPerBuildTarget：" +
                          AssetDatabase.GetAssetPath(existing));
                return;
            }

            var asset = ScriptableObject.CreateInstance<XRGeneralSettingsPerBuildTarget>();
            AssetDatabase.CreateAsset(asset, PerTargetAsset);
            EditorBuildSettings.AddConfigObject(XRGeneralSettings.settingsKey, asset, true);
            AssetDatabase.SaveAssets();
            Debug.Log("[OpenXR] 已创建 " + PerTargetAsset);
        }

        // ---- 2. Android 的 XRGeneralSettings ----

        static XRGeneralSettings GetOrCreateAndroidSettings()
        {
            var perTarget = AssetDatabase.LoadAssetAtPath<XRGeneralSettingsPerBuildTarget>(PerTargetAsset);
            if (perTarget == null)
            {
                EditorBuildSettings.TryGetConfigObject(XRGeneralSettings.settingsKey,
                    out perTarget);
            }
            if (perTarget == null)
            {
                Debug.LogError("[OpenXR] 拿不到 XRGeneralSettingsPerBuildTarget");
                return null;
            }

            // 这是静态方法（不依赖 perTarget 实例），不能写成 perTarget.
            var general = XRGeneralSettingsPerBuildTarget.XRGeneralSettingsForBuildTarget(BuildTargetGroup.Android);
            if (general == null)
            {
                general = ScriptableObject.CreateInstance<XRGeneralSettings>();
                general.name = "Android Settings";
                general.Manager = ScriptableObject.CreateInstance<XRManagerSettings>();
                general.Manager.name = "Android XR Manager";
                AssetDatabase.AddObjectToAsset(general, perTarget);
                AssetDatabase.AddObjectToAsset(general.Manager, perTarget);
                perTarget.SetSettingsForBuildTarget(BuildTargetGroup.Android, general);
                EditorUtility.SetDirty(perTarget);
                AssetDatabase.SaveAssets();
                Debug.Log("[OpenXR] 已为 Android 创建 XRGeneralSettings");
            }

            general.InitManagerOnStart = true;
            EditorUtility.SetDirty(general);
            return general;
        }

        // ---- 3. 指定 OpenXR Loader ----

        static void AssignLoader(XRGeneralSettings general)
        {
            if (general?.Manager == null)
            {
                Debug.LogError("[OpenXR] Manager 为空，无法指定 Loader");
                return;
            }

            bool ok = XRPackageMetadataStore.AssignLoader(
                general.Manager, LoaderTypeName, BuildTargetGroup.Android);

            Debug.Log("[OpenXR] AssignLoader(" + LoaderTypeName + ") = " + ok);

            var names = string.Join(", ", general.Manager.activeLoaders
                .Select(l => l == null ? "(null)" : l.GetType().Name));
            Debug.Log("[OpenXR] 当前 Android 的 loaders: " + names);

            EditorUtility.SetDirty(general.Manager);
            AssetDatabase.SaveAssets();
        }

        // ---- 4. 启用 PICO Feature ----

        static void EnablePicoFeatures()
        {
            // FeatureHelpers.RefreshFeatures 会确保 OpenXR 的包设置资产存在
            // （其内部调用 internal 的 OpenXRPackageSettings.GetOrCreateInstance，
            //   我们直接调不到，所以靠这一步代替）
            FeatureHelpers.RefreshFeatures(BuildTargetGroup.Android);
            var s = OpenXRSettings.GetSettingsForBuildTargetGroup(BuildTargetGroup.Android);
            Debug.Log("[OpenXR] OpenXR Package Settings 就绪: " + (s != null));

            foreach (var id in PicoRequiredFeatures)
            {
                var f = FeatureHelpers.GetFeatureWithIdForBuildTarget(BuildTargetGroup.Android, id);
                if (f == null)
                {
                    Debug.LogError("[OpenXR] 找不到 Feature: " + id);
                    continue;
                }
                f.enabled = true;
                EditorUtility.SetDirty(f);
                Debug.Log("[OpenXR] 已启用 Feature: " + id + "  (" + f.GetType().Name + ")");
            }

            // ---- 交互 Profile ----
            // PICO 的构建校验规则（Runtime/PICOFeature.cs:67）要求：
            //   ① 至少启用一个 PICO 手柄 Profile；
            //   ② 且不能同时启用其它厂商 Profile（否则报 "Only the PICO Touch Interaction Profile..."）。
            // 这里按 id 前缀统一裁决，避免手点遗漏。
            var s2 = OpenXRSettings.GetSettingsForBuildTargetGroup(BuildTargetGroup.Android);
            if (s2 != null)
            {
                foreach (var f in s2.GetFeatures<OpenXRInteractionFeature>())
                {
                    if (f == null) continue;
                    // featureId 是 internal 字段，取不到；按类型名判定。
                    // PICO 的四个 Profile：PICO4ControllerProfile / PICO4UltraControllerProfile
                    //                        / PICONeo3ControllerProfile / PICOG3ControllerProfile
                    string typeName = f.GetType().Name;
                    bool isPico = typeName.StartsWith("PICO");
                    if (f.enabled != isPico)
                    {
                        f.enabled = isPico;
                        EditorUtility.SetDirty(f);
                    }
                    if (isPico || f.enabled)
                        Debug.Log("[OpenXR] 交互 Profile " + (isPico ? "启用" : "关闭") + ": " + typeName);
                }
            }

            AssetDatabase.SaveAssets();
        }

        // ---- 5. Active Input Handling ----

        static void SetInputHandling()
        {
            var assets = AssetDatabase.LoadAllAssetsAtPath("ProjectSettings/ProjectSettings.asset");
            if (assets == null || assets.Length == 0)
            {
                Debug.LogWarning("[OpenXR] 读不到 ProjectSettings.asset");
                return;
            }
            var so = new SerializedObject(assets[0]);
            var p = so.FindProperty("activeInputHandler");
            if (p == null)
            {
                Debug.LogWarning("[OpenXR] 找不到 activeInputHandler 属性");
                return;
            }
            if (p.intValue != 2)
            {
                Debug.Log("[OpenXR] activeInputHandler: " + p.intValue + " → 2 (Both)");
                p.intValue = 2;
                so.ApplyModifiedProperties();
                AssetDatabase.SaveAssets();
            }
            else
            {
                Debug.Log("[OpenXR] activeInputHandler 已是 2 (Both)");
            }
        }

        // ---- 6. 汇总 ----

        static void Report(XRGeneralSettings general)
        {
            var s = OpenXRSettings.GetSettingsForBuildTargetGroup(BuildTargetGroup.Android);
            Debug.Log("[OpenXR] === 汇总 ===");
            Debug.Log("[OpenXR] OpenXRSettings 存在: " + (s != null));
            if (s != null)
            {
                Debug.Log("[OpenXR] renderMode = " + s.renderMode +
                          "  depthSubmissionMode = " + s.depthSubmissionMode +
                          "  foveatedRenderingApi = " + s.foveatedRenderingApi);
            }
            Debug.Log("[OpenXR] Manager InitManagerOnStart = " + (general != null && general.InitManagerOnStart));
        }
    }
}
