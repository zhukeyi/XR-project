"""m2_stills.py — M2 材质管线静帧 + M1/M2 回归对照

三个用途：
  1. 回归：tex_contrast=0 / tex_bump=0 / tex_spec=0 时输出必须与 M1 **逐位相同**
     （mod 恒为 1，基色不变，法线不变，高光路径不变）。这是 M2 没有破坏 M1 的证明。
  2. 出片：正常参数下渲染关键帧，与 M1 拼版对照。
  3. 计时：三平面采样的成本必须量出来，否则不知道还能不能进 800 ms 预算。

用法：
  python3 m2_stills.py                  # 渲染默认关键帧 + 回归校验
  python3 m2_stills.py 10.80 9.60       # 指定时间点
  python3 m2_stills.py --regress-only
"""
import os
import sys
import time

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import film2 as F
import mecha_model as MM
from r3d import Renderer, look_at
from gfx.mesh import Mesh, collect2, from_tris
from gfx.gbuffer import rasterize
from gfx import shade as SH
from gfx.texgen import build_atlas, MATSPEC, KEYS
from test_m1 import FOG, sky_float

W, H, SS = 1280, 720, 2
OUT = os.path.join(HERE, 'out')

ATLAS = None


def get_atlas():
    global ATLAS
    if ATLAS is None:
        p = os.path.join(OUT, 'atlas_albedo.png')
        if os.path.exists(p):
            ATLAS = _load_saved()
        else:
            ATLAS = build_atlas(size=2048, log=False)
    return ATLAS


def _load_saved():
    """从已导出的 PNG 回读。梯度通道 PNG 里没有，需要重算 —— 这里直接重建，
    成本 2.6 s，比每次重算梯度再拼装更简单可靠。"""
    return build_atlas(size=2048, log=False)


def assemble(t):
    """返回 (gb, bases, emis, cm, fov, bg, st, timings)"""
    rd = Renderer(W, H, ss=SS, fov=40)
    eye, tgt, fov, roll = F.camera(t)
    cm = look_at(eye, tgt, roll=roll)
    bg = sky_float(rd)

    mech = Mesh()
    collect2(MM.build_mecha(F.pose(t)), mech)
    meshes = [from_tris(F.build_city()), mech]
    if t > 6.6:
        en = Mesh()
        collect2(MM.build_enemy(F.enemy_pose(t)), en)
        meshes.append(en)

    Ps, Ns, Ts, MIs, FIs, bases, emis = [], [], [], [], [], [], []
    mo = fo = 0
    for m in meshes:
        P, N, T, mi, Fi, b, e = m.arrays()
        Ps.append(P); Ns.append(N); Ts.append(T)
        MIs.append(mi + mo); FIs.append(Fi + fo)
        bases.append(b); emis.append(e)
        mo += len(b); fo += len(Fi)

    t0 = time.perf_counter()
    gb, st = rasterize(np.concatenate(Ps), np.concatenate(Ns), np.concatenate(Ts),
                       np.concatenate(MIs), np.concatenate(FIs), cm, fov,
                       rd.WS, rd.HS)
    return dict(gb=gb, bases=np.concatenate(bases), emis=np.concatenate(emis),
                cm=cm, fov=fov, bg=bg, st=st, rd=rd,
                t_raster=time.perf_counter() - t0)


