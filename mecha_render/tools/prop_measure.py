"""tools/prop_measure.py — 比例实测量（改前 / 改后同口径，可比）

为什么单独一个脚本
  「腿加长、躯干变小、小臂变细」这三句话在图上只能靠感觉争，必须落成数字。
  本脚本不渲染、不判美，只回答四个可复算的问题：

    Q1 腿长 / 全高          胯点到地面 / 头顶
    Q2 躯干 / 全高          腰底到胸顶 / 头顶
    Q3 腿径沿全长分布        每 0.20 m 一层，宽 / 全高 的百分比（看有没有收放节奏）
    Q4 前臂 / 上臂 直径比    最粗处之比（<1 才是人形；>1 是反的）

用法
  python3 tools/prop_measure.py            # 当前 PROP
  python3 tools/prop_measure.py --raw     # 把 PROP 全部置 1（= 改前基线）

★ 截面带宽必须 ≥ 半层厚 + 0.02，否则薄切片会切在壳体的两层之间切空，
  量出 0.12 之类的假值（第一版踩过）。
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'tools'))

from gfx.mesh import Mesh, collect2                       # noqa: E402
import s2_graybox as S                                    # noqa: E402


def pts_of(node):
    m = Mesh()
    collect2(node, m)
    return np.array(m.P, np.float32).reshape(-1, 3)


def tris_of(node):
    P = pts_of(node)
    return P.reshape(-1, 3, 3)


def slice_at(T, y):
    """三角形与水平面 y 的真截面（不是点带）。

    ★ 为什么必须真求交：腿是按 y 层放样的，层距最大 0.417。点带法带宽至少要
      半层 + 0.02，量 1.66 处的小腿肚时会连 1.16 的胫中一起圈进去，取 max →
      局部收放全被抹平，量出来像一根等粗的筒。截面法不受层距影响。

    做法：对每个三角，若 y 落在它的 [ymin, ymax] 内，求三条边与平面的交点，
    收集所有交点取 x/z 范围。竖直壁（两三角共面）由相邻三角覆盖，不漏。
    """
    ymn = T[:, :, 1].min(1)
    ymx = T[:, :, 1].max(1)
    sel = (ymn <= y) & (ymx >= y) & ((ymx - ymn) > 1e-6)
    out = []
    for a, b, c in T[sel]:
        for p, q in ((a, b), (b, c), (c, a)):
            dy = q[1] - p[1]
            if abs(dy) < 1e-9:
                continue
            t = (y - p[1]) / dy
            if -1e-6 <= t <= 1 + 1e-6:
                out.append(p + t * (q - p))
    if not out:
        return 0.0, 0.0, 0
    A = np.array(out)
    return (float(A[:, 0].max() - A[:, 0].min()),
            float(A[:, 2].max() - A[:, 2].min()),
            len(A))


def slice_w(P, y, half):
    """兼容旧调用：直接把 P 当三角集用。"""
    return slice_at(P.reshape(-1, 3, 3), y)


def main():
    raw = '--raw' in sys.argv
    if raw:
        for k in S.PROP:
            S.PROP[k] = 1.0 if k not in ('dy_up', 'dy_arm') else 0.0
        S.PROP['leg_sy'] = S.PROP['leg_sxz'] = 1.0
        S.PROP['tor_sy'] = S.PROP['tor_sxz'] = 1.0
        S.PROP['arm_sxz'] = 1.0

    root, mesh = S.build()
    Pall = pts_of(root)
    y0, y1 = float(Pall[:, 1].min()), float(Pall[:, 1].max())
    Hm = y1 - y0
    tag = '改前基线（PROP=1）' if raw else '当前 PROP'
    print('=' * 78)
    print(f'比例实测量 · {tag}')
    print('=' * 78)
    print(f'  全高（含浮游炮） {y1:.3f}  m     脚底 {y0:.3f}')
    print(f'  全机包络        x {Pall[:,0].max()-Pall[:,0].min():.3f}  '
          f'y {Hm:.3f}  z {Pall[:,2].max()-Pall[:,2].min():.3f}')

    # ---- Q1 腿长 / 全高：用 leg 组自己的 y 上界（胯球顶）
    leg = pts_of(root.children[[c.name for c in root.children].index('leg_L')])
    arm = pts_of(root.children[[c.name for c in root.children].index('arm_L')])
    chest = pts_of(root.children[[c.name for c in root.children].index('chest')])
    waist = pts_of(root.children[[c.name for c in root.children].index('waist')])
    head = pts_of(root.children[[c.name for c in root.children].index('head')])

    y_hip = float(leg[:, 1].max())
    y_tor_bot = float(waist[:, 1].min())
    y_tor_top = float(chest[:, 1].max())
    y_head_top = float(head[:, 1].max())
    print()
    print(f'  Q1 腿长 / 全高      {y_hip:.3f} / {y_head_top:.3f} = {100*y_hip/y_head_top:.1f}%'
          f'   （SEED 实机 53–56%）')
    print(f'  Q2 躯干 / 全高      {y_tor_top-y_tor_bot:.3f} / {y_head_top:.3f} = '
          f'{100*(y_tor_top-y_tor_bot)/y_head_top:.1f}%'
          f'   （腰底 {y_tor_bot:.2f} → 胸顶 {y_tor_top:.2f}）')
    print(f'     头壳高          {y_head_top-float(head[:,1].min()):.3f}  m'
          f'  → {y_head_top/(y_head_top-float(head[:,1].min())):.1f} 头身')

    # ---- Q3 腿径沿全长
    print()
    print('  Q3 大腿/小腿 截面宽（单腿，% 全高；三角形-平面真交，0.10 m 步长）')
    print('       y     宽 m    /H%    深 m    /H%   交点数')
    for y in np.arange(round(y_hip, 1), 0.29, -0.10):
        w, d, n = slice_w(leg, float(y), 0.0)
        if n < 3:
            print(f'      {y:4.2f}    —（空层）')
            continue
        print(f'      {y:4.2f}  {w:6.3f}  {100*w/Hm:5.1f}  {d:6.3f}  {100*d/Hm:5.1f}  {n:5d}')

    # ---- Q4 前臂 / 上臂
    print()
    print('  Q4 臂：上臂 vs 前臂 最大直径（% 全高）')
    # 上臂 y 6.54–5.60，前臂 y 5.45–4.30（改前坐标；改后按 arm 组内相对比例取）
    ay0, ay1 = float(arm[:, 1].min()), float(arm[:, 1].max())
    span = ay1 - ay0
    for label, f0, f1 in (('上臂 上段', 0.80, 0.95), ('前臂 下段', 0.10, 0.30)):
        ya, yb = ay0 + span * f0, ay0 + span * f1
        best = 0.0
        for y in np.linspace(ya, yb, 8):
            w, d, n = slice_w(arm, float(y), 0.06)
            best = max(best, w)
        print(f'      {label}  最粗 {best:.3f} m = {100*best/Hm:.1f}%')
    print()
    print('  组 y 范围：')
    for nm in ('head', 'chest', 'waist', 'hip', 'leg_L', 'arm_L', 'sh_L', 'bay', 'funnels'):
        try:
            P = pts_of(root.children[[c.name for c in root.children].index(nm)])
        except ValueError:
            P = pts_of([c for c in root.children if c.name == nm][0])
        print(f'      {nm:8s} y {P[:,1].min():6.3f} – {P[:,1].max():6.3f}'
              f'   x {P[:,0].min():6.3f} – {P[:,0].max():6.3f}')


if __name__ == '__main__':
    main()
