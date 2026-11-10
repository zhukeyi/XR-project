// BuildAndroidApk.cs — 无头构建 Android APK（链路验证用）
//
// 为什么需要它
//   本机 Unity 是手动安装的，`unity install-modules` 拒绝管理模块；
//   而 GUI 点 Build 无法自动化。要可复现地验证「Unity → APK」，只能走 batchmode
//   + BuildPipeline.BuildPlayer。
//
// 用法
//   Unity -batchmode -quit -projectPath <proj> -buildTarget Android \
//         -executeMethod SteelSpine.EditorTools.BuildAndroidApk.Run -logFile -
//
// 产物
//   out/android/SteelSpine.apk
//
// 退出码：成功 0，失败 1
//
// 两个踩过的坑（都写在此处，避免下次重犯）
//   ① Renderer.bounds 在对象刚实例化、尚未渲染时是陈旧/不完整的值。
//      用它做尺度校正在实测中得出「原高 9.591 m」，于是错误地放大 1.8976 倍；
//      而真实顶点包围盒是 H=18.200 m（正确）。→ 一律按顶点算。
//   ② 只写 PlayerSettings.Android.targetArchitectures 还不够，
//      首次构建前必须先读回确认；为 0（None）时 BuildPlayer 会抛
//      「Target architecture not specified」。

using System;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEngine;
using UnityEngine.Rendering;

namespace SteelSpine.EditorTools
{
    public static class BuildAndroidApk
    {
        const string SceneDir = "Assets/_Project/Scenes/Build";
        const string ScenePath = SceneDir + "/SMOKE_00_Boot.unity";
        const string ModelPath = "Assets/_Project/Models/mecha_parts.fbx";
        const string OutDir = "out/android";
        const string OutApk = OutDir + "/SteelSpine.apk";

        /// <summary>契约总高（m）。仅用于校验偏差，不用于强行缩放。</summary>
        const float ContractHeight = 18.2f;

        public static void Run()
        {
            try
            {
                ConfigurePlayer();
                BuildScene();
                var ok = Build();
                EditorApplication.Exit(ok ? 0 : 1);
            }
            catch (Exception e)
            {
                Debug.LogError("[BuildApk] 异常: " + e);
                EditorApplication.Exit(1);
            }
        }

        // ---------------- Player Settings ----------------

        static void ConfigurePlayer()
        {
            if (EditorUserBuildSettings.activeBuildTarget != BuildTarget.Android)
            {
                bool switched = EditorUserBuildSettings.SwitchActiveBuildTarget(
                    BuildTargetGroup.Android, BuildTarget.Android);
                Debug.Log("[BuildApk] 切换构建目标 → Android: " + switched);
            }

            PlayerSettings.companyName = "SteelRidge";
            PlayerSettings.productName = "Steel Spine";
            PlayerSettings.bundleVersion = "0.1.0";
            PlayerSettings.SetApplicationIdentifier(
                BuildTargetGroup.Android, "com.steelspine.smoke");

            // ★ 必须 IL2CPP。实测依据：模拟器 abilist 只有 arm64-v8a（无 32 位），
            //   而 Unity 的 Mono 后端不支持 Android ARM64 —— 写 ARM64 后
            //   BuildPlayer 会抛「Target architecture not specified」。
            //   所以只能 IL2CPP + ARM64，这也正是比赛正式版该用的组合。
            PlayerSettings.SetScriptingBackend(
                BuildTargetGroup.Android, ScriptingImplementation.IL2CPP);
            PlayerSettings.SetIl2CppCompilerConfiguration(
                BuildTargetGroup.Android, Il2CppCompilerConfiguration.Release);
            PlayerSettings.SetApiCompatibilityLevel(
                BuildTargetGroup.Android, ApiCompatibilityLevel.NET_Standard_2_0);

            // 架构必须非 None，否则 BuildPlayer 直接抛异常
            PlayerSettings.Android.targetArchitectures = AndroidArchitecture.ARM64;
            if (PlayerSettings.Android.targetArchitectures == AndroidArchitecture.None)
            {
                Debug.LogWarning("[BuildApk] 架构写入未生效，改用 SerializedObject 兜底");
                var so = new SerializedObject(AssetDatabase.LoadAllAssetsAtPath(
                    "ProjectSettings/ProjectSettings.asset")[0]);
                var p = so.FindProperty("AndroidTargetArchitectures");
                if (p != null) { p.intValue = (int)AndroidArchitecture.ARM64; so.ApplyModifiedProperties(); }
            }
            Debug.Log("[BuildApk] targetArchitectures 读回 = " +
                      PlayerSettings.Android.targetArchitectures);

            PlayerSettings.Android.minSdkVersion = AndroidSdkVersions.AndroidApiLevel29;
            PlayerSettings.Android.targetSdkVersion = AndroidSdkVersions.AndroidApiLevelAuto;
            PlayerSettings.Android.bundleVersionCode = 1;
            PlayerSettings.Android.forceInternetPermission = false;

            PlayerSettings.defaultInterfaceOrientation = UIOrientation.LandscapeLeft;

            // ★ 只留 GLES3。模拟器 GPU 是 SwiftShader 软件实现，Vulkan 不可靠；
            //   Unity 默认把 Vulkan 排在前面，会导致黑屏。
            PlayerSettings.SetUseDefaultGraphicsAPIs(BuildTarget.Android, false);
            PlayerSettings.SetGraphicsAPIs(
                BuildTarget.Android, new[] { GraphicsDeviceType.OpenGLES3 });

            PlayerSettings.SetMobileMTRendering(BuildTargetGroup.Android, false);

            EditorUserBuildSettings.buildAppBundle = false;
            EditorUserBuildSettings.androidBuildSubtarget = MobileTextureSubtarget.Generic;

            string ndk = EditorPrefs.GetString("AndroidNDKRoot", "");
            Debug.Log("[BuildApk] PlayerSettings 已配置：IL2CPP / ARM64 / GLES3 / minSdk 29 / 横屏");
            Debug.Log("[BuildApk] NDK = " + ndk + " -> " + Directory.Exists(ndk));
        }

