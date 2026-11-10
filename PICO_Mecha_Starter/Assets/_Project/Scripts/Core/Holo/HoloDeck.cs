using System;
using System.Collections.Generic;
using SteelRidge.Core.Platform;
using UnityEngine;

namespace SteelRidge.Core.Holo
{
    /// <summary>
    /// 视场安全区三档。定三档而不是连续缩放，是因为 UI 布局需要"离散且可评审"的锚点：
    /// 连续缩放在每台设备上都略有不同，评审时无法判断对错。
    /// </summary>
    public enum SafeZoneTier
    {
        /// <summary>窄视场：单绿眼镜 / 30° 形态。只放得下 1–2 块面板。</summary>
        Narrow = 0,

        /// <summary>标准：AR Studio 一类 43° 水平。</summary>
        Standard = 1,

        /// <summary>宽视场：VR 一体机 96°+。</summary>
        Wide = 2
    }

    public struct SafeZone
    {
        public SafeZoneTier Tier;
        public float HalfHorizontal;
        public float HalfVertical;

        /// <summary>核心区半径：信息必须落在此角度内，否则用户要转头才看得见。</summary>
        public float CriticalHalfAngle;

        public override string ToString() =>
            $"{Tier}｜±{HalfHorizontal:0.#}°×±{HalfVertical:0.#}°｜核心 ±{CriticalHalfAngle:0}°";
    }

    public static class SafeZoneResolver
    {
        public static SafeZone From(in PlatformCapabilities caps)
        {
            float hh = caps.HalfFovH(caps.IsAdditive ? 4f : 6f);
            float hv = caps.HalfFovV(caps.IsAdditive ? 4f : 6f);

            SafeZoneTier tier;
            if (hh < 16f) tier = SafeZoneTier.Narrow;
            else if (hh < 30f) tier = SafeZoneTier.Standard;
            else tier = SafeZoneTier.Wide;

            // 核心区不超过可用视场的一半，也不超过 20°：再大就不叫"核心"了
            float critical = Mathf.Min(20f, hh * 0.5f, hv * 0.9f);

            return new SafeZone
            {
                Tier = tier,
                HalfHorizontal = hh,
                HalfVertical = hv,
                CriticalHalfAngle = critical
            };
        }

        /// <summary>
        /// 每种档位的 HUD 锚点（相对眼位的 yaw/pitch）。返回顺序固定：
        /// 0 中心、1 左下、2 右下、3 左上、4 右上。
        /// 用固定顺序而不是字典，是为了让"第 3 个锚点"在 VR/AR 上语义一致。
        /// </summary>
        public static Vector2[] Anchors(in SafeZone zone)
        {
            switch (zone.Tier)
            {
                case SafeZoneTier.Narrow:
                    return new[]
                    {
                        new Vector2(0f, 0f),
                        new Vector2(0f, -8f),
                        new Vector2(0f, -12f),
                        new Vector2(0f, 8f),
                        new Vector2(0f, 11f)
                    };

                case SafeZoneTier.Standard:
                    return new[]
                    {
                        new Vector2(0f, -2f),
                        new Vector2(-13f, -9f),
                        new Vector2(13f, -9f),
                        new Vector2(-13f, 8f),
                        new Vector2(13f, 8f)
                    };

                default:
                    return new[]
                    {
                        new Vector2(0f, -4f),
                        new Vector2(-26f, -13f),
                        new Vector2(26f, -13f),
                        new Vector2(-26f, 11f),
                        new Vector2(26f, 11f)
                    };
            }
        }
    }

    /// <summary>
    /// 全息面板组。默认值直接来自契约表 v1.1 的视野角度与仪表距离区间。
    /// 它是"内容"而不是"能力"，所以做资产；能力那部分留在 PlatformProfile。
    /// </summary>
    [CreateAssetMenu(fileName = "HoloDeck", menuName = "Steel Ridge/全息面板组", order = 2)]
    public class HoloDeck : ScriptableObject
    {
        public List<HoloPanelDef> panels = new List<HoloPanelDef>();

