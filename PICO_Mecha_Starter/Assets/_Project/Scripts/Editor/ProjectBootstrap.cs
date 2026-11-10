using System;
using System.Collections.Generic;
using System.Reflection;
using SteelRidge.Core;
using UnityEditor;
using UnityEditor.Build;
using UnityEngine;
using UnityEngine.Rendering;

namespace SteelRidge.EditorTools
{
    /// <summary>
    /// 一键把工程配置成 PICO 比赛要求的构型。
    /// 依据：PICO OpenXR 赛道（最佳沉浸内容创作）硬性要求 + 90Hz 性能预算。
    /// 说明：本脚本只改「能自动改的」。XR 插件勾选、PICO SDK 导入需手动，见 README 第 3 节。
    /// </summary>
    public static class ProjectBootstrap
    {
        public const string PackageName = "com.steelridge.ground";
        public const string ProductName = "钢脊：立于大地";
        public const string CompanyName = "SteelRidge";

        [MenuItem("Steel Ridge/工程/一键配置（Android + IL2CPP + Vulkan + Linear）", false, 10)]
        public static void Apply()
        {
            var changed = new List<string>();

            // 1. 切平台
            if (EditorUserBuildSettings.activeBuildTarget != BuildTarget.Android)
            {
                if (!EditorUserBuildSettings.SwitchActiveBuildTarget(BuildTargetGroup.Android, BuildTarget.Android))
                {
                    EditorUtility.DisplayDialog("切换失败",
                        "无法切换到 Android 平台。请先在 Build Settings 里安装 Android Build Support（含 SDK/NDK/JDK）。",
                        "知道了");
                    return;
                }
                changed.Add("Build Target → Android");
            }

            // 2. 脚本后端 / API 兼容 / 剥离 / 编译器
            PlayerSettings.SetScriptingBackend(NamedBuildTarget.Android, ScriptingImplementation.IL2CPP);
            PlayerSettings.SetApiCompatibilityLevel(NamedBuildTarget.Android, ApiCompatibilityLevel.NET_Standard);
            PlayerSettings.SetIl2CppCompilerConfiguration(NamedBuildTarget.Android, Il2CppCompilerConfiguration.Release);
            PlayerSettings.SetManagedStrippingLevel(NamedBuildTarget.Android, ManagedStrippingLevel.Medium);
            changed.Add("IL2CPP + .NET Standard + Release + 剥离 Medium");

            // 3. 架构：只要 ARM64
            PlayerSettings.Android.targetArchitectures = AndroidArchitecture.ARM64;
            changed.Add("架构 → ARM64（单架构可减包体、避免 32 位兼容问题）");

            // 4. 图形 API：只要 Vulkan，且不用默认列表
            PlayerSettings.SetUseDefaultGraphicsAPIs(BuildTarget.Android, false);
            PlayerSettings.SetGraphicsAPIs(BuildTarget.Android, new[] { GraphicsDeviceType.Vulkan });
            changed.Add("Graphics API → Vulkan（OpenXR 下必选，GLES 会丢 Single Pass Instanced）");

            // 5. 色彩空间
            PlayerSettings.colorSpace = ColorSpace.Linear;
            changed.Add("Color Space → Linear（不做线性会整体发灰，视觉分直接掉）");

            // 6. 包名 / 产品名 / 版本
            PlayerSettings.SetApplicationIdentifier(NamedBuildTarget.Android, PackageName);
            PlayerSettings.productName = ProductName;
            PlayerSettings.companyName = CompanyName;
            PlayerSettings.bundleVersion = "0.1.0";
            changed.Add($"包名 → {PackageName}");

            // 7. 权限：比赛为离线 Demo，不要联网权限
            PlayerSettings.Android.forceInternetPermission = false;
            PlayerSettings.Android.forceSDCardPermission = false;
            changed.Add("关闭 INTERNET / SDCard 权限（离线 Demo，避免评委质疑隐私）");

            // 8. SDK 级别
            PlayerSettings.Android.minSdkVersion = AndroidSdkVersions.AndroidApiLevel29;
            PlayerSettings.Android.targetSdkVersion = AndroidSdkVersions.AndroidApiLevelAuto;
            changed.Add("minSdk 29 / targetSdk Auto");

            // 9. 移动端渲染开关
            PlayerSettings.SetMobileMTRendering(NamedBuildTarget.Android, true);
            PlayerSettings.gpuSkinning = true;
            PlayerSettings.Android.androidIsGame = false;
            changed.Add("多线程渲染 + GPU Skinning 开启；androidIsGame = false");

            // 10. 纹理压缩（ASTC，PICO 全系支持）
            bool astc = TrySetStaticProperty(
                typeof(EditorUserBuildSettings), "androidBuildSubtarget",
                ResolveEnum("UnityEditor.MobileTextureSubtarget, UnityEditor", "ASTC"));
            changed.Add(astc ? "纹理压缩 → ASTC" : "纹理压缩 → 需在 Build Settings 手动设为 ASTC");

            // 11. 立体渲染路径：Single Pass Instanced
            bool spi = TrySetStaticProperty(
                typeof(PlayerSettings), "stereoRenderingPath",
                ResolveEnum("UnityEditor.StereoRenderingPath, UnityEditor", "Instanced"));
            changed.Add(spi ? "立体渲染 → Single Pass Instanced" : "立体渲染 → 需在 XR 设置里手动设 Single Pass Instanced");

            // 12. 质量档
            QualitySettings.antiAliasing = 4;
            QualitySettings.vSyncCount = 0;
            changed.Add("MSAA 4x / vSync 关（90Hz 靠 XR 层提帧）");

            AssetDatabase.SaveAssets();

            Debug.Log("[SteelRidge] 工程配置完成：\n• " + string.Join("\n• ", changed));
            EditorUtility.DisplayDialog("工程配置完成",
                "已应用 " + changed.Count + " 项：\n\n• " + string.Join("\n• ", changed) +
                "\n\n仍需手动完成两项（见 README 第 3 节）：\n" +
                "1) 导入 PICO Unity OpenXR SDK 并在 XR Plug-in Management 勾选 OpenXR\n" +
                "2) Project Validation 里点 Fix All",
                "好");
        }

