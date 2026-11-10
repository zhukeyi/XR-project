using SteelRidge.Core.Audio;
using SteelRidge.Core.Holo;
using SteelRidge.Core.Inputs;
using SteelRidge.Core.Perf;
using SteelRidge.Core.Render;
using SteelRidge.Core.Spatial;
using UnityEngine;

namespace SteelRidge.Core.Platform
{
    /// <summary>
    /// 平台装配根。整个项目里唯一"知道所有子系统"的地方。
    /// 顺序固定：能力 → 空间 → 显示 → 音频 → 输入 → 面板 → 预算。
    /// 顺序不是审美问题：面板要读能力，显示要在相机清屏前定好，预算要在最后采样。
    ///
    /// 场景里放一个即可。没有它，各子系统都只是躺着的类 —— 这正是不做这个组件的典型后果。
    /// </summary>
    [DefaultExecutionOrder(-1000)]
    public sealed class PlatformBootstrap : MonoBehaviour
    {
        [Tooltip("平台档案。留空则按设备名自动探测（并在 Console 里明确告知在猜）")]
        public PlatformProfile profile;

        [Tooltip("座舱根节点（ViewpointPolicy 会移动它）")]
        public Transform cockpitRoot;

        [Tooltip("视点（XR Origin 下的相机）")]
        public Transform viewpoint;

        [Tooltip("全息面板组运行时（可选）")]
        public HoloDeckRuntime holoDeck;

        public InputRouter Router { get; private set; }
        public PlatformCapabilities Caps { get; private set; }

        GroundAnchor _ground;
        ViewpointPolicy _view;
        OcclusionPolicy _occlusion;
        DisplayPolicyApplier _display;
        PerfBudgetEnforcer _perf;
        TrackingQualityMonitor _tracking;

        void Awake()
        {
            // 1. 能力
            Caps = profile != null ? profile.ToCapabilities() : PlatformRegistry.AutoDetect();
            PlatformRegistry.Apply(Caps);

            var issues = profile != null ? profile.Validate() : null;
            if (issues != null)
                foreach (var i in issues)
                    Debug.LogWarning($"[SteelRidge] 档案自检：{i}");

            // 2. 空间
            _ground = GroundAnchor.Ensure();
            _ground.Configure(Caps);

            if (cockpitRoot != null && viewpoint == null)
                viewpoint = Camera.main != null ? Camera.main.transform : null;

            if (cockpitRoot != null && viewpoint != null)
            {
                _view = cockpitRoot.GetComponent<ViewpointPolicy>();
                if (_view == null) _view = cockpitRoot.gameObject.AddComponent<ViewpointPolicy>();
                _view.Configure(Caps, cockpitRoot, viewpoint);
            }

            _occlusion = cockpitRoot != null
                ? cockpitRoot.GetComponentInChildren<OcclusionPolicy>()
                : FindAnyObjectByType<OcclusionPolicy>();

            if (_occlusion != null) _occlusion.Apply(Caps, new NullDepthSource());

            // 3. 显示
            _display = FindAnyObjectByType<DisplayPolicyApplier>();
            if (_display == null && Camera.main != null)
                _display = Camera.main.gameObject.AddComponent<DisplayPolicyApplier>();
            if (_display != null) _display.Apply(Caps);

            // 4. 音频
            SpatialAudio.Configure(Caps);

            // 5. 输入
            Router = new InputRouter();
            Router.Configure(Caps);
            BuildSources();

            // 6. 面板
            if (holoDeck != null)
            {
                if (holoDeck.deck == null) holoDeck.deck = HoloDeck.CreateDefault();
                holoDeck.Apply(Caps);
            }

            // 7. 预算
            _perf = GetComponent<PerfBudgetEnforcer>();
            if (_perf == null) _perf = gameObject.AddComponent<PerfBudgetEnforcer>();
            _perf.Apply(Caps);

            // 8. 跟踪质量。放最后：它只观测，不参与装配决策。
            //    未注入宿主来源时以 NullTrackingStateSource 启动，报告里是 N/A 而不是伪造满分。
            _tracking = GetComponent<TrackingQualityMonitor>();
            if (_tracking == null) _tracking = gameObject.AddComponent<TrackingQualityMonitor>();
            _tracking.Configure(Caps,
                profile != null ? profile.ToAcceptance() : TrackingAcceptance.From(Caps));

            Debug.Log($"[SteelRidge] 装配完成：{Caps}\n{string.Join("\n", Router.Audit())}");
        }

        void Update()
        {
            if (Router != null) Router.Tick(Time.deltaTime);
        }

        void BuildSources()
        {
            // 键盘永远第一位：编辑器与模拟器没有手柄时，它是唯一能让驾驶逻辑跑起来的东西
            Router.Add(new KeyboardDebugSource());

            if (Caps.Has6DoFController)
            {
                var stick = new ControllerStickSource();
                stick.SetNode(UnityEngine.XR.XRNode.RightHand);
                Router.Add(stick);
            }

            if (Caps.HasHandTracking)
                Router.Add(new HandPinchSource());

            if ((Caps.Inputs & InputCapability.Gaze) != 0)
            {
                // 刻意不把 viewpoint 当 Target：目标与相机同位时夹角恒为 0（零向量），
                // 停留计时永不打断 → PanelSelect 变成定时脉冲。S2 由 gameplay 指定真实
                // 可选目标（面板 / 目标锁定物）；在那之前本通道如实报 MISSING，不伪造。
                var gaze = new GazeSource
                {
                    DwellSeconds = Caps.IsAdditive ? 1.0f : 1.4f
                };
                Router.Add(gaze);
            }
        }

        /// <summary>
        /// 一键审计。输出能力矩阵、面板落位、输入降级、预算、显示约束。
        /// 这是"这套东西在 Rokid 上会怎样"的可执行答案，而不是嘴上说。
        /// </summary>
        public string BuildAuditReport()
        {
            var sb = new System.Text.StringBuilder();

            sb.AppendLine($"## 平台：{Caps}");
            sb.AppendLine();
            sb.AppendLine($"- 地面来源：{(_ground != null ? _ground.CurrentSource.ToString() : "未装配")}");
            sb.AppendLine($"- 视角模式：{(_view != null ? _view.Mode.ToString() : "未装配")}");
            sb.AppendLine($"- 遮挡模式：{(_occlusion != null ? _occlusion.Mode.ToString() : "未装配")}");
            sb.AppendLine($"- 显示约束：{(_display != null ? _display.Constraints.ToString() : "未装配")}");
            sb.AppendLine($"- 音频后端：{SpatialAudio.Backend?.Name}");
            sb.AppendLine($"- 帧预算：{(_perf != null ? _perf.Budget.ToString() : "未装配")}");
            sb.AppendLine();

            if (Router != null)
            {
                sb.AppendLine("### 输入降级");
                foreach (var l in Router.Audit()) sb.AppendLine("- " + l);
                sb.AppendLine();
            }

            if (holoDeck != null)
            {
                sb.AppendLine("### 面板落位");
                foreach (var l in holoDeck.Audit()) sb.AppendLine("- " + l);
                sb.AppendLine();
            }

            if (_tracking != null)
            {
                sb.AppendLine("### 跟踪质量");
                foreach (var l in _tracking.Evaluate()) sb.AppendLine("- " + l);
                sb.AppendLine();
            }

            return sb.ToString();
        }
    }
}
