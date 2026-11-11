// BuildXrApk.cs — 生成 OpenXR 场景并出 APK（M1 底座验证）
//
// 目标（只验证底座，不做座舱）
//   ① 应用以 immersive 会话启动（不是 OS 里的一个平面窗口）
//   ② 双眼立体渲染（Single Pass Instanced）
//   ③ 头显姿态由 OpenXR 驱动（TrackedPoseDriver 绑定 <XRHMD>）
//   ④ 能看见 3D 内容（机体放在前方 30 m）
//
// 与 BuildAndroidApk 的分工
//   PlayerSettings 复用 BuildAndroidApk.ConfigurePlayer()，避免两套配置漂移；
//   本脚本只负责「XR 场景」与「输出路径」。
//
// 用法
//   Unity -batchmode -quit -projectPath <proj> -buildTarget Android \
//         -executeMethod SteelSpine.EditorTools.BuildXrApk.Run -logFile -

using System;
using System.IO;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.InputSystem.XR;
using UnityEngine.Rendering;

namespace SteelSpine.EditorTools
{
    public static class BuildXrApk
    {
        const string SceneDir = "Assets/_Project/Scenes/Build";
        const string ScenePath = SceneDir + "/SMOKE_01_OpenXR.unity";
        const string ModelPath = "Assets/_Project/Models/mecha_parts.fbx";
        const string OutDir = "out/android";
        const string OutApk = OutDir + "/SteelSpineXR.apk";

        const float MechaDistance = 30f;
        const float MechaHeight = 18.2f;

        public static void Run()
        {
            try
            {
                BuildAndroidApk.ConfigurePlayer();
                ConfigureXrPlayer();
                BuildScene();
                var ok = Build();
                EditorApplication.Exit(ok ? 0 : 1);
            }
            catch (Exception e)
            {
                Debug.LogError("[BuildXr] 异常: " + e);
                EditorApplication.Exit(1);
            }
        }

        /// <summary>OpenXR 相关的额外 PlayerSettings。</summary>
        static void ConfigureXrPlayer()
        {
            // 立体渲染模式由 OpenXR Package Settings 控制，这里只做断言式记录
            Debug.Log("[BuildXr] Active Input Handling = " +
                      (EditorPrefs.GetInt("ActiveInputHandler", -1)) +
                      "（2 = Both，需重启编辑器后生效）");
        }

        // ---------------- 场景 ----------------

