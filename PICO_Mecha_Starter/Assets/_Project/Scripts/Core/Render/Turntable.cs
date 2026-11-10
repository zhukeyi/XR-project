// Turntable.cs — 运行时转台 + 屏幕信息层
//
// 用途
//   这是给「Unity → APK → 模拟器」链路验证用的最小运行时脚本：
//   ① 让机体绕 Y 轴自转，证明 Update() 真的在跑（静态图无法区分「渲染了一帧」和「循环在跑」）；
//   ② 用 OnGUI 画出构建信息，证明脚本能在 Android 上执行。
//
// 注意
//   OnGUI 直接画进同一个 framebuffer，所以会被 pico-cli capture screenshot 捕获。
//   这与之前 GLES 手工查看器不同——那里 GLSurfaceView 是独立 Surface，
//  叠在上面的普通 View 不会进截图。

using UnityEngine;

namespace SteelSpine.Render
{
    public class Turntable : MonoBehaviour
    {
        [Tooltip("每秒旋转角度")]
        public float degreesPerSecond = 12f;

        float _angle;

        // ★ 不显示 FPS。实测在 PICO 的 2D 窗口模式下，窗口未聚焦时 Unity 会被节流，
        //   smoothDeltaTime 在 0.02 / 0.0001 / 0 之间跳，换算出的 FPS 分别是
        //   50 / 10000 / 0 —— 三个数字都不反映真实性能，展示出来只会被评委追问。
        //   改为显示累计帧数：单调递增，能证明 Update() 在跑，且不构成性能声明。
        int _totalFrames;

        void Update()
        {
            _angle += degreesPerSecond * Time.deltaTime;
            if (_angle > 360f) _angle -= 360f;
            transform.localRotation = Quaternion.Euler(0f, _angle, 0f);

            _totalFrames++;
        }

        void OnGUI()
        {
            var style = new GUIStyle(GUI.skin.label)
            {
                fontSize = Mathf.Max(14, Screen.height / 34),
                alignment = TextAnchor.UpperLeft,
            };
            style.normal.textColor = new Color(0.78f, 0.87f, 0.96f);

            GUI.Label(new Rect(20, 14, Screen.width - 40, Screen.height),
                "Steel Spine  |  Unity Android 链路验证\n" +
                "Unity " + Application.unityVersion +
                "    后端 " + (Application.isEditor ? "Editor" : "Player") + "\n" +
                "屏幕 " + Screen.width + "×" + Screen.height +
                "    累计帧 " + _totalFrames + "\n" +
                "设备 " + SystemInfo.deviceModel +
                "    图形 " + SystemInfo.graphicsDeviceType + "\n" +
                "已运行 " + Mathf.FloorToInt(Time.realtimeSinceStartup) + " s",
                style);
        }
    }
}