        // ---------------- 场景 ----------------

        static void BuildScene()
        {
            if (!Directory.Exists(SceneDir)) Directory.CreateDirectory(SceneDir);

            var scene = UnityEditor.SceneManagement.EditorSceneManager
                .NewScene(UnityEditor.SceneManagement.NewSceneSetup.EmptyScene,
                          UnityEditor.SceneManagement.NewSceneMode.Single);

            // ★ 轴向处理原则：**不改资产、不抹姿态**。
            //   实测过程：FBX 的 GlobalSettings 声明 UpAxis=Y，但 Blender 侧导出时
            //   bake_space_transform=False，几何实际仍是 Z-up；Unity 据此在**根节点**挂
            //   一个 -90°X 的轴向旋转来校正。谁把这个旋转抹掉，机体就躺倒。
            //   而下面两行代码恰好都会抹掉它：
            //     ① mecha.transform.rotation = Quaternion.identity;
            //     ② Turntable 每帧写 transform.localRotation = Euler(0, yaw, 0)
            //   所以这里改成「外层偏航 + 内层保留原姿态」，两者都不再冲突。
            //   同时把 bakeAxisConversion 关掉，回到 ProbeBuildEnv 实测为 H=18.200 的原始状态。
            var imp = AssetImporter.GetAtPath(ModelPath) as ModelImporter;
            if (imp != null && imp.bakeAxisConversion)
            {
                imp.bakeAxisConversion = false;
                imp.SaveAndReimport();
                AssetDatabase.Refresh();
                Debug.Log("[BuildApk] 已关闭 bakeAxisConversion（保持资产原始轴向，由根节点旋转校正）");
            }

            // 外层：只负责绕世界 Y 偏航
            var yawRoot = new GameObject("MECH_YAW");
            yawRoot.transform.position = Vector3.zero;
            yawRoot.transform.rotation = Quaternion.identity;

            GameObject mecha;
            var fbx = AssetDatabase.LoadAssetAtPath<GameObject>(ModelPath);
            if (fbx == null)
            {
                Debug.LogWarning("[BuildApk] 未找到模型 " + ModelPath + "，场景只放参照方块");
                mecha = GameObject.CreatePrimitive(PrimitiveType.Cube);
                mecha.name = "MECH_ROOT";
                mecha.transform.localScale = new Vector3(6f, ContractHeight, 6f);
                mecha.transform.position = new Vector3(0f, ContractHeight * 0.5f, 0f);
                mecha.transform.SetParent(yawRoot.transform, false);
                mecha.transform.position = new Vector3(0f, ContractHeight * 0.5f, 0f);
            }
            else
            {
                mecha = (GameObject)PrefabUtility.InstantiatePrefab(fbx);
                mecha.name = "MECH_ROOT";
                // ★ 只改位置与父级，**绝不写 rotation**：根节点上的轴向旋转是机体的立姿来源。
                mecha.transform.SetParent(yawRoot.transform, false);
                mecha.transform.localPosition = Vector3.zero;
                Debug.Log("[BuildApk] 机体根节点旋转（保持原样）= " +
                          mecha.transform.localEulerAngles.ToString("F2"));
            }

            var spin = yawRoot.AddComponent<SteelSpine.Render.Turntable>();
            spin.degreesPerSecond = 10f;

            // --- 相机取景 ---
            // ★ 取景一律用确定常量，不用运行时测量值。
            //   实测：批处理下 Renderer.bounds 与顶点矩阵在实例化后都会滞后，
            //   曾读出「H 9.59 / D 18.20」（把深度当成了高度），据此取景会裁头。
            //   下面这组数字来自 ProbeBuildEnv 的实测：W 6.471 / H 18.200 / D 9.564，中心 y=9.10。
            Physics.SyncTransforms();
            var measured = CombinedBounds(yawRoot);
            Debug.LogFormat("[BuildApk] 交叉校验（仅记录，不参与取景）：W {0:F2} H {1:F2} D {2:F2}",
                            measured.size.x, measured.size.y, measured.size.z);

            var b = new Bounds(new Vector3(0f, ContractHeight * 0.5f, 0f),
                               new Vector3(6.471f, ContractHeight, 9.564f));
            var camGo = new GameObject("CAM_Main");
            var cam = camGo.AddComponent<Camera>();
            camGo.tag = "MainCamera";
            cam.fieldOfView = 40f;
            cam.nearClipPlane = 0.3f;
            cam.farClipPlane = 500f;
            cam.clearFlags = CameraClearFlags.SolidColor;
            cam.backgroundColor = new Color(0.043f, 0.075f, 0.110f);

            // 机体正面朝 +Z（FBX 声明 FrontAxis=Z），相机站 +Z 侧回看。
            // dist 使机体占画面高度约 80%：可见高 = 2·d·tan(fov/2) = 1.24·h
            float h = Mathf.Max(b.size.y, 1f);
            float dist = (h * 0.62f) / Mathf.Tan(Mathf.Deg2Rad * cam.fieldOfView * 0.5f);
            Vector3 target = b.center;
            camGo.transform.position = target + new Vector3(0f, 0f, dist);
            camGo.transform.LookAt(target);

            // --- 灯光 ---
            var keyGo = new GameObject("LIGHT_Key");
            var key = keyGo.AddComponent<Light>();
            key.type = LightType.Directional;
            key.color = new Color(1f, 0.97f, 0.92f);
            key.intensity = 1.15f;
            keyGo.transform.rotation = Quaternion.Euler(42f, 148f, 0f);

            var rimGo = new GameObject("LIGHT_Rim");
            var rim = rimGo.AddComponent<Light>();
            rim.type = LightType.Directional;
            rim.color = new Color(0.55f, 0.72f, 1f);
            rim.intensity = 0.75f;
            rimGo.transform.rotation = Quaternion.Euler(18f, -46f, 0f);

            RenderSettings.ambientMode = AmbientMode.Flat;
            RenderSettings.ambientLight = new Color(0.20f, 0.24f, 0.30f);
            RenderSettings.fog = false;

            UnityEditor.SceneManagement.EditorSceneManager.SaveScene(scene, ScenePath);
            AssetDatabase.Refresh();

            EditorBuildSettings.scenes = new[]
            {
                new EditorBuildSettingsScene(ScenePath, true),
            };

            Debug.LogFormat("[BuildApk] 场景已生成 {0}；包围盒 W {1:F2} H {2:F2} D {3:F2}；相机距 {4:F2}",
                            ScenePath, b.size.x, b.size.y, b.size.z, dist);
        }

