using UnityEngine;

namespace SteelRidge.Core.Platform
{
    /// <summary>
    /// 平台能力注册表。全项目只在这里读"当前设备能干什么"。
    /// gameplay 不得直接读 SystemInfo / 设备型号 / 厂商 SDK。
    /// </summary>
    public static class PlatformRegistry
    {
        public static PlatformCapabilities Current { get; private set; }

        public static bool IsInitialized { get; private set; }

        public static event System.Action<PlatformCapabilities> Changed;

        public static void Apply(PlatformProfile profile)
        {
            if (profile == null)
            {
                Debug.LogWarning("[SteelRidge] PlatformProfile 为空，回退到内置预设");
                Apply(BuiltinCapabilities.DebugFlat);
                return;
            }
            Apply(profile.ToCapabilities());
        }

        public static void Apply(in PlatformCapabilities caps)
        {
            Current = caps;
            IsInitialized = true;
            Debug.Log($"[SteelRidge] 平台能力已装载：{caps}");
            Changed?.Invoke(caps);
        }

        /// <summary>
        /// 没有 profile 资产时的兜底：从设备名猜一个，并且明确告诉你在猜。
        /// 猜错的代价只是审计不准，不会崩溃 —— 因为 gameplay 只看能力位。
        /// </summary>
        public static PlatformCapabilities AutoDetect()
        {
            string model = (SystemInfo.deviceModel ?? string.Empty).ToLowerInvariant();

            if (model.Contains("rokid"))
            {
                Debug.LogWarning($"[SteelRidge] 检测到 Rokid 设备（{SystemInfo.deviceModel}），按 AR 预设装载。请以实测视场复核。");
                return BuiltinCapabilities.RokidArStudio;
            }

            if (model.Contains("pico"))
            {
                return BuiltinCapabilities.PicoVR;
            }

#if UNITY_EDITOR
            Debug.Log("[SteelRidge] 编辑器环境，装载 DebugFlat 预设（可用菜单覆盖）");
            return BuiltinCapabilities.DebugFlat;
#else
            Debug.LogWarning($"[SteelRidge] 未识别设备 {SystemInfo.deviceModel}，按不透明 VR 预设装载");
            return BuiltinCapabilities.PicoVR;
#endif
        }

        public static void Reset()
        {
            IsInitialized = false;
            Current = default;
        }
    }

    /// <summary>
    /// 内置能力预设。放在代码里，保证"没有 profile 资产也能跑审计"。
    /// 标注「折算」的视场是由对角视场 + 画幅比推算的，验收前必须实测替换。
    /// </summary>
    public static class BuiltinCapabilities
    {
        /// <summary>编辑器/平面调试：视场按显示器估计，仅用于跑通逻辑。</summary>
        public static PlatformCapabilities DebugFlat => new PlatformCapabilities
        {
            Name = "编辑器平面调试",
            Display = DisplayMode.OpaqueVR,
            Translation = TranslationSupport.None,
            Inputs = InputCapability.None,
            // 调试预设：无真实头显，米作为"第一人称代理"量有意义，故标 WorldMetric 以便走通米级代码路径
            Scale = ScaleGrounding.WorldMetric,
            FovHorizontal = 90f,
            FovVertical = 55f,
            PixelsPerDegree = 30f,
            MaxTranslationMeters = 0f,
            RefreshHz = 60
        };

        /// <summary>PICO 4 / PICO Space 一类不透明 VR。视场按官方 ~105° 对角折算。</summary>
        public static PlatformCapabilities PicoVR => new PlatformCapabilities
        {
            Name = "PICO 4（不透明 VR）",
            Display = DisplayMode.OpaqueVR,
            Translation = TranslationSupport.SeatedClamp,
            Inputs = InputCapability.Controller6DoF | InputCapability.EyeTracking,
            Scale = ScaleGrounding.WorldMetric,
            FovHorizontal = 96f,
            FovVertical = 62f,
            PixelsPerDegree = 20f,
            SupportsPassthrough = true,
            SupportsOcclusion = false,
            SupportsLightEstimation = false,
            MaxTranslationMeters = 0.15f,
            RefreshHz = 90
        };

        /// <summary>
        /// Rokid AR Studio：50° 对角 + 16:10 折算 ≈ 43°×28°，1920×1200 → 约 44 PPD。
        /// 无 6DoF 手柄，输入靠手势/射线/语音/Station 遥控。
        /// </summary>
        public static PlatformCapabilities RokidArStudio => new PlatformCapabilities
        {
            Name = "Rokid AR Studio（光学透视）",
            Display = DisplayMode.AdditiveAR,
            Translation = TranslationSupport.RoomScale,
            Inputs = InputCapability.HandTracking | InputCapability.HandRay |
                     InputCapability.Gaze | InputCapability.Voice | InputCapability.PhoneRemote,
            Scale = ScaleGrounding.WorldMetric,
            FovHorizontal = 43f,
            FovVertical = 28f,
            PixelsPerDegree = 44f,
            SupportsPassthrough = true,
            SupportsOcclusion = true,
            SupportsLightEstimation = true,
            MaxTranslationMeters = 0f,
            RefreshHz = 90
        };

        /// <summary>
        /// Rokid Glasses（2025）：30° 对角折算 ≈ 23°×20°，480×400 单绿 → 约 21 PPD。
        /// 这个形态跑不了实时 3D 座舱，只作为"能力下限"参照。
        /// 纯旋转（3DoF）→ 真实世界尺度不可观测，因此 Scale 必须为 HeadRelative。
        /// </summary>
        public static PlatformCapabilities RokidGlasses2025 => new PlatformCapabilities
        {
            Name = "Rokid Glasses（单绿 30°）",
            Display = DisplayMode.AdditiveAR,
            Translation = TranslationSupport.None,
            Inputs = InputCapability.Gaze | InputCapability.Voice | InputCapability.PhysicalButton,
            Scale = ScaleGrounding.HeadRelative,
            FovHorizontal = 23f,
            FovVertical = 20f,
            PixelsPerDegree = 21f,
            SupportsPassthrough = true,
            SupportsOcclusion = false,
            SupportsLightEstimation = false,
            MaxTranslationMeters = 0f,
            RefreshHz = 60
        };
    }
}
