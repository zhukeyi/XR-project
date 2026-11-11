// StripControllerOnly.cs — 去掉 PICO 系统对「必须配对手柄才能启动」的前置拦截
//
// 背景（实测取证，2026-11-11）
//   PICO OpenXR SDK 的 Editor/PICOModifyAndroidManifest.cs:AddPICOMetaData() 会往
//   unityLibrary/src/main/AndroidManifest.xml 写入 <meta-data android:name="controller"
//   android:value="1" />（除「手部追踪 = HandsOnly」一种情形外都会写）。
//   系统侧 com.picoxr.systemui + system_server 的 AppStartInterceptManager 读到它会走
//   ControllerOnly 分支：
//       I AppStartInterceptManager: Intercepted for ControllerOnly: No controller paired.
//       W ActivityTaskManager: addPendingControllerOnlyLaunchItem ...
//   结果：进程根本不创建，只弹一个「需要使用手柄」对话框（按钮：取消／仍然使用／去配对）。
//   模拟器（pxrcontrollerservice 双柄 state=offline、bindstatus=0）永远点不掉这个框，
//   于是 M1 的「是否真进 immersive 会话」无法取证。
//
// 为什么要在打包侧解决而不是去模拟器里伪造配对
//   pxrcontrollerservice 没有 cmd 接口（cmd pxrcontrollerservice → Failed transaction），
//   配对状态存在 system_server 内的私有结构里，无公开注入点。
//   而在 manifest 里去掉这个标记是 PICO 自己也支持的路径（HandsOnly 分支就是删它），
//   真机上表现为「无手柄也能启动，用手部追踪或头控」——这不是 hack，是官方语义。
//
// 代价 / 前提
//   去掉后应用启动时若没有任何输入设备，手柄相关交互不可用；
//   本工程 M1 阶段只验证渲染与位姿（TrackedPoseDriver 绑 <XRHMD>），不依赖手柄，
//   所以此改动不影响结论。等 M3 做输入抽象层时按真机再决定是否恢复为 1。
//
// 用法
//   放在 Assets/_Project/Scripts/Editor/ 下即可，构建时自动生效；无需手动调用。
//   回滚：把 RequireController 改回 true。

using System.IO;
using UnityEditor.Android;
using UnityEditor.Build;
using UnityEditor.Build.Reporting;
using UnityEngine;

namespace SteelSpine.EditorTools
{
    public class StripControllerOnly : IPostGenerateGradleAndroidProject
    {
        /// <summary>true = 保留 SDK 默认（强制配对手柄）；false = 允许无手柄启动。</summary>
        const bool RequireController = false;

        /// <summary>必须大于 PICO SDK 的 OpenXRFeatureBuildHooks.callbackOrder（=1）。</summary>
        public int callbackOrder => 100;

        const string Marker = "\"controller\"";

        public void OnPostGenerateGradleAndroidProject(string path)
        {
            if (RequireController) return;

            var manifest = Path.Combine(path, "src/main/AndroidManifest.xml");
            if (!File.Exists(manifest))
            {
                Debug.LogWarning("[StripController] 未找到 manifest: " + manifest);
                return;
            }

            var lines = File.ReadAllLines(manifest);
            int removed = 0;
            using (var w = new StreamWriter(manifest, false, new System.Text.UTF8Encoding(false)))
            {
                foreach (var line in lines)
                {
                    // 只删 <meta-data ... android:name="controller" ... /> 这一整行
                    if (line.Contains("<meta-data") && line.Contains(Marker))
                    {
                        removed++;
                        continue;
                    }
                    w.WriteLine(line);
                }
            }

            if (removed > 0)
                Debug.Log("[StripController] 已移除 controller 元数据 " + removed + " 处（无手柄可启动）");
            else
                Debug.Log("[StripController] manifest 中本无 controller 元数据，未改动");
        }
    }
}
