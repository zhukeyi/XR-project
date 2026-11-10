// SetAndroidToolchain.cs — 用命令行把 Android SDK / NDK / JDK 路径写进 Unity 偏好
//
// 为什么需要它
//   Unity 的 Android 工具链路径存在 EditorPrefs（每用户），没有 CLI 参数可设。
//   无头构建前必须先写一次，否则 Gradle 会报「找不到 Android SDK」。
//
// 用法
//   Unity -batchmode -quit -projectPath <proj> \
//         -executeMethod SteelSpine.EditorTools.SetAndroidToolchain.Apply
//
// 路径可用环境变量覆盖：UNITY_ANDROID_SDK / UNITY_ANDROID_NDK / UNITY_ANDROID_JDK

using System;
using UnityEditor;
using UnityEngine;

namespace SteelSpine.EditorTools
{
    public static class SetAndroidToolchain
    {
        static string Env(string key, string fallback)
        {
            var v = Environment.GetEnvironmentVariable(key);
            return string.IsNullOrEmpty(v) ? fallback : v;
        }

        public static void Apply()
        {
            string home = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
            string sdk = Env("UNITY_ANDROID_SDK", home + "/Library/Android/sdk");
            string ndk = Env("UNITY_ANDROID_NDK", sdk + "/ndk/23.1.7779620");
            // ★ JDK 必须 11（2022.3 不认 17），且要传 bundle 根，Unity 自己补 Contents/Home
            string jdk = Env("UNITY_ANDROID_JDK", home + "/.local/jdk/jdk11");

            EditorPrefs.SetString("AndroidSDKRoot", sdk);   // ★ 全大写缩写，Unity 真正读取的键名
            EditorPrefs.SetString("AndroidNDKRoot", ndk);   // ★ 同上
            EditorPrefs.SetString("JdkPath", jdk);
            // 关掉「用 Hub 内置工具链」的偏好，强制用上面三条
            EditorPrefs.SetBool("AndroidUseEmbeddedSdk", false);
            EditorPrefs.SetBool("AndroidUseEmbeddedNdk", false);
            EditorPrefs.SetBool("AndroidUseEmbeddedJdk", false);

            bool okSdk = System.IO.Directory.Exists(sdk + "/platforms");
            bool okNdk = System.IO.Directory.Exists(ndk);
            bool okJdk = System.IO.File.Exists(jdk + "/bin/java");
            Debug.Log("[SetAndroidToolchain] SDK=" + sdk + " -> " + okSdk
                      + " | NDK=" + ndk + " -> " + okNdk
                      + " | JDK=" + jdk + " -> " + okJdk);
            if (!okSdk) Debug.LogError("[SetAndroidToolchain] Android SDK 路径无效");
            if (!okJdk) Debug.LogError("[SetAndroidToolchain] JDK 路径无效");
            // NDK 只有 IL2CPP / 原生插件才必需，Mono 构建可缺省，故只告警
            if (!okNdk) Debug.LogWarning("[SetAndroidToolchain] NDK 缺失（Mono 构建可忽略）");
        }
    }
}
