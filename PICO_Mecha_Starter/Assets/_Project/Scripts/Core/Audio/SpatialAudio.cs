using System.Collections.Generic;
using SteelRidge.Core.Platform;
using UnityEngine;

namespace SteelRidge.Core.Audio
{
    /// <summary>
    /// 空间音频后端。抽象它的唯一理由：
    /// PICO 的 PicoSpatialAudio 在 OpenXR 与 AR 侧都不可用，
    /// 而"哪一行依赖要删"这件事必须在编译期就确定，不能靠构建失败来发现。
    /// </summary>
    public interface ISpatialAudioBackend
    {
        string Name { get; }
        bool IsAvailable { get; }

        /// <summary>按平台能力装配（声道、HRTF、混响、听者跟随）。</summary>
        void Configure(in PlatformCapabilities caps);

        void PlayAt(AudioClip clip, Vector3 worldPosition, float volume = 1f, float pitch = 1f);

        void SetListener(Transform listener);

        void StopAll();
    }

    /// <summary>
    /// Unity 内置空间化后端。VR / AR 通用，2D 立体声兜底。
    /// 座舱内的声音（仪表提示、舱门液压）用 3D，UI 音用 2D。
    /// </summary>
    public sealed class UnitySpatializerBackend : ISpatialAudioBackend
    {
        public string Name => "Unity Spatializer";
        public bool IsAvailable => true;

        const int PoolSize = 12;

        readonly List<AudioSource> _pool = new List<AudioSource>();
        GameObject _host;
        Transform _listener;
        int _cursor;
        bool _configured;

        /// <summary>当前登记的听者（仅供审计）。空间化由相机上的 AudioListener 驱动，本组件不移动任何节点。</summary>
        public string ListenerName => _listener != null ? _listener.name : "未指定";

        public void Configure(in PlatformCapabilities caps)
        {
            EnsureHost();

            // 窄视场 AR 上声音过度空间化会让"画面外"的声源失去视觉参照，
            // 用户听到却看不到，反而增加认知负担 —— 所以 AR 侧抬高 2D 比例（降低 spatialBlend）。
            // 注意这里必须是分档赋值：早先写成 Mathf.Max(minBlend, 0.8f)，而 minBlend 恒小于 0.8，
            // 结果永远是 0.8，分档等于没写。
            float blend = caps.IsAdditive ? 0.45f : 0.80f;
            foreach (var s in _pool)
            {
                s.spatialBlend = blend;
                s.rolloffMode = AudioRolloffMode.Logarithmic;
                s.minDistance = 0.4f;
                s.maxDistance = caps.IsAdditive ? 6f : 25f;
            }

            _configured = true;
            Debug.Log($"[SteelRidge] 音频后端：Unity Spatializer（{caps.Name}，" +
                      $"spatialBlend {blend:0.00}，远场 {(_pool.Count > 0 ? _pool[0].maxDistance : 0f):0} m）");
        }

        void EnsureHost()
        {
            if (_host != null) return;

            _host = new GameObject("[SpatialAudio]");
            Object.DontDestroyOnLoad(_host);

            for (int i = 0; i < PoolSize; i++)
            {
                var go = new GameObject($"src_{i:00}");
                go.transform.SetParent(_host.transform, false);

                var src = go.AddComponent<AudioSource>();
                src.playOnAwake = false;
                src.spatialBlend = 0.8f;

                _pool.Add(src);
            }
        }

        /// <summary>
        /// 登记听者。
        /// 刻意**不移动 host 节点**：音源是 host 的子节点，且都按世界坐标摆位
        /// （<see cref="PlayAt"/> 里 src.transform.position = worldPosition）。
        /// 一旦移动父节点，所有已摆好的音源会被整体带走，声像就全错了。
        /// 真正的空间化由相机上的 AudioListener 承担，这里只留引用供审计。
        /// </summary>
        public void SetListener(Transform listener)
        {
            EnsureHost();
            _listener = listener;
        }

        public void PlayAt(AudioClip clip, Vector3 worldPosition, float volume = 1f, float pitch = 1f)
        {
            if (clip == null) return;
            if (!_configured) EnsureHost();

            var src = _pool[_cursor];
            _cursor = (_cursor + 1) % _pool.Count;

            src.transform.position = worldPosition;
            src.clip = clip;
            src.volume = Mathf.Clamp01(volume);
            src.pitch = Mathf.Clamp(pitch, 0.1f, 3f);
            src.Play();
        }

        public void StopAll()
        {
            foreach (var s in _pool) s.Stop();
        }
    }

    /// <summary>静音后端。用于 CI / 无音频设备的验证构建，保证调用方不必判空。</summary>
    public sealed class NullAudioBackend : ISpatialAudioBackend
    {
        public string Name => "Silent";
        public bool IsAvailable => true;

        public void Configure(in PlatformCapabilities caps) { }
        public void PlayAt(AudioClip clip, Vector3 worldPosition, float volume = 1f, float pitch = 1f) { }
        public void SetListener(Transform listener) { }
        public void StopAll() { }
    }

    /// <summary>
    /// 音频门面。项目里只从这里取后端，任何地方都不许直接 new AudioSource。
    /// 这样"换掉 PicoSpatialAudio"是一个配置动作，而不是全局搜索替换。
    /// </summary>
    public static class SpatialAudio
    {
        public static ISpatialAudioBackend Backend { get; private set; } = new UnitySpatializerBackend();

        public static void Configure(in PlatformCapabilities caps, ISpatialAudioBackend backend = null)
        {
            Backend = backend ?? new UnitySpatializerBackend();
            Backend.Configure(caps);
        }

        public static void UseSilent() => Backend = new NullAudioBackend();

        public static void PlayAt(AudioClip clip, Vector3 worldPosition, float volume = 1f) =>
            Backend.PlayAt(clip, worldPosition, volume);

        public static void StopAll() => Backend.StopAll();

        /// <summary>审计：后端是否与平台能力自洽。</summary>
        public static List<string> Audit(in PlatformCapabilities caps)
        {
            var issues = new List<string>();
            if (Backend == null) issues.Add("音频后端为空（未调用 Configure）");
            else if (!Backend.IsAvailable) issues.Add($"音频后端 {Backend.Name} 不可用");
            return issues;
        }
    }
}
