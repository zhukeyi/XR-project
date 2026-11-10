using System.Collections.Generic;
using SteelRidge.Core.Platform;
using UnityEngine;

namespace SteelRidge.Core.Inputs
{
    /// <summary>
    /// 抽象输入通道。gameplay 只认这八个，不认手柄按键名。
    /// 换设备时换的是"谁来供这个通道"，不是改 gameplay。
    /// </summary>
    public enum InputChannel
    {
        /// <summary>转向（左正右负）。</summary>
        SteerYaw = 0,

        /// <summary>俯仰（抬头为正）。</summary>
        SteerPitch = 1,

        /// <summary>油门 0–1。</summary>
        Throttle = 2,

        /// <summary>主武器扳机 0–1。</summary>
        Trigger = 3,

        /// <summary>握持（抓杆/抓刀）0–1。</summary>
        Grip = 4,

        /// <summary>助推 0–1。</summary>
        Boost = 5,

        /// <summary>菜单。</summary>
        Menu = 6,

        /// <summary>面板选择（射线/注视/手势确认归一为一个脉冲）。</summary>
        PanelSelect = 7
    }

    /// <summary>
    /// 一个输入源。声明自己需要什么能力，供不出该通道就返回 false 让路由器降级到下一个。
    /// </summary>
    public interface IInputSource
    {
        string Name { get; }

        /// <summary>该源需要的能力位。PlatformCapabilities.Inputs 不含此位时整源跳过。</summary>
        InputCapability Requires { get; }

        bool Supports(InputChannel channel);

        bool TryRead(InputChannel channel, out float value);

        void Tick(float dt);
    }

    /// <summary>
    /// 输入路由。按注册顺序尝试，第一个能供出值的源胜出。
    /// 目的是让"没有 6DoF 手柄"这类差异表现为一次降级，而不是一串 NullReferenceException。
    /// </summary>
    public sealed class InputRouter
    {
        readonly List<IInputSource> _sources = new List<IInputSource>();
        PlatformCapabilities _caps;
        bool _configured;

        public void Configure(in PlatformCapabilities caps)
        {
            _caps = caps;
            _configured = true;
        }

        public void Add(IInputSource source)
        {
            if (source == null) return;
            _sources.Add(source);
        }

        public void Clear() => _sources.Clear();

        public void Tick(float dt)
        {
            for (int i = 0; i < _sources.Count; i++) _sources[i].Tick(dt);
        }

        /// <summary>某个源在当前能力下是否可用。</summary>
        public bool IsActive(IInputSource s)
        {
            if (!_configured) return true;
            if (s.Requires == InputCapability.None) return true;
            return (_caps.Inputs & s.Requires) == s.Requires;
        }

        public bool TryRead(InputChannel channel, out float value, out string via)
        {
            for (int i = 0; i < _sources.Count; i++)
            {
                var s = _sources[i];
                if (!IsActive(s) || !s.Supports(channel)) continue;
                if (s.TryRead(channel, out value))
                {
                    via = s.Name;
                    return true;
                }
            }

            value = 0f;
            via = null;
            return false;
        }

        public float Read(InputChannel channel)
        {
            return TryRead(channel, out var v, out _) ? v : 0f;
        }

        /// <summary>
        /// 降级审计：每个通道由谁供，哪些源被跳过、为什么。
        /// 这是"AR 上没有手柄会怎样"这个问题的可执行答案。
        /// </summary>
        public List<string> Audit()
        {
            var lines = new List<string>();

            for (int ch = 0; ch <= (int)InputChannel.PanelSelect; ch++)
            {
                var channel = (InputChannel)ch;
                string provider = null;
                var skipped = new List<string>();

                for (int i = 0; i < _sources.Count; i++)
                {
                    var s = _sources[i];
                    if (!s.Supports(channel)) continue;

                    if (!IsActive(s))
                    {
                        skipped.Add($"{s.Name}（缺 {MissingCapability(s)}）");
                        continue;
                    }

                    provider ??= s.Name;
                }

                if (provider == null)
                    lines.Add($"[MISSING] {channel}：无可用输入源（跳过：{string.Join("，", skipped)}）");
                else if (skipped.Count == 0)
                    lines.Add($"[OK] {channel} ← {provider}");
                else
                    lines.Add($"[DEGRADED] {channel} ← {provider}（跳过：{string.Join("，", skipped)}）");
            }

            return lines;
        }

        string MissingCapability(IInputSource s)
        {
            var missing = s.Requires & ~_caps.Inputs;
            return missing.ToString();
        }
    }
}
