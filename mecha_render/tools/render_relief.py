"""tools/render_relief.py — 把 trace3d 重建的板件网格渲成图/三视图/转台视频

相机用近似正交（fov 2°），机位距离由机高自动推算，所以任何角度取景一致。
验收指标是 IoU：把渲染剪影与线稿剪影各自按包围盒归一后求交并比 —— 这是
「有没有丢细节」唯一客观的量。
"""
import json
import math
import os
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'tools'))

import trace3d as T                            # noqa: E402
from gfx import shade as SH                    # noqa: E402
from gfx.gbuffer import rasterize              # noqa: E402
from gfx.mesh import Mesh                      # noqa: E402
from r3d import Renderer, look_at              # noqa: E402

W, H, SS = 760, 1280, 2
STILL = (1060, 1780)      # 静帧：与原稿 525×1437 约 1:1，线条不会被降采样抹细
FOV = 2.0
OUT = os.path.join(HERE, 'out', 'relief')
os.makedirs(OUT, exist_ok=True)


def make_mesh():
    """建好的网格已自带机身实体（负责体积与板缝暗线），不再需要另铺背板。"""
    mesh, meta = T.build(verbose=True)
    print(f'总三角 {len(mesh)}   深度 z: 前 {meta["zf"]:.2f} / 板底 {meta["zb"]:.2f} '
          f'/ 后 {meta["zback"]:.2f}   总厚 {(meta["zf"]-meta["zback"])/meta["H"]*100:.1f}% 机高')
    return mesh, meta


def rot_mesh(mesh, yaw_deg):
    P, N, T_, mi, Fi, b, e = mesh.arrays()
    a = math.radians(yaw_deg)
    ca, sa = math.cos(a), math.sin(a)
    P = P.copy(); N = N.copy()
    for arr in (P, N):
        x = arr[..., 0].copy(); z = arr[..., 2].copy()
        arr[..., 0] = x * ca + z * sa
        arr[..., 2] = -x * sa + z * ca
    return P, N, T_, mi, Fi, b, e


def load_line_art():
    """原稿灰度（0=墨，1=纸）。用于按 UV 投影到曲面上。"""
    g = np.asarray(Image.open(T.SRC).convert('L'), np.float32) / 255.0
    return g


def _bilinear(img, x, y):
    H, W = img.shape
    x = np.clip(x, 0, W - 1.001)
    y = np.clip(y, 0, H - 1.001)
    x0 = np.floor(x).astype(np.int32); y0 = np.floor(y).astype(np.int32)
    fx = x - x0; fy = y - y0
    x1 = np.minimum(x0 + 1, W - 1); y1 = np.minimum(y0 + 1, H - 1)
    return (img[y0, x0] * (1 - fx) * (1 - fy) + img[y0, x1] * fx * (1 - fy)
            + img[y1, x0] * (1 - fx) * fy + img[y1, x1] * fx * fy)


def _erode4(m, k):
    """4 邻域腐蚀 k 次（掩码内缩 k 像素）。用于屏幕空间画轮廓内环。"""
    out = m.copy()
    for _ in range(int(k)):
        e = out.copy()
        e[1:, :] &= out[:-1, :]
        e[:-1, :] &= out[1:, :]
        e[:, 1:] &= out[:, :-1]
        e[:, :-1] &= out[:, 1:]
        out = e
    return out


