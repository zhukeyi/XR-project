using UnityEngine;

namespace SteelRidge.Core.Platform
{
    /// <summary>显示语义。决定座舱能不能靠"黑"遮住真实世界。</summary>
    public enum DisplayMode
    {
        /// <summary>不透明 VR（PICO 4 / Space）。暗场成立，可用全屏后处理。</summary>
        OpaqueVR = 0,

        /// <summary>光学透视 AR。黑 = 透明，禁止依赖暗背景与 bloom。</summary>
        AdditiveAR = 1
    }

    /// <summary>位移支持。决定"把人钉在座椅上"这个假设还成不成立。</summary>
    public enum TranslationSupport
    {
        /// <summary>只有旋转（3DoF）。座椅锚定无意义。</summary>
        None = 0,

        /// <summary>有位移但被钳制（VR 坐姿，±0.15 m）。</summary>
        SeatedClamp = 1,

        /// <summary>房间尺度，用户会走动。座舱必须"随人走"或改为开放式。</summary>
        RoomScale = 2
    }

    /// <summary>
    /// 真实世界度量尺度的可观测性。
    /// 依据：纯旋转（3DoF）下尺度不可观测 —— SLAM Handbook §11.3.3 表 11.1。
    /// 这不是"精度差一点"，而是"这个量根本不存在"，所以必须显式建模；
    /// 零值取保守侧（HeadRelative），漏填只会让我们少做断言，不会做出无效断言。
    /// </summary>
    public enum ScaleGrounding
    {
        /// <summary>真实世界尺度未被测量。以米为单位的断言只相对头部渲染空间成立。</summary>
        HeadRelative = 0,

        /// <summary>真实世界尺度可观测。地面高度、面板物理尺寸、LOD 真实距离均有意义。</summary>
        WorldMetric = 1
    }

    /// <summary>输入能力位标记。gameplay 只查能力，不查设备名。</summary>
    [System.Flags]
    public enum InputCapability
    {
        None = 0,
        Controller6DoF = 1 << 0,
        Controller3DoF = 1 << 1,
        HandTracking = 1 << 2,
        HandRay = 1 << 3,
        Gaze = 1 << 4,
        Voice = 1 << 5,
        PhoneRemote = 1 << 6,
        EyeTracking = 1 << 7,
        PhysicalButton = 1 << 8
    }

    /// <summary>
    /// 运行时能力快照。gameplay 只读这个结构体，不读 PlatformProfile 资产，也不读设备型号。
    /// 这样换设备时改的是 profile 资产，不是代码。
    /// </summary>
    public struct PlatformCapabilities
    {
        public string Name;
        public DisplayMode Display;
        public TranslationSupport Translation;
        public InputCapability Inputs;

        /// <summary>
        /// 真实世界尺度的可观测性。默认值 HeadRelative 是"保守失败侧"。
        /// 判读方式：为 false 时，凡是"这块面板在 0.75 m 外""地面在 y=0"这类断言，
        /// 都只是在渲染空间的相对口径下成立，不能写进验收报告，也不能作为美术比对标定。
        /// </summary>
        public ScaleGrounding Scale;

        /// <summary>水平视场（每眼，度）。</summary>
        public float FovHorizontal;

        /// <summary>垂直视场（每眼，度）。</summary>
        public float FovVertical;

        public float PixelsPerDegree;

        public bool SupportsPassthrough;
        public bool SupportsOcclusion;
        public bool SupportsLightEstimation;

        /// <summary>允许的头部位移上限（米）。RoomScale 时为 0 表示不限制。</summary>
        public float MaxTranslationMeters;

        public int RefreshHz;

        public bool IsAdditive => Display == DisplayMode.AdditiveAR;
        public bool Has6DoFController => (Inputs & InputCapability.Controller6DoF) != 0;
        public bool HasHandTracking => (Inputs & InputCapability.HandTracking) != 0;
        public bool HasRay => (Inputs & (InputCapability.Controller6DoF | InputCapability.HandRay)) != 0;
        public bool IsSeated => Translation != TranslationSupport.RoomScale;

        /// <summary>真实世界的"米"是否被测量到。false 时长度只相对头部渲染空间成立。</summary>
        public bool HasWorldScale => Scale == ScaleGrounding.WorldMetric;

        /// <summary>报告与 UI 用的长度口径标签，避免在 3DoF 设备上写"0.75 m"。</summary>
        public string LengthUnit => HasWorldScale ? "m" : "相对单位";

        /// <summary>可用的水平半视场（度）。加减 margin 给面板留边。</summary>
        public float HalfFovH(float marginDeg = 0f) => Mathf.Max(1f, FovHorizontal * 0.5f - marginDeg);

