using SteelRidge.Core.Platform;
using UnityEngine;

namespace SteelRidge.Core.Spatial
{
    /// <summary>跟踪状态。零值取最坏，与 ScaleGrounding 同一纪律：漏赋值只会低估能力。</summary>
    public enum TrackingState
    {
        /// <summary>无跟踪。设备未上报、或定位系统尚未初始化。</summary>
        Unavailable = 0,

        /// <summary>丢失：位姿不可信。AR 里表现为图形脱锚，VR 里表现为画面冻结或漂移。</summary>
        Lost = 1,

        /// <summary>降级：位姿仍可用，但质量下降（弱纹理、强逆光、纯旋转、地图点稀疏）。</summary>
        Degraded = 2,

        /// <summary>正常。</summary>
        Normal = 3
    }

    /// <summary>
    /// 跟踪状态来源。由宿主注入（XR SDK 的 tracking state、或厂商 SDK 的 tracking quality 枚举）。
    /// 本层不引用任何 XR SDK —— 与 IGroundProvider / IRealDepthSource 同一模式，
    /// 保证同一份代码在 VR、AR、编辑器平面调试三种情形下都能编过。
    /// </summary>
    public interface ITrackingStateSource
    {
        string Name { get; }
        bool TryRead(out TrackingState state);
    }

    /// <summary>
    /// 未接入实现。TryRead 恒返回 false，监控器据此报"无数据"，
    /// **不伪造 Normal** —— 否则审计报告里会出现一个 100% 的假指标，
    /// 比没有指标更危险。
    /// </summary>
    public sealed class NullTrackingStateSource : ITrackingStateSource
    {
        public string Name => "未接入";
        public bool TryRead(out TrackingState state) { state = TrackingState.Unavailable; return false; }
    }

    /// <summary>
    /// 跟踪质量监控器。实现 SLAM Handbook §18.8 度量清单的 3/4/5 项（可用率、重定位成功率、延迟），
    /// 第 9 项（AR 像素配准）需要人工标定，因此只做记录与判定，不自动测量。
    ///
    /// 三条设计纪律：
    /// 1) **逐帧计数，不按采样间隔**。跟踪掉帧是毫秒级现象，4 Hz 采样会系统性漏掉短时丢失。
    /// 2) **短时抖动不算丢失事件**。低于 degradedGraceSeconds 的 Lost 归为噪声：
    ///    它是 XR 运行时正常的重投影行为，计成"丢失"会让重定位成功率毫无意义。
    /// 3) **启动宽限期内不计入分母**。定位系统冷启动必然有几百毫秒的 Unavailable，
    ///    计入分母会让短会话的可用率莫名其妙地低。
    /// </summary>
    [DefaultExecutionOrder(2000)]
    public sealed class TrackingQualityMonitor : MonoBehaviour
    {
        [Tooltip("启动宽限期（秒）。此期间的状态不计入统计分母")]
        public float startupGraceSeconds = 2f;

        [Tooltip("短于此时长的 Lost 视为瞬时抖动，不计为一次丢失事件")]
        public float degradedGraceSeconds = 0.4f;

        [Tooltip("累计运行多久后做一次越线告警（秒）。0 = 不告警")]
        public float warnAfterSeconds = 30f;

        ITrackingStateSource _source = new NullTrackingStateSource();
        TrackingAcceptance _accept;
        bool _configured;

        // ── 逐帧计数 ──
        int _frames;
        int _normal;
        int _degraded;
        int _lost;
        int _unavailable;

        // ── 丢失事件 ──
        int _lossEvents;          // 持续超过宽限期的丢失次数
        int _recoveries;          // 其中成功恢复的次数
        float _recoveredSeconds;  // 已恢复事件的时长累计
        float _worstRecoverySeconds;

        // ── 当前丢失段 ──
        bool _inLoss;
        bool _currentCounted;
        float _currentLossSeconds;

        // ── 帧时间 ──
        double _frameMsSum;
        float _frameMsMax;
        int _frameSamples;

        float _elapsed;
        bool _warned;

        public bool HasData => _frames > 0;
        public string SourceName => _source != null ? _source.Name : "未接入";
        public int ObservedFrames => _frames;
        public int LossEvents => _lossEvents;
        public int Recoveries => _recoveries;
        public float WorstRecoverySeconds => _worstRecoverySeconds;

        /// <summary>跟踪可用率：Normal + Degraded 占有效帧的比例。</summary>
        public float TrackingRobustness => _frames == 0 ? 0f : (float)(_normal + _degraded) / _frames;

        /// <summary>完好率：仅 Normal 占有效帧的比例。</summary>
        public float UndegradedRatio => _frames == 0 ? 0f : (float)_normal / _frames;

        /// <summary>重定位成功率：恢复次数 / 有效丢失次数。无丢失事件时记为 1（不是 0）。</summary>
        public float RelocalizationRobustness =>
            _lossEvents == 0 ? 1f : (float)_recoveries / _lossEvents;