        /// <summary>契约 dashNear / dashFar，用于校验面板距离是否落在可交互区间。</summary>
        public float dashNear = 0.60f;
        public float dashFar = 0.90f;

        public HoloPanelDef Find(string id)
        {
            for (int i = 0; i < panels.Count; i++)
                if (panels[i].id == id) return panels[i];
            return null;
        }

        /// <summary>契约默认五块。顺序即优先级：先核心，再次要，最后环境。</summary>
        public static HoloDeck CreateDefault()
        {
            var d = CreateInstance<HoloDeck>();
            d.name = "HoloDeck_Default";
            d.panels = new List<HoloPanelDef>
            {
                new HoloPanelDef
                {
                    id = "hud_center", priority = PanelPriority.Critical,
                    yaw = 0f, pitch = -2f, distance = 0.75f,
                    size = new Vector2(0.40f, 0.14f), hideWhenOutOfFov = false
                },
                new HoloPanelDef
                {
                    id = "nav_bottom", priority = PanelPriority.Critical,
                    yaw = 0f, pitch = -11f, distance = 0.80f,
                    size = new Vector2(0.56f, 0.16f), hideWhenOutOfFov = false
                },
                new HoloPanelDef
                {
                    id = "sys_left", priority = PanelPriority.Secondary,
                    yaw = -25f, pitch = 2f, distance = 0.85f,
                    size = new Vector2(0.34f, 0.22f), hideWhenOutOfFov = false
                },
                new HoloPanelDef
                {
                    id = "sys_right", priority = PanelPriority.Secondary,
                    yaw = 25f, pitch = 2f, distance = 0.85f,
                    size = new Vector2(0.34f, 0.22f), hideWhenOutOfFov = false
                },
                new HoloPanelDef
                {
                    id = "threat_top", priority = PanelPriority.Ambient,
                    yaw = 0f, pitch = 14f, distance = 0.90f,
                    size = new Vector2(0.50f, 0.12f), hideWhenOutOfFov = true
                }
            };
            return d;
        }

        /// <summary>
        /// 窄视场三块版。给 43°×28° 一类光学透视设备用。
        /// 关键点：**不是把五块压回视场，而是减少块数**。
        /// 五块硬压的结果是全部挤在中央互相遮挡，读起来比三块更差。
        /// </summary>
        public static HoloDeck CreateCompact()
        {
            var d = CreateInstance<HoloDeck>();
            d.name = "HoloDeck_Compact";
            d.panels = new List<HoloPanelDef>
            {
                new HoloPanelDef
                {
                    id = "hud_center", priority = PanelPriority.Critical,
                    yaw = 0f, pitch = -2f, distance = 0.75f,
                    size = new Vector2(0.32f, 0.12f), hideWhenOutOfFov = false
                },
                new HoloPanelDef
                {
                    id = "nav_bottom", priority = PanelPriority.Critical,
                    yaw = 0f, pitch = -7f, distance = 0.75f,
                    size = new Vector2(0.44f, 0.12f), hideWhenOutOfFov = false
                },
                new HoloPanelDef
                {
                    id = "status_top", priority = PanelPriority.Secondary,
                    yaw = 0f, pitch = 9f, distance = 0.85f,
                    size = new Vector2(0.30f, 0.08f), hideWhenOutOfFov = false
                }
            };
            return d;
        }

