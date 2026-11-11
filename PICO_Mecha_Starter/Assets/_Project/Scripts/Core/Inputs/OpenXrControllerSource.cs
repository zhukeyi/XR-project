// OpenXrControllerSource.cs — 基于 Input System 的 6DoF 手柄源（M3）
//
// 为什么再写一个，而不是修 ControllerStickSource
//   实测（2026-11-11，PICO 模拟器 / OpenXR，见 Docs/里程碑_OpenXR沉浸式.md §11）：
//     旧版 UnityEngine.XR.InputDevices 其实**能拿到**手柄设备：
//       [XR] PICO4 Ultra Touch Controller OpenXR | valid=True | Left  | pos=(0,0,0)
//       [XR] PICO4 Ultra Touch Controller OpenXR | valid=True | Right | pos=(0,1.65,0)
//   所以旧 API 并非"失效"。但旧 API 只能拿到布尔/浮点，拿不到这三样关键信息：
//     isTracked、trackingState、devicepose（含角速度）—— 而座舱抓杆/射线都要它们。
//   Input System 侧则完整暴露（同一进程同一帧的实测值）：
//     ./PICO4UltraTouchControllerOpenXR/istracked = 0        ← 左手柄未跟踪
//     ./PICO4UltraTouchControllerOpenXR1/istracked = 1       ← 右手柄已跟踪
//     ./PICO4UltraTouchControllerOpenXR1/devicepose/position = (0.00, 1.65, 0.00)
//     ./PICO4UltraTouchControllerOpenXR1/trackingstate = 15
//   结论：Input System 是正解，旧源保留作降级。
//
// 为什么用 TryGetChildControl 而不是直接引用 PICO4TouchController 类型
//   直接引用 Unity.XR.PICO 的控制器类型会把输入层焊死在这个 SDK 上，
//   换 Quest / Rokie / 后续 PICO5 就得改 gameplay。这里按**控件名**取，
//   各 profile 的控件命名是一致的（thumbstick / trigger / grip / primaryButton / secondaryButton / menu），
//   取不到就返回 false，让路由器如实降级 —— 与 InputRouter 的设计前提一致。
//
// 控件名对照（来自 Packages/com.unity.xr.openxr.picoxr/Runtime/Interactions/PICO4ControllerProfile.cs）
//   thumbstick(Vector2) / thumbstickClicked / trigger(float) / triggerPressed /
//   grip(float) / gripPressed / primaryButton / secondaryButton / menu / system / devicePose / isTracked

using SteelRidge.Core.Platform;
using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.InputSystem.Controls;

namespace SteelRidge.Core.Inputs
{
    /// <summary>
    /// 手柄设备的发现与缓存。Input System 的设备表在热插拔/重连时会变，
    /// 所以「按帧查询 + 失效即重查」比「一次性绑定」稳。
    /// </summary>
    public static class OpenXrDevices
    {
        static InputDevice _left, _right;

        public static InputDevice Left => Resolve(ref _left, "LeftHand");
        public static InputDevice Right => Resolve(ref _right, "RightHand");

        /// <summary>供 HUD / 审计用：当前解析到的设备摘要。</summary>
        public static string Describe()
        {
            return "L: " + Brief(_left) + "   R: " + Brief(_right);
        }

        static string Brief(InputDevice d)
        {
            if (d == null || !d.added) return "none";
            bool tracked = ReadBool(d, "isTracked", out var t) && t;
            string pos = ReadPose(d, out var p)
                ? string.Format("({0:F2},{1:F2},{2:F2})", p.x, p.y, p.z)
                : "nopose";
            return (tracked ? "tracked " : "idle ") + pos;
        }

        /// <summary>按 usage 找 XR 控制器；找不到时退回"任意带 thumbstick 的设备"。</summary>
        static InputDevice Resolve(ref InputDevice cached, string handUsage)
        {
            if (cached != null && cached.added) return cached;

            cached = null;
            InputDevice fallback = null;

            foreach (var d in InputSystem.devices)
            {
                if (d == null || !d.added) continue;

                // XR 控制器布局都以 XRController 为基类；用它筛掉键鼠/触摸屏
                bool isXrController = d.layout.ToLowerInvariant().Contains("controller");
                if (!isXrController) continue;

                foreach (var u in d.usages)
                {
                    if (u.ToString() == handUsage) { cached = d; return cached; }
                }

                fallback ??= d;
            }

            // 只有一只手柄的运行时（例如只配了右手的 PICO 模拟器）时，
            // 让左右都指向它，比让某一路彻底 MISSING 更可用；调用方仍可用 isTracked 区分。
            cached = fallback;
            return cached;
        }

        // ---------------- 控件读取小工具 ----------------

        /// <summary>
        /// 按名字取强类型控件。**必须先取 InputControl 再 as 转**：
        /// <c>TryGetChildControl&lt;T&gt;</c> 在控件存在但类型不符时会抛
        /// InvalidOperationException（实测："Expected control 'thumbstick' to be of type
        /// 'ButtonControl' but is of type 'StickControl' instead!"），
        /// 而这个异常会把调用方整段逻辑打断 —— 一个探测动作不应该具备这个杀伤力。
        /// </summary>
        public static T Ctrl<T>(InputDevice d, string name) where T : InputControl
        {
            if (d == null || !d.added) return null;
            var raw = d.TryGetChildControl(name);   // 取不到返回 null，不抛
            return raw as T;
        }

