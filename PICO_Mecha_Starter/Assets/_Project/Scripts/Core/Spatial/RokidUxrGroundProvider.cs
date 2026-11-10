using UnityEngine;

namespace SteelRidge.Core.Spatial
{
    /// <summary>
    /// Rokid UXR 平面数据的落地适配器。
    ///
    /// 它做两件事，且只做两件事：
    /// 1) **固定宿主调用契约**：UXR 的平面回调（中心位姿 + 类型 + 置信度 + 尺寸）只要翻成
    ///    <see cref="Submit"/> 的四个参数推进来，权重融合、桌面排除、多平面叠加全部复用
    ///    <see cref="DetectedPlaneProvider"/> —— 同一套判据在 PICO 的 AR 模式与 Rokid 上一致。
    /// 2) **把平台差异关在这一个类里**：本文件不出现任何 Rokid SDK 命名空间，
    ///    宿主脚本（引用 UXR SDK 的那个）负责字段映射。这样 VR 构建仍能原样编译，
    ///    合规自检里「无 PICO / Rokid 专有命名空间引用」也仍然是 PASS。
    ///
    /// 不接的情形：3DoF 设备（Rokid Glasses 一类）。纯旋转下平面深度不可观测，
    /// 检测出来的 y 会随头部转动漂移。这条路已由 <see cref="GroundAnchor.Configure"/>
    /// 按 <c>HasWorldScale</c> 拦掉，本适配器不需要再判一次。
    ///
    /// 现状：骨架。没有任何调用方 —— 接 UXR 之前它就是死的，但签名对上这件事必须先验证，
    /// 否则等 SDK 到位才发现要改接口，抽象层就白做了。
    /// </summary>
    public sealed class RokidUxrGroundProvider : IGroundProvider
    {
        readonly DetectedPlaneProvider _inner = new DetectedPlaneProvider();

        public GroundSource Source => GroundSource.DetectedPlane;

        /// <summary>直接暴露内部判据参数，便于在真机上调参与审计时与 VR 侧对齐。</summary>
        public DetectedPlaneProvider Inner => _inner;

        public bool TrySample(Vector3 probeWorld, out GroundHit hit) => _inner.TrySample(probeWorld, out hit);

        /// <summary>
        /// 宿主每帧调用。UXR 侧字段对应关系：
        /// centerPose.position → <paramref name="center"/>（世界坐标，米）；
        /// centerPose.rotation * up → <paramref name="normal"/>（必须是单位向量，内部会再归一化）；
        /// plane.extent / 2 → <paramref name="halfExtent"/>（半长，不是全长）；
        /// plane.confidence → <paramref name="confidence"/>（0–1，没有就给 0.8 的保守默认）。
        /// 时间戳不传：内部用 Time.unscaledTime 判新鲜度，避免宿主与 Unity 时钟不同源。
        /// </summary>
        public void Submit(Vector3 center, Vector3 normal, Vector2 halfExtent, float confidence = 0.8f)
        {
            _inner.Submit(center, normal, halfExtent, confidence, Time.unscaledTime);
        }

        /// <summary>水平面的便捷重载：UXR 的 floor 类型平面只需要中心与长宽。</summary>
        public void SubmitHorizontal(Vector3 center, float sizeX, float sizeZ, float confidence = 0.8f)
        {
            Submit(center, Vector3.up, new Vector2(sizeX * 0.5f, sizeZ * 0.5f), confidence);
        }

        /// <summary>平面消失 / 切场景时清池，否则残影会以低权重继续参与融合直到过期。</summary>
        public void Clear() => _inner.Clear();

        /// <summary>当前池中平面数（审计用）。</summary>
        public int Count => _inner.Count;

        /// <summary>有效倾角截止（度），由实际权重函数扫出，与 VR 侧同源。</summary>
        public float EffectiveTiltCutoffDeg => _inner.EffectiveTiltCutoffDeg();

        /// <summary>有效高度截止（米），同时也是眼高假设的误差预算。</summary>
        public float EffectiveHeightCutoffMeters => _inner.EffectiveHeightCutoffMeters();
    }
}