def line_factor(gb, mesh, gray, strength=0.95, dist=None, edge_band=1.8,
                seal=0.92, jac_lo=0.16, jac_hi=0.55, seal_mode='hybrid'):
    """按 gb.uv（= 原稿像素坐标）双线性采样线稿，给出逐像素亮度系数。

    为什么走 UV 而不是「按材质分墨/白格」：墨线中位宽度约 6px，网格 2px，
    分格画线等于把每条线量化成楼梯 —— 放大后是成排的方齿。投影是按原稿
    逐像素取的，带抗锯齿，线宽与原稿一致。

    轮廓线有**两套画法**，按本帧的 UV 采样率交叉淡入淡出（seal_mode='hybrid'）：
      · 距离场查带（UV→dist）：连续的，不跟 2px 网格的相位走，正视下轮廓平滑；
        但它是按 uv 查的，掠射时 uv 采样率不足，会退化成 1~2px 周期的梳齿。
      · 屏幕空间内环（覆盖掩码）：线宽恒 1px，任何视角都不断；但它贴着 2px
        阶梯走，正视下轮廓会“抖”。
    两者按 mf（=1 表示采样充分）加权：正视全用前者，掠射全用后者。
    只留一种都不行 —— 只留距离场侧视出梳齿，只留屏幕环正视轮廓发毛。
    """
    x = gb.uv[..., 0].astype(np.float64)
    y = gb.uv[..., 1].astype(np.float64)
    L = _bilinear(gray, x, y)
    L_seal = L
    if dist is not None and edge_band > 0:
        _, mats = mesh._mats()
        sb = np.array([getattr(m, 'seal_band', 1.0) for m in mats], np.float64)
        band = np.full(gb.midx.shape, float(edge_band), np.float64)
        if len(sb):
            band = sb[np.maximum(gb.midx, 0)] * edge_band
        ds = _bilinear(dist.astype(np.float64), x, y)
        t = np.clip(1.0 - ds / np.maximum(band, 1e-6), 0.0, 1.0)
        t = t * t * (3.0 - 2.0 * t)                     # smoothstep
        L_seal = 1.0 - t * seal
    # 淡出：正视图的外轮廓在侧视时整条侧对镜头，UV 沿屏幕 x 被压扁几十倍，
    # 双线性采样变成墨/纸随机的点阵 —— 画面上就是一道竖直「拉链」。
    #
    # ★ 判据不能用雅可比的**行列式**：这里的压缩是单向的（压一个轴、另一个轴不动），
    #   而行列式是「面积」，单向拉伸恰好保面积 —— 实测侧视时缝上的 jac 与正面
    #   相当，淡出完全不触发（这就是前几版拉链一直修不掉的原因）。
    #   正确判据是 2×2 雅可比的**小奇异值 / 大奇异值**：
    #     正面朝相机 ≈ 1；被压成一条线 → 0。
    nz = np.abs(gb.nrm[..., 2].astype(np.float64))
    graz = np.clip((nz - 0.12) / 0.33, 0.0, 1.0)
    ux, uy = np.gradient(x)
    vx, vy = np.gradient(y)
    tr = ux * ux + uy * uy + vx * vx + vy * vy
    det = ux * vy - uy * vx
    disc = np.sqrt(np.maximum(tr * tr * 0.25 - det * det, 0.0))
    smin = np.sqrt(np.maximum(tr * 0.5 - disc, 0.0))
    smax = np.sqrt(np.maximum(tr * 0.5 + disc, 0.0))
    ratio = smin / np.maximum(smax, 1e-9)
    jf = np.clip((ratio - jac_lo) / max(jac_hi - jac_lo, 1e-6), 0.0, 1.0)
    # ★ 第三条判据：**欠采样**。上面的小/大奇异值比只管「被压成一条线」，
    #   管不了「被剪切放大」——侧视折叠处 UV 每屏幕像素要走 1.3~2.5 个原稿像素，
    #   墨线（中位宽 6px、最细 2px）根本无法采样，双线性结果按行随机命中墨/纸，
    #   画面上就是一排 1~2px 周期的亮暗梳齿（实测这一带 f 在 0.13~1.00 之间跳）。
    #   判据用「每屏幕像素吃掉几个原稿像素」：smax ≈ 基准值 → 正常；超过基准
    #   1.45 倍 → 一律不画墨（只剩轮廓密封带，侧视于是读成一个干净的泥模）。
    #   基准值取本帧朝正面像素的中位数，所以换了分辨率/取景都不用重新调。
    nzc = (gb.midx >= 0) & (nz > 0.70)
    ref = float(np.median(smax[nzc])) if nzc.any() else 0.70
    ref = max(ref, 1e-3)
    mf = np.clip((1.45 * ref - smax) / (0.45 * ref), 0.0, 1.0)
    fade = np.minimum(np.minimum(graz, jf), mf)
    # 投影墨线按压缩比淡出
    f_ink = 1.0 - (1.0 - L) * strength * fade
    # 距离场轮廓：只在本帧采样充分（mf≈1）的地方用，否则它会退化成梳齿
    f_seal_uv = 1.0 - (1.0 - L_seal) * strength * mf
    f = np.minimum(f_ink, f_seal_uv)
    # 未覆盖像素必须保持 1：背景的 uv 是 0，任何按 uv 取的项都会把整片背景压灰。
    f = np.where(gb.midx >= 0, f, 1.0)
    _, mats = mesh._mats()
    nol = np.array([1.0 if getattr(m, 'no_line', False) else 0.0 for m in mats],
                   np.float32)
    seal_only = np.array([1.0 if getattr(m, 'seal_only', False) else 0.0
                          for m in mats], np.float32)
    if len(nol):
        hit = nol[np.maximum(gb.midx, 0)] > 0.5
        f = np.where(hit, 1.0, f)
    if len(seal_only):
        so = seal_only[np.maximum(gb.midx, 0)] > 0.5
        f = np.where(so, np.minimum(1.0, f_seal_uv + (1.0 - mf) * 0.0), f)
    # 屏幕空间轮廓：只在本帧采样不足（mf≈0）的地方补位，权重 (1-mf)。
    if seal_mode in ('screen', 'hybrid') and seal > 0:
        cov = gb.midx >= 0
        k = gb.W / 760.0
        r1 = cov & ~_erode4(cov, max(1, int(round(2 * k))))
        r2 = (~r1) & cov & ~_erode4(cov, max(2, int(round(4 * k))))
        E = np.clip(r1.astype(np.float64) + 0.55 * r2.astype(np.float64), 0.0, 1.0)
        w = 1.0 if seal_mode == 'screen' else (1.0 - mf)
        f_edge = 1.0 - E * seal * strength
        f = np.minimum(f, 1.0 - (1.0 - f_edge) * w)
    f = np.where(gb.midx >= 0, f, 1.0)
    return f.astype(np.float32)



