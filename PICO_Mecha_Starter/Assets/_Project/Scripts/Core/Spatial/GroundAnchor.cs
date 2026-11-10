using System.Collections.Generic;
using SteelRidge.Core.Platform;
using UnityEngine;

namespace SteelRidge.Core.Spatial
{
    /// <summary>地面来源。决定"这台机甲站在哪"这个问题由谁回答。</summary>
    public enum GroundSource
    {
        /// <summary>虚拟静态地面（VR）。世界 y = 契约地平面。</summary>
        VirtualStatic = 0,

        /// <summary>平面检测（AR，宿主推送）。</summary>
        DetectedPlane = 1,

        /// <summary>深度网格（AR，宿主推送）。用于非平面地面。</summary>
        DepthMesh = 2,

        /// <summary>尚未解析。此时用眼高兜底，绝对不要返回"地面在 0"。</summary>
        Unresolved = 3
    }

    public struct GroundHit
    {
        public bool Valid;
        public GroundSource Source;
        public Vector3 Position;
        public Vector3 Normal;

        /// <summary>置信度 0–1。平面检测刚出现时为低值，UI 应据此淡入而不是硬切。</summary>
        public float Confidence;
    }

    /// <summary>
    /// 地面采样接口。实现者可以是静态平面、AR 平面检测、深度网格，或测试桩。
    /// 玩法只调用 TrySample，不知道也不需要知道背后是哪种。
    /// </summary>
    public interface IGroundProvider
    {
        GroundSource Source { get; }
        bool TrySample(Vector3 probeWorld, out GroundHit hit);
    }

    /// <summary>
    /// 静态虚拟地面。VR 侧默认实现：地面就在契约给的高度，永远可信。
    /// 这不是"没实现"，而是 VR 的正确解 —— 不需要检测，因为座舱是封闭的。
    /// </summary>
    public sealed class StaticGroundProvider : IGroundProvider
    {
        public GroundSource Source => GroundSource.VirtualStatic;

        /// <summary>地面世界高度（米）。默认 0，机甲脚底所在平面。</summary>
        public float PlaneY;

        public StaticGroundProvider(float planeY = 0f) => PlaneY = planeY;

        public bool TrySample(Vector3 probeWorld, out GroundHit hit)
        {
            hit = new GroundHit
            {
                Valid = true,
                Source = GroundSource.VirtualStatic,
                Position = new Vector3(probeWorld.x, PlaneY, probeWorld.z),
                Normal = Vector3.up,
                Confidence = 1f
            };
            return true;
        }
    }

    /// <summary>
    /// 平面检测地面。宿主（AR Foundation 的 ARPlaneManager、或厂商 SDK）每帧把平面推进来，
    /// 本类不引用任何 AR SDK —— 这是"同一份代码在 VR 和 AR 上都能编过"的前提。
    ///
    /// 三处与硬门限有关的设计：
    /// 1) **不用"倾角超 25° 就丢弃"的硬切**。硬门限在边界上产生跳变：平面从 24.9° 走到 25.1° 时，
    ///    来源会从 DetectedPlane 直接掉回 Unresolved，座舱 y 突跳。改为连续权重，让权重自己衰减到 0。
    /// 2) **补一维高度先验**。倾角判据抓不住"把桌面当地面"——桌面也是水平的。
    ///    用「期望地面点到平面的垂距」做第二维权重，桌面通常偏差 0.4 m 以上。
    /// 3) **多平面加权融合**，不取单一最优平面。最优平面切换时位置会跳，加权融合是连续的。
    ///    这是"从一组冲突的测量里提取真相"的最小实现（SLAM Handbook 尾声）。
    /// </summary>
    public sealed class DetectedPlaneProvider : IGroundProvider
    {
        public struct PlaneCandidate
        {
            public Vector3 Center;
            public Vector3 Normal;
            public Vector2 HalfExtent;
            public float Confidence;
            public float LastSeen;
        }

        public GroundSource Source => GroundSource.DetectedPlane;

