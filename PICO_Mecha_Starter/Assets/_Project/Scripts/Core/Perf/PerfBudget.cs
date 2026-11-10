using System.Collections.Generic;
using SteelRidge.Core.Platform;
using UnityEngine;

namespace SteelRidge.Core.Perf
{
    /// <summary>性能档位。和 PlatformCapabilities 一一对应，但独立命名，便于在报告里横向比。</summary>
    public enum PerfTier
    {
        VRFlagship = 0,
        VRStandalone = 1,
        ARStation = 2,
        ARGlasses = 3
    }

    /// <summary>一帧的预算。全部是硬上限，超了就是超了，没有"差不多"。</summary>
    public struct FrameBudget
    {
        public PerfTier Tier;
        public int Triangles;
        public int DrawCalls;
        public int Materials;
        public int HoloPanels;
        public int DynamicRenderTextures;

        /// <summary>帧预算（毫秒）。90 Hz = 11.1 ms，这是含渲染与逻辑的总预算。</summary>
        public float FrameMs;

        /// <summary>LOD 距离缩放。>1 表示更早降级。</summary>
        public float LodBias;

        public float BudgetRatio(int actual, int cap) => cap <= 0 ? 0f : (float)actual / cap;

        public override string ToString() =>
            $"{Tier}｜{Triangles / 10000f:0.#}万面 / {DrawCalls} DC / {Materials} 材质 / {HoloPanels} 面板 / {FrameMs:0.0} ms｜LOD×{LodBias:0.00}";
    }

    /// <summary>
    /// 预算规划器。核心主张：**同一套 LOD 曲线，两套缩放**。
    /// 如果 VR 和 AR 各画一条曲线，美术会维护两份资产，最终必然不一致；
    /// 正确做法是共用 <see cref="SharedLodHeights"/>，只按档位缩距离。
    /// </summary>
    public static class PerfBudgetPlanner
    {
        /// <summary>共用的 LOD 屏幕占比断点（Unity LODGroup 的 screenRelativeTransitionHeight）。</summary>
        public static readonly float[] SharedLodHeights = { 0.60f, 0.30f, 0.12f, 0.04f };

        public static FrameBudget From(in PlatformCapabilities caps)
        {
            if (!caps.IsAdditive)
            {
                // 一体机 VR：90 Hz 是硬指标，低于它必然晕
                return new FrameBudget
                {
                    Tier = PerfTier.VRStandalone,
                    Triangles = 900_000,
                    DrawCalls = 200,
                    Materials = 40,
                    HoloPanels = 5,
                    DynamicRenderTextures = 1,
                    FrameMs = 1000f / Mathf.Max(1, caps.RefreshHz),
                    LodBias = 1.0f
                };
            }

            // AR：视场小 → 同屏可见物少，但 GPU 预算也低一个量级；PPD 高 → 纹理压力大
            bool glassesFormFactor = caps.PixelsPerDegree <= 24f && caps.FovHorizontal <= 30f;
            if (glassesFormFactor)
            {
                return new FrameBudget
                {
                    Tier = PerfTier.ARGlasses,
                    Triangles = 60_000,
                    DrawCalls = 40,
                    Materials = 12,
                    HoloPanels = 2,
                    DynamicRenderTextures = 0,
                    FrameMs = 1000f / Mathf.Max(1, caps.RefreshHz),
                    LodBias = 2.5f
                };
            }

            return new FrameBudget
            {
                Tier = PerfTier.ARStation,
                Triangles = 150_000,
                DrawCalls = 60,
                Materials = 20,
                HoloPanels = 3,
                DynamicRenderTextures = 0,
                FrameMs = 1000f / Mathf.Max(1, caps.RefreshHz),
                LodBias = 1.8f
            };
        }

        /// <summary>
        /// 把共用断点缩成该档位可用的 LOD 距离（米）。
        /// baseDistances 是美术在 VR 下标定的距离，AR 侧乘 bias 提前降级。
        /// </summary>
        public static float[] ScaleLodDistances(float[] baseDistances, in FrameBudget budget)
        {
            if (baseDistances == null) return System.Array.Empty<float>();
            var outArr = new float[baseDistances.Length];
            for (int i = 0; i < baseDistances.Length; i++)
                outArr[i] = baseDistances[i] / Mathf.Max(0.01f, budget.LodBias);
            return outArr;
        }

