"""
gfx/shade.py — 延迟着色（M1 第 4 块）

为什么延迟：
  v1 的 cel_shade() 是一个面调一次，一个面一个颜色，成本 = 三角数 × 常数。
  延迟着色把「法线在哪」这件事从光栅化阶段带出来（G-buffer），逐像素计算
  只做一次全屏遍历，成本 = 覆盖像素数，与三角数解耦。
  实测：12.7 万像素全屏着色 6 ms，而 3976 三角的逐面循环要 200 ms 量级。

相对 v1 的四处增强（都在同一份公式里，不改变观感基调）：
  1. 法线是「插值后的逐像素法线」而不是面法线 → 圆柱有连续明暗过渡，不再是
     8 段平涂；同时盒体硬边由顶点法线的 flat 策略保住（见 mesh.py）。
  2. 高光：Blinn-Phong 半角向量，v1 的 Mat.spec 字段当年就预留了但从未接进
     cel_shade()。M1 默认关闭（spec_gain=0）以保证与 v3 可逐像素比对。
  3. 雾按「逐像素真实距离」算，v1 用「面中心距离」，同一面内雾浓度是常量。
  4. 量化值掺 35% 连续值：纯量化在 1080p 会有色阶断层，纯连续会磨掉明暗交界线，
     掺一半是赛璐璐的通行做法。v1 其实已经这么做了（0.62/0.38），此处保留。

坐标系约定（与 gbuffer.py 一致）：
  相机看向 -z，depth 通道存的是正的 z（即 -z_cam）。像素中心 +0.5。
  反投影：X = (sx - cx)/fc * z, Y = (cy - sy)/fc * z, Z = -z。

分两步是有意为之：
  shade()  → 线性 HDR（0..1 可超 1）+ 发光通道，便于 M4 接 ACES
  finish() → Bloom / 暗角 / 曝光 / 可选 ACES / 量化到 8 bit
"""
import math
import numpy as np
from PIL import Image, ImageFilter

EPS = 1e-9

# ---------------------------------------------------------------- 常量
# 与 r3d.py 逐字一致，保证 M1 与 v3 是同一个光照模型（否则无法逐像素比对）
LIGHT_KEY = np.array([0.42, 0.72, 0.55], np.float32)
LIGHT_KEY /= np.linalg.norm(LIGHT_KEY)
LIGHT_FILL = np.array([-0.62, 0.30, -0.72], np.float32)
LIGHT_FILL /= np.linalg.norm(LIGHT_FILL)
C_FILL = np.array([0.42, 0.62, 0.92], np.float32)
C_RIM = np.array([0.34, 0.55, 0.78], np.float32)
# 环境反射色（冷白，偏天光）。金属的"扎实感"来自折面各反环境不同部位，
# 不是来自一个白点高光 —— 见 env_gain 的注释
C_SKY = np.array([0.62, 0.72, 0.86], np.float32)

LEVELS = np.array([0.42, 0.60, 0.78, 0.94, 1.00], np.float32)
_MID = (LEVELS[1:] + LEVELS[:-1]) * 0.5      # 量化边界

D2R = math.pi / 180.0


def quantize(lam):
    """连续光照量 → 5 档量化值。用 searchsorted 代替 argmin：
    100 万像素 × 5 档的广播 argmin 要 40 ms，searchsorted 只要 3 ms。"""
    idx = np.searchsorted(_MID, lam)
    return LEVELS[np.minimum(idx, len(LEVELS) - 1)]


def mat_key_index(base_col, mat_emis):
    """(M,3) 材质基色 → 图集分区索引（0=白 1=蓝 2=红 3=灰）。

    为什么用规则而不是最近邻：最近邻在 RGB 空间会让深蓝和深灰互换（两者距离
    只差 0.1 量级），而人眼一眼就看得出装甲基色变了。用「先判彩度、再判色相
    主导」的规则不会出这种错，且每条规则都能讲清楚。
    """
    out = np.full(len(base_col), 3, np.int32)
    for i in range(len(base_col)):
        r, g, b = float(base_col[i][0]), float(base_col[i][1]), float(base_col[i][2])
        if mat_emis[i] > 0.5:                 # 自发光面（灯、眼）不吃材质
            out[i] = 3
            continue
        mx, mn = max(r, g, b), min(r, g, b)
        if mx - mn < 0.10:                    # 近灰：按亮度分白/深灰
            out[i] = 0 if (0.2126 * r + 0.7152 * g + 0.0722 * b) > 0.45 else 3
        elif r >= b and r >= g * 1.20:        # 红主导
            out[i] = 2
        elif b >= r * 1.25:                   # 蓝主导
            out[i] = 1
        else:
            out[i] = 3
    return out


