using System;
using System.Collections.Generic;
using UnityEngine;

namespace SteelRidge.Core.Holo
{
    /// <summary>面板优先级。FOV 不够时按此顺序决定谁留下、谁改为"召唤式"。</summary>
    public enum PanelPriority
    {
        /// <summary>核心：任何设备上都必须落在 ±criticalHalfAngle 内。</summary>
        Critical = 0,

        /// <summary>次要：VR 放在侧窗，AR 可移到 20° 内或改为射线呼出。</summary>
        Secondary = 1,

        /// <summary>环境信息：允许在窄视场上直接隐藏。</summary>
        Ambient = 2
    }

    /// <summary>
    /// 全息面板定义 —— 用「相对眼位的角度 + 距离」描述，不用米数坐标。
    /// 理由：同一块面板在 96° VR 里在 ±25° 很舒服，在 43° AR 里直接出画。
    /// 用角度定义，换设备时改的是 clip 规则，不是重新摆位置。
    /// </summary>
    [Serializable]
    public class HoloPanelDef
    {
        [Tooltip("机读 id，代码按名查找")] public string id = "Panel";

        public PanelPriority priority = PanelPriority.Secondary;

        [Tooltip("相对眼位正前方的水平偏航（度），正为右")]
        public float yaw = 0f;

        [Tooltip("相对眼位水平线的俯仰（度），正为上")]
        public float pitch = 0f;

        [Tooltip("面板中心到眼位的距离。ScaleGrounding=WorldMetric 时必须落在契约 dashNear–dashFar 区间；" +
                 "HeadRelative（3DoF）时只是渲染空间的相对距离，不做米级断言")]
        public float distance = 0.75f;

        [Tooltip("面板物理尺寸（米）。抬头显示里真正可验证的是它对眼位张开的角尺寸；" +
                 "HeadRelative 时这个米数只是相对量")]
        public Vector2 size = new Vector2(0.36f, 0.24f);

        [Tooltip("窄视场下是否允许隐藏（false 则改为召唤式/缩小）")]
        public bool hideWhenOutOfFov = true;
    }

    /// <summary>单块面板的落位结果。</summary>
    public struct PanelPlacement
    {
        public bool Fits;
        public Vector3 LocalPosition;
        public Quaternion LocalRotation;

        /// <summary>横向角半宽（由 size.x 决定）。</summary>
        public float AngularHalfWidthH;

        /// <summary>纵向角半宽（由 size.y 决定）。</summary>
        public float AngularHalfWidthV;

        /// <summary>两轴较大值，用于粗算与排序。</summary>
        public float AngularHalfWidth;

        public string Note;
    }

    /// <summary>
    /// 面板布局求解器。输入角度定义 + 平台能力，输出本地坐标与是否在视场内。
    /// 纯函数，无状态，可在编辑器里批量审计，也可在运行时逐帧调用。
    ///
    /// 注意横向与纵向的半宽必须分开算：一块 0.56×0.16 的宽面板，
    /// 若用最大边当纵向半宽，会把 96° VR 都误判成"出画"。
    /// </summary>
    public static class HoloPanelLayout
    {
        /// <summary>
        /// 计算面板落位（相对眼位、眼位朝 +Z 的本地空间）。
        /// </summary>
        public static PanelPlacement Solve(HoloPanelDef def, in SteelRidge.Core.Platform.PlatformCapabilities caps)
        {
            var r = new PanelPlacement();

            float dist = Mathf.Max(0.05f, def.distance);
            var dir = Quaternion.Euler(def.pitch, def.yaw, 0f) * Vector3.forward;
            r.LocalPosition = dir * dist;

            // 面板朝向眼位：Z 轴指向 -dir
            r.LocalRotation = Quaternion.LookRotation(-dir, Vector3.up);

            // 两个轴的角半宽分别由尺寸对应边决定
            r.AngularHalfWidthH = Mathf.Atan2(Mathf.Max(0.001f, def.size.x) * 0.5f, dist) * Mathf.Rad2Deg;
            r.AngularHalfWidthV = Mathf.Atan2(Mathf.Max(0.001f, def.size.y) * 0.5f, dist) * Mathf.Rad2Deg;
            r.AngularHalfWidth = Mathf.Max(r.AngularHalfWidthH, r.AngularHalfWidthV);

            float needH = Mathf.Abs(def.yaw) + r.AngularHalfWidthH;
            float needV = Mathf.Abs(def.pitch) + r.AngularHalfWidthV;

            float availH = caps.HalfFovH(2f);
            float availV = caps.HalfFovV(2f);

            r.Fits = needH <= availH && needV <= availV;

            if (!r.Fits)
            {
                r.Note = needH > availH
                    ? $"横向需 ±{needH:0.#}°，可用 ±{availH:0.#}°"
                    : $"纵向需 ±{needV:0.#}°，可用 ±{availV:0.#}°";
            }

            return r;
        }

        /// <summary>
        /// 在给定设备上把面板压回视场内（保持距离，只改角度）。
        /// 用于 AR 降级：把 ±25° 的侧面板收到 ±(avail - 半宽)。
        /// </summary>
        public static HoloPanelDef ClampIntoFov(HoloPanelDef def, in SteelRidge.Core.Platform.PlatformCapabilities caps)
        {
            var c = new HoloPanelDef
            {
                id = def.id,
                priority = def.priority,
                yaw = def.yaw,
                pitch = def.pitch,
                distance = def.distance,
                size = def.size,
                hideWhenOutOfFov = def.hideWhenOutOfFov
            };

            var p = Solve(c, caps);
            if (p.Fits) return c;

            float limitH = Mathf.Max(0f, caps.HalfFovH(2f) - p.AngularHalfWidthH);
            float limitV = Mathf.Max(0f, caps.HalfFovV(2f) - p.AngularHalfWidthV);

            c.yaw = Mathf.Clamp(c.yaw, -limitH, limitH);
            c.pitch = Mathf.Clamp(c.pitch, -limitV, limitV);
            return c;
        }

        /// <summary>
        /// 批量审计：返回每一块面板在指定设备上的落位结论，供编辑器报告使用。
        /// </summary>
        public static List<string> AuditAll(IEnumerable<HoloPanelDef> defs,
                                           in SteelRidge.Core.Platform.PlatformCapabilities caps,
                                           out int fitCount, out int overflowCount)
        {
            var lines = new List<string>();
            fitCount = 0;
            overflowCount = 0;

            foreach (var d in defs)
            {
                var p = Solve(d, caps);
                if (p.Fits)
                {
                    fitCount++;
                    lines.Add($"[PASS] {d.id}（{d.priority}）yaw {d.yaw:+0;-0;0}° pitch {d.pitch:+0;-0;0}° · {d.distance:0.00} m · 半宽 {p.AngularHalfWidth:0.#}°");
                }
                else
                {
                    overflowCount++;
                    lines.Add($"[FAIL] {d.id}（{d.priority}）{p.Note} → 建议收到 yaw {ClampIntoFov(d, caps).yaw:0.#}°");
                }
            }

            return lines;
        }
    }
}
