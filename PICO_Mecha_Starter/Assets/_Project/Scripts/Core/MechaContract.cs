using System;
using System.Collections.Generic;
using UnityEngine;

namespace SteelRidge.Core
{
    /// <summary>
    /// 尺寸与接口契约 —— 代码、白盒、外包建模三方共用的唯一事实来源。
    /// 与 Contracts/尺寸与接口契约表.md 一一对应。
    /// 流程：改本资产 → 菜单「Steel Ridge/白盒/重建全部」→ 菜单「Steel Ridge/契约/导出 JSON」。
    /// 单位：米（Unity 1 unit = 1 m），坐标系：Y 向上，机体正面朝 +Z。
    /// </summary>
    [CreateAssetMenu(fileName = "MechaContract", menuName = "Steel Ridge/尺寸与接口契约", order = 0)]
    public class MechaContract : ScriptableObject
    {
        public const string AssetPath = "Assets/_Project/Config/MechaContract.asset";

        [Header("整机")]
        [Tooltip("含天线总高 (m)")]
        public float totalHeight = 18.20f;

        [Tooltip("左右肩装甲外缘间距 (m)")]
        public float shoulderWidth = 10.60f;

        [Tooltip("ChestSocket 离地高度 (m)，座舱因此位于胸部正中")]
        public float chestSocketY = 12.60f;

        [Tooltip("CockpitRoot 相对 ChestSocket 的 Y 偏移 (m)，负数向下")]
        public float cockpitRootLocalY = -1.20f;

        [Tooltip("单腿中心线到机体中轴的距离 (m)")]
        public float legOffsetX = 1.70f;

        [Header("手臂")]
        public float shoulderY = 14.20f;
        public float shoulderX = 4.30f;
        public float upperArmLength = 3.00f;
        public float forearmLength = 3.20f;
        public float handLength = 0.60f;
        public float armSection = 1.50f;
        public float saberLength = 1.40f;
        public float saberDiameter = 0.22f;

        [Header("座舱内部（W×H×D）")]
        public Vector3 cockpitInterior = new Vector3(1.60f, 2.00f, 2.20f);

        [Tooltip("坐面离舱地板高度 (m)")]
        public float seatPanHeight = 0.45f;

        [Tooltip("靠背高 (m)，含头枕")]
        public float seatBackHeight = 0.90f;

        [Tooltip("眼位离舱地板高度 (m) —— 相机锚点")]
        public float eyeHeightFromFloor = 1.15f;

        [Tooltip("眼位相对座椅靠背的前向偏移 (m)")]
        public float eyeForwardOffset = 0.15f;

        [Tooltip("主仪表距眼最近距离 (m) —— 交互件必须落在此区间之后")]
        public float dashNear = 0.60f;

        [Tooltip("主仪表距眼最远距离 (m)")]
        public float dashFar = 0.90f;

        public float hatchHeight = 0.85f;
        public float hatchWidth = 1.25f;
        public float hatchMaxAngle = 95f;

        [Header("视野角度")]
        public float windowHalfHorizontal = 35f;
        public float windowUp = 25f;
        public float windowDown = 15f;
        public float windowSideHalfHorizontal = 25f;

        [Header("分件（竖向分层，从地面向上）")]
        public List<MechaPartDef> parts = new List<MechaPartDef>();

        [Header("挂点 Socket（命名固定，代码按名查找）")]
        public List<SocketDef> sockets = new List<SocketDef>();

        [Header("枢轴 Pivot 与限位")]
        public List<PivotDef> pivots = new List<PivotDef>();

        // ───────────────────────────── 派生量 ─────────────────────────────

        /// <summary>座舱几何中心离地高度，契约要求 11.40 m。</summary>
        public float CockpitCenterY => chestSocketY + cockpitRootLocalY;

        /// <summary>舱地板离地高度，契约要求 10.40 m。</summary>
        public float CockpitFloorY => CockpitCenterY - cockpitInterior.y * 0.5f;

        /// <summary>舱顶离地高度，契约要求 12.40 m。</summary>
        public float CockpitCeilingY => CockpitCenterY + cockpitInterior.y * 0.5f;

        /// <summary>眼位世界高度，契约要求 11.55 m。</summary>
        public float SeatAnchorWorldY => CockpitFloorY + eyeHeightFromFloor;

        public float ElbowY => shoulderY - upperArmLength;
        public float WristY => ElbowY - forearmLength;

        /// <summary>CockpitFloor 节点相对 CockpitRoot 的本地坐标。</summary>
        public Vector3 CockpitFloorLocal => new Vector3(0f, -cockpitInterior.y * 0.5f, 0f);

        /// <summary>眼位（SeatAnchor）相对 CockpitRoot 的本地坐标。</summary>
        public Vector3 SeatAnchorLocal => new Vector3(0f, CockpitFloorLocal.y + eyeHeightFromFloor, eyeForwardOffset);