        /// <summary>平均恢复时间（秒）。无恢复样本时为 0。</summary>
        public float MeanRecoverySeconds => _recoveries == 0 ? 0f : _recoveredSeconds / _recoveries;

        /// <summary>平均帧时间（毫秒）。这是 CPU 侧帧时间，不是运动到光子延迟。</summary>
        public float MeanFrameMs => _frameSamples == 0 ? 0f : (float)(_frameMsSum / _frameSamples);

        public float MaxFrameMs => _frameMsMax;
        public TrackingAcceptance Acceptance => _accept;

        public void Configure(in PlatformCapabilities caps, TrackingAcceptance acceptance,
                              ITrackingStateSource source = null)
        {
            _accept = acceptance;
            _source = source ?? new NullTrackingStateSource();
            _configured = true;
            Reset();

            Debug.Log($"[SteelRidge] 跟踪质量监控：{caps.Name}｜来源 {_source.Name}｜门槛 {_accept}");
        }

        public void SetSource(ITrackingStateSource source)
        {
            _source = source ?? new NullTrackingStateSource();
            Debug.Log($"[SteelRidge] 跟踪来源切换为 {_source.Name}");
        }

        public void Reset()
        {
            _frames = _normal = _degraded = _lost = _unavailable = 0;
            _lossEvents = _recoveries = 0;
            _recoveredSeconds = _worstRecoverySeconds = 0f;
            _inLoss = false;
            _currentCounted = false;
            _currentLossSeconds = 0f;
            _frameMsSum = 0;
            _frameMsMax = 0f;
            _frameSamples = 0;
            _elapsed = 0f;
            _warned = false;
        }

        void Update()
        {
            float dt = Time.unscaledDeltaTime;
            if (dt <= 0f) return;

            _elapsed += dt;

            // 帧时间统计：与跟踪状态无关，任何平台都要有
            _frameMsSum += dt * 1000.0;
            _frameSamples++;
            if (dt * 1000f > _frameMsMax) _frameMsMax = dt * 1000f;

            if (_elapsed < startupGraceSeconds) return;

            TrackingState state = TrackingState.Unavailable;
            bool hasReading = _source != null && _source.TryRead(out state);

            if (!hasReading)
            {
                // 无来源 / 来源读不到时**不进分母**（不进 _frames，也不计入 _unavailable），
                // 否则报告里会出现"不可用 500 帧 / 有效 300 帧"这种分子大于分母的怪数。
                // 让 HasData 保持 false，报告里显式写"未接入"。
                return;
            }

            _frames++;
            if (state == TrackingState.Normal) _normal++;
            else if (state == TrackingState.Degraded) _degraded++;
            else if (state == TrackingState.Lost) _lost++;
            else _unavailable++;

            AccountLoss(state == TrackingState.Lost, dt);

            if (!_warned && warnAfterSeconds > 0f && _elapsed >= warnAfterSeconds && _frames > 0)
            {
                _warned = true;
                if (TrackingRobustness < _accept.MinTrackingRobustness)
                {
                    Debug.LogWarning($"[SteelRidge] 跟踪可用率 {TrackingRobustness:P1} 低于门槛 " +
                                     $"{_accept.MinTrackingRobustness:P0}（{_frames} 帧，丢失事件 {_lossEvents} 次）");
                }
            }
        }

        /// <summary>
        /// 丢失事件记账。只有当一次丢失持续超过 degradedGraceSeconds 才升级为"事件"，
        /// 事件在跨越宽限期的那一刻就计数 —— 这样会话结束仍在丢失的情形也不会被漏掉。
        /// </summary>
        void AccountLoss(bool isLost, float dt)
        {
            if (isLost)
            {
                if (!_inLoss)
                {
                    _inLoss = true;
                    _currentCounted = false;
                    _currentLossSeconds = 0f;
                }

                _currentLossSeconds += dt;

                if (!_currentCounted && _currentLossSeconds >= degradedGraceSeconds)
                {
                    _currentCounted = true;
                    _lossEvents++;
                }

                return;
            }

            if (!_inLoss) return;

            // 恢复：只有升级为事件的那一段才计入成功重定位
            if (_currentCounted)
            {
                _recoveries++;
                _recoveredSeconds += _currentLossSeconds;
                if (_currentLossSeconds > _worstRecoverySeconds)
                    _worstRecoverySeconds = _currentLossSeconds;
            }

            _inLoss = false;
            _currentCounted = false;
            _currentLossSeconds = 0f;
        }

