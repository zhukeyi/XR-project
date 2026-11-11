// InputSystemProbe.cs — 输入层运行时取证装置（M3 前置）
//
// 为什么需要它
//   M1 的 XrStatus 用**旧版 UnityEngine.XR.InputDevices** 读手柄，实测 L/R hand 全是零值。
//   这有两种可能，必须分开，否则会照错药方：
//     (a) 旧 API 在 OpenXR 下拿不到设备 —— 要改用 Input System；
//     (b) 设备本身不存在（模拟器没给手柄）—— 改什么都没用，得换验证手段。
//   本探针把 Input System 的完整设备树、旧版 XR 的全部设备、以及 PICO 控制器布局是否注册
//   一次性打到 logcat，用事实裁定上面两种可能。
//
// 设计上的两个防坑点（第一版踩过）
//   1) 第一版把 Runner 写成 InputSystemProbe 的**私有嵌套 MonoBehaviour**，并延迟 30 帧才输出。
//      结果 logcat 里一行都没有，且无法判断是「Boot 没被调用」还是「Dump 抛异常」。
//      所以现在：进 Boot 立刻打一行 MARK，Dump 直接同步跑一遍，再挂顶层 Runner 做延迟复采，
//      且整段包 try/catch。三者任意一环出错都能在日志里定位到具体环节。
//   2) 不加延后依赖：XR 子系统由 XR Management 的 InitManagerOnStart 在**场景加载前**启动，
//      所以 AfterSceneLoad 时刻设备表已就绪，不需要等帧。
//
// 输出约定
//   logcat 单行上限约 4 KB，所以按 1.2 KB 分块输出，块间用 [INSYS#n] 序号标记，便于拼回。

using System;
using System.Collections.Generic;
using System.Text;
using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.XR;

// UnityEngine.InputSystem 与 UnityEngine.XR 有两组同名类型（InputDevice / CommonUsages），
// 同时 using 两个命名空间必然 CS0104。这里用别名把它们钉死，避免整篇全限定名。
using XRDevice = UnityEngine.XR.InputDevice;
using XRCommonUsages = UnityEngine.XR.CommonUsages;

namespace SteelRidge.Core.Inputs
{
    public static class InputSystemProbe
    {
        /// <summary>关掉即可静默（保留代码备查）。</summary>
        public const bool Enabled = true;

        const int ChunkChars = 1200;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void Boot()
        {
            if (!Enabled) return;

            Debug.Log("[INSYS] MARK boot entered");

            // 1) 立刻同步采一遍：此时 XR 设备表已就绪
            SafeDump("t0");

            // 2) 再挂一个延迟复采，用来观察设备在运行中是否被异步注册（PICO 运行时常见）
            var go = new GameObject("[InputSystemProbe]");
            UnityEngine.Object.DontDestroyOnLoad(go);
            go.AddComponent<InputProbeRunner>();

            Debug.Log("[INSYS] MARK boot exit (runner attached)");
        }

        static void SafeDump(string phase)
        {
            try { Dump(phase); }
            catch (Exception e)
            {
                Debug.LogError("[INSYS] DUMP FAILED phase=" + phase + " :: " +
                               e.GetType().Name + ": " + e.Message + "\n" + e.StackTrace);
            }
        }