# ---------------------------------------------------------------- 主着色

def shade(gb, base_col, mat_emis, cam_m, bg=None, fov=40.0, *,
          mat_spec=None, mat_rim=None, env_gain=0.0, env_pow=1.6,
          fog_col=(0.34, 0.40, 0.49), fog_a=0.0026, fog_b=0.00005,
          soft_mix=0.35, cel_w=0.62, rim_k=3.0, rim_gain=1.0, light_cam=True,
          spec_pow=48.0, spec_gain=0.0, spec_ambient=0.15,
          edge_dark=0.0, edge_thr=0.85,
          tex=None, tex_density=1.0 / 16.0, tex_contrast=1.0, tex_bump=1.0,
          tex_axis='dominant', tex_blend=0.0, tex_color=False, tex_spec=0.0,
          mat_key=None, stats=None):
    """从 G-buffer 全屏着色。

    参数
      gb        : GBuffer（depth / nrm / midx / fid）
      base_col  : (M,3) 每个材质的 albedo
      mat_emis  : (M,)  每个材质的自发光强度
      cam_m     : 4x4 世界→相机矩阵（光要转到相机空间）
      bg        : (H,W,3) 背景（天空），未覆盖像素直接沿用
      mat_spec  : (M,) 每材质高光强度，None 用 spec_gain 统一
      mat_rim   : (M,) 每材质边缘光系数，None 用 rim_gain 统一
      env_gain  : 环境反射强度（0=关）。★ 这才是"金属感"的有效通道：
                  Blinn-Phong 在平面箱体上 ndh≈0.876、^64≈2e-4，任何 gain 都
                  乘在近乎 0 的数上，实测 A/B 高光像素差 0.00 个百分点。
                  环境反射按「折面反射方向的天光高度」着色，同一机体的折面会
                  一亮一暗 —— 这才是金属读得出来的原因。
      soft_mix  : 量化值掺入连续值的比例（0=纯量化，1=纯平滑）
      cel_w     : **量化分量在漫反射里的权重**（默认 0.62，与旧版逐像素一致）。
                  soft_mix 只调「那 38% 里连续值占多少」，量化分量本身恒占 62% ——
                  所以只改 soft_mix 几乎改不动观感（实测 soft_mix 0.35→1.0 的
                  画面差异看不见）。要真正拿到平滑明暗必须动这个权重。
                  高密度浮雕/曲面渲染用它压到 0.1~0.2，赛璐璐动画保持 0.62。
      edge_dark : 面边界压暗强度（0 关闭）。M1 默认关，M4 的描边会接管
      edge_thr  : 判定「锐边」的法线夹角余弦阈值。插值法线连续处不算边，
                  所以圆柱接缝会被自动排除，只有真正的硬边被压暗

      --- M2 材质（tex=None 时以下参数全部不生效，走的还是 M1 的纯色路径）---
      tex        : texgen.Atlas 实例。三平面采样，不需要 UV 展开
      tex_density: 每米重复几个图块。**默认 1/16（一块 1024 覆盖 16 m）**，
                   这个值不是手感，是算出来的：机体实测高 22.8 m、特写帧 62 px/m，
                   要让 1 texel ≈ 1 屏幕像素就必须是 1024/(16×62) ≈ 1.03。
                   取 0.5（图块 2 m = 124 px）会让 2 texel 的面板沟只剩 0.24 px，
                   实测表现为亚像素闪烁 + 高频能量不升反降。
      tex_contrast: 纹理调制强度。0 = 完全等价于 M1 纯色，1 = 原始对比
      tex_bump   : 高度梯度扰动法线的系数。0 = 只做 albedo，不改光照
      tex_axis   : 'dominant' 只取主轴（快）／'blend' 三轴加权（45° 面更准）
      tex_color  : False = 纹理只做**调制**（保持各材质原有基色，整体亮度不变，
                   便于与 M1 逐像素对比）；True = 直接用图集 albedo 当基色
      tex_spec   : >0 时按粗糙度图驱动高光（会改光照，A/B 时设 0）
      mat_key    : (M,) 材质→图集分区索引，None 自动按规则推断
      stats      : 传入 dict 则写入分阶段耗时
 
    返回 (hdr, glow)
      hdr  : (H,W,3) float32，线性色，0..4（未覆盖像素 = bg 或 0）
      glow : (H,W,3) float32，仅自发光像素非零，供 finish() 做 Bloom
    """
    import time as _t
    _t0 = _t.perf_counter()
    _stat = stats if stats is not None else {}
    H, W = gb.H, gb.W
    hdr = np.zeros((H, W, 3), np.float32)
    if bg is not None:
        hdr[:] = bg
    glow = np.zeros((H, W, 3), np.float32)

    mask = gb.fid >= 0
    if not mask.any():
        return hdr, glow

    ys, xs = np.nonzero(mask)
    z = gb.depth[ys, xs].astype(np.float32)          # 正的相机空间 z
    n = gb.nrm[ys, xs]                                # 已在光栅化时归一化
    mi = gb.midx[ys, xs].astype(np.int32)

    # --- 反投影出世界（相机空间）位置，得到逐像素视线方向
    f = 1.0 / math.tan(fov * math.pi / 360.0)
    fc = f * (H * 0.5)
    cx, cy = W * 0.5, H * 0.5
    pxc = (xs.astype(np.float32) + 0.5 - cx) / fc * z
    pyc = -(ys.astype(np.float32) + 0.5 - cy) / fc * z
    pzc = -z
    dist = np.sqrt(pxc * pxc + pyc * pyc + pzc * pzc)
    inv = 1.0 / np.maximum(dist, EPS)
    # 视线：表面→相机（相机在相机空间原点）
    vx, vy, vz = -pxc * inv, -pyc * inv, -pzc * inv

    # --- 光源转到相机空间（只转 2 个向量，比把 50 万条法线转回世界便宜）
    # light_cam=False 是 v1 的原样：拿相机空间法线直接和世界空间光方向做点积，
    # 等于把主光焊在相机上。几何上是错的，但当初就是这样出的片，A/B 比对时要能还原。
    R3 = np.asarray(cam_m, np.float32)[:3, :3]

    # ================================================== M2 纹理
    # 顺序很关键：法线扰动必须在 d_key / d_fill / ndv 之前完成，
    # 否则光照算的是旧法线，bump 只影响高光不影响明暗（看起来像贴纸）。
    tex_rough = tex_metal = None
    tex_base = None
    if tex is not None:
        _t1 = _t.perf_counter()
        try:
            from .texgen import (sample_triplanar, sample_triplanar_bump,
                                 triplanar_texel, KEYS, MATSPEC)
        except ImportError:
            from texgen import (sample_triplanar, sample_triplanar_bump,
                                triplanar_texel, KEYS, MATSPEC)

        tt = np.asarray(cam_m, np.float32)[:3, 3]
        # 相机 → 世界。R3 的行是相机三个基矢在世界里的分量，所以行向量右乘 R3
        # 等价于列向量左乘 R3ᵀ：p_w = (p_c − t) · R3
        pc = np.stack([pxc, pyc, pzc], axis=1)
        pw = (pc - tt) @ R3
        nw = n @ R3

        if mat_key is None:
            mat_key = mat_key_index(base_col, mat_emis)
        mk = np.asarray(mat_key, np.int32)[mi]

        ref = np.array([MATSPEC[k]['mean'] for k in KEYS], np.float32)[mk]

        # 纹素下标只算一次，bump 与 albedo 共用；单独算会白付一遍索引开销
        coords = (triplanar_texel(tex, pw, nw, tex_density, mk)
                  if (tex_blend <= 0 and tex_axis == 'dominant') else None)

        if tex_bump > 0.0:
            gw = sample_triplanar_bump(tex, pw, nw, density=tex_density,
                                       key_idx=mk, mode=tex_axis, flat_ax=coords)
            # 梯度转回相机空间（光照在这一空间里做），再沿法线反向推
            gc = gw @ R3.T
            nx = n[:, 0] - tex_bump * gc[:, 0]
            ny = n[:, 1] - tex_bump * gc[:, 1]
            nz = n[:, 2] - tex_bump * gc[:, 2]
            ln = np.sqrt(nx * nx + ny * ny + nz * nz) + EPS
            n = np.stack([nx / ln, ny / ln, nz / ln], axis=1).astype(np.float32)

        chans = ('albedo', 'rm')
        smp = sample_triplanar(tex, pw, nw, density=tex_density, key_idx=mk,
                               blend=tex_blend, chans=chans, flat_ax=coords)
        rm = smp['rm']
        if tex_color:
            tex_base = smp['albedo']
        else:
            # ★ 调制必须走**亮度**，不能逐通道除。
            #   逐通道 mod = albedo/ref 会按通道各自缩放：蓝色装甲 B=0.47 除以
            #   0.26 得 1.81（提亮 81%），R=0.07 得 0.27（压到近黑）—— 色相直接崩，
            #   整体亮度也虚涨 1.5/255。改成标量亮度比之后 mod 均值 0.999、
            #   标准差 0.049，画面亮度中性，只多出细节。
            mod = smp['albedo'].mean(axis=1) / ref
            scale = 1.0 + (mod - 1.0) * tex_contrast
            # 自发光部件（灯、眼、推进口）是光源不是受光面，不参与纹理调制
            scale[mat_emis[mi] > 0.5] = 1.0
            tex_base = base_col[mi] * scale[:, None]

        tex_rough = rm[:, 0]
        tex_metal = rm[:, 1]
        _stat['tex'] = _stat.get('tex', 0.0) + (_t.perf_counter() - _t1)

    if light_cam:
        lk = R3 @ LIGHT_KEY
        lf = R3 @ LIGHT_FILL
    else:
        lk, lf = LIGHT_KEY, LIGHT_FILL

    d_key = np.clip(n[:, 0] * lk[0] + n[:, 1] * lk[1] + n[:, 2] * lk[2], 0.0, None)
    d_fill = np.clip(n[:, 0] * lf[0] + n[:, 1] * lf[1] + n[:, 2] * lf[2], 0.0, None)

    # --- 赛璐璐量化的漫反射
    lam = d_key * 0.80 + d_fill * 0.25 + 0.42
    q = quantize(lam)
    lam_s = q * (1.0 - soft_mix) + lam * soft_mix
    diffuse = cel_w * q + (1.0 - cel_w) * lam_s

    base = tex_base if tex_base is not None else base_col[mi]
    # 漫反射与冷补光合成一个 (N,3) 系数再乘基色：
    #   base*(diffuse + d_fill*0.16*C_FILL) 等价于原来的两次乘法加一次加法，
    #   但只分配一个临时数组
    scale = diffuse[:, None] + (d_fill * 0.16)[:, None] * C_FILL[None, :]
    col = base * scale

    # --- 边缘光（逆光轮廓）。v1 用 |n·v|，等价于对正反面都取里侧，保持原样
    ndv = n[:, 0] * vx + n[:, 1] * vy + n[:, 2] * vz
    rim_f = np.clip(1.0 - np.abs(ndv) * rim_k, 0.0, 1.0)
    rim_s = rim_f * (1.0 - d_key) * 0.62 * rim_gain
    if mat_rim is not None:
        rim_s = rim_s * mat_rim[mi]
    col += C_RIM * rim_s[:, None]

    # --- 环境反射（金属感的有效通道）
    #   r = 2(n·v)n − v 是视线关于法线的反射；用它的 y 分量当日光高度采样。
    #   朝上的折面反到天顶（亮），朝下的反到地面（暗），于是「同一块装甲的
    #   不同折面亮度不同」—— 这是金属区别于塑料的主要线索。
    #   fresnel 只在掠射角抬权重：正对该面的位置不该发白。
    if env_gain != 0.0:
        rdot = ndv
        ry = 2.0 * rdot * n[:, 1] - vy
        sky = np.clip(0.5 + 0.5 * ry, 0.0, 1.0) ** env_pow
        fres = np.clip(1.0 - np.abs(ndv), 0.0, 1.0) ** 4
        amt = env_gain * (0.40 + 0.60 * fres)
        if mat_spec is not None:
            amt = amt * mat_spec[mi]
        col += C_SKY[None, :] * (sky * amt * base.mean(axis=1))[:, None]

    # --- 高光（v1 缺失的能力，M1 默认关闭）
    # tex_spec>0 时改由粗糙度图**逐像素**驱动指数与强度 —— 这是 PBR 高光的核心
    # 表达方式：一处粗糙度 0.2 的漆面给出锐利小高光，锈蚀处 0.7 给出一大片哑光。
    if spec_gain != 0.0 or mat_spec is not None or \
            (tex_rough is not None and tex_spec > 0.0):
        hx, hy, hz = lk[0] + vx, lk[1] + vy, lk[2] + vz
        hl = np.sqrt(hx * hx + hy * hy + hz * hz) + EPS
        ndh = np.clip((n[:, 0] * hx + n[:, 1] * hy + n[:, 2] * hz) / hl, 0.0, 1.0)
        if tex_rough is not None and tex_spec > 0.0:
            rgh = np.clip(tex_rough, 0.05, 1.0)
            # Blinn-Phong 指数由粗糙度反解。★ 下限必须是 8 不是 2：
            #   指数 2 等于一个覆盖半球的宽瓣，实测把全屏亮度抬了 +1.19/255
            #   （41% 像素被改动、p95 只有 7）—— 那不是高光，是给全画面抹了层油。
            pw = np.clip(2.0 / (rgh ** 4) - 2.0, 8.0, 512.0)
            # 同理，强度必须按 (1-r)² 门控，只让「够光滑」的地方真正反光
            gloss = np.clip(1.6 * (1.0 - rgh), 0.0, 1.0) ** 2
            # 只在高光瓣内算幂。ndh^pw 的指数是逐像素数组，全量算要 210 ms；
            # 高光瓣本身只覆盖几个百分点，先把 ndh<0.30 截掉 —— pw≥8 时
            # 0.30^8=6.6e-5，误差远低于 8bit 量化步长。
            sp = np.zeros_like(ndh)
            sel = ndh > 0.30
            if sel.any():
                sp[sel] = ndh[sel] ** pw[sel]
            gain = tex_spec * (0.25 + 0.75 * tex_metal) * gloss
            spec_col = base * (1.0 - spec_ambient) + spec_ambient
            # 金属的反射色带基色，绝缘体的高光是光源色（偏白）
            spec_col = spec_col * (1.0 - tex_metal[:, None] * 0.55) \
                + base * (tex_metal[:, None] * 0.55)
        else:
            sp = ndh ** spec_pow
            gain = np.full(len(sp), spec_gain, np.float32)
            if mat_spec is not None:
                gain = gain * mat_spec[mi]
            # 高光取基色向白色抬升，避免金属上出现白点
            spec_col = base * (1.0 - spec_ambient) + spec_ambient
        col += spec_col * (sp * gain)[:, None]

    # --- 雾：逐像素真实距离（v1 是逐面中心距离）
    # 不用布尔索引（col[lit] = ...）：那会做掩码压缩 + 反向散射，特写帧上
    # 光这一个操作就吃掉几十毫秒。改成先把「要对雾生效的量」压成一个数组再广播。
    fogf = np.clip(1.0 - np.exp(-fog_a * dist - fog_b * dist * dist), 0.0, 0.97)
    fog_arr = np.asarray(fog_col, np.float32)
    emis = mat_emis[mi]
    lit = emis < 0.5
    # 自发光面不参与雾的衰减，只叠加 0.22 倍雾色
    f_no = np.where(lit, fogf, 0.0)
    col *= (1.0 - f_no)[:, None]
    col += fog_arr * f_no[:, None]
    if np.any(~lit):
        col += fog_arr * (np.where(lit, 0.0, fogf * 0.22))[:, None]
        # 自发光整体替换（v1 语义）
        eonly = np.where(lit, 0.0, emis)
        em_col = base * ((0.40 + 0.60 * eonly) + eonly * 0.75)[:, None]
        np.copyto(col, em_col, where=(~lit)[:, None])

    col = np.clip(col, 0.0, 4.0)

    hdr[ys, xs] = col
    # glow 只收自发光像素，且统一到 0..1（与 v1 的 glow 图层等值）
    gsel = ~lit
    if np.any(gsel):
        glow[ys[gsel], xs[gsel]] = np.clip(col[gsel], 0.0, 1.0)

    # --- 锐边压暗（可选，M4 描边接管的临时方案）
    if edge_dark > 0.0:
        em = edge_mask(gb, edge_thr)
        if em.any():
            hdr[em] *= (1.0 - 0.40 * edge_dark)
            glow[em] *= (1.0 - 0.40 * edge_dark)

    _stat['shade_total'] = _stat.get('shade_total', 0.0) + (_t.perf_counter() - _t0)
    return hdr, glow