        /// <summary>超过这个秒数没刷新就开始降权；再过同样时长即从池中移除。</summary>
        public float StaleSeconds = 2f;

        /// <summary>法线偏差在此角度内视为完全可信，之后开始平滑降权。</summary>
        public float SoftTiltDeg = 15f;

        /// <summary>法线偏差超过此角度权重归零。仍保留在池里，只是不参与融合。</summary>
        public float HardTiltDeg = 40f;

        /// <summary>期望地面点到平面的垂距容差（米）。超此值权重归零，用于排除桌面、台面。</summary>
        public float HeightToleranceMeters = 0.35f;

        /// <summary>融合后权重低于此值视为未解析，由 GroundAnchor 走眼高兜底。</summary>
        public float MinConfidence = 0.25f;

        /// <summary>探针落在平面范围外时的权重折减（不直接拒，靠置信度表达不确定性）。</summary>
        public float OutOfBoundsPenalty = 0.5f;

        readonly List<PlaneCandidate> _planes = new List<PlaneCandidate>();

        /// <summary>宿主调用：提交/更新一块平面。</summary>
        public void Submit(Vector3 center, Vector3 normal, Vector2 halfExtent,
                           float confidence, float now)
        {
            for (int i = 0; i < _planes.Count; i++)
            {
                var p = _planes[i];
                if ((p.Center - center).sqrMagnitude < 0.0004f)
                {
                    p.Center = center;
                    p.Normal = normal;
                    p.HalfExtent = halfExtent;
                    p.Confidence = confidence;
                    p.LastSeen = now;
                    _planes[i] = p;
                    return;
                }
            }

            _planes.Add(new PlaneCandidate
            {
                Center = center,
                Normal = normal,
                HalfExtent = halfExtent,
                Confidence = confidence,
                LastSeen = now
            });
        }

        public void Clear() => _planes.Clear();

        /// <summary>当前池中平面数（审计用）。</summary>
        public int Count => _planes.Count;

        /// <summary>
        /// 采样。probeWorld 是**期望地面点**（GroundAnchor 用「眼位 − 眼高」算出来的那个点），
        /// 不是眼位本身 —— 高度先验以此为基准，两者不能混。
        /// </summary>
        public bool TrySample(Vector3 probeWorld, out GroundHit hit)
        {
            hit = default;
            float now = Time.unscaledTime;

            Vector3 posAcc = Vector3.zero;
            Vector3 nrmAcc = Vector3.zero;
            float wSum = 0f;

            for (int i = _planes.Count - 1; i >= 0; i--)
            {
                var p = _planes[i];
                float age = now - p.LastSeen;

                if (age > StaleSeconds * 2f) { _planes.RemoveAt(i); continue; }

                float w = PlaneWeight(p, probeWorld, age);
                if (w <= 0.0001f) continue;

                var n = p.Normal.normalized;

                // ★ 位置取"探针在该平面上的投影"，不是平面中心。
                //   取中心会让机甲跳到检测平面的正中；检测到的是半块地面时就是一次可见位移。
                var onPlane = probeWorld - Vector3.Dot(probeWorld - p.Center, n) * n;

                posAcc += onPlane * w;
                nrmAcc += n * w;
                wSum += w;
            }

            if (wSum <= 0.0001f) return false;

            // 多平面重叠时不让置信度无限叠加，截断到 1
            float confidence = Mathf.Clamp01(wSum);
            if (confidence < MinConfidence) return false;

            hit = new GroundHit
            {
                Valid = true,
                Source = GroundSource.DetectedPlane,
                Position = posAcc / wSum,
                Normal = nrmAcc.sqrMagnitude > 1e-6f ? nrmAcc.normalized : Vector3.up,
                Confidence = confidence
            };
            return true;
        }

