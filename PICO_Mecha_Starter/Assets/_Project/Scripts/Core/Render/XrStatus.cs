// XrStatus.cs — 运行时 XR 状态面板（M1 底座验证用）
//
// 为什么改成 world-space Canvas
//   实测（2026-11-11，PICO 模拟器 OpenXR 会话）：IMGUI 的 OnGUI 在 SinglePassInstanced
//   立体渲染下完全不出现 —— 截图里只有 3D 场景，没有任何文字。IMGUI 不参与 XR 立体渲染，
//   这是硬限制。所以面板必须用 world-space Canvas（这也是后续座舱 HUD 的唯一可行路径）。
//
// 为什么文字用英文
//   Resources.GetBuiltinResource 只提供西文字体（LegacyRuntime.ttf），不含中文字形。
//   诊断面板用英文可避免「一片方块」；正式 HUD 会走自定义字体/图集。
//
// 它同时是实验装置
//   故意用**旧版 UnityEngine.XR.InputDevices** 读手柄与头显：
//   如果 leftHand/rightHand 的 isValid 为真、能取到 devicePosition，说明旧 API 在
//   OpenXR 下可用，Core/Inputs/InputSources.cs 的 OpenXRControllerSource 不必重写；
//   如果读不到，就必须改写为 Input System 的 action —— 这是 M1 的关键判断点。
//
// 每条显示项都对应一条验收条件，不做装饰性信息；同时每 2 s 用 Debug.Log 打一份到
// logcat，便于无截图时取证。

using System.Text;
using SteelRidge.Core.Inputs;
using UnityEngine;
using UnityEngine.UI;
using UnityEngine.XR;

namespace SteelSpine.Render
{
    public class XrStatus : MonoBehaviour
    {
        [Tooltip("仅用于在面板上提示机体距离")]
        public float distanceHint = 30f;

        [Tooltip("HUD 距相机的米数（座舱内 HUD 的一般量级）")]
        public float hudDistance = 1.6f;

        [Tooltip("HUD 面板物理宽度（米）")]
        public float hudWidthMeters = 0.46f;

        [Tooltip("HUD 相对视线中心的偏移（米）：左上角摆位，避免压住正前方的机体")]
        public Vector2 hudOffset = new Vector2(-0.34f, 0.22f);

        Text _text;
        readonly StringBuilder _sb = new StringBuilder(768);
        InputDevice _hmd, _left, _right;
        float _nextProbe;
        float _nextLog;
        bool _hudBuilt;

        void Start()
        {
            BuildHud();
        }

        // ---------------- HUD ----------------

        void BuildHud()
        {
            var cam = Camera.main;
            if (cam == null) cam = GetComponentInChildren<Camera>();
            if (cam == null)
            {
                Debug.LogError("[XrStatus] 找不到相机，HUD 未创建");
                return;
            }

            var canvasGo = new GameObject("HUD_Canvas");
            canvasGo.transform.SetParent(cam.transform, false);
            canvasGo.transform.localPosition = new Vector3(hudOffset.x, hudOffset.y, hudDistance);
            canvasGo.transform.localRotation = Quaternion.identity;
            // 1 canvas 单位 = 1 mm，便于用物理尺寸思考排版
            canvasGo.transform.localScale = Vector3.one * 0.001f;

            var canvas = canvasGo.AddComponent<Canvas>();
            canvas.renderMode = RenderMode.WorldSpace;
            canvas.worldCamera = cam;

            float w = hudWidthMeters * 1000f;
            var rt = canvasGo.GetComponent<RectTransform>();
            rt.sizeDelta = new Vector2(w, w * 0.60f);

            // 半透明底板：浅色文字压在白色地面上时，没有底板几乎读不出来
            var bgGo = new GameObject("HUD_Bg");
            bgGo.transform.SetParent(canvasGo.transform, false);
            var bg = bgGo.AddComponent<Image>();
            bg.color = new Color(0.02f, 0.05f, 0.09f, 0.74f);
            bg.raycastTarget = false;
            var brt = bg.rectTransform;
            brt.anchorMin = Vector2.zero;
            brt.anchorMax = Vector2.one;
            brt.offsetMin = Vector2.zero;
            brt.offsetMax = Vector2.zero;

            var textGo = new GameObject("HUD_Text");
            textGo.transform.SetParent(canvasGo.transform, false);

            _text = textGo.AddComponent<Text>();
            _text.font = LoadFont();
            _text.fontSize = 19;
            _text.alignment = TextAnchor.UpperLeft;
            _text.horizontalOverflow = HorizontalWrapMode.Wrap;
            _text.verticalOverflow = VerticalWrapMode.Overflow;
            _text.color = new Color(0.86f, 0.93f, 1f, 1f);
            _text.raycastTarget = false;

            var trt = _text.rectTransform;
            trt.anchorMin = Vector2.zero;
            trt.anchorMax = Vector2.one;
            trt.offsetMin = new Vector2(12, 8);
            trt.offsetMax = new Vector2(-12, -8);

            _hudBuilt = true;
            Debug.Log("[XrStatus] HUD 已创建（world-space Canvas，" + hudDistance + " m）");
        }

