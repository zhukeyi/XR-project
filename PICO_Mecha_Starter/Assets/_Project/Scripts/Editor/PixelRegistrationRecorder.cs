using SteelRidge.Core.Platform;
using UnityEditor;
using UnityEngine;

namespace SteelRidge.EditorTools
{
    /// <summary>
    /// AR 像素配准误差记录器。
    /// 这是全套验收指标里唯一不能自动测量的一项（需要外部物理靶标），
    /// 所以必须有一个"把标定结果写回档案"的入口 ——
    /// 否则这个数字永远不会被记录，验收报告里永远是 N/A。
    /// </summary>
    public sealed class PixelRegistrationRecorder : EditorWindow
    {
        PlatformProfile _profile;
        float _errorPx = 1.5f;
        float _maxPx = 1.5f;
        string _note = "";

        [MenuItem("Steel Ridge/平台/记录 AR 像素配准误差（写入所选档案）", false, 47)]
        static void Open()
        {
            var w = GetWindow<PixelRegistrationRecorder>("AR 像素配准误差");
            w.minSize = new Vector2(380, 260);

            w._profile = Selection.activeObject as PlatformProfile;
            w.LoadFromProfile();
        }

        /// <summary>
        /// 从档案读当前值。上限也必须从档案读 —— 早先这里是窗口自带的默认值，
        /// 于是"窗口说达标、报告说超限"（窗口 1.5 / 验收硬编码 1.5 / 档案自检 2.0）三处各说一套。
        /// 现在唯一事实来源是 PlatformProfile.maxArPixelRegistrationError。
        /// </summary>
        void LoadFromProfile()
        {
            if (_profile == null) return;
            if (_profile.arPixelRegistrationError > 0f) _errorPx = _profile.arPixelRegistrationError;
            if (_profile.maxArPixelRegistrationError > 0f) _maxPx = _profile.maxArPixelRegistrationError;
        }

        void OnGUI()
        {
            EditorGUILayout.HelpBox(
                "标定方法：打印十字靶贴墙 → 卷尺量靶心到地面与两侧墙角的距离（独立于头显的真值）→ " +
                "应用内同一坐标放 1 px 线宽十字 → 1.5 m 处用设备自带截屏（不要拍屏）→ " +
                "量虚拟十字与靶心的像素偏差，三点取均值。详见菜单 ⑤ 的审计报告。",
                MessageType.Info);

            var picked = (PlatformProfile)EditorGUILayout.ObjectField(
                "目标档案", _profile, typeof(PlatformProfile), false);
            if (picked != _profile) { _profile = picked; LoadFromProfile(); }

            using (new EditorGUI.DisabledScope(_profile == null))
            {
                _errorPx = EditorGUILayout.FloatField("实测误差（px）", _errorPx);
                _maxPx = EditorGUILayout.FloatField("上限（px）", _maxPx);
                _note = EditorGUILayout.TextField("备注（站位/距离/光照）", _note);

                bool over = _errorPx > _maxPx;
                EditorGUILayout.HelpBox(
                    over
                        ? $"超限：{_profile.pixelsPerDegree:0} PPD 下 {_errorPx:0.0} px 约 " +
                          $"{_errorPx / Mathf.Max(1f, _profile.pixelsPerDegree) * 60f:0.0}′ 视角，叠加在真实边缘会被用户察觉，属于「显脏」而非「不准」。"
                        : "达标。",
                    over ? MessageType.Warning : MessageType.None);

                if (GUILayout.Button("写入档案"))
                {
                    Undo.RecordObject(_profile, "记录 AR 像素配准误差");
                    _profile.arPixelRegistrationError = Mathf.Max(0.01f, _errorPx);
                    _profile.maxArPixelRegistrationError = Mathf.Max(0.01f, _maxPx);
                    EditorUtility.SetDirty(_profile);
                    AssetDatabase.SaveAssets();
                    Debug.Log($"[SteelRidge] {_profile.displayName}：AR 像素配准误差写入 {_errorPx:0.00} px " +
                              $"（上限 {_maxPx:0.00} px）{_note}");
                }
            }

            if (_profile == null)
                EditorGUILayout.HelpBox("先在 Project 面板里选中一个 PlatformProfile，或在上方字段拖入。",
                                        MessageType.None);
        }
    }
}