def render(A, tex=None, save=None, **kw):
    st = {}
    t1 = time.perf_counter()
    hdr, glow = SH.shade(A['gb'], A['bases'], A['emis'], A['cm'], bg=A['bg'],
                         fov=A['fov'], stats=st, tex=tex, **kw, **FOG)
    t2 = time.perf_counter()
    img = SH.to_image(hdr, glow, glow_radius=14, glow_gain=1.0,
                      vignette_k=0.35).resize((W, H), Image.LANCZOS)
    t3 = time.perf_counter()
    if save:
        img.save(save)
    return img, (A['t_raster'], t2 - t1, t3 - t2), st


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('-')]
    only_reg = '--regress-only' in sys.argv
    ts = [float(x) for x in args] or [1.60, 4.50, 9.60, 10.80]
    os.makedirs(OUT, exist_ok=True)

    at = get_atlas()
    mkey = None
    print('图集：%d²  分区 %s' % (at.size, {k: at.uv_rect(k) for k in KEYS}))

    # ---------------- 回归：必须先证明 M2 的 no-op 参数等于 M1
    if True:
        t = ts[0]
        A = assemble(t)
        img1, tm1, _ = render(A)
        a1 = np.asarray(img1, np.int16)
        # 同一个 G-buffer 只着色一次 M1 版本，再着色一次 M2 no-op 版本
        A2 = assemble(t)
        img2, tm2, st2 = render(A2, tex=at, tex_contrast=0.0, tex_bump=0.0,
                                tex_spec=0.0)
        a2 = np.asarray(img2, np.int16)
        d = np.abs(a1 - a2)
        print('\n[回归] t=%.2f  M2 no-op vs M1：最大差 %d  不同像素 %d  (%.4f%%)'
              % (t, d.max(), int((d.max(axis=2) > 0).sum()),
                 (d.max(axis=2) > 0).mean() * 100))
        print('[回归] 判定：%s' % ('逐位一致 ✓' if d.max() == 0 else '有差异 ✗'))
        print('[计时] t=%.2f  M1 光栅 %.0f 着色 %.0f 合成 %.0f  合计 %.0f ms'
              % (t, tm1[0] * 1000, tm1[1] * 1000, tm1[2] * 1000, sum(tm1) * 1000))
        print('[计时] t=%.2f  M2 光栅 %.0f 着色 %.0f 合成 %.0f  合计 %.0f ms'
              '（其中纹理采样 %.0f ms）'
              % (t, tm2[0] * 1000, tm2[1] * 1000, tm2[2] * 1000, sum(tm2) * 1000,
                 st2.get('tex', 0) * 1000))
        if only_reg:
            return

    # ---------------- 出片
    print('\n渲染关键帧：')
    for t in ts:
        A = assemble(t)
        kw = dict(tex=at, tex_density=0.5, tex_contrast=1.0, tex_bump=1.0,
                  tex_axis='dominant', tex_blend=0.0, tex_spec=0.55)
        img_m2, tm2, st2 = render(A, save=os.path.join(OUT, 'm2_t%05.2f.png' % t), **kw)
        A1 = assemble(t)
        img_m1, tm1, _ = render(A1, save=os.path.join(OUT, 'm2_base_t%05.2f.png' % t))
        print('  t=%5.2f  三角 %5d 覆盖 %4.1f%%  M1 合计 %4.0f ms | '
              'M2 光栅 %4.0f 着色 %4.0f 合成 %3.0f 合计 %4.0f ms（纹理 %3.0f）'
              % (t, A['st'].total, A['gb'].coverage() * 100, sum(tm1) * 1000,
                 tm2[0] * 1000, tm2[1] * 1000, tm2[2] * 1000, sum(tm2) * 1000,
                 st2.get('tex', 0) * 1000))

    # ---------------- 拼版
    names = ['m2_base_t%05.2f.png' % t for t in ts]
    names += ['m2_t%05.2f.png' % t for t in ts]
    if all(os.path.exists(os.path.join(OUT, n)) for n in names):
        _sheet(ts)


def _sheet(ts, tw=880, th=495):
    n = len(ts)
    rows, cols = 2, n
    pad, top = 6, 20
    Ws = cols * tw + pad * (cols + 1)
    Hs = rows * (th + top) + pad * (rows + 1)
    sh = Image.new('RGB', (Ws, Hs), (20, 22, 26))
    from PIL import ImageDraw
    d = ImageDraw.Draw(sh)
    for r, pre in enumerate(('m2_base_t', 'm2_t')):
        for c, t in enumerate(ts):
            f = os.path.join(OUT, '%s%05.2f.png' % (pre, t))
            im = Image.open(f).convert('RGB').resize((tw, th), Image.LANCZOS)
            x = pad + c * (tw + pad)
            y = pad + r * (th + top + pad)
            sh.paste(im, (x, y + top))
            d.text((x + 4, y + 4), 'M1 原始  t=%.2f' % t if r == 0 else 'M2 材质  t=%.2f' % t,
                   fill=(190, 205, 225))
    p = os.path.join(OUT, 'm2_sheet.png')
    sh.save(p)
    print('\n拼版 -> %s' % p)


if __name__ == '__main__':
    main()
