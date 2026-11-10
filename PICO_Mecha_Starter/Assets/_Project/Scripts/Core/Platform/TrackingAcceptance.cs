using System.Collections.Generic;
using UnityEngine;

namespace SteelRidge.Core.Platform
{
    /// <summary>
    /// 跟踪质量验收门槛。四项指标取自 SLAM Handbook §18.8 的度量清单（第 3/4/5/9 项）。
    ///
    /// 为什么选这四项而不是"定位精度"：
    /// 精度需要外部真值（动捕系统），竞赛现场与客户现场都不具备；
    /// 而跟踪可用率、重定位成功率、帧时间是应用侧可自测的，
    /// 像素配准精度是全套指标里唯一需要一次人工标定的。
    /// 这四项合起来能回答"漂了怎么办"这个问题，而不需要承诺"不漂" —— 后者没人做得到。
    /// </summary>
    public struct TrackingAcceptance
    {
        /// <summary>跟踪可用率下限（Normal + Degraded 占全部有效帧）。</summary>
        public float MinTrackingRobustness;

        /// <summary>
        /// 完好率下限（仅 Normal 占全部有效帧）。
        /// 单独设一档的理由：VIO 在弱纹理、强逆光、纯旋转下必然降级，把降级算作失败会
        /// 让可用率永远不达标；但降级帧多到一定比例就是产品问题，不能混进可用率里掩盖。
        /// </summary>
        public float MinUndegradedRatio;

        /// <summary>重定位成功率下限（丢失后成功恢复的次数 / 有效丢失次数）。</summary>
        public float MinRelocalizationRobustness;

        /// <summary>平均恢复时间上限（秒）。</summary>
        public float MaxMeanRecoverySeconds;

        /// <summary>帧时间上限（毫秒）。与 PerfBudget 同源，都由 RefreshHz 决定。</summary>
        public float MaxFrameMs;

        /// <summary>
        /// AR 像素配准误差实测值（像素）。&lt; 0 表示未实测。
        /// 该值不可在应用内自动测量 —— 需要一次人工标定，见 PlatformAudit 的验收规程。
        /// </summary>
        public float ArPixelRegistrationError;

        /// <summary>AR 像素配准误差上限（像素）。</summary>
        public float MaxArPixelRegistrationError;

        public bool HasPixelRegistration => ArPixelRegistrationError > 0f;

        /// <summary>
        /// 按平台给出默认门槛。AR 一律比 VR 严：光学透视是把图形叠在真实世界上，
        /// 同样的抖动在 VR 里是"画面在晃"，在 AR 里是"世界在晃"，后者无法归因于内容。
        /// </summary>
        public static TrackingAcceptance From(in PlatformCapabilities caps)
        {
            bool ar = caps.IsAdditive;

            return new TrackingAcceptance
            {
                MinTrackingRobustness = ar ? 0.99f : 0.98f,
                MinUndegradedRatio = ar ? 0.90f : 0.85f,
                MinRelocalizationRobustness = ar ? 0.95f : 0.90f,
                MaxMeanRecoverySeconds = ar ? 1.5f : 2.0f,
                MaxFrameMs = 1000f / Mathf.Max(1, caps.RefreshHz),
                ArPixelRegistrationError = -1f,
                MaxArPixelRegistrationError = 1.5f
            };
        }

        public List<string> Validate()
        {
            var issues = new List<string>();

            if (MinTrackingRobustness <= 0f || MinTrackingRobustness > 1f)
                issues.Add($"跟踪可用率门槛 {MinTrackingRobustness:P0} 不在 (0,1] 区间");
            if (MinUndegradedRatio > MinTrackingRobustness)
                issues.Add($"完好率门槛 {MinUndegradedRatio:P0} 高于可用率门槛 {MinTrackingRobustness:P0}，逻辑矛盾");
            if (MinRelocalizationRobustness <= 0f || MinRelocalizationRobustness > 1f)
                issues.Add($"重定位成功率门槛 {MinRelocalizationRobustness:P0} 不在 (0,1] 区间");
            if (MaxMeanRecoverySeconds <= 0f)
                issues.Add("平均恢复时间上限未填");
            if (MaxArPixelRegistrationError <= 0f)
                issues.Add("像素配准误差上限未填");

            return issues;
        }

        public override string ToString() =>
            $"跟踪可用率 ≥{MinTrackingRobustness:P0}｜完好率 ≥{MinUndegradedRatio:P0}｜" +
            $"重定位 ≥{MinRelocalizationRobustness:P0}｜恢复 ≤{MaxMeanRecoverySeconds:0.0} s｜" +
            $"帧时间 ≤{MaxFrameMs:0.0} ms｜配准 ≤{MaxArPixelRegistrationError:0.0} px";
    }
}
