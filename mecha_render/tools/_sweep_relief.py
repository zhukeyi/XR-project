"""tools/_sweep_relief.py — 参数对照：同一套几何，只改「板面高差」强弱

一次出三行，每行 −28° / 0° / +28°。目的是用眼睛定 RLEV 该多大 ——
高差 0 时墨线只剩材质色差；高差大时板缝有实体的厚度感但容易把线加粗。
"""
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'tools'))

import relief_v2 as R                                  # noqa: E402
import render_relief as RR                             # noqa: E402

OUT = os.path.join(HERE, 'out', 'spike')
os.makedirs(OUT, exist_ok=True)

VAR = [
    ('高差 0（纯材质墨线）', (0.0, 0.000, 0.000, 0.000)),
    ('高差 弱', (0.0, 0.055, 0.100, 0.145)),
    ('高差 中', (0.0, 0.110, 0.190, 0.280)),
    ('高差 强', (0.0, 0.200, 0.330, 0.480)),
]


def main():
    y0, y1 = 40, 700
    rows = []
    for name, rlev in VAR:
        R.RLEV = rlev
        mesh, meta = R.build(y0, y1, 2, verbose=False)
        ims = []
        for yaw in (-28, 0, 28):
            p = os.path.join(OUT, f'sw_{yaw:+d}.png')
            _, img = RR.render(mesh, meta, yaw, p, size=(520, 800))
            ims.append(img)
        rows.append((name, ims))
        print(f'{name}  tris={len(mesh)}')

    Wp, Hp = rows[0][1][0].size
    sheet = Image.new('RGB', (Wp * 3, Hp * len(rows)), '#f6f4ef')
    d = ImageDraw.Draw(sheet)
    try:
        f = ImageFont.truetype('/System/Library/Fonts/PingFang.ttc', 26)
    except Exception:
        f = ImageFont.load_default()
    for r, (name, ims) in enumerate(rows):
        for c, im in enumerate(ims):
            sheet.paste(im, (c * Wp, r * Hp))
        d.text((14, r * Hp + 12), f'{name}   {(-28, 0, 28)[0]}°…', fill='#222', font=f)
    sp = os.path.join(OUT, 'sweep_raise.png')
    sheet.save(sp)
    print('→', sp)


if __name__ == '__main__':
    main()