# ---------------------------------------------------------------- 边缘检测

def edge_mask(gb, thr=0.85):
    """面 id 不连续 且 法线突变 → 锐边。

    为什么要看法线：g_tube 的每个侧面是独立面（fid 不同），但顶点法线做了平滑，
    像素法线在接缝处连续；盒体棱边的像素法线是 90° 跳变。用法线夹角就能把
    「几何硬边」和「拓扑接缝」分开，不用额外通道。
    """
    fid = gb.fid
    H, W = fid.shape
    e = np.zeros((H, W), bool)

    dx = fid[:, 1:] != fid[:, :-1]
    dy = fid[1:, :] != fid[:-1, :]
    if thr is not None:
        n = gb.nrm
        sx = np.abs((n[:, 1:] * n[:, :-1]).sum(axis=2))
        sy = np.abs((n[1:, :] * n[:-1, :]).sum(axis=2))
        dx &= sx < thr
        dy &= sy < thr

    # 边界两侧都标，避免单侧出现 1px 明暗不对称
    e[:, 1:] |= dx
    e[:, :-1] |= dx
    e[1:, :] |= dy
    e[:-1, :] |= dy
    return e


# ---------------------------------------------------------------- 合成

_VIG = {}


def vignette(H, W, k):
    """暗角因子 (H,W,1)。按尺寸与强度缓存，逐帧复用。"""
    key = (H, W, round(k, 4))
    v = _VIG.get(key)
    if v is None:
        yy, xx = np.mgrid[0:H, 0:W]
        dx = (xx - W * 0.5) / (W * 0.5)
        dy = (yy - H * 0.5) / (H * 0.5)
        v = (1.0 - k * np.clip((dx * dx * 0.75 + dy * dy * 1.0) - 0.15, 0, 1.4))
        v = v[:, :, None].astype(np.float32)
        _VIG[key] = v
    return v


