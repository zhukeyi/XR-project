"""tools/probe.py — 侧视/斜视快速对照探针（单次 build，多次 render）

用法：
    python3 tools/probe.py TAG y1 [y2] [--dbl] [--band 1.8] [--yaws -28,0,28,90]

只做一件事：把当前 relief_v2 的几何渲成几张图，方便对着图下结论。
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'tools'))

import relief_v2 as R                                  # noqa: E402
import render_relief as RR                             # noqa: E402

OUT = os.path.join(HERE, 'out', 'spike')
os.makedirs(OUT, exist_ok=True)


def main():
    tag = sys.argv[1] if len(sys.argv) > 1 else 'p'
    y1 = int(sys.argv[2]) if len(sys.argv) > 2 else 700
    y2 = int(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3].isdigit() else None
    if y2 is None:
        y0, y1 = 40, y1
    else:
        y0, y1 = y1, y2
    dbl = '--dbl' in sys.argv
    band = 1.8
    yaws = (-28, 0, 28, 90)
    for k, a in enumerate(sys.argv):
        if a == '--band':
            band = float(sys.argv[k + 1])
        if a == '--yaws':
            yaws = tuple(int(v) for v in sys.argv[k + 1].split(','))

    if dbl:
        R.RIM_DBL = True

    mesh, meta = R.build(y0, y1, 2, verbose=True)
    print(f'总三角 {len(mesh)}   RIM_DBL={R.RIM_DBL}  band={band}')

    line = RR.load_line_art()
    for yaw in yaws:
        p = os.path.join(OUT, f'{tag}_{yaw:+03d}.png')
        mask, _ = RR.render(mesh, meta, yaw, p, size=(760, 1180),
                            line=line, line_dist=meta['dist'], line_band=band)
        print(f'  yaw={yaw:+d} 覆盖 {int(mask.sum())}px → {p}')


if __name__ == '__main__':
    main()