        public float HalfFovV(float marginDeg = 0f) => Mathf.Max(1f, FovVertical * 0.5f - marginDeg);

        public override string ToString() =>
            $"{Name}｜{Display}｜{FovHorizontal:0}×{FovVertical:0}°｜{PixelsPerDegree:0} PPD｜{Inputs}｜尺度 {Scale}";
    }

    /// <summary>
    /// 平台档案：一套能力 + 一套性能预算 + 一套布局约束。
    /// 一个项目可以有多个档案（VR / AR Studio / 眼镜），构建时选一个。
    /// </summary>
    [CreateAssetMenu(fileName = "PlatformProfile", menuName = "Steel Ridge/平台能力档案", order = 1)]
    public class PlatformProfile : ScriptableObject
    {
        [Header("识别")]
        public string displayName = "PICO 4（不透明 VR）";
        public string note = "";

        [Header("能力")]
        public DisplayMode displayMode = DisplayMode.OpaqueVR;
        public TranslationSupport translation = TranslationSupport.SeatedClamp;
        public InputCapability inputs = InputCapability.Controller6DoF | InputCapability.EyeTracking;

        [Tooltip("真实世界尺度是否可观测。纯旋转（3DoF）AR 必须设为 HeadRelative：此时以米为单位的尺寸只是渲染空间的相对量")]
        public ScaleGrounding scaleGrounding = ScaleGrounding.WorldMetric;

        [Tooltip("水平视场（每眼，度）")]
        public float fovHorizontal = 96f;

        [Tooltip("垂直视场（每眼，度）")]
        public float fovVertical = 62f;

        [Tooltip("每度像素数。决定文字最小字号：12px 字高约需 8 PPD 以上")]
        public float pixelsPerDegree = 20f;

        public bool supportsPassthrough = false;
        public bool supportsOcclusion = false;
        public bool supportsLightEstimation = false;

        [Tooltip("位移上限（米）。0 = 不限制（RoomScale）")]
        public float maxTranslationMeters = 0.15f;

        public int refreshHz = 90;

        [Header("性能预算（每帧）")]
        public int triangleBudget = 900_000;
        public int drawCallBudget = 200;
        public int materialBudget = 40;
        public int maxHoloPanels = 5;
        public int maxDynamicRenderTextures = 1;

        [Header("布局约束")]
        [Tooltip("UI 安全边距（度）。面板中心离视场边缘至少留这么多")]
        public float safeMarginDeg = 3f;

        [Tooltip("核心信息必须落在 ±该角度内（度）")]
        public float criticalHalfAngle = 20f;

        [Header("渲染约定")]
        [Tooltip("禁止依赖全屏后处理（bloom/暗角/景深）。加色混合下会糊成一片")]
        public bool forbidFullScreenPostFx = false;

        [Tooltip("座舱壳体是否需要改为半透明/线框")]
        public bool cockpitShellMustBeTransparent = false;

        [Header("跟踪质量验收（§18.8 四项指标）")]
        [Tooltip("跟踪可用率下限（正常 + 降级 占有效帧）。AR 建议 ≥99%，VR ≥98%")]
        [Range(0.5f, 1f)]
        public float minTrackingRobustness = 0.98f;

        [Tooltip("完好率下限（仅正常 占有效帧）。降级帧多到一定比例即产品问题，不能混进可用率掩盖")]
        [Range(0.5f, 1f)]
        public float minUndegradedRatio = 0.85f;

        [Tooltip("重定位成功率下限（丢失后成功恢复 / 有效丢失次数）")]
        [Range(0.5f, 1f)]
        public float minRelocalizationRobustness = 0.90f;

        [Tooltip("平均恢复时间上限（秒）")]
        public float maxMeanRecoverySeconds = 2f;

        [Tooltip("AR 像素配准误差实测值（像素）。-1 = 未实测，报告里显式写 N/A 而不是 0")]
        public float arPixelRegistrationError = -1f;

        [Tooltip("AR 像素配准误差上限（像素）。这是唯一一处阈值定义：验收判定、档案自检、" +
                 "记录窗口三处都读它，避免各写一个数")]
        public float maxArPixelRegistrationError = 1.5f;

        public PlatformCapabilities ToCapabilities()
        {
            return new PlatformCapabilities
            {
                Name = displayName,
                Display = displayMode,
                Translation = translation,
                Inputs = inputs,
                Scale = scaleGrounding,
                FovHorizontal = fovHorizontal,
                FovVertical = fovVertical,
                PixelsPerDegree = pixelsPerDegree,
                SupportsPassthrough = supportsPassthrough,
                SupportsOcclusion = supportsOcclusion,
                SupportsLightEstimation = supportsLightEstimation,
                MaxTranslationMeters = maxTranslationMeters,
                RefreshHz = refreshHz
            };
        }

