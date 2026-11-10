"""
gfx/texgen.py — 程序化 PBR 图集生成（M2）

设计取舍（与《纹理流程规格.md》的差异，必须说明）
--------------------------------------------------
规格假定的路线是「图像模型出底图 → 六步净化 → 图集」。本实现走的是规格第 3 节的
**降级路径（纯程序化）**，原因有两条：

1. 净化流程（低频压制 / 边缘融合 / 频域对齐）只有在真的有模型图时才有意义。
   程序化噪声天然无缝、天然无光照烘焙，跳过净化反而更干净。
2. 无缝性在这里是构造性的，不是修补出来的：所有噪声都用**周期性晶格**生成，
   所有模糊/求导都用 `wrap` 边界。所以「3×3 平铺无接缝」不是靠事后检测去凑，
   而是数学上必然成立。规格环节 3 的 a/b/c 三步一步都不需要。

规格里的环节 2/3（净化、无缝化）代码保留在 `purify()` / `seam_blend()` 里，
只在 `sources=` 传入真实图片时才走。这样两条路都通，只是默认走程序化。

UV 方案：三平面（triplanar）而非 UV 展开
--------------------------------------------------
M1 的 UV 是 `(x*0.15, z*0.15)` 的 XZ 平面投影 —— 朝前的面完全被压扁，是占位值。
真做 UV 展开需要按图元类型手动切边、处理接缝、写图集布局，成本远高于收益。

改为三平面：按世界空间法线的主轴选投影面，坐标取自世界位置。好处是
  · 所有零件纹素密度一致（不管盒子被拉多长，不会拉伸）
  · 无需展开，任意新图元自动适配
  · 图集分区只是「选哪个区块」的整数偏移，不参与采样
代价是 45° 过渡带会有轻微双重投影；用 `blend` 控制过渡带宽度，实测 0.25 足够。

坐标约定
--------
图集通道均为 float32 [0,1]。
法线图是切线空间，OpenGL 约定（+Y 朝上），编码 `n*0.5+0.5`。
"""
import math
import numpy as np
from PIL import Image, ImageDraw, ImageFont

EPS = 1e-9

# ---------------------------------------------------------------- 材质定义
# mean 是 texcheck 的亮度靶值（RGB 三通道算术平均），不是 Rec.709 亮度 ——
# 校验器读的是像素值，口径必须和它一致，否则调不到靶。
MATSPEC = {
    'w':  dict(name='装甲白', rgb=(0.885, 0.895, 0.905), mean=0.90,
               metal=0.00, ns=1.4, rough=0.40, cell=0.30, wear=0.55),
    'bl': dict(name='装甲蓝', rgb=(0.070, 0.235, 0.470), mean=0.26,
               metal=0.00, ns=1.4, rough=0.34, cell=0.34, wear=0.60),
    'rd': dict(name='警示红', rgb=(0.655, 0.135, 0.150), mean=0.32,
               metal=0.00, ns=1.5, rough=0.32, cell=0.42, wear=0.70),
    'gr': dict(name='骨架深灰', rgb=(0.230, 0.238, 0.250), mean=0.24,
               metal=0.85, ns=3.0, rough=0.55, cell=0.20, wear=0.85),
}
KEYS = ('w', 'bl', 'rd', 'gr')