        /// <summary>
        /// 面板组自检。
        /// <paramref name="hasWorldScale"/> = false（3DoF，真实世界尺度不可观测）时，
        /// 跳过 dashNear–dashFar 的米级检查 —— 那组区间是"手臂可及距离"的物理断言，
        /// 纯旋转设备上无法验证；改为只查角度，因为角尺寸才是这个形态下唯一可观测的量。
        /// </summary>
        public List<string> Validate(bool hasWorldScale = true)
        {
            var issues = new List<string>();

            if (panels == null || panels.Count == 0)
            {
                issues.Add("面板组为空");
                return issues;
            }

            var ids = new HashSet<string>();

            foreach (var p in panels)
            {
                if (string.IsNullOrEmpty(p.id)) issues.Add("存在空 id 的面板");
                else if (!ids.Add(p.id)) issues.Add($"面板 id 重复：{p.id}");

                if (hasWorldScale && (p.distance < dashNear || p.distance > dashFar))
                    issues.Add($"{p.id}：距离 {p.distance:0.00} m 不在交互区间 {dashNear:0.00}–{dashFar:0.00} m");

                if (p.size.x <= 0.01f || p.size.y <= 0.01f)
                    issues.Add($"{p.id}：尺寸异常 {p.size.x:0.00}×{p.size.y:0.00} m");

                // 角尺寸检查与尺度无关，任何平台都必须过：单块面板不该占掉半个视场
                float hwH = Mathf.Atan2(Mathf.Max(0.001f, p.size.x) * 0.5f, Mathf.Max(0.05f, p.distance)) * Mathf.Rad2Deg;
                float hwV = Mathf.Atan2(Mathf.Max(0.001f, p.size.y) * 0.5f, Mathf.Max(0.05f, p.distance)) * Mathf.Rad2Deg;
                if (hwH > 45f || hwV > 30f)
                    issues.Add($"{p.id}：角半宽 {hwH:0.#}°×{hwV:0.#}° 过大，单块面板不该占掉半个视场");

                if (Mathf.Abs(p.pitch) > 30f || Mathf.Abs(p.yaw) > 40f)
                    issues.Add($"{p.id}：偏角 {p.yaw:0}°/{p.pitch:0}° 过大，超出契约视窗");
            }

            // 面板之间不能互相遮挡：同一方向上的两块面板角距必须大于各自半宽
            for (int i = 0; i < panels.Count; i++)
            {
                for (int j = i + 1; j < panels.Count; j++)
                {
                    float sep = Mathf.Sqrt(
                        Mathf.Pow(panels[i].yaw - panels[j].yaw, 2f) +
                        Mathf.Pow(panels[i].pitch - panels[j].pitch, 2f));

                    float hwI = Mathf.Atan2(Mathf.Max(panels[i].size.x, panels[i].size.y) * 0.5f, panels[i].distance) * Mathf.Rad2Deg;
                    float hwJ = Mathf.Atan2(Mathf.Max(panels[j].size.x, panels[j].size.y) * 0.5f, panels[j].distance) * Mathf.Rad2Deg;

                    if (sep < (hwI + hwJ) * 0.6f)
                        issues.Add($"{panels[i].id} 与 {panels[j].id} 角距仅 {sep:0.#}°，可能互相遮挡");
                }
            }

            return issues;
        }
    }

    /// <summary>
    /// 面板组运行时装载器。把角度定义解算成子节点位姿，并按视场决定隐藏/压回/召唤。
    /// 不实例化 prefab：白盒阶段面板就是空 GameObject，S2 再挂真实 UI。
    /// </summary>
    public sealed class HoloDeckRuntime : MonoBehaviour
    {
        [Tooltip("眼位（相机）。面板以它为原点按角度布放")]
        public Transform eye;

        [Tooltip("面板组的父节点（通常与眼位同源，逻辑坐标一致）")]
        public Transform deckRoot;

        public HoloDeck deck;

        [Tooltip("窄视场替身面板组（可选）。安全区为 Narrow/Standard 时自动切换")]
        public HoloDeck compactDeck;

        [Tooltip("窄视场下是否自动切到 compactDeck")]
        public bool autoCompactForNarrowFov = true;

        public readonly Dictionary<string, PanelPlacement> Placements = new Dictionary<string, PanelPlacement>();

        PlatformCapabilities _caps;
        SafeZone _zone;
        HoloDeck _activeDeck;

        public SafeZone Zone => _zone;

        public HoloDeck ActiveDeck => _activeDeck;