        public SocketDef FindSocket(string name)
        {
            for (int i = 0; i < sockets.Count; i++)
                if (sockets[i].name == name) return sockets[i];
            return null;
        }

        public PivotDef FindPivot(string name)
        {
            for (int i = 0; i < pivots.Count; i++)
                if (pivots[i].name == name) return pivots[i];
            return null;
        }

        // ───────────────────────────── 自检 ─────────────────────────────

        /// <summary>
        /// 契约内部一致性自检。返回空列表代表通过。
        /// 这是防止「表里写 18.2 m、白盒却是 17 m」这类低级错误的唯一手段。
        /// </summary>
        public List<string> Validate()
        {
            var issues = new List<string>();

            if (parts == null || parts.Count == 0)
                issues.Add("分件列表为空");

            // 1. 每个分件 size.y 必须等于 top-bottom
            for (int i = 0; parts != null && i < parts.Count; i++)
            {
                var p = parts[i];
                float h = p.top - p.bottom;
                if (Mathf.Abs(p.size.y - h) > 0.011f)
                    issues.Add($"分件 {p.id}：size.y={p.size.y:F2} 与 top-bottom={h:F2} 不一致");
                if (p.top <= p.bottom)
                    issues.Add($"分件 {p.id}：top({p.top}) 不大于 bottom({p.bottom})");
            }

            // 2. 竖向分层应连续（无缝隙/无重叠）
            for (int i = 0; parts != null && i < parts.Count - 1; i++)
            {
                float gap = parts[i + 1].bottom - parts[i].top;
                if (Mathf.Abs(gap) > 0.011f)
                    issues.Add($"分件 {parts[i].id} 顶({parts[i].top:F2}) 与 {parts[i + 1].id} 底({parts[i + 1].bottom:F2}) 不连续，差 {gap:F2} m");
            }

            // 2b. 横向比例：分件必须被相邻更宽的体块包住。
            // 这一组检查是 v1.1 加的 —— v1.0 曾出现「大腿外缘 2.65 m 捅出胯部半宽 2.20 m」
            // 和「肩甲只比手臂宽 0.15 m」，单看表格数字完全看不出来，渲染出来就是腿从腰里长出来。
            var byId = new Dictionary<string, MechaPartDef>();
            for (int i = 0; parts != null && i < parts.Count; i++) byId[parts[i].id] = parts[i];

            MechaPartDef Get(string id) => byId.TryGetValue(id, out var v) ? v : null;

            var thigh = Get("thigh");
            var hip = Get("hip");
            var foot = Get("foot");

            if (thigh != null && hip != null)
            {
                float thighOuter = thigh.mirrorOffsetX + thigh.size.x * 0.5f;
                float hipHalf = hip.size.x * 0.5f;
                if (thighOuter > hipHalf)
                    issues.Add($"大腿外缘 {thighOuter:F2} m 超出胯部半宽 {hipHalf:F2} m（差 {thighOuter - hipHalf:F2} m）：加宽胯部或收窄腿距");
            }

            if (foot != null)
            {
                float footInner = foot.mirrorOffsetX - foot.size.x * 0.5f;
                if (footInner < 0.50f)
                    issues.Add($"双足内缘间距仅 {footInner * 2f:F2} m，双足会并成一块：收窄脚掌或拉开腿距");
                if (foot.mirrorOffsetX + foot.size.x * 0.5f > shoulderWidth * 0.5f)
                    issues.Add($"脚外缘超出肩宽半宽：站姿比肩还宽，重心读起来不稳");
            }

            float armOuter = shoulderX + armSection * 0.5f;
            float shoulderHalf = shoulderWidth * 0.5f;
            if (armOuter > shoulderHalf)
                issues.Add($"手臂外缘 {armOuter:F2} m 超出肩宽半宽 {shoulderHalf:F2} m：肩甲包不住手臂");
            else if (shoulderHalf - armOuter < 0.15f)
                issues.Add($"肩甲仅比手臂外缘宽 {shoulderHalf - armOuter:F2} m，视觉上等于没有肩甲（建议 ≥0.20 m）");


            // 3. 总高一致
            if (parts != null && parts.Count > 0)
            {
                float tallest = parts[parts.Count - 1].top;
                if (Mathf.Abs(tallest - totalHeight) > 0.011f)
                    issues.Add($"末段顶 {tallest:F2} 与 totalHeight {totalHeight:F2} 不一致");
            }

            // 4. 座舱派生量锁死
            if (Mathf.Abs(CockpitCenterY - 11.40f) > 0.011f)
                issues.Add($"座舱中心 {CockpitCenterY:F2} ≠ 契约 11.40（检查 chestSocketY + cockpitRootLocalY）");
            if (Mathf.Abs(CockpitFloorY - 10.40f) > 0.011f)
                issues.Add($"舱地板 {CockpitFloorY:F2} ≠ 契约 10.40（检查 cockpitInterior.y）");
            if (Mathf.Abs(SeatAnchorWorldY - 11.55f) > 0.011f)
                issues.Add($"眼位 {SeatAnchorWorldY:F2} ≠ 契约 11.55（检查 eyeHeightFromFloor）");

            // 5. 挂点存在性与父子引用
            string[] required =
            {
                "MECH_ROOT", "Sockets", "HeadSocket", "ChestSocket", "CockpitRoot", "SeatAnchor",
                "HatchHinge_L", "HatchHinge_R", "ShoulderSocket_L", "ShoulderSocket_R",
                "BackpackMount", "SaberRack_L", "SaberRack_R"
            };
            foreach (var r in required)
                if (FindSocket(r) == null)
                    issues.Add($"缺少必备挂点 {r}");

            for (int i = 0; sockets != null && i < sockets.Count; i++)
            {
                var s = sockets[i];
                if (s.name != "MECH_ROOT" && FindSocket(s.parent) == null)
                    issues.Add($"挂点 {s.name} 的父级 {s.parent} 不存在");
            }

            // 6. 挂点世界高度交叉校验
            var seat = FindSocket("SeatAnchor");
            if (seat != null)
            {
                float worldY = chestSocketY + cockpitRootLocalY + seat.localPosition.y;
                if (Mathf.Abs(worldY - SeatAnchorWorldY) > 0.011f)
                    issues.Add($"Socket SeatAnchor 推算世界高度 {worldY:F2} 与派生值 {SeatAnchorWorldY:F2} 不一致");
            }

            // 7. 枢轴父子引用
            for (int i = 0; pivots != null && i < pivots.Count; i++)
            {
                var pv = pivots[i];
                if (FindSocket(pv.parent) == null &&
                    pv.parent != "MECH_ROOT" && pv.parent != "CockpitFloor" &&
                    pv.parent != "UpperArm_R" && pv.parent != "Forearm_R")
                    issues.Add($"枢轴 {pv.name} 的父级 {pv.parent} 不在已知节点集合内");
                if (pv.maxAngle <= pv.minAngle)
                    issues.Add($"枢轴 {pv.name} 限位异常：{pv.minAngle}→{pv.maxAngle}");
            }

            // 8. 交互距离：仪表必须比 dashNear 更远，否则手会穿模
            if (dashFar <= dashNear)
                issues.Add($"dashFar({dashFar}) 必须大于 dashNear({dashNear})");

            return issues;
        }

