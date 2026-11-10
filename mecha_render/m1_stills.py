"""m1_stills.py — 用 M1 管线渲染若干关键帧静帧，输出 out/m1_t*.png

与 test_m1.py 共用装配逻辑，但只出图 + 计时，用于人工核对观感。
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
from test_m1 import FOG, sky_float

W, H, SS = 1280, 720, 2


def frame(t, out, ss=SS):
    rd = Renderer(W, H, ss=ss, fov=40)
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
                       np.concatenate(MIs), np.concatenate(FIs), cm, fov, rd.WS, rd.HS)
    t1 = time.perf_counter()
    hdr, glow = SH.shade(gb, np.concatenate(bases), np.concatenate(emis), cm,
                         bg=bg, fov=fov, **FOG)
    t2 = time.perf_counter()
    img = SH.to_image(hdr, glow, glow_radius=14, glow_gain=1.0,
                      vignette_k=0.35).resize((W, H), Image.LANCZOS)
    t3 = time.perf_counter()
    img.save(out)
    print(f'  t={t:5.2f}  三角 {st.total:5d} 绘制 {st.drawn:4d} 覆盖 {gb.coverage()*100:4.1f}%'
          f'  光栅 {(t1-t0)*1000:4.0f} 着色 {(t2-t1)*1000:3.0f} 合成 {(t3-t2)*1000:3.0f}'
          f'  合计 {(t3-t0)*1000:4.0f} ms -> {os.path.basename(out)}')


if __name__ == '__main__':
    os.makedirs(os.path.join(HERE, 'out'), exist_ok=True)
    ts = [float(x) for x in sys.argv[1:]] or [1.60, 4.50, 9.60, 10.80]
    for t in ts:
        frame(t, os.path.join(HERE, 'out', f'm1_t{t:05.2f}.png'))