        internal static void Dump(string phase)
        {
            var sb = new StringBuilder(4096);

            sb.AppendLine("=== INPUT PROBE BEGIN phase=" + phase + " ===");
            sb.AppendLine("InputSystem.version = " + InputSystem.version);
            sb.AppendLine("InputSystem.updateMode = " + InputSystem.settings.updateMode);
            sb.AppendLine("XRSettings.isDeviceActive = " + XRSettings.isDeviceActive);
            sb.AppendLine("XRSettings.loadedDeviceName = " + XRSettings.loadedDeviceName);

            // ---------- 1. Input System 设备树 ----------
            var devices = InputSystem.devices;
            sb.AppendLine("--- InputSystem.devices.Count = " + devices.Count + " ---");

            foreach (var d in devices)
            {
                if (d == null) continue;
                var usageList = new List<string>();
                foreach (var u in d.usages) usageList.Add(u.ToString());
                sb.AppendLine(string.Format(
                    "[IS] layout={0} | name={1} | id={2} | enabled={3} | native={4} | usages={5}",
                    d.layout, d.displayName, d.deviceId, d.enabled, d.native,
                    usageList.Count > 0 ? string.Join(",", usageList) : "(none)"));

                // 只对疑似 XR 控制器展开控件，避免刷屏
                bool interesting =
                    d.layout.Contains("PICO") || d.layout.Contains("XRController") ||
                    d.layout.Contains("Touch") || d.layout.Contains("Hand") ||
                    d.layout.Contains("HMD");

                if (!interesting) continue;

                int shown = 0;
                foreach (var c in d.allControls)
                {
                    if (c == null) continue;
                    string val;
                    try { val = c.ReadValueAsObject()?.ToString() ?? "null"; }
                    catch (Exception e) { val = "<" + e.GetType().Name + ">"; }

                    sb.AppendLine(string.Format("      .{0} = {1}", c.path, Trim(val)));

                    if (++shown >= 40) { sb.AppendLine("      ... (truncated)"); break; }
                }
            }

            // ---------- 2. 旧版 XR 设备 ----------
            sb.AppendLine("--- UnityEngine.XR.InputDevices ---");
            var legacy = new List<XRDevice>();
            InputDevices.GetDevices(legacy);
            sb.AppendLine("legacy count = " + legacy.Count);
            foreach (var d in legacy)
            {
                string pos = "?";
                try
                {
                    if (d.TryGetFeatureValue(XRCommonUsages.devicePosition, out var p))
                        pos = PosStr(p);
                }
                catch { }
                sb.AppendLine(string.Format(
                    "[XR] name={0} | manufacturer={1} | valid={2} | characteristics={3} | pos={4}",
                    d.name, d.manufacturer, d.isValid, d.characteristics, pos));
            }

            sb.AppendLine("--- XRNode 逐节点 ---");
            XRDevice[] nodes =
            {
                InputDevices.GetDeviceAtXRNode(XRNode.Head),
                InputDevices.GetDeviceAtXRNode(XRNode.LeftHand),
                InputDevices.GetDeviceAtXRNode(XRNode.RightHand),
            };
            string[] nodeNames = { "Head", "LeftHand", "RightHand" };
            for (int i = 0; i < nodes.Length; i++)
            {
                sb.AppendLine(string.Format("node {0,-10} valid={1} name={2}",
                    nodeNames[i], nodes[i].isValid, nodes[i].isValid ? nodes[i].name : "-"));
            }

            // ---------- 3. 布局注册情况 ----------
            sb.AppendLine("--- registered layouts (XR/PICO 相关) ---");
            var names = new List<string>();
            try
            {
                foreach (var l in UnityEngine.InputSystem.InputSystem.ListLayouts())
                {
                    if (l.Contains("PICO") || l.Contains("XRController") || l.Contains("OpenXR"))
                        names.Add(l);
                }
            }
            catch (Exception e) { names.Add("<err " + e.GetType().Name + ">"); }
            names.Sort();
            sb.AppendLine(names.Count == 0 ? "(none)" : string.Join("\n", names));

            // ---------- 4. 控件名解析自检 ----------
            // 探针 dump 里看到控件路径是全小写（primarybutton / thumbstickclicked），
            // 而 OpenXrControllerSource 按驼峰名取（primaryButton）。TryGetChildControl 是否
            // 大小写不敏感必须实测，否则真机上会出现"扳机有值、A 键永远按不出来"这种偏科 bug。
            sb.AppendLine("--- 控件名解析自检（OpenXrControllerSource 实际用的名字）---");
            var dev = OpenXrDevices.Right ?? OpenXrDevices.Left;
            if (dev == null)
            {
                sb.AppendLine("(无手柄设备，跳过)");
            }
            else
            {
                sb.AppendLine("device = " + dev.displayName + " [" + dev.layout + "]");
                string[] expect =
                {
                    "thumbstick", "trigger", "grip",
                    "primaryButton", "secondaryButton", "menu",
                    "devicePosition", "isTracked"
                };
                foreach (var n in expect)
                {
                    string kind;
                    if (OpenXrDevices.Ctrl<UnityEngine.InputSystem.Controls.ButtonControl>(dev, n) != null) kind = "Button";
                    else if (OpenXrDevices.Ctrl<UnityEngine.InputSystem.Controls.AxisControl>(dev, n) != null) kind = "Axis";
                    else if (OpenXrDevices.Ctrl<UnityEngine.InputSystem.Controls.Vector2Control>(dev, n) != null) kind = "Vector2";
                    else if (OpenXrDevices.Ctrl<UnityEngine.InputSystem.Controls.Vector3Control>(dev, n) != null) kind = "Vector3";
                    else kind = "MISSING";
                    sb.AppendLine(string.Format("   {0,-16} -> {1}", n, kind));
                }
            }

            sb.AppendLine("=== INPUT PROBE END phase=" + phase + " ===");

            Emit(sb.ToString());
        }

        static string PosStr(Vector3 p) =>
            string.Format("({0:F2},{1:F2},{2:F2})", p.x, p.y, p.z);

        static string Trim(string s)
        {
            if (string.IsNullOrEmpty(s)) return "null";
            return s.Length > 60 ? s.Substring(0, 60) + "…" : s;
        }

        /// <summary>按 ChunkChars 切块输出，规避 logcat 单行长度限制。</summary>
        static void Emit(string text)
        {
            var lines = text.Split('\n');
            var buf = new StringBuilder(ChunkChars + 256);
            int part = 0;

            foreach (var raw in lines)
            {
                var line = raw.TrimEnd('\r');
                if (buf.Length + line.Length + 1 > ChunkChars)
                {
                    Debug.Log("[INSYS#" + (part++) + "] " + buf.ToString());
                    buf.Length = 0;
                }
                buf.AppendLine(line);
            }
            if (buf.Length > 0) Debug.Log("[INSYS#" + part + "] " + buf.ToString());
        }
    }

    /// <summary>
    /// 延迟复采。必须是**顶层类型**：第一版写成嵌套私有类，AddComponent 环节的可疑性无法排除。
    /// </summary>
    internal sealed class InputProbeRunner : MonoBehaviour
    {
        int _frames;
        bool _done;

        void Update()
        {
            _frames++;
            if (_done || _frames < 90) return;   // 约 1.5 s @60fps
            _done = true;
            Debug.Log("[INSYS] MARK runner firing at frame " + _frames);
            InputSystemProbe.Dump("t1");
        }
    }
}