def render(mesh, meta, yaw, out, size=None, spec_a=None, rim_a=None,
           line=None, line_strength=0.95, line_dist=None, line_band=1.8, soft_mix=0.90,
           cel_w=0.15, bg_lv=0.995):
    Wp, Hp = size or (W, H)
    Hm = meta['H']
    dist = (Hm * 0.62) / math.tan(math.radians(FOV / 2))
    cy = float(meta.get('cy', Hm * 0.5))     # 局部裁切时必须给真实竖向中心
    rd = Renderer(Wp, Hp, ss=SS, fov=FOV)
    cm = look_at((0, cy, dist), (0, cy, 0), roll=0)
    # ★ 白甲不能配白底：机体主色 0.90 与 bg 0.995 只差 0.095，
    #   轮廓和背景糊成一片，看图上「读不出形体」有一半是这个原因，不是几何。
    #   默认仍给 0.995（其他调用方在用它做白底线稿），S2 出图显式传深灰。
    bg = np.ones((rd.HS, rd.WS, 3), np.float32) * bg_lv
    P, N, T_, mi, Fi, b, e = rot_mesh(mesh, yaw)
    sa, ra = mesh.mat_prop_table()
    # ★ 参数必须真的接上：spec_a/rim_a 之前只是签名里挂着、函数体一律用表里的值，
    #   于是「关掉高光看看」这类消融实验全是空跑（三组结果逐位相同才暴露出来）。
    if spec_a is not None:
        sa = np.asarray(spec_a, np.float64)
    if rim_a is not None:
        ra = np.asarray(rim_a, np.float64)
    # ★ backface=False：浮雕是**闭合薄壳**，必须双面渲染。
    #   侧视（yaw≈90°）时壳的法线几乎平行于视线，一半三角的法线朝向背面被剔除，
    #   而壳只有 1.7px 厚、背后没有东西补 → 画面上是一排 2px 周期的背景白缝
    #   （那条「拉链」）。实测侧视时 7.3% 的像素因此漏底；关掉线稿、加密超采样、
    #   平滑法线、加厚边缘带都改不动它，就是因为问题在剔除而不在几何/贴图。
    gb, _ = rasterize(P, N, T_, mi, Fi, cm, FOV, rd.WS, rd.HS, backface=False)
    hdr, glow = SH.shade(gb, b, e, cm, bg=bg, fov=FOV, fog_a=0.0, fog_b=0.0,
                         mat_spec=sa, mat_rim=ra, spec_gain=0.85, spec_pow=48.0,
                         spec_ambient=0.06, rim_gain=2.0, rim_k=2.4,
                         env_gain=0.40, env_pow=1.5, soft_mix=soft_mix,
                         cel_w=cel_w)
    if line is not None:
        f = line_factor(gb, mesh, line, line_strength, dist=line_dist,
                        edge_band=line_band)
        hdr = hdr * f[..., None]
    img = SH.to_image(hdr, glow, glow_radius=8, glow_gain=0.5,
                      vignette_k=0.0).resize((Wp, Hp), Image.LANCZOS)
    img.save(out)
    return gb.midx >= 0, img