        /// <summary>
        /// 人工标定入口：把本次会话的判定基准改掉。
        /// 注意：只改内存里的 <see cref="TrackingAcceptance"/> 副本，**不落盘**。
        /// 要写回档案（下次启动仍生效），走菜单「平台 ▸ 记录 AR 像素配准误差」。
        /// 两个入口都在是刻意的：运行时要有地方记录，档案要有唯一事实来源。
        /// </summary>
        public void RecordPixelRegistration(float errorPixels)
        {
            _accept.ArPixelRegistrationError = errorPixels;
            Debug.Log($"[SteelRidge] AR 像素配准误差记录为 {errorPixels:0.00} px" +
                      (errorPixels <= _accept.MaxArPixelRegistrationError ? "（达标）" : "（超限）") +
                      "｜本次会话有效，写回档案请用菜单「平台 ▸ 记录 AR 像素配准误差」");
        }

        /// <summary>逐项判定。数据不足时给 [N/A]，不给 [PASS] —— 没有样本不等于通过。</summary>
        public System.Collections.Generic.List<string> Evaluate()
        {
            var lines = new System.Collections.Generic.List<string>();

            if (!_configured)
            {
                lines.Add("[N/A] 监控器未配置");
                return lines;
            }

            if (!HasData)
            {
                lines.Add($"[N/A] 跟踪来源{SourceName}（无有效样本，指标不可判定）");
                lines.Add($"- 帧时间：平均 {MeanFrameMs:0.0} ms / 峰值 {MaxFrameMs:0.0} ms（门槛 ≤{_accept.MaxFrameMs:0.0}）" +
                          (MeanFrameMs <= _accept.MaxFrameMs ? " [PASS]" : " [FAIL]"));
                lines.Add($"[N/A] AR 像素配准：{PixelText()}");
                return lines;
            }

            lines.Add(Verdict("跟踪可用率", TrackingRobustness, _accept.MinTrackingRobustness, "≥", "P1",
                              $"{_frames} 帧"));
            lines.Add(Verdict("完好率", UndegradedRatio, _accept.MinUndegradedRatio, "≥", "P1",
                              $"降级 {_degraded} 帧 / 丢失 {_lost} 帧 / 不可用 {_unavailable} 帧"));

            if (_lossEvents == 0)
                lines.Add("[PASS] 重定位成功率：会话内无超过宽限期的丢失事件（分母为 0，记满分）");
            else
                lines.Add(Verdict("重定位成功率", RelocalizationRobustness, _accept.MinRelocalizationRobustness,
                                  "≥", "P0", $"丢失 {_lossEvents} 次 / 恢复 {_recoveries} 次"));

            // 无恢复样本时 MeanRecoverySeconds 是 0，若照常判 ≤ 上限就永远是 PASS ——
            // 这是"没数据当满分"的典型形态，必须显式写 N/A。
            lines.Add(_recoveries == 0
                ? "[N/A] 平均恢复时间：本次会话没有恢复样本（无丢失事件或仅瞬时抖动），该指标不可判定"
                : Verdict("平均恢复时间", MeanRecoverySeconds, _accept.MaxMeanRecoverySeconds, "≤", "0.0",
                          $"最差 {_worstRecoverySeconds:0.00} s / {_recoveries} 个样本"));

            // 帧时间是"≤ 上限"，与上面几项方向相反，单独判
            lines.Add(MeanFrameMs <= _accept.MaxFrameMs
                ? $"[PASS] 帧时间：平均 {MeanFrameMs:0.0} ms ≤ {_accept.MaxFrameMs:0.0} ms（峰值 {MaxFrameMs:0.0} ms）"
                : $"[FAIL] 帧时间：平均 {MeanFrameMs:0.0} ms > {_accept.MaxFrameMs:0.0} ms（峰值 {MaxFrameMs:0.0} ms）");

            lines.Add(Acceptance.HasPixelRegistration
                ? (Acceptance.ArPixelRegistrationError <= Acceptance.MaxArPixelRegistrationError
                    ? $"[PASS] AR 像素配准：{Acceptance.ArPixelRegistrationError:0.00} px ≤ {Acceptance.MaxArPixelRegistrationError:0.0} px"
                    : $"[FAIL] AR 像素配准：{Acceptance.ArPixelRegistrationError:0.00} px > {Acceptance.MaxArPixelRegistrationError:0.0} px")
                : $"[N/A] AR 像素配准：未实测（需人工标定，见 PlatformAudit ⑤）");

            return lines;
        }

        string PixelText() => Acceptance.HasPixelRegistration
            ? $"{Acceptance.ArPixelRegistrationError:0.00} px"
            : "未实测";

        static string Verdict(string name, float actual, float threshold, string cmp, string fmt, string detail)
        {
            bool pass = cmp == "≥" ? actual >= threshold : actual <= threshold;
            string actualText = fmt == "P1" ? actual.ToString("P1") : actual.ToString(fmt);
            string thresholdText = fmt == "P1" ? threshold.ToString("P0") : threshold.ToString(fmt);
            return $"{(pass ? "[PASS]" : "[FAIL]")} {name}：{actualText} {cmp} {thresholdText}（{detail}）";
        }
    }
}
