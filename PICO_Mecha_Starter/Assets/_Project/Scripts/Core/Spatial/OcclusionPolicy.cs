using SteelRidge.Core.Platform;
using UnityEngine;
using UnityEngine.Rendering;

namespace SteelRidge.Core.Spatial
{
    /// <summary>遮挡语义。光学透视下"遮挡"只有三种可能，没有第四种。</summary>
    public enum OcclusionMode
    {
        /// <summary>壳体不透明，靠几何挡住后面的一切（VR）。</summary>
        ShellOpaque = 0,

        /// <summary>真实深度与虚拟深度做软比较，虚拟物被真实物体挡住（AR + 深度传感器）。</summary>
        DepthSoft = 1,

        /// <summary>无深度可用：壳体必须消失，改用极低的"空间提示面"保留体积感。</summary>
        None = 2
    }

    /// <summary>
    /// 真实深度来源。AR 侧由宿主（深度传感器 / 平面 + 环境理解）实现，
    /// 本接口不依赖任何 AR SDK，保证 VR 构建不被拖进来。
    /// </summary>
    public interface IRealDepthSource
    {
        string Name { get; }
        bool IsAvailable { get; }

        /// <summary>查询某世界方向上的真实表面距离（米）。false = 该方向无有效深度。</summary>
        bool TryGetSurfaceDistance(Vector3 worldOrigin, Vector3 worldDirection, out float meters);
    }

    public static class OcclusionResolver
    {
        /// <summary>
        /// 决定遮挡模式。注意 SupportsOcclusion 只是"设备理论上支持"，
        /// 还必须真的有深度来源；只有前者就当成有深度是常见的翻车点。
        /// </summary>
        public static OcclusionMode Resolve(in PlatformCapabilities caps, bool depthSourceAvailable)
        {
            if (!caps.IsAdditive) return OcclusionMode.ShellOpaque;
            return caps.SupportsOcclusion && depthSourceAvailable
                ? OcclusionMode.DepthSoft
                : OcclusionMode.None;
        }
    }

    /// <summary>
    /// 座舱遮挡策略。一个组件管三件事：
    /// 1) 壳体 renderer 的开关与透明度；
    /// 2) 深度软遮挡的全局开关（交给渲染管线读）；
    /// 3) AR 无深度时的替身 —— 极淡的空间提示面。
    ///
    /// 之所以集中在一个组件，是因为这三件事必须同时改；分开写必然出现
    /// "壳体关了但提示面没开"的黑屏中间态。
    /// </summary>
    public sealed class OcclusionPolicy : MonoBehaviour
    {
        [Header("壳体")]
        [Tooltip("座舱壳体 renderer。VR 里是全遮挡主力，AR 里必须淡出")]
        public Renderer[] shellRenderers;

        [Tooltip("AR 无深度时启用的线框/极淡替身（可选）")]
        public GameObject shellGhostProxy;

        [Tooltip("座舱内的地面与座椅面：AR 里保留，提供脚下与身后的体积感")]
        public Renderer[] interiorCueRenderers;

        [Header("参数")]
        [Range(0f, 0.5f)]
        [Tooltip("AR 下壳体保留的不透明度。0 = 完全消失；建议 0.04–0.10，仅作轮廓提示")]
        public float arShellAlpha = 0.06f;

        [Range(0f, 0.5f)]
        [Tooltip("AR 下地面/座椅提示面的不透明度")]
        public float arCueAlpha = 0.18f;

        [Tooltip("深度软遮挡的全局关键字（渲染管线侧读取）")]
        public string softOcclusionKeyword = "_SR_SOFT_OCCLUSION";

        public OcclusionMode Mode { get; private set; } = OcclusionMode.ShellOpaque;
        public IRealDepthSource DepthSource { get; private set; }

        MaterialPropertyBlock _mpb;
        static readonly int AlphaId = Shader.PropertyToID("_Alpha");
        static readonly int ColorAlphaId = Shader.PropertyToID("_Color");
        static readonly int BaseColorId = Shader.PropertyToID("_BaseColor");
        bool _warnedOpaqueMaterial;

        /// <summary>装配。depthSource 可为 null —— 那就是"设备号称支持但没接上"的常见情况。</summary>
        public void Apply(in PlatformCapabilities caps, IRealDepthSource depthSource = null)
        {
            DepthSource = depthSource;
            Mode = OcclusionResolver.Resolve(caps, depthSource != null && depthSource.IsAvailable);

            bool shellOn = Mode == OcclusionMode.ShellOpaque;
            SetRenderersEnabled(shellRenderers, shellOn);
            SetRenderersEnabled(interiorCueRenderers, shellOn);

            if (shellGhostProxy != null) shellGhostProxy.SetActive(Mode == OcclusionMode.None);

            if (Mode == OcclusionMode.ShellOpaque)
            {
                SetAlpha(shellRenderers, 1f);
                SetAlpha(interiorCueRenderers, 1f);
            }
            else
            {
                // AR：壳体保留极淡轮廓，提示面保留脚下
                SetRenderersEnabled(shellRenderers, true);
                SetRenderersEnabled(interiorCueRenderers, true);
                SetAlpha(shellRenderers, arShellAlpha);
                SetAlpha(interiorCueRenderers, arCueAlpha);

                // alpha 只是"请求"，材质本身必须是不透明以外的工作模式才会生效。
                // 这里只报告不改材质 —— 自动把 Opaque 改成 Transparent 会顺手关掉
                // 深度写入与阴影，属于会把美术意图抹掉的决定（同 AdditiveMaterialGuard 的纪律）。
                WarnIfOpaque(shellRenderers, "壳体");
            }

            Shader.SetGlobalFloat("_SR_OcclusionMode", (float)Mode);
            if (Mode == OcclusionMode.DepthSoft)
                Shader.EnableKeyword(softOcclusionKeyword);
            else
                Shader.DisableKeyword(softOcclusionKeyword);

            Debug.Log($"[SteelRidge] OcclusionPolicy：{caps.Name} → {Mode}" +
                      (Mode == OcclusionMode.None ? "（无深度来源，壳体已退为提示面）" : ""));
        }