        static void BuildScene()
        {
            if (!Directory.Exists(SceneDir)) Directory.CreateDirectory(SceneDir);

            var scene = UnityEditor.SceneManagement.EditorSceneManager
                .NewScene(UnityEditor.SceneManagement.NewSceneSetup.EmptyScene,
                          UnityEditor.SceneManagement.NewSceneMode.Single);

            // ---------- XR Origin ----------
            // 层级：XR Origin → Camera Offset → Main Camera(TrackedPoseDriver)
            // Camera Offset 用于"坐姿/站姿"的地面偏移；M1 阶段先为 0（由设备自身高度决定）。
            var origin = new GameObject("XR Origin");
            origin.transform.position = Vector3.zero;

            var offset = new GameObject("Camera Offset");
            offset.transform.SetParent(origin.transform, false);
            offset.transform.localPosition = Vector3.zero;

            var camGo = new GameObject("Main Camera");
            camGo.tag = "MainCamera";
            camGo.transform.SetParent(offset.transform, false);
            camGo.transform.localPosition = Vector3.zero;

            var cam = camGo.AddComponent<Camera>();
            cam.fieldOfView = 60f;
            cam.nearClipPlane = 0.05f;
            cam.farClipPlane = 500f;
            cam.clearFlags = CameraClearFlags.SolidColor;
            cam.backgroundColor = new Color(0.043f, 0.075f, 0.110f);
            // XR 下必须双眼渲染；这是"是否真的立体"的开关之一
            cam.stereoTargetEye = StereoTargetEyeMask.Both;

            camGo.AddComponent<AudioListener>();

            // TrackedPoseDriver：把相机位姿交给 OpenXR，不再由 Transform 手控
            var tpd = camGo.AddComponent<TrackedPoseDriver>();
            tpd.trackingType = TrackedPoseDriver.TrackingType.RotationAndPosition;
            tpd.updateType = TrackedPoseDriver.UpdateType.UpdateAndBeforeRender;

            var posAction = new InputAction("HeadPosition", InputActionType.Value,
                "<XRHMD>/centerEyePosition", null, null, "Vector3");
            var rotAction = new InputAction("HeadRotation", InputActionType.Value,
                "<XRHMD>/centerEyeRotation", null, null, "Quaternion");
            tpd.positionInput = new InputActionProperty(posAction);
            tpd.rotationInput = new InputActionProperty(rotAction);

            // ---------- 机体（放在前方，便于确认"看见的是 3D"）----------
            var fbx = AssetDatabase.LoadAssetAtPath<GameObject>(ModelPath);
            if (fbx != null)
            {
                var mecha = (GameObject)PrefabUtility.InstantiatePrefab(fbx);
                mecha.name = "MECH_ROOT";
                mecha.transform.position = new Vector3(0f, 0f, MechaDistance);
                // 正面朝 +Z，所以转 180° 让它面向观察者
                mecha.transform.rotation = Quaternion.Euler(0f, 180f, 0f);
                Debug.Log("[BuildXr] 机体放在 z=" + MechaDistance + " m，面向相机");
            }
            else
            {
                Debug.LogWarning("[BuildXr] 未找到模型，场景只放参照方块");
                var cube = GameObject.CreatePrimitive(PrimitiveType.Cube);
                cube.name = "MECH_ROOT";
                cube.transform.position = new Vector3(0f, MechaHeight * 0.5f, MechaDistance);
                cube.transform.localScale = new Vector3(6f, MechaHeight, 6f);
            }

            // ---------- 地面参照（无贴图也能感知深度）----------
            var ground = GameObject.CreatePrimitive(PrimitiveType.Plane);
            ground.name = "GROUND_Ref";
            ground.transform.position = new Vector3(0f, 0f, MechaDistance * 0.5f);
            ground.transform.localScale = new Vector3(8f, 1f, 8f);
            var gm = new Material(Shader.Find("Standard"));
            gm.color = new Color(0.16f, 0.19f, 0.24f);
            ground.GetComponent<Renderer>().sharedMaterial = gm;

            // ---------- 灯光 ----------
            var keyGo = new GameObject("LIGHT_Key");
            var key = keyGo.AddComponent<Light>();
            key.type = LightType.Directional;
            key.color = new Color(1f, 0.97f, 0.92f);
            key.intensity = 1.1f;
            keyGo.transform.rotation = Quaternion.Euler(38f, 152f, 0f);

            var rimGo = new GameObject("LIGHT_Rim");
            var rim = rimGo.AddComponent<Light>();
            rim.type = LightType.Directional;
            rim.color = new Color(0.55f, 0.72f, 1f);
            rim.intensity = 0.7f;
            rimGo.transform.rotation = Quaternion.Euler(16f, -50f, 0f);

            RenderSettings.ambientMode = AmbientMode.Flat;
            RenderSettings.ambientLight = new Color(0.20f, 0.24f, 0.30f);
            RenderSettings.fog = false;

            // 把 XR 状态打到场景里，设备上第一帧就能看到是否真的进了 XR
            var status = origin.AddComponent<SteelSpine.Render.XrStatus>();
            status.distanceHint = MechaDistance;

            UnityEditor.SceneManagement.EditorSceneManager.SaveScene(scene, ScenePath);
            AssetDatabase.Refresh();

            EditorBuildSettings.scenes = new[] { new EditorBuildSettingsScene(ScenePath, true) };
            Debug.Log("[BuildXr] 场景已生成 " + ScenePath);
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
            Debug.LogFormat("[BuildXr] 结果 {0}｜大小 {1:F1} MB｜耗时 {2:F1} s｜错误 {3}｜警告 {4}",
                            s.result, s.totalSize / 1048576f, s.totalTime.TotalSeconds,
                            s.totalErrors, s.totalWarnings);

            if (s.result != BuildResult.Succeeded)
            {
                Debug.LogError("[BuildXr] 构建失败");
                return false;
            }
            Debug.Log("[BuildXr] APK → " + Path.GetFullPath(OutApk));
            return true;
        }
    }
}