        /// <summary>
        /// 预算对比表。直接进报告，用于说明"为什么 AR 侧必须砍模型"。
        /// </summary>
        public static List<string> CompareTable(IEnumerable<FrameBudget> budgets)
        {
            var lines = new List<string>
            {
                "| 档位 | 三角面 | Draw Call | 材质 | 全息面板 | 动态 RT | 帧预算 | LOD 缩放 |",
                "|---|---|---|---|---|---|---|---|"
            };

            foreach (var b in budgets)
            {
                lines.Add($"| {b.Tier} | {b.Triangles / 10000f:0.#} 万 | {b.DrawCalls} | {b.Materials} | {b.HoloPanels} | {b.DynamicRenderTextures} | {b.FrameMs:0.0} ms | ×{b.LodBias:0.00} |");
            }

            return lines;
        }
    }

    /// <summary>
    /// 运行时预算执行器。每 Interval 秒粗算一次场景规模，超预算只告警一次（不刷屏）。
    /// 之所以自己数而不是读 Profiler：玩家版本没有 Profiler 数据，
    /// 而"在真机上第一次发现超预算"是最贵的发现方式。
    /// </summary>
    public sealed class PerfBudgetEnforcer : MonoBehaviour
    {
        [Tooltip("采样间隔（秒）。太频繁本身就成了开销")]
        public float interval = 5f;

        [Tooltip("计入统计的根节点。留空 = 全场景")]
        public Transform scopeRoot;

        public FrameBudget Budget { get; private set; }
        public int LastTriangles { get; private set; }
        public int LastRenderers { get; private set; }

        readonly HashSet<Material> _materials = new HashSet<Material>();
        float _next;
        bool _warnedTri;
        bool _warnedDc;

        public void Apply(in PlatformCapabilities caps)
        {
            Budget = PerfBudgetPlanner.From(caps);
            Debug.Log($"[SteelRidge] 性能预算：{Budget}");
        }

        void Update()
        {
            if (Time.unscaledTime < _next) return;
            _next = Time.unscaledTime + Mathf.Max(1f, interval);
            Sample();
        }

        public void Sample()
        {
            var root = scopeRoot != null ? scopeRoot : null;
            var renderers = root != null
                ? root.GetComponentsInChildren<Renderer>(true)
                : FindObjectsByType<Renderer>(FindObjectsInactive.Exclude, FindObjectsSortMode.None);

            int tris = 0;
            int count = 0;
            _materials.Clear();

            foreach (var r in renderers)
            {
                if (r == null || !r.enabled || !r.gameObject.activeInHierarchy) continue;

                count++;

                if (r is MeshRenderer)
                {
                    var mf = r.GetComponent<MeshFilter>();
                    if (mf != null && mf.sharedMesh != null)
                        tris += (int)(mf.sharedMesh.triangles.Length / 3L);
                }
                else if (r is SkinnedMeshRenderer smr && smr.sharedMesh != null)
                {
                    tris += (int)(smr.sharedMesh.triangles.Length / 3L);
                }

                foreach (var m in r.sharedMaterials)
                    if (m != null) _materials.Add(m);
            }

            LastTriangles = tris;
            LastRenderers = count;

            if (!_warnedTri && tris > Budget.Triangles)
            {
                _warnedTri = true;
                Debug.LogWarning($"[SteelRidge] 三角面超预算：{tris:N0} / {Budget.Triangles:N0}（{Budget.Tier}）");
            }

            if (!_warnedDc && count > Budget.DrawCalls * 2)
            {
                // renderer 数不等于 DC（批处理会合并），超过 2 倍才值得报
                _warnedDc = true;
                Debug.LogWarning($"[SteelRidge] renderer 数 {count} 远超 DC 预算 {Budget.DrawCalls}，批处理可能失效（材质 {_materials.Count} 个）");
            }
        }

        public List<string> Report()
        {
            var lines = new List<string>
            {
                $"档位：{Budget.Tier}",
                $"三角面：{LastTriangles:N0} / {Budget.Triangles:N0}（{Budget.BudgetRatio(LastTriangles, Budget.Triangles):P0}）",
                $"renderer：{LastRenderers} / DC 预算 {Budget.DrawCalls}",
                $"材质：{_materials.Count} / {Budget.Materials}"
            };

            if (LastTriangles > Budget.Triangles) lines.Add("→ 超预算：优先降 LOD，其次合并材质");
            else if (LastTriangles > Budget.Triangles * 0.85f) lines.Add("→ 接近上限，留不出弹性给特效");

            return lines;
        }
    }
}