        static Font LoadFont()
        {
            // Unity 2022 的内置西文字体名；旧版本回落到 Arial
            var f = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            if (f == null) f = Resources.GetBuiltinResource<Font>("Arial.ttf");
            if (f == null) Debug.LogError("[XrStatus] 内置字体加载失败，HUD 文字可能不显示");
            return f;
        }

        // ---------------- 状态采集 ----------------

        void Update()
        {
            if (Time.unscaledTime < _nextProbe) return;
            _nextProbe = Time.unscaledTime + 0.5f;

            _hmd = InputDevices.GetDeviceAtXRNode(XRNode.Head);
            _left = InputDevices.GetDeviceAtXRNode(XRNode.LeftHand);
            _right = InputDevices.GetDeviceAtXRNode(XRNode.RightHand);

            string line = Compose();

            if (_hudBuilt && _text != null) _text.text = line;

            // 2 s 一次进 logcat，便于 adb 取证
            if (Time.unscaledTime >= _nextLog)
            {
                _nextLog = Time.unscaledTime + 2f;
                Debug.Log("[XrStatus] " + line.Replace("\n", " | "));
            }
        }

        string Compose()
        {
            var cam = Camera.main;
            _sb.Length = 0;
            _sb.AppendLine("STEEL SPINE  /  OPENXR BASELINE CHECK");
            _sb.AppendLine("XR active : " + XRSettings.isDeviceActive
                           + "   runtime: " + (string.IsNullOrEmpty(XRSettings.loadedDeviceName)
                               ? "(none)" : XRSettings.loadedDeviceName));
            _sb.AppendLine("Stereo    : " + XRSettings.stereoRenderingMode
                           + "   eye: " + (cam != null ? cam.stereoTargetEye.ToString() : "no cam"));
            // 管线与清除设置：M1 转 URP 后，「画面是否还按相机 bg 清屏」必须能一眼看到。
            // 实测（2026-11-11，URP 14.0.12 + 模拟器）出现过背景全黑、地面不见，
            // 只有把 clearFlags / backgroundColor / 管线名同时打出来，
            // 才能区分「清屏没生效」和「相机位姿跑到地面以下，单面地面被背面剔除」。
            _sb.AppendLine("Pipeline  : " + PipelineName(cam));
            // eyeTextureDesc 是「是否真立体」的直接证据：
            // SinglePass 下 width 为单眼宽、volumeDepth=2（或用 2× 宽打包双眼）
            var desc = XRSettings.eyeTextureDesc;
            _sb.AppendLine("Eye tex   : " + desc.width + "x" + desc.height
                           + " vol=" + desc.volumeDepth + " fmt=" + desc.graphicsFormat);
            _sb.AppendLine("Screen    : " + Screen.width + "x" + Screen.height
                           + "   frame: " + Time.frameCount
                           + "   fps: " + Mathf.RoundToInt(1f / Mathf.Max(1e-4f, Time.smoothDeltaTime)));
            _sb.AppendLine("HMD pose  : " + Pose3(_hmd));
            // 相机世界坐标是「TrackedPoseDriver 是否真的接管相机」的交叉验证：
            // 场景里相机 localPosition 为 0，若这里出现 ~1.65 的 Y，即说明位姿来自 OpenXR。
            _sb.AppendLine("Cam world : " + (cam != null
                ? string.Format("({0:F2},{1:F2},{2:F2})", cam.transform.position.x,
                                cam.transform.position.y, cam.transform.position.z)
                : "no cam"));
            _sb.AppendLine("L hand(IS): " + HandIs(false));
            _sb.AppendLine("R hand(IS): " + HandIs(true));
            _sb.AppendLine("Mecha     : " + distanceHint + " m ahead (+Z)");
            return _sb.ToString();
        }

