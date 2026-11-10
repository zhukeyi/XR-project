using SteelRidge.Core.Platform;
using UnityEngine;
using UnityEngine.XR;

namespace SteelRidge.Core.Inputs
{
    /// <summary>
    /// 键盘/鼠标调试源。零依赖，编辑器和模拟器里都能用。
    /// 作用：没有设备时也能把驾驶逻辑跑通 —— 这是"白盒阶段不被硬件卡住"的关键。
    /// </summary>
    public sealed class KeyboardDebugSource : IInputSource
    {
        public string Name => "Keyboard/Mouse";
        public InputCapability Requires => InputCapability.None;

        public bool Supports(InputChannel channel)
        {
            switch (channel)
            {
                case InputChannel.SteerYaw:
                case InputChannel.SteerPitch:
                case InputChannel.Throttle:
                case InputChannel.Trigger:
                case InputChannel.Grip:
                case InputChannel.Boost:
                case InputChannel.Menu:
                case InputChannel.PanelSelect:
                    return true;
                default:
                    return false;
            }
        }

        public bool TryRead(InputChannel channel, out float value)
        {
            value = 0f;

#if ENABLE_LEGACY_INPUT_MANAGER
            switch (channel)
            {
                case InputChannel.SteerYaw:
                    value = Input.GetAxisRaw("Horizontal");
                    return Mathf.Abs(value) > 0.001f;

                case InputChannel.SteerPitch:
                    value = Input.GetAxisRaw("Vertical");
                    return Mathf.Abs(value) > 0.001f;

                case InputChannel.Throttle:
                    value = Input.GetKey(KeyCode.W) ? 1f : 0f;
                    return value > 0f;

                case InputChannel.Trigger:
                    value = Input.GetMouseButton(0) ? 1f : 0f;
                    return value > 0f;

                case InputChannel.Grip:
                    value = Input.GetMouseButton(1) ? 1f : 0f;
                    return value > 0f;

                case InputChannel.Boost:
                    value = Input.GetKey(KeyCode.LeftShift) ? 1f : 0f;
                    return value > 0f;

                case InputChannel.Menu:
                    value = Input.GetKeyDown(KeyCode.Escape) ? 1f : 0f;
                    return value > 0f;

                case InputChannel.PanelSelect:
                    value = Input.GetKeyDown(KeyCode.F) ? 1f : 0f;
                    return value > 0f;
            }
#endif
            return false;
        }

        public void Tick(float dt) { }
    }

    /// <summary>
    /// 6DoF 手柄源（PICO / Quest / 任何 OpenXR 运行时）。
    /// 只读 XR 通用 usage，不引用任何厂商 SDK，这是可移植的前提。
    ///
    /// 两个映射上的事实，写下来免得以后当成 bug 查：
    /// 1) 手柄没有"油门轴"。座舱内的油门真实来源是抓取 Pivot_Throttle（握持深度），
    ///    这里的摇杆映射只是调试便利；副摇杆不可用时退回主摇杆，会与 SteerPitch 抢同一根轴，
    ///    属于明确降级，因此只告警一次。
    /// 2) 8 个抽象通道必须全部有供给侧，否则真机上就是"某个功能按不出来"。
    ///    所以 Boost 与 PanelSelect 分别挂在主键（A/X）与副键（B/Y）上。
    /// </summary>
    public sealed class ControllerStickSource : IInputSource
    {
        public string Name => "XR Controller (6DoF)";
        public InputCapability Requires => InputCapability.Controller6DoF;

        XRNode _node = XRNode.RightHand;
        InputDevice _device;
        bool _warnedAxisConflict;

        public void SetNode(XRNode node) => _node = node;

        public bool Supports(InputChannel channel)
        {
            switch (channel)
            {
                case InputChannel.SteerYaw:
                case InputChannel.SteerPitch:
                case InputChannel.Throttle:
                case InputChannel.Trigger:
                case InputChannel.Grip:
                case InputChannel.Boost:
                case InputChannel.Menu:
                case InputChannel.PanelSelect:
                    return true;
                default:
                    return false;
            }
        }

        public void Tick(float dt) => _device = InputDevices.GetDeviceAtXRNode(_node);