        /// <summary>合并子物体 Renderer 的世界包围盒（调用前先 Physics.SyncTransforms）。</summary>
        static Bounds CombinedBounds(GameObject root)
        {
            var rs = root.GetComponentsInChildren<Renderer>();
            if (rs.Length == 0) return new Bounds(root.transform.position, Vector3.one);
            var b = rs[0].bounds;
            for (int i = 1; i < rs.Length; i++) b.Encapsulate(rs[i].bounds);
            return b;
        }

        // ---------------- 构建 ----------------

        static bool Build()
        {
            if (!Directory.Exists(OutDir)) Directory.CreateDirectory(OutDir);
            if (File.Exists(OutApk)) File.Delete(OutApk);

            var opts = new BuildPlayerOptions
            {
                scenes = new[] { ScenePath },
                locationPathName = OutApk,
                target = BuildTarget.Android,
                targetGroup = BuildTargetGroup.Android,
                options = BuildOptions.None,
            };

            var report = BuildPipeline.BuildPlayer(opts);
            var s = report.summary;

            Debug.LogFormat("[BuildApk] 结果 {0}｜大小 {1:F1} MB｜耗时 {2:F1} s｜错误 {3}｜警告 {4}",
                            s.result, s.totalSize / 1048576f, s.totalTime.TotalSeconds,
                            s.totalErrors, s.totalWarnings);

            if (s.result != BuildResult.Succeeded)
            {
                Debug.LogError("[BuildApk] 构建失败，详见上方 BuildPipeline 日志");
                return false;
            }

            Debug.Log("[BuildApk] APK → " + Path.GetFullPath(OutApk));
            return true;
        }
    }
}