        /// <summary>
        /// 一行说明当前生效的渲染管线 + 相机清屏方式。
        /// 用 GraphicsSettings.currentRenderPipeline 而非自己记的字段：
        /// 它读的是「真正生效的那个」，能暴露「资产建了但没挂上」这类问题。
        /// </summary>
        static string PipelineName(Camera cam)
        {
            var asset = UnityEngine.Rendering.GraphicsSettings.currentRenderPipeline;
            string pipe = asset != null ? asset.name + "(" + asset.GetType().Name + ")" : "Built-in";
            if (cam == null) return pipe + "  cam=none";
            var bg = cam.backgroundColor;
            return pipe + "  clear=" + cam.clearFlags
                        + " bg=" + bg.r.ToString("F2") + "/" + bg.g.ToString("F2") + "/" + bg.b.ToString("F2")
                        + " a=" + bg.a.ToString("F2")
                        + " MSAA=" + (cam.allowMSAA ? "on" : "off");
        }

        static string Pose3(InputDevice d)
        {            if (!d.isValid) return "invalid";
            return d.TryGetFeatureValue(CommonUsages.devicePosition, out var p)
                ? string.Format("({0:F2},{1:F2},{2:F2})", p.x, p.y, p.z)
                : "no pose";
        }

        static string Hand(InputDevice d)
        {
            if (!d.isValid) return "invalid";
            string trig = d.TryGetFeatureValue(CommonUsages.triggerButton, out var t) ? (t ? "1" : "0") : "-";
            string grip = d.TryGetFeatureValue(CommonUsages.gripButton, out var g) ? (g ? "1" : "0") : "-";
            return Pose3(d) + " trig=" + trig + " grip=" + grip;
        }

        /// <summary>
        /// Input System 侧的手柄摘要。相比旧 API 多出三样关键信息：
        /// isTracked（T/-）、摇杆连续值、扳机/握持连续值 —— 座舱抓杆与射线都依赖它们。
        /// 实测对照见 Docs/里程碑_OpenXR沉浸式.md §11。
        /// </summary>
        static string HandIs(bool right)
        {
            var d = right ? OpenXrDevices.Right : OpenXrDevices.Left;
            if (d == null || !d.added) return "none";

            string trk = OpenXrDevices.IsTracked(d) ? "T" : "-";

            string pos = OpenXrDevices.ReadPose(d, out var p)
                ? string.Format("({0:F2},{1:F2},{2:F2})", p.x, p.y, p.z)
                : "nopose";

            string trig = OpenXrDevices.ReadFloat(d, "trigger", out var t) ? t.ToString("F2") : "-";
            string grip = OpenXrDevices.ReadFloat(d, "grip", out var g) ? g.ToString("F2") : "-";
            string stick = OpenXrDevices.ReadStick(d, out var s)
                ? string.Format("{0:F1}/{1:F1}", s.x, s.y)
                : "-";

            return string.Format("{0} {1} trig={2} grip={3} stick={4}", trk, pos, trig, grip, stick);
        }

        // ---------------- 平面模式后备 ----------------
        // 桌面/编辑器预览（非 XR）时 Canvas 也能显示，这里保留一次保险：
        // 万一 HUD 因字体或渲染问题没出来，仍有 OnGUI 可读。
        GUIStyle _guiStyle;

        void OnGUI()
        {
            if (_hudBuilt) return;   // HUD 正常就不重复画
            if (_guiStyle == null)
            {
                _guiStyle = new GUIStyle(GUI.skin.label)
                {
                    fontSize = Mathf.Max(13, Screen.height / 40),
                    alignment = TextAnchor.UpperLeft,
                    richText = false,
                };
            }
            _guiStyle.normal.textColor = new Color(0.78f, 0.87f, 0.96f);
            GUI.Label(new Rect(18, 12, Screen.width - 36, Screen.height), Compose(), _guiStyle);
        }
    }
}