        public bool TryRead(InputChannel channel, out float value)
        {
            value = 0f;
            if (!_device.isValid) _device = InputDevices.GetDeviceAtXRNode(_node);
            if (!_device.isValid) return false;

            switch (channel)
            {
                case InputChannel.SteerYaw:
                    if (_device.TryGetFeatureValue(CommonUsages.primary2DAxis, out var stick))
                    {
                        value = Mathf.Abs(stick.x) > 0.12f ? stick.x : 0f;
                        return Mathf.Abs(value) > 0.001f;
                    }
                    return false;

                case InputChannel.SteerPitch:
                    if (_device.TryGetFeatureValue(CommonUsages.primary2DAxis, out var stick2))
                    {
                        value = Mathf.Abs(stick2.y) > 0.12f ? stick2.y : 0f;
                        return Mathf.Abs(value) > 0.001f;
                    }
                    return false;

                case InputChannel.Throttle:
                    // 优先副摇杆，避免与 SteerPitch 抢同一根轴
                    if (_device.TryGetFeatureValue(CommonUsages.secondary2DAxis, out var t2))
                    {
                        value = Mathf.Clamp01(t2.y);
                        return true;
                    }
                    if (_device.TryGetFeatureValue(CommonUsages.primary2DAxis, out var t1))
                    {
                        if (!_warnedAxisConflict)
                        {
                            _warnedAxisConflict = true;
                            Debug.LogWarning($"[SteelRidge] {Name}：副摇杆不可用，Throttle 退回主摇杆 y 轴 —— " +
                                             "推杆将同时改变俯仰与油门（降级映射，真机油门应由 Pivot_Throttle 抓取驱动）");
                        }
                        value = Mathf.Clamp01(t1.y);
                        return true;
                    }
                    return false;

                case InputChannel.Trigger:
                    if (_device.TryGetFeatureValue(CommonUsages.trigger, out var trig))
                    {
                        value = trig;
                        return trig > 0.02f;
                    }
                    return false;

                case InputChannel.Grip:
                    if (_device.TryGetFeatureValue(CommonUsages.grip, out var grip))
                    {
                        value = grip;
                        return grip > 0.02f;
                    }
                    return false;

                case InputChannel.Boost:
                    if (_device.TryGetFeatureValue(CommonUsages.primaryButton, out var boost))
                    {
                        value = boost ? 1f : 0f;
                        return boost;
                    }
                    return false;

                case InputChannel.PanelSelect:
                    if (_device.TryGetFeatureValue(CommonUsages.secondaryButton, out var select))
                    {
                        value = select ? 1f : 0f;
                        return select;
                    }
                    return false;

                case InputChannel.Menu:
                    if (_device.TryGetFeatureValue(CommonUsages.menuButton, out var menu))
                    {
                        value = menu ? 1f : 0f;
                        return menu;
                    }
                    return false;
            }

            return false;
        }
    }

    /// <summary>
    /// 注视源：单目/双目都可用，窄视场设备的主要交互手段（Rokid 一类）。
    /// 实现为"注视停留确认"，避免视点即点击造成的误触。
    ///
    /// 一个必须防住的退化：Target 若与相机同位（例如误把 eye 自己传进来），
    /// 视点方向与"到目标的向量"夹角恒为 0（Vector3.Angle 对零向量返回 0），
    /// 停留计时永远不会被打断 —— 结果是把 PanelSelect 变成每 DwellSeconds 一次的
    /// 定时脉冲，与用户看哪里完全无关。这种"假阳性输入"比没有输入更糟，
    /// 所以这里做成"目标无效即不供值"，让路由器如实报 MISSING。
    /// </summary>
    public sealed class GazeSource : IInputSource
    {
        public string Name => "Gaze (dwell)";
        public InputCapability Requires => InputCapability.Gaze;

        public Transform Target;
        public float DwellSeconds = 1.2f;
        public float MaxAngleDeg = 4f;

        /// <summary>目标与相机距离小于此值（米）视为无效目标：夹角无意义。</summary>
        public float MinTargetDistance = 0.10f;

        float _dwell;
        float _pulse;
        bool _warnedNoTarget;

        public bool Supports(InputChannel channel) => channel == InputChannel.PanelSelect;

        public void Tick(float dt)
        {
            _pulse = 0f;

            var cam = Camera.main;
            if (cam == null) { _dwell = 0f; return; }

            var toTarget = Target != null ? Target.position - cam.transform.position : Vector3.zero;

            if (Target == null || toTarget.sqrMagnitude < MinTargetDistance * MinTargetDistance)
            {
                if (!_warnedNoTarget)
                {
                    _warnedNoTarget = true;
                    Debug.LogWarning($"[SteelRidge] {Name}：目标" +
                        (Target == null ? "未指定" : "与相机重合") +
                        "，注视角度无意义，本通道不供值（避免定时脉冲式的假阳性选择）");
                }
                _dwell = 0f;
                return;
            }

            float angle = Vector3.Angle(cam.transform.forward, toTarget);

            if (angle <= MaxAngleDeg)
            {
                _dwell += dt;
                if (_dwell >= DwellSeconds)
                {
                    _pulse = 1f;
                    _dwell = 0f;
                }
            }
            else
            {
                _dwell = 0f;
            }
        }

        public bool TryRead(InputChannel channel, out float value)
        {
            value = channel == InputChannel.PanelSelect ? _pulse : 0f;
            return value > 0f;
        }
    }

    /// <summary>
    /// 手势 pinch 源。骨架已就位，取手部位姿依赖 XR Hands 包 —— SDK 未导入时保持静默降级。
    /// 明确返回 false 而不是返回假数据：宁可让路由器显示 MISSING，也不要在审计里撒谎。
    /// </summary>
    public sealed class HandPinchSource : IInputSource
    {
        public string Name => "Hand pinch (XR Hands)";
        public InputCapability Requires => InputCapability.HandTracking;

        public bool Supports(InputChannel channel)
        {
            return channel == InputChannel.Grip ||
                   channel == InputChannel.PanelSelect ||
                   channel == InputChannel.Trigger;
        }

        public void Tick(float dt) { }

        public bool TryRead(InputChannel channel, out float value)
        {
            value = 0f;
            return false;
        }
    }
}