        /// <summary>当前档位的 HUD 锚点（中心 + 四角）。UI 层按顺序取，不要自己算角度。</summary>
        public Vector2[] HudAnchors() => SafeZoneResolver.Anchors(_zone);

        public void Apply(in PlatformCapabilities caps)
        {
            _caps = caps;
            _zone = SafeZoneResolver.From(caps);

            if (deck == null)
            {
                Debug.LogWarning("[SteelRidge] HoloDeckRuntime 未指定面板组");
                return;
            }

            // 窄视场先换面板组，再谈压回：块数不对的话，压回只会把东西挤在一起
            _activeDeck = (autoCompactForNarrowFov && compactDeck != null && _zone.Tier != SafeZoneTier.Wide)
                ? compactDeck
                : deck;

            Placements.Clear();

            foreach (var def in _activeDeck.panels)
            {
                var placement = HoloPanelLayout.Solve(def, caps);
                var effective = def;

                if (!placement.Fits)
                {
                    if (def.priority == PanelPriority.Ambient && def.hideWhenOutOfFov)
                    {
                        SetChildActive(def.id, false);
                        Placements[def.id] = placement;
                        continue;
                    }

                    // 核心与次要面板压回视场，绝不隐藏
                    effective = HoloPanelLayout.ClampIntoFov(def, caps);
                    placement = HoloPanelLayout.Solve(effective, caps);
                    placement.Note = "已压回视场：" + (effective.yaw != def.yaw ? $"yaw {def.yaw:0}→{effective.yaw:0}° " : "") +
                                     (effective.pitch != def.pitch ? $"pitch {def.pitch:0}→{effective.pitch:0}°" : "");
                }

                Placements[def.id] = placement;
                var t = FindChild(def.id);

                if (t != null)
                {
                    t.gameObject.SetActive(true);
                    t.localPosition = placement.LocalPosition;
                    t.localRotation = placement.LocalRotation;

                    // 面板尺寸按角度约束收缩：窄视场下同一块面板必须等比缩小，否则边缘出画
                    float availH = caps.HalfFovH(2f) - Mathf.Abs(effective.yaw);
                    float availV = caps.HalfFovV(2f) - Mathf.Abs(effective.pitch);
                    float shrinkH = placement.AngularHalfWidthH <= 0.01f ? 1f : availH / placement.AngularHalfWidthH;
                    float shrinkV = placement.AngularHalfWidthV <= 0.01f ? 1f : availV / placement.AngularHalfWidthV;
                    float shrink = Mathf.Clamp01(Mathf.Min(shrinkH, shrinkV));
                    t.localScale = new Vector3(shrink, shrink, 1f);
                }
            }

            Debug.Log($"[SteelRidge] 面板组装载：{caps.Name}｜{_zone}｜{Placements.Count} 块（{_activeDeck.name}）");
        }

        Transform FindChild(string id)
        {
            var root = deckRoot != null ? deckRoot : transform;
            for (int i = 0; i < root.childCount; i++)
            {
                var c = root.GetChild(i);
                if (c.name == id) return c;
            }
            return null;
        }

        void SetChildActive(string id, bool on)
        {
            var t = FindChild(id);
            if (t != null) t.gameObject.SetActive(on);
        }

        /// <summary>审计：每块面板在本设备上的结论。</summary>
        public List<string> Audit()
        {
            var lines = new List<string> { $"安全区：{_zone}" };
            var src = _activeDeck != null ? _activeDeck : deck;

            foreach (var kv in Placements)
            {
                var def = src != null ? src.Find(kv.Key) : null;
                string pri = def != null ? def.priority.ToString() : "?";
                float yaw = def != null ? def.yaw : 0f;
                float pitch = def != null ? def.pitch : 0f;

                lines.Add(kv.Value.Fits
                    ? $"[PASS] {kv.Key}（{pri}）yaw {yaw:0}° pitch {pitch:0}°"
                    : $"[ADJUST] {kv.Key}（{pri}）{kv.Value.Note}");
            }

            return lines;
        }
    }
}
