// ProbeBuildEnv.cs — 构建前环境探针（只读 + 诊断，不产包）
//
// 为什么需要它
//   第一次构建失败在「Target architecture not specified」，说明
//   PlayerSettings.Android.targetArchitectures 被写成了 0。
//   同时尺度校正后包围盒出现「深 36 m」的异常值，需要看导入器真实参数
//   与真实顶点包围盒（Renderer.bounds 会滞后一帧，不可靠）。
//
// 用法
//   Unity -batchmode -quit -projectPath <proj> -buildTarget Android \
//         -executeMethod SteelSpine.EditorTools.ProbeBuildEnv.Run -logFile -

using System.Linq;
using System.Text;
using UnityEditor;
using UnityEngine;

namespace SteelSpine.EditorTools
{
    public static class ProbeBuildEnv
    {
        const string ModelPath = "Assets/_Project/Models/mecha_parts.fbx";

        public static void Run()
        {
            var sb = new StringBuilder();
            sb.AppendLine("=== 构建环境探针 ===");
            sb.AppendLine("activeBuildTarget : " + EditorUserBuildSettings.activeBuildTarget);
            sb.AppendLine("targetArchitectures（读）: " + PlayerSettings.Android.targetArchitectures);
            sb.AppendLine("scriptingBackend（读）   : " +
                PlayerSettings.GetScriptingBackend(BuildTargetGroup.Android));
            sb.AppendLine("graphicsAPIs（读）       : " +
                string.Join(",", PlayerSettings.GetGraphicsAPIs(BuildTarget.Android)
                    .Select(g => g.ToString())));
            sb.AppendLine("minSdk / targetSdk       : " +
                PlayerSettings.Android.minSdkVersion + " / " +
                PlayerSettings.Android.targetSdkVersion);

            // 试写并读回
            PlayerSettings.Android.targetArchitectures = AndroidArchitecture.ARM64;
            sb.AppendLine("写入 ARM64 后读回        : " + PlayerSettings.Android.targetArchitectures);

            // 导入器真实参数
            var imp = AssetImporter.GetAtPath(ModelPath) as ModelImporter;
            if (imp != null)
            {
                sb.AppendLine("--- ModelImporter ---");
                sb.AppendLine("globalScale      : " + imp.globalScale);
                sb.AppendLine("useFileScale     : " + imp.useFileScale);
                sb.AppendLine("importNormals    : " + imp.importNormals);
                sb.AppendLine("materialImportMode: " + imp.materialImportMode);
                sb.AppendLine("bakeAxisConversion: " + imp.bakeAxisConversion);
            }

            // 真实顶点包围盒
            var fbx = AssetDatabase.LoadAssetAtPath<GameObject>(ModelPath);
            if (fbx == null) { sb.AppendLine("✗ 加载模型失败"); Debug.Log(sb.ToString()); return; }

            var go = (GameObject)PrefabUtility.InstantiatePrefab(fbx);
            var b = TrueBounds(go);
            sb.AppendLine("--- 实例化后真实包围盒 ---");
            sb.AppendLine(string.Format("min ({0:F3}, {1:F3}, {2:F3})   max ({3:F3}, {4:F3}, {5:F3})",
                b.min.x, b.min.y, b.min.z, b.max.x, b.max.y, b.max.z));
            sb.AppendLine(string.Format("size  W {0:F3}  H {1:F3}  D {2:F3}", b.size.x, b.size.y, b.size.z));
            sb.AppendLine("renderer 数        : " + go.GetComponentsInChildren<Renderer>().Length);
            sb.AppendLine("meshFilter 数      : " + go.GetComponentsInChildren<MeshFilter>().Length);

            // 找出尺寸最大的 5 个 mesh，确认「深 36 m」是哪个物体造成的
            var top = go.GetComponentsInChildren<MeshFilter>()
                .Select(mf => new { mf.name, size = mf.sharedMesh != null ? mf.sharedMesh.bounds.size : Vector3.zero,
                                    c = mf.transform.TransformPoint(mf.sharedMesh != null ? mf.sharedMesh.bounds.center : Vector3.zero) })
                .OrderByDescending(x => Mathf.Max(x.size.x, Mathf.Max(x.size.y, x.size.z)))
                .Take(5);
            sb.AppendLine("--- 局部尺寸最大的 5 个网格 ---");
            foreach (var t in top)
                sb.AppendLine(string.Format("  {0,-30} local {1:F2}×{2:F2}×{3:F2}  worldCenter {4:F2},{5:F2},{6:F2}",
                    t.name, t.size.x, t.size.y, t.size.z, t.c.x, t.c.y, t.c.z));

            // 场景里残留物？
            sb.AppendLine("当前场景根对象     : " +
                string.Join(", ", UnityEngine.SceneManagement.SceneManager
                    .GetActiveScene().GetRootGameObjects().Select(o => o.name)));

            Object.DestroyImmediate(go);
            Debug.Log(sb.ToString());
        }

        /// <summary>按真实顶点算包围盒（不依赖 Renderer.bounds，避免滞后一帧）。</summary>
        static Bounds TrueBounds(GameObject root)
        {
            var mfs = root.GetComponentsInChildren<MeshFilter>();
            bool has = false;
            var b = new Bounds();
            foreach (var mf in mfs)
            {
                if (mf.sharedMesh == null) continue;
                var mw = mf.transform.localToWorldMatrix;
                foreach (var v in mf.sharedMesh.vertices)
                {
                    var p = mw.MultiplyPoint3x4(v);
                    if (!has) { b = new Bounds(p, Vector3.zero); has = true; }
                    else b.Encapsulate(p);
                }
            }
            return b;
        }
    }
}
