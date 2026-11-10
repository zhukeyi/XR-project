"""m2_crops.py — 1:1 细节裁切对照

720p 成片看不出材质细节（纹理主要落在 1~3 个像素的变化上），必须按超采样原始
分辨率 1:1 裁切才看得清。这个脚本渲染 t=10.80（最特写帧）的 2560×1440 原图，
在机体上裁 3 块 640×640 的 1:1 区域，M1 / M2 左右并排。
"""
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import m2_stills as M
from gfx.shade import finish, to_image

OUT = os.path.join(HERE, 'out')
CROP = 640


def full(t, **kw):
    """渲染超采样原图（不下采样），返回 PIL Image。"""
    A = M.assemble(t)
    hdr, glow = M.SH.shade(A['gb'], A['bases'], A['emis'], A['cm'], bg=A['bg'],
                           fov=A['fov'], **kw, **M.FOG)
    arr = finish(hdr, glow, glow_radius=14, glow_gain=1.0, vignette_k=0.35)
    return Image.fromarray(arr), A


def main():
    t = float(sys.argv[1]) if len(sys.argv) > 1 else 10.80
    at = M.get_atlas()
    kw2 = dict(tex=at, tex_density=1.0 / 16.0, tex_contrast=1.0, tex_bump=1.0,
               tex_axis='dominant', tex_blend=0.0, tex_spec=0.55)

    im1, A = full(t)
    im2, _ = full(t, **kw2)
    im1.save(os.path.join(OUT, 'm2_full_t%05.2f_m1.png' % t))
    im2.save(os.path.join(OUT, 'm2_full_t%05.2f_m2.png' % t))

    a1 = np.asarray(im1)
    a2 = np.asarray(im2)
    H, W = a1.shape[:2]

    # 挑机体像素最密集的三个区域（3×3 网格里取 top3）
    gb = A['gb']
    body = (gb.midx >= 20).astype(np.float32)
    gh, gw = 3, 3
    score = []
    for r in range(gh):
        for c in range(gw):
            y0 = H * r // gh
            y1 = H * (r + 1) // gh
            x0 = W * c // gw
            x1 = W * (c + 1) // gw
            score.append((float(body[y0:y1, x0:x1].mean()), r, c, x0, y0))
    score.sort(reverse=True)
    picks = []
    for s, r, c, x0, y0 in score:
        cx = min(max(x0 + (W // gw) // 2, CROP // 2), W - CROP // 2)
        cy = min(max(y0 + (H // gh) // 2, CROP // 2), H - CROP // 2)
        picks.append((cx, cy, s))
        if len(picks) == 3:
            break

    cols = len(picks)
    pad, top = 8, 22
    sh = Image.new('RGB', (CROP * 2 * cols + pad * (cols + 1),
                           CROP + top + pad * 2), (20, 22, 26))
    d = ImageDraw.Draw(sh)
    for i, (cx, cy, s) in enumerate(picks):
        box = (cx - CROP // 2, cy - CROP // 2, cx + CROP // 2, cy + CROP // 2)
        for j, (src, nm) in enumerate(((a1, 'M1 纯色'), (a2, 'M2 材质'))):
            crop = Image.fromarray(src[box[1]:box[3], box[0]:box[2]])
            x = pad + i * (CROP * 2 + pad) + j * CROP
            sh.paste(crop, (x, pad + top))
            d.text((x + 4, pad + 5), '%s  (%d,%d)' % (nm, cx, cy), fill=(190, 205, 225))
    p = os.path.join(OUT, 'm2_crops_t%05.2f.png' % t)
    sh.save(p)
    print('裁切对照 -> %s   (%d 个区域, 每个 %d×%d 1:1)' % (p, cols, CROP, CROP))


if __name__ == '__main__':
    main()
