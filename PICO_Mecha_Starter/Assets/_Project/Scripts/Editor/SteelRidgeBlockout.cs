using System.Collections.Generic;
using System.IO;
using SteelRidge.Core;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace SteelRidge.EditorTools
{
    /// <summary>
    /// 白盒生成器。菜单「Steel Ridge/白盒/*」。
    /// 只依赖 MechaContract，不依赖任何外部美术资源 —— 因此美术未到位时也能开工。
    /// 生成结果全部可重建（幂等）：重复执行会先删除同名根节点再重建。
    /// </summary>
    public static class SteelRidgeBlockout
    {
        const string RootName = "MECH_ROOT";
        const string GroundScenePath = "Assets/_Project/Scenes/Blockout/Blockout_00_Ground.unity";
        const string CockpitScenePath = "Assets/_Project/Scenes/Blockout/Blockout_01_Cockpit.unity";

        static Material _armor, _grey, _interactive, _hazard, _holo, _site;

        // ═════════════════════════ 菜单 ═════════════════════════

        [MenuItem("Steel Ridge/白盒/重建全部（地面序章 + 座舱内构）", false, 0)]
        public static void RebuildAll()
        {
            var c = EnsureContract();
            if (c == null) return;

            var issues = c.Validate();
            if (issues.Count > 0)
            {
                string msg = "契约自检未通过，已中止重建：\n\n• " + string.Join("\n• ", issues);
                Debug.LogError("[SteelRidge] " + msg);
                EditorUtility.DisplayDialog("契约自检未通过", msg, "去修契约");
                return;
            }

            if (!EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo()) return;

            BuildGroundScene(c);
            BuildCockpitScene(c);

            EditorUtility.DisplayDialog(
                "白盒重建完成",
                $"已生成：\n• {GroundScenePath}\n• {CockpitScenePath}\n\n" +
                $"整机 {c.totalHeight:F2} m / 肩宽 {c.shoulderWidth:F2} m / 眼位 {c.SeatAnchorWorldY:F2} m\n" +
                "下一步：菜单 Steel Ridge/合规/运行比赛合规自检",
                "好");

            AssetDatabase.Refresh();
        }

        [MenuItem("Steel Ridge/白盒/只重建当前场景内的机体", false, 1)]
        public static void RebuildMechaInCurrentScene()
        {
            var c = EnsureContract();
            if (c == null) return;

            var scene = SceneManager.GetActiveScene();
            foreach (var go in scene.GetRootGameObjects())
                if (go.name == RootName) Object.DestroyImmediate(go);

            BuildMecha(c, null);
            EditorSceneManager.MarkSceneDirty(scene);
            Debug.Log($"[SteelRidge] 机体白盒已重建（{c.parts.Count} 个分件 / {c.sockets.Count} 个挂点）");
        }

        [MenuItem("Steel Ridge/白盒/删除场景内的机体", false, 2)]
        public static void RemoveMechaInCurrentScene()
        {
            var scene = SceneManager.GetActiveScene();
            foreach (var go in scene.GetRootGameObjects())
                if (go.name == RootName) Object.DestroyImmediate(go);
            EditorSceneManager.MarkSceneDirty(scene);
        }

        // ═════════════════════════ 场景 ═════════════════════════

        static void BuildGroundScene(MechaContract c)
        {
            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);

            BuildSite("SITE_GROUND", c);
            var mecha = BuildMecha(c, null);

            // 评审机位：1.7 m 眼高、25 m 距离，仰角约 21°（看向 11.4 m 座舱）
            var camGo = new GameObject("CAM_Review");
            var cam = camGo.AddComponent<Camera>();
            cam.fieldOfView = 60f;
            cam.nearClipPlane = 0.05f;
            cam.farClipPlane = 600f;
            camGo.tag = "MainCamera";
            camGo.transform.position = new Vector3(0f, 1.70f, 25f);
            camGo.transform.LookAt(new Vector3(0f, c.CockpitCenterY, 0f));

            var marker = new GameObject("VIEWPOINT_25M（1.7m 眼高）");
            marker.transform.position = new Vector3(0f, 1.70f, 25f);

            var key = new GameObject("LIGHT_Key").AddComponent<Light>();
            key.type = LightType.Directional;
            key.intensity = 1.1f;
            key.color = new Color(1f, 0.98f, 0.94f);
            key.transform.rotation = Quaternion.Euler(48f, -32f, 0f);

            var rim = new GameObject("LIGHT_Rim").AddComponent<Light>();
            rim.type = LightType.Directional;
            rim.intensity = 0.35f;
            rim.color = new Color(0.62f, 0.76f, 1f);
            rim.transform.rotation = Quaternion.Euler(24f, 150f, 0f);

            EnsureFolder(Path.GetDirectoryName(GroundScenePath));
            EditorSceneManager.SaveScene(scene, GroundScenePath);
            Debug.Log($"[SteelRidge] 已保存 {GroundScenePath}；机体顶点（分件 {c.parts.Count} 个）");
            if (mecha != null) Selection.activeGameObject = mecha;
        }

        static void BuildCockpitScene(MechaContract c)
        {
            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);

            var mecha = BuildMecha(c, null);

            // 座舱内打光：暖色天顶光模拟全息投影的漫反射
            var l = new GameObject("LIGHT_Cockpit").AddComponent<Light>();
            l.type = LightType.Point;
            l.range = 4f;
            l.intensity = 1.6f;
            l.color = new Color(0.72f, 0.88f, 1f);
            l.transform.position = new Vector3(0f, c.CockpitCeilingY - 0.15f, 0f);

            // 评审机位直接放在 SeatAnchor 上 —— 所见即玩家所见
            var seat = FindDeep(mecha.transform, "SeatAnchor");
            var camGo = new GameObject("CAM_SeatAnchor（玩家眼位）");
            var cam = camGo.AddComponent<Camera>();
            cam.fieldOfView = 95f;
            cam.nearClipPlane = 0.03f;
            cam.farClipPlane = 600f;
            camGo.tag = "MainCamera";
            if (seat != null)
            {
                camGo.transform.position = seat.position;
                camGo.transform.rotation = seat.rotation;
            }
            else
            {
                camGo.transform.position = new Vector3(0f, c.SeatAnchorWorldY, c.eyeForwardOffset);
            }

            EnsureFolder(Path.GetDirectoryName(CockpitScenePath));
            EditorSceneManager.SaveScene(scene, CockpitScenePath);
            Debug.Log($"[SteelRidge] 已保存 {CockpitScenePath}；眼位 {c.SeatAnchorWorldY:F2} m，主仪表距眼 {c.dashNear:F2}–{c.dashFar:F2} m");
        }

        // ═════════════════════════ 机体 ═════════════════════════

        static GameObject BuildMecha(MechaContract c, Transform parent)
        {
            var root = new GameObject(RootName);
            root.transform.SetParent(parent, false);

            var art = new GameObject("ArtRoot").transform;
            art.SetParent(root.transform, false);

            var sockets = new GameObject("Sockets").transform;
            sockets.SetParent(root.transform, false);

            // 碰撞代理独立节点，未来换真模型时整体替换，不动 ArtRoot
            var collision = new GameObject("Collision").transform;
            collision.SetParent(root.transform, false);

            // ── 1. 竖向分层分件 ──
            foreach (var p in c.parts)
            {
                if (p.mirrored)
                {
                    Box(art, $"BLK_{p.id}_L", new Vector3(-p.mirrorOffsetX, p.CenterY, 0f), p.size, _armor);
                    Box(art, $"BLK_{p.id}_R", new Vector3(+p.mirrorOffsetX, p.CenterY, 0f), p.size, _armor);
                }
                else
                {
                    Box(art, $"BLK_{p.id}", new Vector3(0f, p.CenterY, 0f), p.size, _armor);
                }
            }

            // ── 2. 挂点（严格按契约创建，顺序保证父级先于子级） ──
            var map = new Dictionary<string, Transform> { { RootName, root.transform } };

            // MECH_ROOT 的 Transform 即为根，不重复建节点
            foreach (var s in c.sockets)
            {
                if (s.name == "MECH_ROOT") continue;

                Transform parentTf = root.transform;
                if (!string.IsNullOrEmpty(s.parent))
                {
                    if (!map.TryGetValue(s.parent, out parentTf))
                    {
                        Debug.LogError($"[SteelRidge] 挂点 {s.name} 的父级 {s.parent} 尚未创建（契约顺序有误）");
                        continue;
                    }
                }

                var go = new GameObject(s.name);
                go.transform.SetParent(parentTf, false);
                go.transform.localPosition = s.localPosition;
                map[s.name] = go.transform;
            }

            // ── 3. 手臂（挂在肩挂点下，形成 IK 目标链） ──
            BuildArm(c, map, "L", -1f);
            BuildArm(c, map, "R", +1f);

            // ── 4. 背包与翼状挂架 ──
            if (map.TryGetValue("BackpackMount", out var bp))
            {
                Box(bp, "BLK_Backpack", Vector3.zero, new Vector3(3.00f, 3.00f, 1.20f), _grey);
                Box(bp, "BLK_Binder_L", new Vector3(-1.85f, 0.55f, -0.75f), new Vector3(0.24f, 3.20f, 2.40f), _grey,
                    Quaternion.Euler(0f, -12f, 0f));
                Box(bp, "BLK_Binder_R", new Vector3(1.85f, 0.55f, -0.75f), new Vector3(0.24f, 3.20f, 2.40f), _grey,
                    Quaternion.Euler(0f, 12f, 0f));
            }

            // ── 5. 光剑（挂在腰侧刀架） ──
            foreach (var side in new[] { "L", "R" })
            {
                if (!map.TryGetValue($"SaberRack_{side}", out var rack)) continue;
                Cylinder(rack, $"BLK_Saber_{side}", new Vector3(0f, -0.10f, 0.30f),
                    new Vector3(c.saberDiameter, c.saberLength * 0.5f, c.saberDiameter), _hazard);
            }

            // ── 6. 座舱内构（挂在 CockpitRoot 下） ──
            if (map.TryGetValue("CockpitRoot", out var cockpit))
                BuildCockpit(c, cockpit, map);

            // ── 7. 枢轴（座舱与手臂节点已就绪） ──
            foreach (var pv in c.pivots)
            {
                Transform ptf;
                if (pv.parent == "MECH_ROOT") ptf = root.transform;
                else if (!map.TryGetValue(pv.parent, out ptf))
                {
                    Debug.LogWarning($"[SteelRidge] 枢轴 {pv.name} 的父级 {pv.parent} 不存在，已跳过");
                    continue;
                }

                var go = new GameObject(pv.name);
                go.transform.SetParent(ptf, false);
                go.transform.localPosition = pv.localPosition;
                map[pv.name] = go.transform;
            }

            return root;
        }

        static void BuildArm(MechaContract c, Dictionary<string, Transform> map, string side, float sign)
        {
            if (!map.TryGetValue($"ShoulderSocket_{side}", out var shoulder)) return;

            // 肩甲：外缘必须落在 shoulderWidth/2，否则整机视觉宽度会溢出契约
            float outerEdge = c.shoulderWidth * 0.5f - c.shoulderX;
            float armorW = Mathf.Max(0.6f, outerEdge * 2f);
            Box(shoulder, $"BLK_ShoulderArmor_{side}", Vector3.zero,
                new Vector3(armorW, 1.50f, 1.90f), _armor);

            var upper = new GameObject($"UpperArm_{side}").transform;
            upper.SetParent(shoulder, false);
            map[$"UpperArm_{side}"] = upper;
            Box(upper, $"BLK_UpperArm_{side}", new Vector3(0f, -c.upperArmLength * 0.5f, 0f),
                new Vector3(c.armSection, c.upperArmLength, c.armSection), _armor);

            var elbow = new GameObject($"Elbow_{side}").transform;
            elbow.SetParent(upper, false);
            elbow.localPosition = new Vector3(0f, -c.upperArmLength, 0f);
            map[$"Elbow_{side}"] = elbow;

            var fore = new GameObject($"Forearm_{side}").transform;
            fore.SetParent(elbow, false);
            map[$"Forearm_{side}"] = fore;
            Box(fore, $"BLK_Forearm_{side}", new Vector3(0f, -c.forearmLength * 0.5f, 0f),
                new Vector3(c.armSection, c.forearmLength, c.armSection), _armor);

            var wrist = new GameObject($"Wrist_{side}").transform;
            wrist.SetParent(fore, false);
            wrist.localPosition = new Vector3(0f, -c.forearmLength, 0f);
            map[$"Wrist_{side}"] = wrist;

            Box(wrist, $"BLK_Hand_{side}", new Vector3(0f, -c.handLength * 0.5f, 0f),
                new Vector3(c.armSection * 0.8f, c.handLength, c.armSection * 0.6f), _grey);
        }

        // ═════════════════════════ 座舱内构 ═════════════════════════

        static void BuildCockpit(MechaContract c, Transform cockpit, Dictionary<string, Transform> map)
        {
            float halfW = c.cockpitInterior.x * 0.5f;
            float halfH = c.cockpitInterior.y * 0.5f;
            float halfD = c.cockpitInterior.z * 0.5f;
            float eyeY = c.eyeHeightFromFloor - halfH;   // 相对 CockpitRoot，= 0.15

            var floor = new GameObject("CockpitFloor").transform;
            floor.SetParent(cockpit, false);
            floor.localPosition = new Vector3(0f, -halfH, 0f);
            map["CockpitFloor"] = floor;

            // 壳体（薄板，白盒只为量尺寸）
            Box(cockpit, "CPT_Floor", new Vector3(0f, -halfH - 0.03f, 0f),
                new Vector3(c.cockpitInterior.x, 0.06f, c.cockpitInterior.z), _grey);
            Box(cockpit, "CPT_Ceiling", new Vector3(0f, halfH + 0.03f, 0f),
                new Vector3(c.cockpitInterior.x, 0.06f, c.cockpitInterior.z), _grey);
            Box(cockpit, "CPT_BackWall", new Vector3(0f, 0f, -halfD - 0.03f),
                new Vector3(c.cockpitInterior.x, c.cockpitInterior.y, 0.06f), _grey);
            Box(cockpit, "CPT_Wall_L", new Vector3(-halfW - 0.03f, 0f, 0f),
                new Vector3(0.06f, c.cockpitInterior.y, c.cockpitInterior.z), _grey);
            Box(cockpit, "CPT_Wall_R", new Vector3(+halfW + 0.03f, 0f, 0f),
                new Vector3(0.06f, c.cockpitInterior.y, c.cockpitInterior.z), _grey);

            // 前窗框：上沿 +25°、下沿 −15°，用梁示意，不做斜面
            float winTop = eyeY + Mathf.Tan(c.windowUp * Mathf.Deg2Rad) * halfD;
            float winBottom = eyeY - Mathf.Tan(c.windowDown * Mathf.Deg2Rad) * halfD;
            float winHalfW = Mathf.Tan(c.windowHalfHorizontal * Mathf.Deg2Rad) * halfD;

            Box(cockpit, "CPT_Frame_Top", new Vector3(0f, Mathf.Min(halfH - 0.05f, winTop), halfD),
                new Vector3(c.cockpitInterior.x, 0.18f, 0.08f), _grey);
            Box(cockpit, "CPT_Frame_Bottom", new Vector3(0f, Mathf.Max(-halfH + 0.05f, winBottom), halfD),
                new Vector3(c.cockpitInterior.x, 0.20f, 0.08f), _grey);
            Box(cockpit, "CPT_Pillar_L", new Vector3(-Mathf.Min(halfW - 0.05f, winHalfW), eyeY, halfD),
                new Vector3(0.14f, c.cockpitInterior.y, 0.08f), _grey);
            Box(cockpit, "CPT_Pillar_R", new Vector3(+Mathf.Min(halfW - 0.05f, winHalfW), eyeY, halfD),
                new Vector3(0.14f, c.cockpitInterior.y, 0.08f), _grey);

            // 座椅
            float panTop = -halfH + c.seatPanHeight;
            Box(cockpit, "CPT_SeatPan", new Vector3(0f, panTop - 0.05f, -0.35f),
                new Vector3(0.50f, 0.10f, 0.50f), _grey);
            Box(cockpit, "CPT_SeatBack", new Vector3(0f, panTop + c.seatBackHeight * 0.5f, -0.62f),
                new Vector3(0.50f, c.seatBackHeight, 0.10f), _grey);
            Box(cockpit, "CPT_Headrest", new Vector3(0f, panTop + c.seatBackHeight - 0.08f, -0.58f),
                new Vector3(0.36f, 0.22f, 0.16f), _grey);

            // 主仪表：必须落在 dashNear–dashFar 区间
            float dashZ = c.eyeForwardOffset + (c.dashNear + c.dashFar) * 0.5f;
            Box(cockpit, "CPT_Dash", new Vector3(0f, eyeY - 0.25f, dashZ),
                new Vector3(1.20f, 0.30f, 0.06f), _grey);

            // 三块全息面板锚点（左 25° / 中 0° / 右 −25°）—— 后期 HoloPanel 直接挂这里
            var holo = new GameObject("HoloPanels").transform;
            holo.SetParent(cockpit, false);
            HoloAnchor(holo, "HoloPanel_Left", new Vector3(-0.52f, eyeY + 0.02f, dashZ - 0.02f), 25f);
            HoloAnchor(holo, "HoloPanel_Center", new Vector3(0f, eyeY + 0.10f, dashZ), 0f);
            HoloAnchor(holo, "HoloPanel_Right", new Vector3(0.52f, eyeY + 0.02f, dashZ - 0.02f), -25f);

            // 驾驶杆（枢轴在 CockpitFloor 下，限位由契约保证）
            var stick = new GameObject("VIS_Stick").transform;
            stick.SetParent(floor, false);
            stick.localPosition = new Vector3(0.30f, 0.35f, 0.55f);
            Cylinder(stick, "CPT_StickShaft", new Vector3(0f, 0.09f, 0f), new Vector3(0.045f, 0.09f, 0.045f), _interactive);
            Box(stick, "CPT_StickGrip", new Vector3(0f, 0.20f, 0f), new Vector3(0.07f, 0.12f, 0.07f), _interactive);

            // 油门
            var throttle = new GameObject("VIS_Throttle").transform;
            throttle.SetParent(floor, false);
            throttle.localPosition = new Vector3(-0.30f, 0.35f, 0.55f);
            Box(throttle, "CPT_ThrottleLever", new Vector3(0f, 0.06f, 0.04f), new Vector3(0.06f, 0.14f, 0.06f), _interactive);

            // 脚舵
            Box(floor, "CPT_Pedal_L", new Vector3(-0.22f, 0.09f, 0.72f), new Vector3(0.12f, 0.18f, 0.30f), _interactive);
            Box(floor, "CPT_Pedal_R", new Vector3(+0.22f, 0.09f, 0.72f), new Vector3(0.12f, 0.18f, 0.30f), _interactive);

            // 舱门面板（挂在左铰链枢轴下，向右展开 1.25 m）
            if (map.TryGetValue("HatchHinge_L", out var hinge))
            {
                var shaft = new GameObject("VIS_Hatch").transform;
                shaft.SetParent(hinge, false);
                Box(shaft, "CPT_HatchPanel", new Vector3(c.hatchWidth * 0.5f, 0f, 0f),
                    new Vector3(c.hatchWidth, c.hatchHeight, 0.06f), _hazard);
            }
        }

        static void HoloAnchor(Transform parent, string name, Vector3 pos, float yaw)
        {
            var go = new GameObject(name);
            go.transform.SetParent(parent, false);
            go.transform.localPosition = pos;
            go.transform.localRotation = Quaternion.Euler(0f, yaw, 0f);
            // 面板边框（示意 0.36×0.24 m，真实尺寸在 S3 定）
            Box(go.transform, "frame", new Vector3(0f, 0f, 0.01f), new Vector3(0.36f, 0.24f, 0.004f), _holo);
        }

        // ═════════════════════════ 地面序章 ═════════════════════════

        static void BuildSite(string name, MechaContract c)
        {
            var site = new GameObject(name).transform;

            // 地面
            Box(site, "SITE_Ground", new Vector3(0f, -0.10f, 0f), new Vector3(300f, 0.20f, 300f), _site);

            // 30×30 停机标记
            float half = 15f;
            for (int i = 0; i < 4; i++)
            {
                bool horiz = i < 2;
                float s = (i % 2 == 0) ? -half : half;
                Box(site, $"SITE_Mark_{i}",
                    horiz ? new Vector3(0f, 0.02f, s) : new Vector3(s, 0.02f, 0f),
                    horiz ? new Vector3(half * 2f, 0.02f, 0.10f) : new Vector3(0.10f, 0.02f, half * 2f),
                    _hazard);
            }

            // 升降井（16×20 m）位于机体正前方 18 m
            var shaft = new GameObject("SITE_Shaft").transform;
            shaft.SetParent(site, false);
            shaft.localPosition = new Vector3(0f, 0f, 18f);
            Box(shaft, "Shaft_Dark", new Vector3(0f, -8f, 0f), new Vector3(16f, 0.1f, 20f), _grey);
            Box(shaft, "Shaft_Curb_N", new Vector3(0f, 0.35f, 10f), new Vector3(16.6f, 0.70f, 0.30f), _hazard);
            Box(shaft, "Shaft_Curb_S", new Vector3(0f, 0.35f, -10f), new Vector3(16.6f, 0.70f, 0.30f), _hazard);
            Box(shaft, "Shaft_Curb_W", new Vector3(-8f, 0.35f, 0f), new Vector3(0.30f, 0.70f, 20f), _hazard);
            Box(shaft, "Shaft_Curb_E", new Vector3(8f, 0.35f, 0f), new Vector3(0.30f, 0.70f, 20f), _hazard);
            foreach (var corner in new[] { new Vector2(-8f, -10f), new Vector2(8f, -10f), new Vector2(-8f, 10f), new Vector2(8f, 10f) })
                Box(shaft, "Shaft_Post", new Vector3(corner.x, 1.2f, corner.y), new Vector3(0.25f, 2.4f, 0.25f), _interactive);

            // 12 m 集装箱 —— 最直观的尺度参照物
            for (int i = 0; i < 5; i++)
                Box(site, $"SITE_Container_{i}", new Vector3(-26f + i * 13f, 1.3f, -32f),
                    new Vector3(12f, 2.6f, 2.4f), _site);

            // 40 m 龙门吊 —— 第二层尺度参照（机体 18.2 m 只到其一半高）
            foreach (var sx in new[] { -22f, 22f })
            {
                Box(site, "SITE_CraneColumn", new Vector3(sx, 20f, -6f), new Vector3(1.2f, 40f, 1.2f), _grey);
                Box(site, "SITE_CraneFoot", new Vector3(sx, 0.4f, -6f), new Vector3(3.0f, 0.8f, 3.0f), _site);
            }
            Box(site, "SITE_CraneBeam", new Vector3(0f, 40f, -6f), new Vector3(44.4f, 1.0f, 1.2f), _grey);
            Box(site, "SITE_CraneTrolley", new Vector3(0f, 38.6f, -6f), new Vector3(2.2f, 1.6f, 2.2f), _hazard);
            Box(site, "SITE_CraneCable", new Vector3(0f, 31f, -6f), new Vector3(0.10f, 15f, 0.10f), _grey);

            // 泛光灯
            foreach (var p in new[] { new Vector3(-22f, 34f, -5f), new Vector3(22f, 34f, -5f),
                                      new Vector3(-18f, 12f, 6f), new Vector3(18f, 12f, 6f) })
                Box(site, "SITE_Floodlight", p, new Vector3(1.0f, 0.6f, 0.4f), _holo);

            Debug.Log($"[SteelRidge] 地面序章已生成：参照物 12 m 集装箱 ×5 / 40 m 龙门吊 / 16×20 m 升降井");
        }

        // ═════════════════════════ 基础件 ═════════════════════════

        static GameObject Box(Transform parent, string name, Vector3 localPos, Vector3 size,
                              Material mat, Quaternion? rot = null)
        {
            var go = GameObject.CreatePrimitive(PrimitiveType.Cube);
            go.name = name;
            go.transform.SetParent(parent, false);
            go.transform.localPosition = localPos;
            go.transform.localRotation = rot ?? Quaternion.identity;
            go.transform.localScale = size;
            Object.DestroyImmediate(go.GetComponent<Collider>());
            if (mat != null) go.GetComponent<Renderer>().sharedMaterial = mat;
            return go;
        }

        static GameObject Cylinder(Transform parent, string name, Vector3 localPos, Vector3 scale, Material mat)
        {
            var go = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
            go.name = name;
            go.transform.SetParent(parent, false);
            go.transform.localPosition = localPos;
            go.transform.localScale = scale;
            Object.DestroyImmediate(go.GetComponent<Collider>());
            if (mat != null) go.GetComponent<Renderer>().sharedMaterial = mat;
            return go;
        }

        static Transform FindDeep(Transform root, string name)
        {
            if (root == null) return null;
            if (root.name == name) return root;
            for (int i = 0; i < root.childCount; i++)
            {
                var r = FindDeep(root.GetChild(i), name);
                if (r != null) return r;
            }
            return null;
        }

        // ═════════════════════════ 资源 ═════════════════════════

        public static MechaContract EnsureContract()
        {
            var existing = AssetDatabase.LoadAssetAtPath<MechaContract>(MechaContract.AssetPath);
            if (existing != null)
            {
                if (_armor == null) LoadMaterials();
                return existing;
            }

            EnsureFolder("Assets/_Project/Config");
            var c = MechaContract.CreateDefault();
            AssetDatabase.CreateAsset(c, MechaContract.AssetPath);
            AssetDatabase.SaveAssets();

            var issues = c.Validate();
            if (issues.Count > 0)
                Debug.LogWarning("[SteelRidge] 新建契约存在不一致：\n• " + string.Join("\n• ", issues));
            else
                Debug.Log($"[SteelRidge] 已按契约表 v1.0 生成 {MechaContract.AssetPath}，自检通过");

            LoadMaterials();
            return c;
        }

        static void LoadMaterials()
        {
            _armor = GetOrCreate("M_Blockout_Armor", new Color(0.86f, 0.88f, 0.90f), 0.15f);
            _grey = GetOrCreate("M_Blockout_Grey", new Color(0.55f, 0.57f, 0.60f), 0.30f);
            _interactive = GetOrCreate("M_Blockout_Interactive", new Color(0.16f, 0.48f, 0.96f), 0.20f);
            _hazard = GetOrCreate("M_Blockout_Hazard", new Color(0.95f, 0.55f, 0.10f), 0.25f);
            _holo = GetOrCreate("M_Blockout_Holo", new Color(0.28f, 0.82f, 1f), 0.10f, new Color(0.20f, 0.70f, 1f) * 2.2f);
            _site = GetOrCreate("M_Blockout_Site", new Color(0.34f, 0.35f, 0.37f), 0.40f);
        }

        static Material GetOrCreate(string name, Color color, float smoothness, Color? emission = null)
        {
            const string dir = "Assets/_Project/Art/Blockout";
            string path = $"{dir}/{name}.mat";

            var m = AssetDatabase.LoadAssetAtPath<Material>(path);
            if (m != null) return m;

            EnsureFolder(dir);
            var shader = Shader.Find("Universal Render Pipeline/Lit");
            if (shader == null) shader = Shader.Find("Standard");
            if (shader == null) shader = Shader.Find("Diffuse");

            m = new Material(shader) { name = name };
            if (m.HasProperty("_BaseColor")) m.SetColor("_BaseColor", color);
            if (m.HasProperty("_Color")) m.SetColor("_Color", color);
            if (m.HasProperty("_Smoothness")) m.SetFloat("_Smoothness", smoothness);
            if (m.HasProperty("_Glossiness")) m.SetFloat("_Glossiness", smoothness);
            if (emission.HasValue && m.HasProperty("_EmissionColor"))
            {
                m.EnableKeyword("_EMISSION");
                m.SetColor("_EmissionColor", emission.Value);
            }

            AssetDatabase.CreateAsset(m, path);
            return m;
        }

        public static void EnsureFolder(string path)
        {
            if (string.IsNullOrEmpty(path) || AssetDatabase.IsValidFolder(path)) return;

            string abs = Path.Combine(Directory.GetCurrentDirectory(), path);
            if (!Directory.Exists(abs)) Directory.CreateDirectory(abs);
            AssetDatabase.Refresh();
        }
    }
}