        /// <summary>单个平面的连续权重 0–1。四个因子连乘，任一因子归零即整体归零。</summary>
        float PlaneWeight(in PlaneCandidate p, Vector3 probeWorld, float age)
        {
            float w = Mathf.Clamp01(p.Confidence);
            if (w <= 0f) return 0f;

            // ① 法向贴合：软阈值内为 1，软→硬之间平滑衰减到 0
            float tilt = Vector3.Angle(p.Normal, Vector3.up);
            if (tilt >= HardTiltDeg) return 0f;
            if (tilt > SoftTiltDeg)
                w *= 1f - Mathf.SmoothStep(0f, 1f, (tilt - SoftTiltDeg) / Mathf.Max(0.01f, HardTiltDeg - SoftTiltDeg));

            // ② 新鲜度：StaleSeconds 内为 1，之后线性衰减，两个周期后移除
            if (age > StaleSeconds)
                w *= 1f - Mathf.Clamp01((age - StaleSeconds) / Mathf.Max(0.01f, StaleSeconds));

            var n = p.Normal.normalized;

            // ③ 高度先验：桌面、台面、货架隔板都是水平的，只能靠高度排除
            float distanceToPlane = Mathf.Abs(Vector3.Dot(probeWorld - p.Center, n));
            if (distanceToPlane >= HeightToleranceMeters) return 0f;
            w *= 1f - Mathf.SmoothStep(0f, 1f, distanceToPlane / Mathf.Max(0.01f, HeightToleranceMeters));

            // ④ 探针是否落在平面范围内：不在范围内只降权，不直接拒
            var toProbe = probeWorld - p.Center;
            var planar = toProbe - Vector3.Dot(toProbe, n) * n;
            // 法线与 forward 平行时叉积为零向量，normalized 后是 (0,0,0)，
            // 会让 u/v 恒为 0、inBounds 恒真 —— 虽然这种平面已被倾角判据排除，
            // 但零向量参与点乘是静默错误，这里显式换个参考轴。
            var right = Vector3.Cross(n, Vector3.forward);
            if (right.sqrMagnitude < 1e-6f) right = Vector3.Cross(n, Vector3.right);
            right.Normalize();
            var fwd = Vector3.Cross(right, n).normalized;
            float u = Vector3.Dot(planar, right);
            float v = Vector3.Dot(planar, fwd);
            bool inBounds = Mathf.Abs(u) <= p.HalfExtent.x && Mathf.Abs(v) <= p.HalfExtent.y;
            if (!inBounds) w *= Mathf.Clamp01(OutOfBoundsPenalty);

            return Mathf.Clamp01(w);
        }

        /// <summary>
        /// 审计用：单平面在"刚刷新、探针在范围内"条件下的稳态权重。
        /// 抽成公开方法是刻意的 —— 报告里的阈值必须由**实际代码**算出，
        /// 而不是另外手算一份公式贴进文档，否则代码改了报告不会跟着变。
        /// </summary>
        public float SteadyWeight(float hostConfidence, float tiltDeg, float heightOffsetMeters)
        {
            float w = Mathf.Clamp01(hostConfidence);
            if (w <= 0f) return 0f;

            if (tiltDeg >= HardTiltDeg) return 0f;
            if (tiltDeg > SoftTiltDeg)
                w *= 1f - Mathf.SmoothStep(0f, 1f, (tiltDeg - SoftTiltDeg) / Mathf.Max(0.01f, HardTiltDeg - SoftTiltDeg));

            if (heightOffsetMeters >= HeightToleranceMeters) return 0f;
            w *= 1f - Mathf.SmoothStep(0f, 1f, Mathf.Abs(heightOffsetMeters) / Mathf.Max(0.01f, HeightToleranceMeters));

            return Mathf.Clamp01(w);
        }

        /// <summary>
        /// 审计用：扫出"权重恰好跌破 MinConfidence"的临界角（度）。
        /// 返回 -1 表示在 0–89° 内始终不跌破。
        /// </summary>
        public float EffectiveTiltCutoffDeg(float hostConfidence = 0.8f, float heightOffsetMeters = 0.05f)
        {
            for (float t = 0f; t <= 89f; t += 0.5f)
                if (SteadyWeight(hostConfidence, t, heightOffsetMeters) < MinConfidence) return t;
            return -1f;
        }