# ================================================================ 基础算子
def _blur1d_wrap(a, r, axis):
    """wrap 边界的盒式模糊（沿单轴）。用前缀和实现，O(N) 与半径无关。

    wrap 而非 reflect：只有 wrap 才能保证「模糊后的图仍然无缝」。reflect 会在
    边界造出一条假的亮/暗带，3×3 平铺时上下两条边对不上。
    """
    n = a.shape[axis]
    r = int(r)
    if r < 1:
        return a
    r = min(r, max(1, n // 2))
    k = 2 * r + 1
    idx_pre = np.arange(n - r, n) % n
    idx_post = np.arange(0, r) % n
    pad = np.concatenate([np.take(a, idx_pre, axis=axis), a,
                          np.take(a, idx_post, axis=axis)], axis=axis)
    c = np.cumsum(pad, axis=axis, dtype=np.float32)
    sh = list(pad.shape)
    sh[axis] = 1
    c = np.concatenate([np.zeros(sh, np.float32), c], axis=axis)
    hi = np.take(c, np.arange(k, k + n), axis=axis)
    lo = np.take(c, np.arange(0, n), axis=axis)
    return (hi - lo) * (1.0 / k)


def blur_wrap(a, r):
    """近似高斯：三次盒式。半径 r 的等效 σ ≈ r*0.87。"""
    if r < 1:
        return a
    b = _blur1d_wrap(a, r, 0)
    b = _blur1d_wrap(b, r, 1)
    b = _blur1d_wrap(b, r, 0)
    return b


def _snap_freq(freq, size):
    """把晶格数吸附到能整除 size 的值。

    ★ 这是无缝性的硬前提（踩过的坑）：值噪声的晶格周期是 size/freq 个像素，
    只有 freq 整除 size，索引 size-1 → 0 才恰好跨过一个完整周期。
    freq=160 / size=512 时 512/160=3.2，接缝处错位 0.2 个格子 —— 3×3 平铺
    的接缝梯度会是内部的 3.35 倍。实测就是这么暴露出来的。

    size 是 2 的幂时吸附到最近的 2 的幂即可；否则退到最大真因子。
    """
    freq = max(1, int(round(freq)))
    if size % freq == 0:
        return freq
    if size & (size - 1) == 0:                      # size 是 2 的幂
        import math as _m
        return max(1, 1 << int(round(_m.log2(freq))))
    for f in range(min(freq, size), 0, -1):         # 最大真因子
        if size % f == 0:
            return f
    return 1


def _value_noise(h, w, freq, rng):
    """周期性值噪声。freq 吸附到 size 的因子，保证 t=1 时坐标恰好绕回 0。"""
    freq = _snap_freq(freq, min(h, w))
    g = rng.random((freq, freq)).astype(np.float32)
    ys = (np.arange(h, dtype=np.float32) + 0.5) * (freq / h)
    xs = (np.arange(w, dtype=np.float32) + 0.5) * (freq / w)
    y0 = np.floor(ys).astype(np.int32)
    x0 = np.floor(xs).astype(np.int32)
    fy = ys - y0
    fx = xs - x0
    fy = fy * fy * (3.0 - 2.0 * fy)          # smoothstep，消除线性插值的方格感
    fx = fx * fx * (3.0 - 2.0 * fx)
    y0 %= freq
    x0 %= freq
    y1 = (y0 + 1) % freq
    x1 = (x0 + 1) % freq
    v00 = g[np.ix_(y0, x0)]
    v01 = g[np.ix_(y0, x1)]
    v10 = g[np.ix_(y1, x0)]
    v11 = g[np.ix_(y1, x1)]
    a = v00 + (v01 - v00) * fx[None, :]
    b = v10 + (v11 - v10) * fx[None, :]
    return a + (b - a) * fy[:, None]


def spectral_noise(h, w, alpha=1.8, rng=None, f_lo=2.0, f_hi=None):
    """频域整形噪声：白噪 → FFT → 乘 k^(-α/2) → IFFT。

    为什么用它代替叠八度 fBm（两组实测数据）：
      · 叠八度：值噪声的功率谱本身就比 1/f² 陡，加上 5 个八度后实测 α=2.75~2.90，
        超出规格的 [1.2, 2.2]；靠调 gain 硬凑会把高频一起抬起来，像噪点。
      · 频域整形：α 是**直接参数**，一次 FFT 到位，且 DFT 天然周期
        —— 无缝性是这个方法的副产品，不是额外工作。
    代价是多一次 rfft2/irfft2（1024² 约 30 ms），可接受。
    """
    rng = rng or np.random.default_rng(0)
    F = np.fft.rfft2(rng.standard_normal((h, w)).astype(np.float32))
    fy = np.fft.fftfreq(h)[:, None] * h
    fx = np.fft.rfftfreq(w)[None, :] * w
    k = np.sqrt(fx * fx + fy * fy)
    k[0, 0] = 1.0
    g = np.power(k, -0.5 * alpha).astype(np.float32)
    g[k < f_lo] = 0.0                # 掐掉 DC 与极低频，否则整块出现巨大色斑
    if f_hi:
        g[k > f_hi] = 0.0
    g[0, 0] = 0.0
    out = np.fft.irfft2(F * g, s=(h, w)).astype(np.float32)
    lo, hi = float(out.min()), float(out.max())
    return (out - lo) / max(hi - lo, EPS)


def fbm(h, w, octaves=4, freq0=4, rng=None, gain=0.5, lac=2):
    """fBm。gain=0.5 / lac=2 时二维径向功率谱 ≈ 1/f²，落在规格要求的 α∈[1.2,2.2] 内。"""
    rng = rng or np.random.default_rng(0)
    out = np.zeros((h, w), np.float32)
    amp, tot, f = 1.0, 0.0, freq0
    for _ in range(octaves):
        out += _value_noise(h, w, f, rng) * amp
        tot += amp
        amp *= gain
        f = int(max(1, round(f * lac)))
    out /= tot
    lo, hi = float(out.min()), float(out.max())
    return (out - lo) / max(hi - lo, EPS)


def _sobel_wrap(a):
    """wrap 边界的中心差分。返回 (dh/dx, dh/dy)，像素单位。"""
    dx = (np.roll(a, -1, 1) - np.roll(a, 1, 1)) * 0.5
    dy = (np.roll(a, -1, 0) - np.roll(a, 1, 0)) * 0.5
    return dx, dy


def sat(x):
    return np.clip(x, 0.0, 1.0)


# ================================================================ 面板与磨损
def _cut_positions(size, n, rng, jitter=0.22):
    """等分 + 抖动。等分保证平铺后格子尺寸均匀，抖动去掉「瓷砖感」。"""
    base = np.arange(n, dtype=np.float32) * (size / n)
    j = rng.uniform(-jitter, jitter, n).astype(np.float32) * (size / n)
    return np.sort((base + j) % size)


def _dist_to_lines(size, pos):
    """一维坐标到最近分割线的距离，wrap。pos 已经在 [0,size)。"""
    xs = np.arange(size, dtype=np.float32) + 0.5
    d = (xs[:, None] - pos[None, :] + size * 0.5) % size - size * 0.5
    return np.abs(d).min(axis=1)


def _broken_envelope(size, rng, keep=0.72, soft=6.0):
    """沿一条线的通断包络：0..1，先低分辨率随机再平滑，边缘软一点像崩漆。"""
    nb = 28
    b = (rng.random(nb) < keep).astype(np.float32)
    b = np.repeat(b, int(math.ceil(size / nb)))[:size]
    return sat(blur_wrap(b[None, :], int(soft))[0] * 1.6)


def _panel_layer(size, cell, rng):
    """面板线 / 倒角 / 铆钉。全部 wrap，平铺无缝。

    返回 dict:
      groove  凹陷（压暗、下压高度）
      bevel   上侧倒角高光（受光边）
      rivet   铆钉遮罩 (0..1)
      corners 铆钉中心的像素坐标列表
    """
    n = max(2, int(round(1.0 / cell)))
    vx = _cut_positions(size, n, rng)
    hy = _cut_positions(size, n, rng)

    W = 2.0                       # 主沟宽（px）
    dv = _dist_to_lines(size, vx)     # 沿 x 变化
    dh = _dist_to_lines(size, hy)     # 沿 y 变化
    # 抗锯齿：以 W/2 为中心，1.2px 过渡
    lv = sat((W * 0.5 + 0.6 - dv) / 1.2)
    lh = sat((W * 0.5 + 0.6 - dh) / 1.2)

    # 通断：每条线有自己的包络（竖线按 y 断，横线按 x 断）
    env_v = np.stack([_broken_envelope(size, rng) for _ in range(len(vx))])  # (nv,size)
    env_h = np.stack([_broken_envelope(size, rng) for _ in range(len(hy))])  # (nh,size)
    # 取最近的线的包络（简化：直接取最小距离那条的索引）
    iv = np.abs((np.arange(size, dtype=np.float32)[:, None] - vx[None, :]
                 + size * 0.5) % size - size * 0.5).argmin(axis=1)
    ih = np.abs((np.arange(size, dtype=np.float32)[:, None] - hy[None, :]
                 + size * 0.5) % size - size * 0.5).argmin(axis=1)

    groove_v = (lv * env_v[iv, :].T)            # (size_y, size_x)
    groove_h = (lh * env_h[ih, :])              # (size_y, size_x)
    groove = sat(groove_v + groove_h - groove_v * groove_h)

    # 倒角：把 groove 向上平移 2px（光从上方来，沟的上沿是亮的）
    bevel = np.roll(groove, -2, axis=0)
    bevel = sat(bevel - groove) * 0.9

    # 铆钉：格子交点
    corners = []
    xs = np.arange(size, dtype=np.float32) + 0.5
    ys = np.arange(size, dtype=np.float32) + 0.5
    dmin = np.full((size, size), 1e9, np.float32)
    for cx in vx:
        for cy in hy:
            dx = np.abs((xs - cx + size * 0.5) % size - size * 0.5)
            dy = np.abs((ys - cy + size * 0.5) % size - size * 0.5)
            d2 = np.maximum(dx[None, :], dy[:, None])       # 方形铆钉
            np.minimum(dmin, d2, out=dmin)
            corners.append((float(cx), float(cy)))
    R = 3.2
    rivet = sat((R + 0.7 - dmin) / 1.4)
    rivet_hi = sat((R + 2.2 - dmin) / 1.4) - rivet        # 外圈亮边
    return dict(groove=groove, bevel=bevel, rivet=rivet,
                rivet_hi=sat(rivet_hi), corners=corners, n=n)


def _stencil(size, rng, text=None, cell=0.5):
    """编号喷字。程序化在这里比图像模型强 —— 模型画不准字。

    放在图块正中央且宽度 < 0.55 块，保证平铺时不跨边、不被切。
    """
    m = Image.new('L', (size, size), 0)
    d = ImageDraw.Draw(m)
    txt = text or ('%02d' % rng.integers(1, 40))
    px = int(size * 0.16)
    font = None
    for path in ('/System/Library/Fonts/Supplemental/DIN Condensed Bold.ttf',
                 '/System/Library/Fonts/Helvetica.ttc',
                 '/System/Library/Fonts/Supplemental/Arial Bold.ttf'):
        try:
            font = ImageFont.truetype(path, px)
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()
    tw = d.textlength(txt, font=font) if hasattr(d, 'textlength') else px * len(txt) * 0.6
    d.text(((size - tw) * 0.5, size * 0.42), txt, fill=255, font=font)
    a = np.asarray(m, np.float32) / 255.0
    # 笔画先柔 0.8px：硬二值字形在径向谱上是一根 3.0 的刺（实测），
    # 且喷字本来就不是刀刻的，边缘该有雾化
    a = sat(blur_wrap(a, 1) * 1.35)
    # 剥落：用噪声吃掉一部分笔画
    flake = spectral_noise(size, size, alpha=1.55, rng=rng, f_lo=14.0)
    a = a * sat((flake - 0.24) * 2.6)
    return a


def _wear(albedo_l, groove, rng, target=0.13):
    """磨损遮罩：沟边邻近度 + 噪声阈值。

    没有 scipy 就没有真 EDT，用「沟掩膜的小半径模糊」近似邻近度场 —— 对磨损来说
    这个近似完全够用：磨损本质是「离边越近越脏」，不需要精确欧氏距离。

    ★ target 是显式目标均值，靠偏移量反解，不靠手感调。上一版写死 −0.28 偏移，
    实测均值只有 0.015 —— 等于整片被 sat() 吃掉，磨损完全没生效，但它在频谱里
    照样贡献了一份陡峭度（α=4.84）。这种「看不见却拖后腿」的项最难查，
    所以这里改成用 `np.quantile` 反解偏移：取 1−target 分位数当阈值。
    """
    near = sat(blur_wrap(groove, 4) * 6.0)
    n1 = spectral_noise(*albedo_l.shape, alpha=1.85, rng=rng, f_lo=8.0)
    n2 = spectral_noise(*albedo_l.shape, alpha=1.10, rng=rng, f_lo=40.0)
    raw = near * 0.62 + sat((n1 - 0.52) * 2.0) * 0.60 + (n2 - 0.5) * 0.55
    thr = float(np.quantile(raw, 1.0 - target))
    w = sat((raw - thr) / max(1e-3, 1.0 - thr))
    return sat(blur_wrap(w, 1) * 1.10)


# ================================================================ 单块生成
def _proc_tile(key, size, seed):
    """纯程序化生成一块 1024² 材质。返回 (rgb, height, rough_mul, wear, info)"""
    sp = MATSPEC[key]
    rng = np.random.default_rng(seed)
    base = np.array(sp['rgb'], np.float32)

    # ★ 不要设 f_hi。带限会在截止频率处造出「断崖」，径向谱拟合看到的是断崖不是
    #   斜率 —— 实测 f_hi=0.18S 的场真实 α=2.35，被测成 13.79。让 k^-α 一直延伸到
    #   Nyquist：这是自然纹理该有的样子，顺带把 8bit 量化的带状噪声压掉。
    macro = spectral_noise(size, size, alpha=1.72, rng=rng, f_lo=3.0)
    micro = spectral_noise(size, size, alpha=1.45, rng=rng, f_lo=26.0)
    # 漆面应有的细微色差：大尺度 ±8%，微观 ±5%
    L = 1.0 + (macro - 0.5) * 0.16 + (micro - 0.5) * 0.10

    pl = _panel_layer(size, sp['cell'], rng)
    groove, bevel = pl['groove'], pl['bevel']
    rivet, rivet_hi = pl['rivet'], pl['rivet_hi']

    # 凹陷压暗 + 倒角提亮 + 铆钉
    L = L * (1.0 - 0.42 * groove) + 0.115 * bevel
    L = L * (1.0 - 0.28 * rivet) + 0.10 * rivet_hi

    # 骨架材质多做一道拉丝：沿 u 方向的细条纹
    if key == 'gr':
        brush = fbm(size, size, octaves=3, freq0=2, rng=rng)
        stripe = _value_noise(size, size, 160, rng)
        L = L * (1.0 + (stripe - 0.5) * 0.13) * (0.97 + brush * 0.06)

    rgb = base[None, None, :] * L[:, :, None]
    # 磨损处偏冷灰（露底材），不做出金属裸色 —— 规格说 M2 简化版先不做
    wear = _wear(L, groove, rng) * sp['wear']
    rgb = rgb * (1.0 - 0.30 * wear[:, :, None]) + \
        np.array([0.30, 0.31, 0.33], np.float32)[None, None, :] * (0.30 * wear[:, :, None])

    stencil = _stencil(size, rng)
    rgb = rgb * (1.0 - 0.55 * stencil[:, :, None]) + \
        np.array([0.12, 0.13, 0.15], np.float32)[None, None, :] * (0.55 * stencil[:, :, None])

    # 细颗粒：漆面本身的砂面质感。没有它整块在高频段是空的 —— 径向谱会显得「过陡」，
    # 翻译成人话就是 1:1 看很糊。α=0.55 只在 f≥64 有能量，等效于给频谱尾部垫一层。
    grain = spectral_noise(size, size, alpha=0.55, rng=rng, f_lo=64.0)
    gmul = 1.0 + (grain - 0.5) * 0.048
    rgb = rgb * gmul[:, :, None]
    L = L * gmul

    # 高度：亮度当微观起伏 + 沟与铆钉下压
    height = sat(L * 0.5) - 0.35 * groove - 0.22 * rivet + 0.05 * stencil
    return rgb, height, wear, dict(groove=groove, stencil=stencil, pl=pl)


def _match_mean(rgb, target):
    """把 RGB 算术平均拉到靶值。比线性缩放 RGB 更稳，不会把暗部压死。"""
    cur = float(rgb.mean())
    if cur < EPS:
        return rgb
    return np.clip(rgb * (target / cur), 0.0, 1.0).astype(np.float32)


# ================================================================ 真实图片路径
def purify(rgb):
    """规格环节 2：低频压制去烘焙光照。

    为什么是「除以低频」而不是「减去低频」：模型画进图里的光照是**乘性**的
    （亮面 = 反照率 × 光照），除回去才能恢复反照率；减掉会把反照率的整体亮度
    也一起带走，暗材质直接变黑。
    """
    L = rgb.mean(axis=2)
    r = max(4, rgb.shape[1] // 8)
    Llow = blur_wrap(L, r)
    gain = L.mean() / np.maximum(Llow, 1e-4)
    return np.clip(rgb * gain[:, :, None], 0.0, 1.0).astype(np.float32)


def seam_blend(rgb, frac=0.05):
    """规格环节 3a：四边与对边 alpha 渐变混合。只在导入真实图时用。"""
    h, w = rgb.shape[:2]
    k = max(2, int(round(min(h, w) * frac)))
    t = np.linspace(0.0, 1.0, k, dtype=np.float32)[:, None, None] * 0.5
    a = rgb.copy()
    # 左 ↔ 右
    a[:, :k] = rgb[:, :k] * (1 - t) + rgb[:, -k:][:, ::-1] * t
    a[:, -k:] = rgb[:, -k:] * (1 - t[::-1]) + rgb[:, :k][:, ::-1] * t[::-1]
    # 上 ↔ 下
    s = t.transpose(1, 0, 2)
    b = a.copy()
    b[:k, :] = a[:k, :] * (1 - s) + a[-k:, :][::-1] * s
    b[-k:, :] = a[-k:, :] * (1 - s[::-1]) + a[:k, :][::-1] * s[::-1]
    return b.astype(np.float32)


def _load_source(path, size):
    im = Image.open(path).convert('RGB')
    if im.size != (size, size):
        im = im.resize((size, size), Image.LANCZOS)
    return np.asarray(im, np.float32) / 255.0


# ================================================================ 图集
class Atlas:
    """四张图集 + 分区坐标。通道都是 float32 [0,1] 的 (size,size,·)。

    除了规格要求的 albedo/normal/rough/metal，额外存三张**辅助通道**：

      height  高度（微观起伏），只在调试和梯度重算时用
      dhu/dhv ∂h/∂u 与 ∂h/∂v，像素单位

    ★ 为什么存梯度而不在着色器里靠切线空间法线图换算：
    三平面采样要构造三个互相正交的切线基，每个轴的 T/B 手性不同，符号错一个
    轴，那一轴上的凸起就变凹 —— 而凸起变凹在静帧上极难用肉眼发现，会一直错到
    出片。直接存 u/v 方向的梯度就绕开了整个问题：着色器只需要知道「这个轴的
    u 取自哪个世界轴」，梯度就是 `∂h/∂u · e_iu + ∂h/∂v · e_iv`，没有手性、
    没有符号约定，数学上封死。代价是两张单通道图。
    """

    def __init__(self, albedo, normal, rough, metal, size, log=None,
                 height=None, dhu=None, dhv=None):
        self.albedo = albedo
        self.normal = normal
        self.rough = rough
        self.metal = metal
        self.height = height
        self.dhu = dhu
        self.dhv = dhv
        self.size = size
        self.log = log or {}
        # 打包通道：rough 与 metal 合成一张 (S,S,2)。
        # 着色器要做 3 次 gather 才能取到 albedo/rough/metal，打包后只要 2 次
        # —— 每次 gather 在 1440p 特写帧上是 15~20 ms，这一项直接省掉一个。
        self.rm = np.stack([rough, metal], axis=2).astype(np.float32)
        b = size // 2
        # 布局：左上 / 右上 / 左下 / 右下
        self._rects = {
            'w':  (0, 0, b, b),
            'bl': (b, 0, size, b),
            'rd': (0, b, b, size),
            'gr': (b, b, size, size),
        }

    # --- 分区 ---
    def uv_rect(self, key, topleft_origin=True):
        """返回 (u0,v0,u1,v1)。默认 v 从图顶往下（PIL/图像惯例）。"""
        x0, y0, x1, y1 = self._rects[key]
        s = float(self.size)
        return (x0 / s, y0 / s, x1 / s, y1 / s)

    def key_index(self, key):
        return KEYS.index(key)

    def to_image(self):
        def enc(a):
            return Image.fromarray((np.clip(a, 0, 1) * 255.0 + 0.5).astype(np.uint8))
        return dict(albedo=enc(self.albedo), normal=enc(self.normal),
                    rough=enc(self.rough), metal=enc(self.metal))

    def mean_lum(self):
        out = {}
        for k in KEYS:
            x0, y0, x1, y1 = self._rects[k]
            out[k] = float(self.albedo[y0:y1, x0:x1].mean())
        return out

    def save(self, prefix):
        ims = self.to_image()
        paths = {}
        for n, im in ims.items():
            p = '%s_%s.png' % (prefix, n)
            im.save(p)
            paths[n] = p
        return paths


def build_atlas(sources=None, fallback=True, size=2048, seed=20261106, log=False):
    """对外唯一入口。

    sources : {'w': path, 'bl': path, ...}，可缺省。给了就走「导入 + 净化 + 无缝化」，
              没给或文件读不到且 fallback=True 就走纯程序化。
    size    : 图集边长，必须是偶数。2048 → 每块 1024²。
    """
    size = int(size) - (int(size) % 2)
    b = size // 2
    sources = sources or {}
    info = {}

    al = np.zeros((size, size, 3), np.float32)
    nr = np.zeros((size, size, 3), np.float32)
    ro = np.zeros((size, size), np.float32)
    me = np.zeros((size, size), np.float32)
    hh = np.zeros((size, size), np.float32)
    gu = np.zeros((size, size), np.float32)
    gv = np.zeros((size, size), np.float32)

    probe = Atlas(al, nr, ro, me, size)   # 只借 _rects

    for i, key in enumerate(KEYS):
        sp = MATSPEC[key]
        x0, y0, x1, y1 = probe._rects[key]

        rgb = None
        src = sources.get(key)
        if src:
            try:
                rgb = _load_source(src, b)
                rgb = purify(rgb)
                rgb = seam_blend(rgb, 0.05)
                info[key] = 'imported'
            except Exception as e:
                info[key] = 'import-failed:%s' % type(e).__name__
                rgb = None
        if rgb is None:
            if not fallback:
                raise FileNotFoundError('source for %r missing and fallback=False' % key)
            rgb, height, wear, aux = _proc_tile(key, b, seed + i * 97)
            info.setdefault(key, 'procedural')
        else:
            # 导入路径：高度取净化后亮度，磨损按沟（这里没有沟，用边缘）
            grey = rgb.mean(axis=2)
            gdx, gdy = _sobel_wrap(grey)
            emag = np.sqrt(gdx * gdx + gdy * gdy)
            height = sat(grey * 0.5 - sat(emag * 3.0) * 0.20)
            wear = sat(blur_wrap(sat(emag * 4.0), 4) * 0.8) * sp['wear']

        rgb = _match_mean(rgb, sp['mean'])
        al[y0:y1, x0:x1] = rgb

        # --- 法线：h → 梯度 → 切线空间
        dx, dy = _sobel_wrap(height)
        s = float(sp['ns'])
        n = np.empty((b, b, 3), np.float32)
        n[:, :, 0] = -dx * s
        n[:, :, 1] = dy * s          # 图像 y 向下，OpenGL 法线 +Y 朝上 → 取正号抵消
        n[:, :, 2] = 1.0
        ln = np.sqrt((n * n).sum(axis=2, keepdims=True))
        n /= np.maximum(ln, EPS)
        nr[y0:y1, x0:x1] = n * 0.5 + 0.5

        # --- 辅助通道：高度 + u/v 梯度（着色器做三平面 bump 用）
        hh[y0:y1, x0:x1] = height
        gu[y0:y1, x0:x1] = dx * s
        gv[y0:y1, x0:x1] = dy * s

        # --- 粗糙度：亮处更光滑，边缘/磨损更粗糙
        L = rgb.mean(axis=2)
        edx, edy = _sobel_wrap(L)
        edge = sat(np.sqrt(edx * edx + edy * edy) * 6.0)
        r = 0.95 - 0.45 * sat(L - 0.60) - 0.25 * edge
        r = r * (1.0 - 0.20 * (1.0 - sp['rough'])) + 0.06 * (blur_wrap(
            np.random.default_rng(seed + i).random((b, b)).astype(np.float32), 1) - 0.5)
        ro[y0:y1, x0:x1] = np.clip(r + (sp['rough'] - 0.45), 0.05, 1.0)

        # --- 金属度：常量 × (1 - 磨损)
        me[y0:y1, x0:x1] = np.clip(sp['metal'] * (1.0 - 0.55 * wear), 0.0, 1.0)

    at = Atlas(al, nr, ro, me, size, info, height=hh, dhu=gu, dhv=gv)
    if log:
        print('[texgen] size=%d  路径: %s' % (size, at.log))
        for k, v in at.mean_lum().items():
            print('        %-3s %-8s 亮度 %.4f（靶 %.2f）'
                  % (k, MATSPEC[k]['name'], v, MATSPEC[k]['mean']))
    return at


# ================================================================ 采样
def triplanar_texel(atlas, pos, nrm, density=0.5, key_idx=None):
    """主轴三平面的纹素下标。返回 (flat, ax)。

    ★ 这里刻意不用布尔掩码。上一版按轴分三组、每组拿 pos[m, iu] 取一遍，看着
    省计算，实际全花在布尔压缩上：2.1M 像素每轴要压 8 个数组，实测 320 ms。
    改成「全量算 + 按轴索引」后同一帧降到 100 ms 出头。
    顺带验证了瓶颈不是 cache：图集从 2048 换到 512（albedo 50 MB→3 MB）
    只从 321 降到 259 ms —— 真正的成本是掩码，不是内存带宽。
    """
    S = atlas.size
    b = S // 2
    N = len(pos)
    if key_idx is None:
        key_idx = np.full(N, KEYS.index('gr'), np.int32)
    key_idx = np.asarray(key_idx).astype(np.int32)
    ax = np.abs(nrm).argmax(axis=1).astype(np.int8)
    ar = np.arange(N)
    # 三个轴的 (u,v) 取自哪两个世界轴：X→(z,y)  Y→(x,z)  Z→(x,y)
    axu = np.array([2, 0, 0], np.int8)[ax]
    axv = np.array([1, 2, 1], np.int8)[ax]
    u = pos[ar, axu] * density
    v = pos[ar, axv] * density
    pu = (sat(u - np.floor(u)) * (b - 1)).astype(np.int32) + (key_idx % 2) * b
    pv = (sat(v - np.floor(v)) * (b - 1)).astype(np.int32) + (key_idx // 2) * b
    return pv * S + pu, ax


def sample_triplanar(atlas, pos, nrm, blend=0.0, density=1.0, key_idx=None,
                     chans=('albedo',), flat_ax=None):
    """三平面采样。

    pos (N,3) 世界坐标（米）· nrm (N,3) 世界法线（已归一）
    density : 每米重复次数。0.5 → 一块 1024 覆盖 2 m²
    blend   : 0 = 只取主轴（快，盒体几何默认够用）；>0 = 按 |n| 三轴加权
    key_idx : (N,) 每像素材质索引 0..3，对应 KEYS 顺序；None 全用 'gr'
    flat_ax : 传入 (flat, ax) 复用 triplanar_texel 的结果，省一次计算
    """
    S = atlas.size
    b = S // 2
    N = len(pos)
    out = {}
    for c in chans:
        arr = getattr(atlas, c)
        nc = 1 if arr.ndim == 2 else arr.shape[2]
        out[c] = np.zeros((N,) if nc == 1 else (N, nc), np.float32)

    if blend <= 0:
        flat, _ = flat_ax if flat_ax is not None else triplanar_texel(
            atlas, pos, nrm, density, key_idx)
        for c in chans:
            arr = getattr(atlas, c).reshape(S * S, -1)
            val = arr[flat]
            if val.ndim == 2 and val.shape[1] == 1:
                val = val[:, 0]
            out[c][:] = val
        return out

    # --- 三轴加权（45° 面更准，代价约 3 倍）
    an = np.abs(nrm)
    wts = an / (an.sum(axis=1, keepdims=True) + EPS)
    if key_idx is None:
        key_idx = np.full(N, KEYS.index('gr'), np.int32)
    key_idx = np.asarray(key_idx).astype(np.int32)
    for a in range(3):
        m = wts[:, a] > 0.04
        if not m.any():
            continue
        w1 = wts[m, a]
        iu, iv = AXIS_UV[a]
        u = pos[m, iu] * density
        v = pos[m, iv] * density
        pu = (sat(u - np.floor(u)) * (b - 1)).astype(np.int32) + (key_idx[m] % 2) * b
        pv = (sat(v - np.floor(v)) * (b - 1)).astype(np.int32) + (key_idx[m] // 2) * b
        flat = pv * S + pu
        for c in chans:
            arr = getattr(atlas, c).reshape(S * S, -1)
            val = arr[flat]
            if val.ndim == 2 and val.shape[1] == 1:
                val = val[:, 0]
            val = val * (w1[:, None] if val.ndim == 2 else w1)
            out[c][m] += val
    return out


def sample_uv(atlas, uv, chans=('albedo',)):
    """传统 UV 采样（M2 备用：将来真做展开时走这条）。uv 已是图集坐标 0..1。"""
    S = atlas.size
    u = np.clip(uv[:, 0], 0.0, 0.999999)
    v = np.clip(uv[:, 1], 0.0, 0.999999)
    pu = (u * (S - 1)).astype(np.int32)
    pv = (v * (S - 1)).astype(np.int32)
    flat = pv * S + pu
    out = {}
    for c in chans:
        arr = getattr(atlas, c).reshape(S * S, -1)
        out[c] = arr[flat]
    return out


AXIS_UV = ((2, 1), (0, 2), (0, 1))       # 轴 → (u 取自哪个世界轴, v 取自哪个世界轴)

def sample_triplanar_bump(atlas, pos, nrm, density=0.5, key_idx=None,
                          mode='dominant', flat_ax=None):
    """返回世界空间高度梯度 (N,3)，着色器用 `n' = normalize(n - k·g)` 扰动。

    mode='dominant' : 只取主轴（2 次采样）
    mode='blend'    : 三轴按 |n| 加权（6 次采样，45° 面更准）

    世界空间的写法是 `g = Σ (∂h/∂u)·e_u + (∂h/∂v)·e_v`，e 是世界坐标基矢 ——
    只依赖「u 取自哪个世界轴」，不涉及切线空间的手性，所以不会出现
    「某一轴上凸起变凹陷」这种在静帧上几乎看不出来的隐蔽错误。
    """
    S = atlas.size
    b = S // 2
    N = len(pos)
    g = np.zeros((N, 3), np.float32)
    dhu = atlas.dhu.reshape(-1)
    dhv = atlas.dhv.reshape(-1)

    if mode == 'dominant':
        flat, ax = flat_ax if flat_ax is not None else triplanar_texel(
            atlas, pos, nrm, density, key_idx)
        du = dhu[flat]
        dv = dhv[flat]
        # 用 where 逐分量选轴，不做布尔散播：g[:, iu] += du[m] 会退化成掩码操作
        axu = np.array([2, 0, 0], np.int8)[ax]
        axv = np.array([1, 2, 1], np.int8)[ax]
        for comp in range(3):
            g[:, comp] = np.where(axu == comp, du, 0.0) + np.where(axv == comp, dv, 0.0)
        return g

    an = np.abs(nrm)
    wts = an / (an.sum(axis=1, keepdims=True) + EPS)
    ki_all = (np.full(N, KEYS.index('gr'), np.int32) if key_idx is None
              else np.asarray(key_idx, np.int32))
    for a in range(3):
        m = wts[:, a] > 0.04
        if not m.any():
            continue
        w1 = wts[m, a]
        iu, iv = AXIS_UV[a]
        u = pos[m, iu] * density
        v = pos[m, iv] * density
        ki = ki_all[m]
        pu = (sat(u - np.floor(u)) * (b - 1)).astype(np.int32) + (ki % 2) * b
        pv = (sat(v - np.floor(v)) * (b - 1)).astype(np.int32) + (ki // 2) * b
        flat = pv * S + pu
        g[m, iu] += dhu[flat] * w1
        g[m, iv] += dhv[flat] * w1
    return g
