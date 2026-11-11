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

            // 2026-11-11：URP 生效后 Shader.Find("Standard") 仍能返回 shader，
            // 但 Standard 不在 URP 的着色器集合里 —— 跑起来是整片洋红（已知症状）。
            // ① 按当前管线选 shader；② 颜色按属性名分流（Standard 认 _Color，URP/Lit 认 _BaseColor）；
            // ③ 材质必须落成**真实资产**：编辑器里 new 出来的 Material 没有资产路径，
            //    场景序列化时引用会丢，包里就变回默认材质。
            bool urp = GraphicsSettings.defaultRenderPipeline != null;
            var gm = EnsureGroundMaterial(urp);
            ground.GetComponent<Renderer>().sharedMaterial = gm;
            Debug.Log("[BuildXr] 地面材质 " + AssetDatabase.GetAssetPath(gm) +
                      "｜shader=" + (gm.shader != null ? gm.shader.name : "null") +
                      "｜管线=" + (urp ? "URP" : "Built-in"));

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

            // ---------- 平台装配根 ----------
            // 2026-11-11 发现：此前场景里**没有** PlatformBootstrap，于是 DisplayPolicy / SpatialAudio /
            // InputRouter / PerfBudgetEnforcer / TrackingQualityMonitor 全是躺着的类 ——
            // 输入路由写了却没人 Tick，审计报告里的 [OK]/[MISSING] 也从未在设备上出现过。
            // 放在最后创建：它 Awake 里要 FindAnyObjectByType 找相机与各策略组件，先有它们再找才成立。
            var bootGo = new GameObject("PLATFORM_Bootstrap");
            var boot = bootGo.AddComponent<SteelRidge.Core.Platform.PlatformBootstrap>();
            boot.viewpoint = camGo.transform;
            boot.cockpitRoot = null;   // 座舱（M4）落地后再指过去；为空时 ViewpointPolicy 自动跳过

            UnityEditor.SceneManagement.EditorSceneManager.SaveScene(scene, ScenePath);
            AssetDatabase.Refresh();

            EditorBuildSettings.scenes = new[] { new EditorBuildSettingsScene(ScenePath, true) };
            Debug.Log("[BuildXr] 场景已生成 " + ScenePath);
        }

        // ---------------- 地面材质 ----------------

        const string MaterialDir = "Assets/_Project/Materials";
        const string GroundMatPath = MaterialDir + "/GROUND_Ref_Mat.mat";

        /// <summary>
        /// 取或建地面材质资产。已存在时只校正 shader（管线切换后残留 Standard 也能自愈）。
        /// </summary>
        static Material EnsureGroundMaterial(bool urp)
        {
            if (!AssetDatabase.IsValidFolder(MaterialDir))
                AssetDatabase.CreateFolder("Assets/_Project", "Materials");

            var shader = urp
                ? Shader.Find("Universal Render Pipeline/Lit")
                : Shader.Find("Standard");
            if (shader == null) shader = Shader.Find("Standard");

            var m = AssetDatabase.LoadAssetAtPath<Material>(GroundMatPath);
            if (m == null)
            {
                m = new Material(shader) { name = "GROUND_Ref_Mat" };
                AssetDatabase.CreateAsset(m, GroundMatPath);
            }
            else if (m.shader != shader)
            {
                m.shader = shader;
            }

            var color = new Color(0.16f, 0.19f, 0.24f);
            if (m.HasProperty("_BaseColor")) m.SetColor("_BaseColor", color);
            if (m.HasProperty("_Color")) m.SetColor("_Color", color);
            if (m.HasProperty("_Smoothness")) m.SetFloat("_Smoothness", 0.25f);
            if (m.HasProperty("_Glossiness")) m.SetFloat("_Glossiness", 0.25f);
            EditorUtility.SetDirty(m);
            AssetDatabase.SaveAssets();
            return m;
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
