using System;
using System.Collections.Generic;
using SteelRidge.Core.Platform;
using UnityEngine;

namespace SteelRidge.Core.Render
{
    /// <summary>混合语义。这是 AR 复用 VR 成果时第一个必须改的东西。</summary>
    public enum BlendSemantic
    {
        /// <summary>不透明：黑就是黑，可以清屏、可以暗场。</summary>
        Opaque = 0,

        /// <summary>加色：黑 = 透明，亮 = 可见。全息面板在光学透视下的正确解。</summary>
        Additive = 1,

        /// <summary>常规 Alpha 混合：AR 里仅用于需要"压暗真实世界"的元素（如提示面）。</summary>
        AlphaBlend = 2
    }

    /// <summary>
    /// 显示约束。从 PlatformCapabilities 派生，不落资产 ——
    /// 因为它全部是能力的函数，落资产只会带来"资产和代码不一致"这一种 bug。
    /// </summary>
    [Serializable]
    public struct DisplayConstraints
    {
        public BlendSemantic Blend;

        /// <summary>是否允许把"黑"当作背景。AR 下必须 false。</summary>
        public bool AllowBlackBackground;

        /// <summary>是否允许全屏后处理（bloom / 暗角 / 景深 / 色调映射曲线）。</summary>
        public bool AllowFullScreenPostFx;

        /// <summary>是否允许 bloom。加色叠加下 bloom 会把亮部糊成一片白。</summary>
        public bool AllowBloom;

        /// <summary>是否需要"描边替代阴影"：AR 里没有可控光源，靠轮廓读形。</summary>
        public bool RequireOutlineOverShadow;

        /// <summary>自发光亮度上限（倍数，1 = 材质的 HDR 强度 1）。AR 上过曝即不可读。</summary>
        public float MaxEmissiveIntensity;

        /// <summary>座舱壳体是否必须半透明。</summary>
        public bool ShellMustBeTransparent;

        /// <summary>是否需要环境光估计来驱动虚拟物亮度。</summary>
        public bool NeedsLightEstimation;

        /// <summary>相机清屏 alpha。AR = 0，VR = 1。</summary>
        public float ClearAlpha;

        public static DisplayConstraints From(in PlatformCapabilities caps)
        {
            if (!caps.IsAdditive)
            {
                return new DisplayConstraints
                {
                    Blend = BlendSemantic.Opaque,
                    AllowBlackBackground = true,
                    AllowFullScreenPostFx = true,
                    AllowBloom = true,
                    RequireOutlineOverShadow = false,
                    MaxEmissiveIntensity = 8f,
                    ShellMustBeTransparent = false,
                    NeedsLightEstimation = false,
                    ClearAlpha = 1f
                };
            }

            return new DisplayConstraints
            {
                Blend = BlendSemantic.Additive,
                AllowBlackBackground = false,
                AllowFullScreenPostFx = false,
                AllowBloom = false,
                RequireOutlineOverShadow = true,
                MaxEmissiveIntensity = 1.6f,
                ShellMustBeTransparent = true,
                NeedsLightEstimation = caps.SupportsLightEstimation,
                ClearAlpha = 0f
            };
        }

        /// <summary>面板材质该用哪种混合。</summary>
        public BlendSemantic PanelBlend => Blend == BlendSemantic.Additive ? BlendSemantic.Additive : BlendSemantic.Opaque;

        public override string ToString() =>
            $"{Blend}｜黑板 {(AllowBlackBackground ? "允许" : "禁止")}｜后处理 {(AllowFullScreenPostFx ? "允许" : "禁止")}｜自发光 ≤{MaxEmissiveIntensity:0.0}";
    }

    /// <summary>
    /// 把显示约束落到运行时：相机清屏、后处理开关、全局 shader 参数。
    /// 这是"gameplay 禁止依赖全屏后处理"这条纪律的执行者 —— 没有它，纪律只是文档里的一句话。
    /// </summary>
    [DefaultExecutionOrder(-500)]
    public sealed class DisplayPolicyApplier : MonoBehaviour
    {
        [Tooltip("主相机。留空则用 Camera.main")]
        public Camera targetCamera;

        [Tooltip("需要按显示语义开关的后处理 Volume（可留空，会自动扫描）")]
        public List<Component> postFxVolumes = new List<Component>();

        [Tooltip("AR 下自动扫描并禁用场景内所有 Volume")]
        public bool autoFindVolumes = true;

        public DisplayConstraints Constraints { get; private set; }
        public bool IsApplied { get; private set; }

        static readonly int EmissiveCapId = Shader.PropertyToID("_SR_EmissiveCap");
        static readonly int AdditiveModeId = Shader.PropertyToID("_SR_AdditiveMode");

        public void Apply(in PlatformCapabilities caps)
        {
            Constraints = DisplayConstraints.From(caps);

            var cam = targetCamera != null ? targetCamera : Camera.main;
            if (cam != null)
            {
                if (Constraints.AllowBlackBackground)
                {
                    cam.clearFlags = CameraClearFlags.SolidColor;
                    cam.backgroundColor = Color.black;
                }
                else
                {
                    // AR：清成完全透明，让透视层透出来
                    cam.clearFlags = CameraClearFlags.SolidColor;
                    cam.backgroundColor = new Color(0f, 0f, 0f, 0f);
                }
            }

            if (!Constraints.AllowFullScreenPostFx)
                DisablePostFx();

            Shader.SetGlobalFloat(EmissiveCapId, Constraints.MaxEmissiveIntensity);
            Shader.SetGlobalFloat(AdditiveModeId, Constraints.Blend == BlendSemantic.Additive ? 1f : 0f);

            IsApplied = true;
            Debug.Log($"[SteelRidge] DisplayPolicy：{caps.Name} → {Constraints}");
        }

