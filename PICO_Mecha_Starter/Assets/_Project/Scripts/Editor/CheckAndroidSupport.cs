// CheckAndroidSupport.cs — 让 Unity 自己回答「Android 构建目标到底可不可用」
//
// 为什么需要它
//   Unity 的 Android 模块装在 /Applications/Unity/PlaybackEngines/AndroidPlayer
//   （Unity.app 的兄弟目录），而不是 Unity.app/Contents/PlaybackEngines。
//   只看目录是否存在容易判断错，必须问引擎自己。
//
// 用法
//   Unity -batchmode -quit -projectPath <proj> \
//         -executeMethod SteelSpine.EditorTools.CheckAndroidSupport.Run -logFile -
//
// 退出码：Android 可用 = 0，不可用 = 1（便于脚本判断）

using System;
using System.IO;
using UnityEditor;
using UnityEngine;

namespace SteelSpine.EditorTools
{
    public static class CheckAndroidSupport
    {
        public static void Run()
        {
            bool supported = BuildPipeline.IsBuildTargetSupported(
                BuildTargetGroup.Android, BuildTarget.Android);

            Debug.Log("=== Android 支持检查 ===");
            Debug.Log("Unity 版本        : " + Application.unityVersion);
            Debug.Log("IsBuildTargetSupported(Android) : " + supported);

            // 工具链路径（SetAndroidToolchain 写入的 EditorPrefs）
            string sdk = EditorPrefs.GetString("AndroidSdkRoot", "(未设置)");
            string ndk = EditorPrefs.GetString("AndroidNdkRoot", "(未设置)");
            string jdk = EditorPrefs.GetString("JdkPath", "(未设置)");
            Debug.Log("AndroidSdkRoot    : " + sdk + " -> " + Directory.Exists(sdk + "/platforms"));
            Debug.Log("AndroidNdkRoot    : " + ndk + " -> " + Directory.Exists(ndk));
            Debug.Log("JdkPath           : " + jdk + " -> " + File.Exists(jdk + "/bin/java"));

            // Gradle 模板是 AndroidPlayer 的核心资产，缺了就无法出包
            // 模块装在 Unity.app 的兄弟目录，不是 Contents 下（这正是之前判断错的地方）
            string pe = "/Applications/Unity/PlaybackEngines/AndroidPlayer/Tools/GradleTemplates";
            Debug.Log("GradleTemplates   : " + pe + " -> " + Directory.Exists(pe));

            if (supported)
            {
                Debug.Log("✓ Android 构建目标可用");
                EditorApplication.Exit(0);
            }
            else
            {
                Debug.LogError("✗ Android 构建目标不可用");
                EditorApplication.Exit(1);
            }
        }
    }
}