        // ───────────────────────────── 默认值（= 契约表 v1.0） ─────────────────────────────

        public static MechaContract CreateDefault()
        {
            var c = CreateInstance<MechaContract>();
            c.name = "MechaContract";

            c.parts = new List<MechaPartDef>
            {
                Part("foot",    "脚掌", 0.00f,  0.70f, 2.40f, 5.00f, true,  1.70f),
                Part("shin",    "小腿", 0.70f,  4.50f, 1.60f, 1.80f, true,  1.70f),
                Part("thigh",   "大腿", 4.50f,  8.40f, 1.90f, 2.00f, true,  1.70f),
                Part("hip",     "胯部", 8.40f,  9.30f, 5.60f, 3.20f),
                Part("waist",   "腰部", 9.30f, 10.10f, 3.60f, 3.00f),
                Part("chest",   "胸部", 10.10f, 15.10f, 6.40f, 4.20f),
                Part("neck",    "颈部", 15.10f, 15.40f, 0.90f, 0.90f),
                Part("head",    "头部", 15.40f, 17.60f, 1.60f, 1.90f),
                Part("antenna", "天线", 17.60f, 18.20f, 0.10f, 0.10f, true, 0.35f)
            };

            c.sockets = new List<SocketDef>
            {
                Sock("MECH_ROOT",         null,           0f,      0f,     0f,     "整机根节点，脚底中心"),
                Sock("Sockets",           "MECH_ROOT",    0f,      0f,     0f,     "挂点容器"),
                Sock("HeadSocket",        "Sockets",      0f,     15.40f,  0f,     "头部安装"),
                Sock("ChestSocket",       "Sockets",      0f,     12.60f,  0f,     "胸部安装"),
                Sock("CockpitRoot",       "ChestSocket",  0f,     -1.20f,  0f,     "座舱根（世界 11.40）"),
                Sock("SeatAnchor",        "CockpitRoot",  0f,      0.15f,  0.15f,  "相机锚点（世界 11.55）"),
                Sock("HatchHinge_L",      "ChestSocket", -0.425f, -1.20f,  2.10f,  "舱门左铰链"),
                Sock("HatchHinge_R",      "ChestSocket",  0.425f, -1.20f,  2.10f,  "舱门右铰链"),
                Sock("ShoulderSocket_L",  "Sockets",     -4.30f,  14.20f,  0f,     "左肩"),
                Sock("ShoulderSocket_R",  "Sockets",      4.30f,  14.20f,  0f,     "右肩"),
                Sock("BackpackMount",     "Sockets",      0f,     13.50f, -2.10f,  "翼状背包"),
                Sock("SaberRack_L",       "Sockets",     -1.80f,   9.60f,  0f,     "左刀架"),
                Sock("SaberRack_R",       "Sockets",      1.80f,   9.60f,  0f,     "右刀架")
            };

            c.pivots = new List<PivotDef>
            {
                Pivot("Pivot_StickBase",    "CockpitFloor", new Vector3( 0.30f, 0.35f, 0.55f), Vector3.right,   -25f, 25f,  "驾驶杆，绕 X 前后推拉"),
                Pivot("Pivot_Throttle",     "CockpitFloor", new Vector3(-0.30f, 0.35f, 0.55f), Vector3.right,     0f, 40f,  "油门，只能向前推"),
                Pivot("Pivot_Hatch_L",      "HatchHinge_L", Vector3.zero,                        Vector3.up,        0f, 95f,  "左舱门，铰链在左缘"),
                Pivot("Pivot_Hatch_R",      "HatchHinge_R", Vector3.zero,                        Vector3.up,        0f, 95f,  "右舱门，铰链在右缘"),
                Pivot("Pivot_Skirt_Front",  "MECH_ROOT",    new Vector3(0f, 8.40f, 1.30f),      Vector3.right,   -12f, 12f,  "前裙甲，走路避让"),
                Pivot("Pivot_Skirt_Side_L", "MECH_ROOT",    new Vector3(-1.90f, 8.40f, 0f),     Vector3.forward, -10f, 10f,  "左侧裙甲"),
                Pivot("Pivot_Skirt_Side_R", "MECH_ROOT",    new Vector3( 1.90f, 8.40f, 0f),     Vector3.forward, -10f, 10f,  "右侧裙甲"),
                Pivot("Pivot_Elbow_R",      "UpperArm_R",   new Vector3(0f, -3.00f, 0f),        Vector3.right,     0f, 120f, "右肘，IK 目标链中段"),
                Pivot("Pivot_Wrist_R",      "Forearm_R",    new Vector3(0f, -3.20f, 0f),        Vector3.one,       0f, 360f, "右腕，自由三轴")
            };

            return c;
        }

