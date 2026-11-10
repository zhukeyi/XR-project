"""tools/turntable.py — 浮雕转台（摆动式，不含 90° 退化视角）

浮雕是单面高度场：正好 90°（沿板面看进去）是退化视角，任何浮雕都一样，
所以转台做成 0 → +A → 0 → −A → 0 的摆动，帧数固定、循环无缝。

    python3 tools/turntable.py [前缀] [总帧] [幅度] [y0] [y1] [宽] [高]
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'tools'))

import relief_v2 as R                                  # noqa: E402
import render_relief as RR                             # noqa: E402

OUT = os.path.join(HERE, 'out', 'spike')


def main():
    a = sys.argv
    tag = a[1] if len(a) > 1 else 'tt'
    N = int(a[2]) if len(a) > 2 else 121
    amp = float(a[3]) if len(a) > 3 else 45.0
    y0 = int(a[4]) if len(a) > 4 else 40
    y1 = int(a[5]) if len(a) > 5 else 700
    Wp = int(a[6]) if len(a) > 6 else 760
    Hp = int(a[7]) if len(a) > 7 else 1180
    d = os.path.join(OUT, 'frames_' + tag)
    os.makedirs(d, exist_ok=True)

    mesh, meta = R.build(y0, y1, 2, verbose=True)
    line = RR.load_line_art()
    print(f'{N} 帧 @ {Wp}x{Hp}  幅度 ±{amp}°')

    for i in range(N):
        # 0 → +A → 0 → −A → 0；用正弦保证首尾速度为 0，循环无跳帧
        yaw = amp * math.sin(2.0 * math.pi * i / N)
        RR.render(mesh, meta, yaw, os.path.join(d, f'{i:04d}.png'),
                  size=(Wp, Hp), line=line, line_dist=meta['dist'])
        if i % 10 == 0:
            print(f'  {i}/{N}  yaw={yaw:+.1f}°', flush=True)
    print(f'→ {d}  ({N} 帧)')


if __name__ == '__main__':
    main()