        /// <summary>审计用：扫出临界高度偏差（米）。返回 -1 表示容差内始终达标。</summary>
        public float EffectiveHeightCutoffMeters(float hostConfidence = 0.8f, float tiltDeg = 3f)
        {
            for (float h = 0f; h <= HeightToleranceMeters; h += 0.005f)
                if (SteadyWeight(hostConfidence, tiltDeg, h) < MinConfidence) return h;
            return -1f;
        }
    }

    /// <summary>
    /// 地面锚点。全项目唯一回答"地面在哪"的组件。
    /// VR：静态平面，零成本；AR：等宿主推送平面，未推送时按眼高兜底并标记 Unresolved。
    /// 关键约束：**未解析时绝不允许返回 y=0**，否则机甲的脚会出现在用户头顶或脚下。
    ///
    /// 眼高为什么要分坐姿与站姿两档：这两个 1.15 与 1.65 是**不同的物理量**。
    /// 1.15 m 是契约里"舱地板→SeatAnchor"的坐姿眼高；1.65 m 是"真实地面→站立用户眼睛"的
    /// 人体假设。AR 房间尺度下用户是站着的，若沿用 1.15 m 去算探针，探针会浮在真实地面上方
    /// 约 0.5 m，直接超过 DetectedPlaneProvider 的高度容差（0.35 m）→ 真实地面权重恒为 0 →
    /// 平面检测永远 Unresolved，退回眼高兜底。这不是精度问题，是量纲用错。
    /// </summary>
    public sealed class GroundAnchor : MonoBehaviour
    {
        public static GroundAnchor Instance { get; private set; }

        /// <summary>坐姿眼高默认值（米）。等于契约 eyeHeightFromFloor。</summary>
        public const float DefaultSeatedEyeHeight = 1.15f;

        /// <summary>站姿眼高默认值（米）。中国成年男性均值，个体差异约 ±0.15 m。</summary>
        public const float DefaultStandingEyeHeight = 1.65f;

        [Tooltip("坐姿眼高（米）。VR 座舱：舱地板→眼位，等于契约 eyeHeightFromFloor = 1.15")]
        public float seatedEyeHeight = DefaultSeatedEyeHeight;

        [Tooltip("站姿眼高（米）。AR 房间尺度：真实地面→站立用户眼睛。1.65 = 中国成年男性均值，" +
                 "个体差异 ±0.15 m；这个误差就是高度先验的误差预算（见审计报告的地面置信度一节）")]
        public float standingEyeHeight = DefaultStandingEyeHeight;

        [Tooltip("座舱壳体是否需要贴地。AR 无地面检测时置 false")]
        public bool requireGround = true;

        IGroundProvider _provider = new StaticGroundProvider();
        PlatformCapabilities _caps;
        bool _configured;
        bool _warnedUnresolved;
        float _eyeHeight = 1.15f;

        public GroundSource CurrentSource => _provider?.Source ?? GroundSource.Unresolved;
        public bool IsResolved { get; private set; }
        public GroundHit LastHit { get; private set; }

        /// <summary>
        /// 眼高是否为假设值。true 表示本平台真实世界尺度不可观测（3DoF），
        /// <see cref="EffectiveEyeHeight"/> 只是取的默认人体眼高，不是测量值 ——
        /// 因此"地面在 y=0"这句话不能写进验收报告，也不能拿来判断机甲脚是否踩实。
        /// </summary>
        public bool EyeHeightAssumed => _configured && !_caps.HasWorldScale;

        /// <summary>当前生效的眼高（米）。由 <see cref="Configure"/> 按位移能力选定。</summary>
        public float EffectiveEyeHeight => _eyeHeight;

        /// <summary>
        /// 给定位移能力下应当采用的眼高。纯函数，审计与运行时共用同一判据，
        /// 避免"报告里写 1.65、代码里用 1.15"这类只在真机上暴露的错位。
        /// </summary>
        public float EyeHeightFor(in PlatformCapabilities caps) =>
            caps.Translation == TranslationSupport.RoomScale ? standingEyeHeight : seatedEyeHeight;