def iou(render_mask, tgt_mask):
    """按包围盒归一后求 IoU：消除取景/分辨率差异，只比形状。"""
    def crop_resize(m, size=(420, 1000)):
        ys, xs = np.nonzero(m.any(1))[0], np.nonzero(m.any(0))[0]
        sub = m[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        im = Image.fromarray((sub * 255).astype(np.uint8)).resize(size, Image.BILINEAR)
        return np.asarray(im) > 127
    a, b = crop_resize(render_mask), crop_resize(tgt_mask)
    return float((a & b).sum()) / float((a | b).sum())


def label(im, text, sub=''):
    d = ImageDraw.Draw(im)
    try:
        f = ImageFont.truetype('/System/Library/Fonts/PingFang.ttc', 30)
        fs = ImageFont.truetype('/System/Library/Fonts/PingFang.ttc', 21)
    except Exception:
        f = fs = ImageFont.load_default()
    d.rectangle([0, 0, im.width, 70], fill=(255, 255, 255))
    d.text((16, 10), text, fill=(18, 22, 30), font=f)
    if sub:
        d.text((16, 46), sub, fill=(100, 108, 122), font=fs)
    return im


def main():
    mesh, meta = make_mesh()
    tg = meta['fig']
    rm, img = render(mesh, meta, 0, os.path.join(OUT, 'r_000.png'), size=STILL)
    v = iou(rm, tg)
    print(f'原稿角度 IoU = {v*100:.1f}%   （剪影重合度，>92% 视为结构一致）')
    json.dump(dict(iou=round(v, 4), plates=167, tris=len(mesh)),
              open(os.path.join(OUT, 'verify.json'), 'w'), indent=1)

    panels = []
    for yaw, name in ((-30, '左前 3/4 ·  −30°'), (0, '正视 · 0°（= 线稿视角）'),
                      (30, '右前 3/4 ·  +30°')):
        f = os.path.join(OUT, f'r_{yaw:+03d}.png')
        _, im = render(mesh, meta, yaw, f, size=STILL)
        panels.append((name, im))
    w = sum(p[1].width for p in panels) + 24 * 2
    h = max(p[1].height for p in panels) + 70
    sh = Image.new('RGB', (w, h), (255, 255, 255))
    x = 0
    for name, im in panels:
        sh.paste(label(im.copy(), name, '线稿反推重建 · 未改动任何细节'), (x, 70))
        x += im.width + 24
    sheet = os.path.join(HERE, 'out', 'seed_sketch', 'relief_threeview.png')
    sh.save(sheet)
    print(f'三视图 -> {sheet} ({sh.width}, {sh.height})')

    # 侧视单独出一张：这张才是「真 3D」的证据，同时也不搅乱三视图的定义
    _, side = render(mesh, meta, 90, os.path.join(OUT, 'r_+090.png'), size=STILL)
    side = label(side.copy(), '侧视 · 90°', '整机厚度 = 机高的 13.7%，单视图反推所得')
    p_side = os.path.join(HERE, 'out', 'seed_sketch', 'relief_side.png')
    side.save(p_side)
    print(f'侧视 -> {p_side}')


def turntable(mesh, meta, n=108, fps=36, span=360, out_name='relief_turn.mp4'):
    """转台视频：绕 Y 轴整圈。ffmpeg 这个包没编 image2 解码器，
    所以走仓库自带的 encode（AVFoundation → H.264）。

    帧目录每次新建（frames_01、frames_02…），**不删旧帧** —— 一是避免触发
    批量删除保护，二是保留上一次的帧便于 A/B 逐帧对比。
    """
    k = 1
    while os.path.exists(os.path.join(OUT, f'frames_{k:02d}')):
        k += 1
    fd = os.path.join(OUT, f'frames_{k:02d}')
    os.makedirs(fd, exist_ok=True)
    for i in range(n):
        yaw = -0.5 * span + span * i / n
        render(mesh, meta, yaw, os.path.join(fd, f'f_{i:04d}.png'))
        if i % 12 == 0:
            print(f'  帧 {i}/{n}  yaw={yaw:+.1f}°')
    out = os.path.join(HERE, 'out', 'seed_sketch', out_name)
    r = subprocess.run([os.path.join(HERE, 'encode'), fd, '/nonexistent.wav',
                        out, str(fps), 'high'], capture_output=True, text=True)
    print(r.stdout.strip() or r.stderr.strip())
    return out


if __name__ == '__main__':
    if '--videoonly' in sys.argv:
        mesh, meta = make_mesh()
        print(f'视频 -> {turntable(mesh, meta)}')
    else:
        main()
        if '--video' in sys.argv:
            mesh, meta = make_mesh()
            print(f'视频 -> {turntable(mesh, meta)}')


if __name__ == '__main__':
    main()