        public static bool ReadButton(InputDevice d, string name)
        {
            var c = Ctrl<ButtonControl>(d, name);
            return c != null && c.isPressed;
        }

        public static bool ReadBool(InputDevice d, string name, out bool value)
        {
            value = false;
            var c = Ctrl<ButtonControl>(d, name);
            if (c == null) return false;
            value = c.isPressed;
            return true;
        }

        public static bool ReadFloat(InputDevice d, string name, out float value)
        {
            value = 0f;
            var c = Ctrl<AxisControl>(d, name);
            if (c == null) return false;
            value = c.ReadValue();
            return true;
        }

        public static bool ReadStick(InputDevice d, out Vector2 value)
        {
            value = Vector2.zero;
            var c = Ctrl<Vector2Control>(d, "thumbstick");
            if (c == null) return false;
            value = c.ReadValue();
            return true;
        }

        /// <summary>devicePosition 在 OpenXR 下是形如 <c>Vector3Control</c> 的子控件。</summary>
        public static bool ReadPose(InputDevice d, out Vector3 pos)
        {
            pos = Vector3.zero;
            var c = Ctrl<Vector3Control>(d, "devicePosition");
            if (c == null) return false;
            pos = c.ReadValue();
            return true;
        }

        public static bool IsTracked(InputDevice d)
        {
            if (d == null || !d.added) return false;
            return ReadBool(d, "isTracked", out var t) && t;
        }
    }

    /// <summary>
    /// 6DoF 手柄输入源（Input System 版）。通道映射与 ControllerStickSource 保持一一对应，
    /// 差别只在"值从哪来"，这样 gameplay 侧不需要知道用的是哪个源。
    /// </summary>
    public sealed class OpenXrControllerSource : IInputSource
    {
        public string Name => "OpenXR Controller (InputSystem)";
        public InputCapability Requires => InputCapability.Controller6DoF;

        /// <summary>true = 右手柄，false = 左手柄。</summary>
        public bool RightHand = true;

        /// <summary>摇杆死区。0.12 与旧源保持一致，避免两路手感不同。</summary>
        public float StickDeadzone = 0.12f;

        bool _warnedNoThumbstick;

        InputDevice Dev => RightHand ? OpenXrDevices.Right : OpenXrDevices.Left;

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

        // 设备解析在 TryRead 里按需做（内部有缓存），Tick 保持空实现即可。
        public void Tick(float dt) { }

        public bool TryRead(InputChannel channel, out float value)
        {
            value = 0f;

            var d = Dev;
            if (d == null || !d.added)
            {
                if (!_warnedNoThumbstick)
                {
                    _warnedNoThumbstick = true;
                    Debug.LogWarning($"[SteelRidge] {Name}：未解析到手柄设备（{(RightHand ? "右" : "左")}手），本通道降级");
                }
                return false;
            }

            switch (channel)
            {
                case InputChannel.SteerYaw:
                    if (!OpenXrDevices.ReadStick(d, out var s1)) return false;
                    value = Mathf.Abs(s1.x) > StickDeadzone ? s1.x : 0f;
                    return Mathf.Abs(value) > 0.001f;

                case InputChannel.SteerPitch:
                    if (!OpenXrDevices.ReadStick(d, out var s2)) return false;
                    value = Mathf.Abs(s2.y) > StickDeadzone ? s2.y : 0f;
                    return Mathf.Abs(value) > 0.001f;

                case InputChannel.Throttle:
                    // 摇杆上推即油门。与旧源同样的降级说明：真机油门应由 Pivot_Throttle 抓取深度驱动。
                    if (!OpenXrDevices.ReadStick(d, out var st)) return false;
                    value = Mathf.Clamp01(st.y);
                    return value > 0.001f;

                case InputChannel.Trigger:
                    if (!OpenXrDevices.ReadFloat(d, "trigger", out var trig)) return false;
                    value = trig;
                    return trig > 0.02f;

                case InputChannel.Grip:
                    if (!OpenXrDevices.ReadFloat(d, "grip", out var grip)) return false;
                    value = grip;
                    return grip > 0.02f;

                case InputChannel.Boost:
                    if (!OpenXrDevices.ReadBool(d, "primaryButton", out var boost)) return false;
                    value = boost ? 1f : 0f;
                    return boost;

                case InputChannel.PanelSelect:
                    if (!OpenXrDevices.ReadBool(d, "secondaryButton", out var sel)) return false;
                    value = sel ? 1f : 0f;
                    return sel;

                case InputChannel.Menu:
                    if (!OpenXrDevices.ReadBool(d, "menu", out var menu)) return false;
                    value = menu ? 1f : 0f;
                    return menu;
            }

            return false;
        }
    }
}