        [MenuItem("Steel Ridge/工程/打印当前配置（体检用）", false, 11)]
        public static void PrintCurrent()
        {
            var sb = new System.Text.StringBuilder();
            sb.AppendLine("=== 当前工程配置 ===");
            sb.AppendLine($"BuildTarget            : {EditorUserBuildSettings.activeBuildTarget}");
            sb.AppendLine($"ScriptingBackend       : {PlayerSettings.GetScriptingBackend(NamedBuildTarget.Android)}");
            sb.AppendLine($"ApiCompatibilityLevel  : {PlayerSettings.GetApiCompatibilityLevel(NamedBuildTarget.Android)}");
            sb.AppendLine($"Architectures          : {PlayerSettings.Android.targetArchitectures}");
            sb.AppendLine($"GraphicsAPIs(Android)  : {string.Join(", ", PlayerSettings.GetGraphicsAPIs(BuildTarget.Android))}");
            sb.AppendLine($"ColorSpace             : {PlayerSettings.colorSpace}");
            sb.AppendLine($"PackageName            : {PlayerSettings.GetApplicationIdentifier(NamedBuildTarget.Android)}");
            sb.AppendLine($"forceInternetPermission: {PlayerSettings.Android.forceInternetPermission}");
            sb.AppendLine($"minSdk / targetSdk     : {PlayerSettings.Android.minSdkVersion} / {PlayerSettings.Android.targetSdkVersion}");
            sb.AppendLine($"MSAA                   : {QualitySettings.antiAliasing}x");
            sb.AppendLine($"Unity 版本             : {Application.unityVersion}");
            Debug.Log(sb.ToString());
        }

        // ── 反射工具：避免不同 Unity 版本属性改名导致整个编辑器程序集编译失败 ──

        static object ResolveEnum(string typeName, string member)
        {
            var t = Type.GetType(typeName);
            if (t == null || !t.IsEnum) return null;
            try { return Enum.Parse(t, member); } catch { return null; }
        }

        static bool TrySetStaticProperty(Type t, string prop, object value)
        {
            if (t == null || value == null) return false;
            var p = t.GetProperty(prop, BindingFlags.Public | BindingFlags.Static);
            if (p == null || !p.CanWrite || !p.PropertyType.IsInstanceOfType(value)) return false;
            try { p.SetValue(null, value); return true; }
            catch { return false; }
        }

        [MenuItem("Steel Ridge/工程/打开契约资产", false, 12)]
        public static void SelectContract()
        {
            var c = SteelRidgeBlockout.EnsureContract();
            if (c != null) Selection.activeObject = c;
        }
    }
}