        /// <summary>帧预算（毫秒）。90Hz = 11.1 ms。</summary>
        public float FrameBudgetMs => 1000f / Mathf.Max(1, refreshHz);

        /// <summary>验收门槛。像素配准实测值随档案一起交付，便于比对两次标定。</summary>
        public TrackingAcceptance ToAcceptance()
        {
            return new TrackingAcceptance
            {
                MinTrackingRobustness = minTrackingRobustness,
                MinUndegradedRatio = minUndegradedRatio,
                MinRelocalizationRobustness = minRelocalizationRobustness,
                MaxMeanRecoverySeconds = maxMeanRecoverySeconds,
                MaxFrameMs = FrameBudgetMs,
                ArPixelRegistrationError = arPixelRegistrationError,
                MaxArPixelRegistrationError = maxArPixelRegistrationError > 0f
                    ? maxArPixelRegistrationError
                    : 1.5f
            };
        }

        /// <summary>档案自检：数值是否自相矛盾。</summary>
        public System.Collections.Generic.List<string> Validate()
        {
            var issues = new System.Collections.Generic.List<string>();

            if (fovHorizontal <= 10f || fovVertical <= 10f)
                issues.Add($"{displayName}：视场 {fovHorizontal}×{fovVertical}° 不合理");
            if (fovVertical > fovHorizontal)
                issues.Add($"{displayName}：垂直视场大于水平，检查是否填反");
            if (criticalHalfAngle > fovHorizontal * 0.5f - safeMarginDeg)
                issues.Add($"{displayName}：核心区 ±{criticalHalfAngle}° 超出可用视场 ±{fovHorizontal * 0.5f - safeMarginDeg:0.#}°");
            if (displayMode == DisplayMode.AdditiveAR && !forbidFullScreenPostFx)
                issues.Add($"{displayName}：加色显示却允许全屏后处理，bloom 会盖住真实世界");
            if (displayMode == DisplayMode.AdditiveAR && !cockpitShellMustBeTransparent)
                issues.Add($"{displayName}：加色显示下座舱壳体必须半透明，否则整块变黑");
            if (translation == TranslationSupport.None && maxTranslationMeters > 0.001f)
                issues.Add($"{displayName}：3DoF 设备却设置了位移上限 {maxTranslationMeters}");

            // AR + 3DoF = 纯旋转，尺度不可观测（SLAM Handbook §11.3.3 表 11.1）。
            // 不透明 VR 的 3DoF 预设只在编辑器调试里出现，不纳入此判据。
            if (translation == TranslationSupport.None && displayMode == DisplayMode.AdditiveAR
                && scaleGrounding == ScaleGrounding.WorldMetric)
                issues.Add($"{displayName}：AR 3DoF 却声明真实世界尺度可观测 —— 纯旋转下尺度不可观测，应设为 HeadRelative");
            if (triangleBudget <= 0 || drawCallBudget <= 0)
                issues.Add($"{displayName}：性能预算未填");
            if (pixelsPerDegree < 8f)
                issues.Add($"{displayName}：{pixelsPerDegree} PPD 低于 8，中文小字不可读");

            if (minUndegradedRatio > minTrackingRobustness)
                issues.Add($"{displayName}：完好率门槛 {minUndegradedRatio:P0} 高于可用率门槛 {minTrackingRobustness:P0}，逻辑矛盾");
            if (minTrackingRobustness <= 0f || minTrackingRobustness > 1f)
                issues.Add($"{displayName}：跟踪可用率门槛 {minTrackingRobustness:P0} 不在 (0,1]");
            if (maxMeanRecoverySeconds <= 0f)
                issues.Add($"{displayName}：平均恢复时间上限未填");

            if (maxArPixelRegistrationError <= 0f)
                issues.Add($"{displayName}：AR 像素配准上限未填（应给正数，默认 1.5 px）");

            // 已实测且超限才算问题。未实测（-1）不报错，但审计报告里会显式列出 N/A。
            // 阈值只从 maxArPixelRegistrationError 取，不在这里另写一个数。
            if (displayMode == DisplayMode.AdditiveAR && arPixelRegistrationError > 0f
                && arPixelRegistrationError > maxArPixelRegistrationError)
                issues.Add($"{displayName}：AR 像素配准误差 {arPixelRegistrationError:0.00} px 超过上限 " +
                           $"{maxArPixelRegistrationError:0.00} px（在 {pixelsPerDegree:0} PPD 上约 " +
                           $"{arPixelRegistrationError / Mathf.Max(1f, pixelsPerDegree) * 60f:0.0}′ 视角，叠加在真实边缘会显脏）");

            return issues;
        }
    }
}