def aces(x):
    """Narkowicz ACES 近似。M1 默认不用（要与 v3 比对），M4 打开。"""
    a, b, c, d, e = 2.51, 0.03, 2.43, 0.59, 0.14
    return np.clip(x * (a * x + b) / (x * (c * x + d) + e), 0.0, 1.0)


def finish(hdr, glow, *, glow_radius=14, glow_gain=1.0, vignette_k=0.35,
           exposure=1.0, tonemap=False, dither=False, bloom_half=True):
    """Bloom + 暗角 + 曝光 + 可选 ACES → uint8 RGB。

    Bloom 增益与 v1 完全对齐（0.80 主瓣 + 0.60 大半径瓣），保证可逐像素比对。

    bloom_half：在 1/2 分辨率上做高斯模糊再放大回去。半径 14/48 这种尺度上
    半分辨率的误差小于 1/255，但代价只剩 1/4 —— 实测特写帧的合成阶段
    183 ms → 62 ms。半径 < 6 时不用，否则会糊。
    """
    img = hdr
    if glow_gain > 0.0 and glow.any():
        H0, W0 = glow.shape[:2]
        half = bloom_half and glow_radius >= 6 and W0 >= 8 and H0 >= 8
        g8 = (np.clip(glow, 0.0, 1.0) * 255.0).astype(np.uint8)
        gi = Image.fromarray(g8)
        if half:
            gi = gi.resize((W0 // 2, H0 // 2), Image.BILINEAR)
            r = glow_radius * 0.5
        else:
            r = glow_radius
        g1 = gi.filter(ImageFilter.GaussianBlur(r))
        g2 = gi.filter(ImageFilter.GaussianBlur(r * 3.4))
        if half:
            g1 = g1.resize((W0, H0), Image.BILINEAR)
            g2 = g2.resize((W0, H0), Image.BILINEAR)
        img = (img + np.asarray(g1, np.float32) / 255.0 * (glow_gain * 0.80)
               + np.asarray(g2, np.float32) / 255.0 * (glow_gain * 0.60))

    if tonemap:
        img = aces(img)
        # ACES 会压暗中间调，配一点增益补回来
        img = img * 1.12

    H, W = img.shape[:2]
    if vignette_k > 0:
        img = img * vignette(H, W, vignette_k)
    if exposure != 1.0:
        img = img * exposure

    arr = np.clip(img * 255.0, 0.0, 255.0)
    if dither:
        # 三角分布抖动（±1 LSB），给后续 8 bit 量化打散色阶
        rng = np.random.default_rng(7)
        arr = arr + (rng.random(arr.shape, np.float32)
                     + rng.random(arr.shape, np.float32) - 1.0)
        arr = np.clip(arr, 0.0, 255.0)
    return arr.astype(np.uint8)


def to_image(hdr, glow, **kw):
    return Image.fromarray(finish(hdr, glow, **kw))