        static MechaPartDef Part(string id, string label, float bottom, float top,
                                 float width, float depth, bool mirrored = false, float mirrorOffsetX = 0f)
        {
            return new MechaPartDef
            {
                id = id,
                label = label,
                bottom = bottom,
                top = top,
                size = new Vector3(width, top - bottom, depth),
                mirrored = mirrored,
                mirrorOffsetX = mirrorOffsetX
            };
        }

        static SocketDef Sock(string name, string parent, float x, float y, float z, string purpose)
        {
            return new SocketDef
            {
                name = name,
                parent = parent,
                localPosition = new Vector3(x, y, z),
                purpose = purpose
            };
        }

        static PivotDef Pivot(string name, string parent, Vector3 pos, Vector3 axis,
                              float min, float max, string note)
        {
            return new PivotDef
            {
                name = name,
                parent = parent,
                localPosition = pos,
                axis = axis,
                minAngle = min,
                maxAngle = max,
                note = note
            };
        }
    }

    [Serializable]
    public class MechaPartDef
    {
        [Tooltip("机读 id，命名规范用，勿改")] public string id;
        [Tooltip("中文标签，仅用于汇报")] public string label;
        [Tooltip("底部离地高度 (m)")] public float bottom;
        [Tooltip("顶部离地高度 (m)")] public float top;
        [Tooltip("W×H×D (m)，H 必须等于 top-bottom")] public Vector3 size;

        [Tooltip("是否左右对称（腿 / 天线）")] public bool mirrored;
        [Tooltip("镜像中心到中轴的距离 (m)")] public float mirrorOffsetX;

        public float CenterY => (bottom + top) * 0.5f;
        public float Height => top - bottom;
    }

    [Serializable]
    public class SocketDef
    {
        public string name;
        [Tooltip("父级节点名；MECH_ROOT 的父级留空")] public string parent;
        [Tooltip("相对父级的本地坐标 (m)")] public Vector3 localPosition;
        public string purpose;
    }

    [Serializable]
    public class PivotDef
    {
        public string name;
        public string parent;
        public Vector3 localPosition;
        [Tooltip("旋转轴（本地空间）")] public Vector3 axis;
        public float minAngle;
        public float maxAngle;
        public string note;
    }
}
