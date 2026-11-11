// SetAndroidTools.cs — 在 Unity 进程内写入 Android 外部工具路径
//
// 为什么需要它
//   batchmode 构建时报 "UnityException: JDK not found"，但 ~/.local/jdk/jdk11 明明完好
//   （Contents/Home/bin/java 可执行）。用 defaults write 改 plist 之后仍然失败，
//   说明 Unity 读 EditorPrefs 的时机/缓存与外部写入不同步。
//   在 Unity 进程内部用 EditorPrefs.SetString 写入，再由下一次进程读，才能保证格式与键名一致。
//
// 用法
//   Unity -batchmode -quit -projectPath <proj> -executeMethod SteelSpine.EditorTools.SetAndroidTools.Run

using System;
using UnityEditor;
using UnityEngine;

namespace SteelSpine.EditorTools
{
    public static class SetAndroidTools
    {
        const string Jdk = "/Users/zhukeyi/.local/jdk/jdk11";
        const string Sdk = "/Users/zhukeyi/Library/Android/sdk";
        const string Ndk = "/Users/zhukeyi/Library/Android/sdk/ndk/23.1.7779620";

        public static void Run()
        {
            // Unity 2022.3 使用的键（AndroidBuildTools）
            EditorPrefs.SetString("JdkPath", Jdk);
            EditorPrefs.SetString("SdkPath", Sdk);
            EditorPrefs.SetString("NdkPath", Ndk);
            EditorPrefs.SetBool("JdkUseEmbedded", false);
            EditorPrefs.SetBool("SdkUseEmbedded", false);
            EditorPrefs.SetBool("NdkUseEmbedded", false);

            // 旧式全大写键，一并写入避免版本差异
            EditorPrefs.SetString("AndroidJDKRoot", Jdk);
            EditorPrefs.SetString("AndroidSDKRoot", Sdk);
            EditorPrefs.SetString("AndroidNDKRoot", Ndk);
            EditorPrefs.SetString("AndroidSdkRoot", Sdk);

            Debug.Log("[SetAndroidTools] JdkPath=" + EditorPrefs.GetString("JdkPath", "")
                      + " exists=" + System.IO.Directory.Exists(Jdk));

            WriteExternalToolsAsset();

            EditorApplication.Exit(0);
        }

        /// <summary>
        /// 真正起作用的是项目级 ScriptableSingleton —— 它存在才读这些路径。
        /// 这里直接把它创建出来并写入三个属性（属性名由反射确认：
        /// jdkRootPath / sdkRootPath / ndkRootPath）。
        ///
        /// 实测（2026-11-11）：该类并非可脚本化的 ScriptableObject，
        /// ScriptableObject.CreateInstance 返回 null，此路不通。
        /// 真正有效的是给 Unity 进程传 JAVA_HOME / ANDROID_SDK_ROOT /
        /// ANDROID_NDK_ROOT 环境变量 —— 见 scripts/build_xr.sh。
        /// 本方法保留仅作诊断，失败不阻断。
        /// </summary>
        static void WriteExternalToolsAsset()
        {
            try
            {
                TryWriteExternalToolsAsset();
            }
            catch (System.Exception e)
            {
                Debug.LogWarning("[SetAndroidTools] 写 AndroidExternalToolsSettings 失败（已知，不影响）：" + e.GetType().Name);
            }
        }

        static void TryWriteExternalToolsAsset()
        {
            const string assetPath = "ProjectSettings/AndroidExternalToolsSettings.asset";
            var type = FindType("UnityEditor.Android.AndroidExternalToolsSettings");
            if (type == null) { Debug.LogError("[SetAndroidTools] 找不到 AndroidExternalToolsSettings"); return; }

            var existing = AssetDatabase.LoadAssetAtPath<ScriptableObject>(assetPath);
            var so = existing;
            if (so == null)
            {
                so = ScriptableObject.CreateInstance(type);
                AssetDatabase.CreateAsset(so, assetPath);
                Debug.Log("[SetAndroidTools] 已创建 " + assetPath);
            }

            Set(so, "jdkRootPath", Jdk);
            Set(so, "sdkRootPath", Sdk);
            Set(so, "ndkRootPath", Ndk);

            EditorUtility.SetDirty(so);
            AssetDatabase.SaveAssets();
            AssetDatabase.Refresh();

            Debug.Log("[SetAndroidTools] asset 写入后 jdkRootPath=" + Get(so, "jdkRootPath"));
        }

        static void Set(object o, string prop, string value)
        {
            var p = o.GetType().GetProperty(prop,
                System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.NonPublic |
                System.Reflection.BindingFlags.Instance);
            if (p != null && p.CanWrite) { p.SetValue(o, value); Debug.Log("[SetAndroidTools] set " + prop + " = " + value); }
            else Debug.LogError("[SetAndroidTools] 无法写入 " + prop);
        }

        static string Get(object o, string prop)
        {
            var p = o.GetType().GetProperty(prop,
                System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.NonPublic |
                System.Reflection.BindingFlags.Instance);
            return p == null ? "?" : (p.GetValue(o) ?? "null").ToString();
        }

        static System.Type FindType(string fullName)
        {
            foreach (var asm in System.AppDomain.CurrentDomain.GetAssemblies())
            {
                var t = asm.GetType(fullName, false);
                if (t != null) return t;
            }
            try { return System.Reflection.Assembly.Load("UnityEditor.Android.Extensions").GetType(fullName); }
            catch { return null; }
        }
    }
}