        public static GroundAnchor Ensure()
        {
            if (Instance != null) return Instance;
            var go = new GameObject("[GroundAnchor]");
            Instance = go.AddComponent<GroundAnchor>();
            return Instance;
        }

        void Awake()
        {
            if (Instance != null && Instance != this) { Destroy(this); return; }
            Instance = this;
        }

        /// <summary>
        /// 按平台能力切换地面来源。
        /// VR 用静态平面；AR 有房间尺度时用平面检测；
        /// 而**尺度不可观测的平台（3DoF AR）一律退回静态平面** ——
        /// 纯旋转下检测到的平面深度不可信，用一个"稳定但假设"的地面，
        /// 好过用一个"看起来在测但值会乱跳"的地面。
        /// </summary>
        public void Configure(in PlatformCapabilities caps, IGroundProvider provider = null)
        {
            _caps = caps;
            _configured = true;
            _warnedUnresolved = false;

            // 站姿 / 坐姿是两套物理量，不能共用一个默认值（见类注释）
            _eyeHeight = EyeHeightFor(caps);

            bool canDetect = caps.HasWorldScale
                             && (caps.IsAdditive || caps.Translation == TranslationSupport.RoomScale);

            if (provider != null)
            {
                _provider = provider;
            }
            else if (canDetect)
            {
                _provider = new DetectedPlaneProvider();
            }
            else
            {
                _provider = new StaticGroundProvider(0f);
            }

            string scaleNote = caps.HasWorldScale ? "" : "（尺度不可观测：眼高为假设值）";
            Debug.Log($"[SteelRidge] GroundAnchor 装配：{caps.Name} → {_provider.Source}" +
                      $"，眼高 {_eyeHeight:0.00} m{scaleNote}");
        }

        /// <summary>宿主注入平面（AR）。VR 下调用是空操作。</summary>
        public void SubmitPlane(Vector3 center, Vector3 normal, Vector2 halfExtent, float confidence = 0.8f)
        {
            if (_provider is DetectedPlaneProvider dp)
                dp.Submit(center, normal, halfExtent, confidence, Time.unscaledTime);
        }

        /// <summary>
        /// 解析地面位姿。eyeWorld = 当前视点世界坐标。
        /// 返回 false 时 pose 为兜底值（眼高以下），调用方必须读 Resolved 字段决定是否淡入。
        /// </summary>
        public bool TryResolve(Vector3 eyeWorld, out Pose pose)
        {
            var probe = new Vector3(eyeWorld.x, eyeWorld.y - _eyeHeight, eyeWorld.z);

            if (_provider != null && _provider.TrySample(probe, out var hit))
            {
                LastHit = hit;
                IsResolved = true;
                pose = new Pose(hit.Position, Quaternion.FromToRotation(Vector3.up, hit.Normal));
                return true;
            }

            IsResolved = false;
            pose = new Pose(new Vector3(eyeWorld.x, eyeWorld.y - _eyeHeight, eyeWorld.z), Quaternion.identity);

            // 只告警一次：TryResolve 每帧都可能被调用，逐帧刷日志会把真机的 logcat 淹掉，
            // 反而看不到第一次失败的原因。
            if (requireGround && _configured && !_warnedUnresolved)
            {
                _warnedUnresolved = true;
                Debug.LogWarning(EyeHeightAssumed
                    ? $"[SteelRidge] 地面未解析（{CurrentSource}），使用眼高兜底 y={pose.position.y:0.00}；" +
                      "本平台真实世界尺度不可观测，此高度为假设值"
                    : $"[SteelRidge] 地面未解析（{CurrentSource}），使用眼高兜底 y={pose.position.y:0.00}");
            }

            return false;
        }

        /// <summary>把某个物体摆到地面上（保持水平朝向）。</summary>
        public bool SnapToGround(Transform target, Vector3 eyeWorld)
        {
            if (target == null) return false;
            if (!TryResolve(eyeWorld, out var pose)) return false;

            var e = target.eulerAngles;
            target.SetPositionAndRotation(pose.position, Quaternion.Euler(0f, e.y, 0f));
            return true;
        }
    }
}
