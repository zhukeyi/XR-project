using SteelRidge.Core.Platform;
using UnityEngine;

namespace SteelRidge.Core.Spatial
{
    /// <summary>视角与座舱的相对关系。这是"把人钉在座椅上"这个假设的显式表达。</summary>
    public enum FollowMode
    {
        /// <summary>3DoF：座舱完全补偿头部平移，等于永远坐在原位。</summary>
        Locked = 0,

        /// <summary>坐姿 VR：允许 ±r 的头部平移（自然的探头感），超出则座舱跟着挪。</summary>
        SeatedClamp = 1,

        /// <summary>AR 房间尺度：座舱跟随用户水平移动，忽略俯仰与竖直。</summary>
        FollowHorizontal = 2
    }

    /// <summary>
    /// 视点策略。核心思路是**移动座舱，而不是钳制相机**。
    /// 理由：直接写相机 transform 会和 XR 运行时的重投影/晚锁争夺位姿，
    /// 表现为画面抖、边缘拉扯；而反向平移座舱根节点只是改场景层级，
    /// 视觉结果等价（相对位姿被约束），但不触碰跟踪数据。
    ///
    /// 三种模式共用同一套补偿逻辑，只改半径与平滑，因此 VR / AR 不会分叉出两套代码。
    /// </summary>
    [DefaultExecutionOrder(1000)]
    public sealed class ViewpointPolicy : MonoBehaviour
    {
        [Tooltip("座舱根节点（被移动的对象）")]
        public Transform cockpitRoot;

        [Tooltip("视点（通常是 XR Origin 下的相机）")]
        public Transform viewpoint;

        [Tooltip("跟随平滑（秒）。0 = 硬跟随，AR 里建议 0.12")]
        public float smoothing = 0.12f;

        [Tooltip("FollowHorizontal 模式下是否跟随用户朝向（false = 座舱保持世界朝向）")]
        public bool followYaw = true;

        public FollowMode Mode { get; private set; } = FollowMode.SeatedClamp;

        float _radius = 0.15f;
        Vector3 _velocity;
        float _yawVelocity;

        public void Configure(in PlatformCapabilities caps, Transform cockpit, Transform view)
        {
            cockpitRoot = cockpit;
            viewpoint = view;

            switch (caps.Translation)
            {
                case TranslationSupport.None:
                    // 3DoF：只有旋转，真实世界尺度不可观测（ScaleGrounding.HeadRelative）。
                    // 因此这里不承诺任何"米"——半径 0 的含义是"座舱完全吃掉平移量"，
                    // 而平移量本身在这个形态下恒为 0，所以实际效果是座舱刚性跟头。
                    Mode = FollowMode.Locked;
                    _radius = 0f;
                    smoothing = 0f;
                    break;

                case TranslationSupport.SeatedClamp:
                    Mode = FollowMode.SeatedClamp;
                    _radius = Mathf.Max(0f, caps.MaxTranslationMeters);
                    break;

                case TranslationSupport.RoomScale:
                    Mode = FollowMode.FollowHorizontal;
                    _radius = 0f;
                    smoothing = 0.12f;
                    followYaw = !caps.IsAdditive; // AR 里 favour 稳定：默认不跟朝向
                    break;
            }

            Debug.Log($"[SteelRidge] ViewpointPolicy：{caps.Name} → {Mode}（半径 {_radius:0.00} m）");
        }

        void LateUpdate()
        {
            if (cockpitRoot == null || viewpoint == null) return;

            // ★ SE(3) 一致性：位姿是流形上的量（SLAM Handbook §2.1.4），位置与朝向必须用
            //   同一时间常数平滑，且朝向先更新、位移在更新后的朝向下解算。
            //   早先的写法是位置 SmoothDamp 0.12 s、朝向硬赋值，两者时间常数不一致，
            //   刚体轨迹在 SE(3) 上不连续 —— 表现为座舱绕一个滞后的点甩动，AR 里尤其明显
            //   （真实场景不跟着甩，人立刻察觉）。改成同步平滑后，舱体只做刚性运动。
            var targetRot = ComputeTargetRotation();

            // 只在需要改朝向时碰旋转：Locked / SeatedClamp 下座舱朝向由关卡布置决定，
            // 每帧重写会把可能存在的俯仰一起抹平。
            if (targetRot.HasValue)
            {
                if (smoothing > 0f)
                {
                    float yaw = Mathf.SmoothDampAngle(cockpitRoot.eulerAngles.y, targetRot.Value.eulerAngles.y,
                                                      ref _yawVelocity, smoothing);
                    cockpitRoot.rotation = Quaternion.Euler(0f, yaw, 0f);
                }
                else
                {
                    cockpitRoot.rotation = targetRot.Value;
                }
            }

            var target = ComputeTargetPosition();
            if (target == null) return;

            cockpitRoot.position = smoothing > 0f
                ? Vector3.SmoothDamp(cockpitRoot.position, target.Value, ref _velocity, smoothing)
                : target.Value;
        }

        /// <summary>
        /// 座舱应有的朝向。只有 FollowHorizontal + followYaw 才改朝向；
        /// 其余模式返回 null，表示"不要动朝向"，避免把胶囊体拧歪。
        /// </summary>
        Quaternion? ComputeTargetRotation()
        {
            if (Mode != FollowMode.FollowHorizontal || !followYaw) return null;
            var e = viewpoint.eulerAngles;
            return Quaternion.Euler(0f, e.y, 0f);
        }

        /// <summary>
        /// 计算座舱应该在哪。返回 null 表示不需要动。
        /// 语义：让「视点相对座舱的偏移」落在允许范围内。
        /// </summary>
        Vector3? ComputeTargetPosition()
        {
            // 视点在座舱本地空间中的偏移（去掉座舱自身的旋转影响）
            var localOffset = cockpitRoot.InverseTransformPoint(viewpoint.position);

            Vector3 allowed;

            switch (Mode)
            {
                case FollowMode.Locked:
                    // 完全补偿：座舱吃掉全部平移，人永远在舱内同一位置
                    allowed = Vector3.zero;
                    break;

                case FollowMode.SeatedClamp:
                    // 只钳制水平面内超出半径的部分，竖直方向保留（头抬起不该带动舱）
                    var horizontal = new Vector3(localOffset.x, 0f, localOffset.z);
                    allowed = horizontal.magnitude <= _radius
                        ? localOffset
                        : new Vector3(horizontal.normalized.x * _radius, localOffset.y, horizontal.normalized.z * _radius);
                    break;

                case FollowMode.FollowHorizontal:
                default:
                    // 座舱跟着人走：水平偏移清零，竖直保留（人蹲下时舱不跟着沉）
                    allowed = new Vector3(0f, localOffset.y, 0f);
                    break;
            }

            // 无位移指令时不动，省掉一次矩阵运算
            var delta = localOffset - allowed;
            if (delta.sqrMagnitude < 1e-6f) return null;

            // 反向平移座舱：把超出的部分抵消掉
            return cockpitRoot.position - cockpitRoot.TransformVector(delta);
        }

        /// <summary>
        /// 审计用：当前模式在给定位移下会把座舱推多远。
        /// 用于回答"AR 里用户走 3 米，座舱会跟着飘多远"。
        /// </summary>
        public float PredictedDrift(float userMoveMeters)
        {
            switch (Mode)
            {
                case FollowMode.Locked: return userMoveMeters;          // 全部由座舱吸收
                case FollowMode.SeatedClamp: return Mathf.Max(0f, userMoveMeters - _radius);
                case FollowMode.FollowHorizontal: return userMoveMeters;
                default: return 0f;
            }
        }
    }
}