        void DisablePostFx()
        {
            if (autoFindVolumes)
            {
                // 反射找 Volume，避免对 URP 程序集的硬依赖（VR-only 构建也能编过）
                foreach (var mb in FindObjectsByType<MonoBehaviour>(FindObjectsInactive.Include, FindObjectsSortMode.None))
                {
                    if (mb == null) continue;
                    var t = mb.GetType();
                    if (t.Name != "Volume" && !t.Name.Contains("PostProcess")) continue;
                    if (!postFxVolumes.Contains(mb)) postFxVolumes.Add(mb);
                }
            }

            foreach (var v in postFxVolumes)
            {
                if (v == null) continue;
                var prop = v.GetType().GetProperty("enabled");
                if (prop != null && prop.CanWrite) prop.SetValue(v, false);
                else v.gameObject.SetActive(false);
            }

            if (postFxVolumes.Count == 0)
                Debug.Log("[SteelRidge] DisplayPolicy：未发现后处理 Volume，加色显示下这是正确状态");
        }

        /// <summary>自检：AR 下最容易犯的三个错。</summary>
        public List<string> Audit(in PlatformCapabilities caps)
        {
            var issues = new List<string>();
            var c = DisplayConstraints.From(caps);

            if (!IsApplied)
                issues.Add("DisplayPolicy 未执行 Apply：相机清屏与后处理开关都还是默认值");

            if (caps.IsAdditive && c.AllowFullScreenPostFx)
                issues.Add("加色设备仍允许全屏后处理");

            if (caps.IsAdditive && postFxVolumes.Count > 0)
            {
                foreach (var v in postFxVolumes)
                    if (v != null && !IsComponentEnabled(v))
                        return issues; // 已禁用，正确
                issues.Add($"加色设备下仍有 {postFxVolumes.Count} 个后处理 Volume 处于启用状态");
            }

            return issues;
        }

        static bool IsComponentEnabled(Component c)
        {
            var prop = c.GetType().GetProperty("enabled");
            if (prop != null) return (bool)prop.GetValue(c);
            return c.gameObject.activeSelf;
        }
    }

    /// <summary>
    /// 加色材质守卫。扫描指定 renderer，检查材质是否适合光学透视：
    /// 不透明黑底、依赖阴影、依赖光照 —— 这三类在 AR 里全部失效。
    /// 只报告不自动改材质：自动替换材质会把美术的意图抹掉，改材质必须是人的决定。
    /// </summary>
    public sealed class AdditiveMaterialGuard : MonoBehaviour
    {
        [Tooltip("需要检查的 renderer（全息面板、壳体、UI）")]
        public Renderer[] targets;

        [Tooltip("命名约定：名字里含该后缀的材质视为已有加色变体")]
        public string additiveVariantSuffix = "_Additive";

        /// <summary>
        /// 返回问题清单。caps 为非加色设备时直接返回空 —— 这条检查只对 AR 有意义。
        /// </summary>
        public List<string> Audit(in PlatformCapabilities caps)
        {
            var issues = new List<string>();
            if (!caps.IsAdditive || targets == null) return issues;

            foreach (var r in targets)
            {
                if (r == null) { issues.Add("targets 中存在空引用"); continue; }

                var mats = r.sharedMaterials;
                if (mats == null || mats.Length == 0)
                {
                    issues.Add($"{r.name}：没有材质");
                    continue;
                }

                foreach (var m in mats)
                {
                    if (m == null) continue;
                    string mn = m.name;

                    if (mn.Contains(additiveVariantSuffix)) continue;

                    if (m.IsKeywordEnabled("_ALPHABLEND_ON") == false && !IsTransparent(m))
                        issues.Add($"{r.name} / {mn}：不透明材质，AR 下会遮住真实世界（需要 {additiveVariantSuffix} 变体）");

                    if (m.HasProperty("_EmissiveIntensity") && m.GetFloat("_EmissiveIntensity") > 2f)
                        issues.Add($"{r.name} / {mn}：自发光强度 {m.GetFloat("_EmissiveIntensity"):0.0} 过高，AR 上会过曝成白块");

                    if (mn.Contains("Shadow") || mn.Contains("shadow"))
                        issues.Add($"{r.name} / {mn}：依赖阴影的材质，AR 里没有可控光源");
                }
            }

            return issues;
        }

        static bool IsTransparent(Material m)
        {
            if (m.renderQueue >= 3000) return true;
            if (m.HasProperty("_Surface")) return m.GetFloat("_Surface") > 0.5f;
            if (m.HasProperty("_Mode")) return Mathf.Approximately(m.GetFloat("_Mode"), 2f) || Mathf.Approximately(m.GetFloat("_Mode"), 3f);
            return false;
        }
    }
}