        /// <summary>运行时暂停/恢复（例如用户摘镜、或切到纯 2D 预览）。</summary>
        public void SetPaused(bool paused)
        {
            if (Mode == OcclusionMode.ShellOpaque)
                SetRenderersEnabled(shellRenderers, !paused);
        }

        void SetAlpha(Renderer[] rs, float a)
        {
            if (rs == null || rs.Length == 0) return;
            _mpb ??= new MaterialPropertyBlock();

            foreach (var r in rs)
            {
                if (r == null) continue;
                r.GetPropertyBlock(_mpb);
                _mpb.SetFloat(AlphaId, a);
                // 三个都写：内置管线用 _Color，URP Lit 用 _BaseColor，自定义 shader 常用 _Alpha。
                // 只写其中一个的后果是"代码没错、画面是黑的"，最难查。
                _mpb.SetColor(ColorAlphaId, new Color(1f, 1f, 1f, a));
                _mpb.SetColor(BaseColorId, new Color(1f, 1f, 1f, a));
                r.SetPropertyBlock(_mpb);
            }
        }

        /// <summary>材质工作模式是否不是不透明。反射读不到属性时按"未知"处理，不误报。</summary>
        static bool LooksTransparent(Material m)
        {
            if (m.HasProperty("_Surface")) return m.GetFloat("_Surface") > 0.5f;       // URP: 0=Opaque 1=Transparent
            if (m.HasProperty("_Mode")) return m.GetFloat("_Mode") > 0.5f;             // 内置: 0=Opaque 1=Cutout …
            if (m.renderQueue >= 3000) return true;
            return true;                                                              // 无法判定：不报
        }

        void WarnIfOpaque(Renderer[] rs, string what)
        {
            if (_warnedOpaqueMaterial || rs == null) return;

            foreach (var r in rs)
            {
                if (r == null) continue;
                foreach (var m in r.sharedMaterials)
                {
                    if (m == null || LooksTransparent(m)) continue;
                    _warnedOpaqueMaterial = true;
                    Debug.LogWarning($"[SteelRidge] {what}材质 {m.name} 是不透明工作模式，" +
                                     $"写入的 alpha {arShellAlpha:0.00} 不会生效 —— AR 下这一块会显示为实心色块。" +
                                     "需要做透明/加色变体（AdditiveMaterialGuard 会列出全部受影响材质）。");
                    return;
                }
            }
        }

        static void SetRenderersEnabled(Renderer[] rs, bool on)
        {
            if (rs == null) return;
            foreach (var r in rs)
                if (r != null) r.enabled = on;
        }

        /// <summary>
        /// 遮挡自检：回答"这台设备上，我的虚拟物会不会盖在真实桌面上"。
        /// 返回空列表 = 语义自洽。
        /// </summary>
        public System.Collections.Generic.List<string> Audit(in PlatformCapabilities caps)
        {
            var issues = new System.Collections.Generic.List<string>();
            var mode = OcclusionResolver.Resolve(caps, DepthSource != null && DepthSource.IsAvailable);

            if (Mode != mode)
                issues.Add($"遮挡模式未同步：当前 {Mode}，应为 {mode}（是否忘了调用 Apply？）");

            if (caps.IsAdditive && (shellRenderers == null || shellRenderers.Length == 0))
                issues.Add("AR 下未登记壳体 renderer，无法淡出，座舱会变成一块黑");

            if (caps.IsAdditive && mode == OcclusionMode.None && shellGhostProxy == null)
                issues.Add("AR 无深度且没有线框替身：用户完全失去座舱体积感");

            if (!caps.IsAdditive && (shellRenderers == null || shellRenderers.Length == 0))
                issues.Add("VR 下未登记壳体 renderer：暗场不成立，外部环境会漏进来");

            if (caps.IsAdditive && mode == OcclusionMode.None && interiorCueRenderers != null)
            {
                foreach (var r in interiorCueRenderers)
                    if (r == null)
                        issues.Add("interiorCueRenderers 中存在空引用");
            }

            return issues;
        }
    }

    /// <summary>
    /// 测试/无深度时的空实现。显式返回 false，让 OcclusionResolver 落到 None，
    /// 而不是偷偷返回一个假距离把虚拟物挡掉一半。
    /// </summary>
    public sealed class NullDepthSource : IRealDepthSource
    {
        public string Name => "No depth";
        public bool IsAvailable => false;

        public bool TryGetSurfaceDistance(Vector3 worldOrigin, Vector3 worldDirection, out float meters)
        {
            meters = float.PositiveInfinity;
            return false;
        }
    }
}
