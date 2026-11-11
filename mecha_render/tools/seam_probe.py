"""tools/seam_probe.py — 「这道缝是谁填的？」

给定一个高度 y（米）与一个 x 区间，回答：在该高度上，x 落在区间内的
**是哪几个零件**（含父链名）、各占多宽、z 范围多少。
正面看到的那条「连成一片」的边，就是这些件叠出来的。

★ 为什么需要它：视觉尺量出「我们每行平均 1.90 段、参考 3.51 段」，
  但指标不会说是哪个零件把缝填了。改几何前先问清楚，才不会再犯
  「往错的件上加切削」的老错。

用法：
    python3 tools/seam_probe.py 6.20 0.90 1.55
    python3 tools/seam_probe.py 4.30 0.30 0.90
    python3 tools/seam_probe.py 6.20 0.90 1.55 --all   # 两侧一起看（默认）
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'tools'))

import s2_graybox as S                                       # noqa: E402


def leaves(node, path=''):
    out = []
    nm = (path + '/' + node.name) if node.name else path
    if node.prim is not None and not node.hide:
        V, F = node.prim
        if len(V):
            M = node.world()
            W = np.asarray(V, float) @ M[:3, :3].T + M[:3, 3]
            out.append((nm.strip('/') or '(unnamed)', W, F))
    for c in node.children:
        out += leaves(c, nm)
    return out


def slice_xz(W, F, y):
    """与平面 y=const 求交，返回该件在此高度上的 (xmin,xmax,zmin,zmax)。"""
    xs, zs = [], []
    for f in F:
        k = len(f)
        for i in range(k):
            p = W[f[i]]
            q = W[f[(i + 1) % k]]
            if (p[1] - y) * (q[1] - y) <= 0 and abs(q[1] - p[1]) > 1e-12:
                t = (y - p[1]) / (q[1] - p[1])
                r = p + t * (q - p)
                xs.append(r[0])
                zs.append(r[2])
    if not xs:
        return None
    return min(xs), max(xs), min(zs), max(zs)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    y = float(args[0]) if len(args) > 0 else 6.20
    xa = float(args[1]) if len(args) > 1 else 0.90
    xb = float(args[2]) if len(args) > 2 else 1.55
    S.CLEAN = True
    root, mesh = S.build()
    L = leaves(root)
    print('叶数 %d ｜ 探针 y=%.2f m ｜ x ∈ [%.2f, %.2f]（取绝对值，左右合并）' %
          (len(L), y, xa, xb))

    hits = []
    for nm, W, F in L:
        if W[:, 1].min() - 1e-6 > y or W[:, 1].max() + 1e-6 < y:
            continue
        s = slice_xz(W, F, y)
        if s is None:
            continue
        xmin, xmax, zmin, zmax = s
        W_ = xmax - xmin
        # 用绝对值判定重叠（左右对称一起看）
        if xmax < xa and -xmin < xa:
            continue
        if xmin > xb and -xmax > xb:
            continue
        hits.append((nm, xmin, xmax, zmin, zmax, W_))

    print('\n该高度上与 x 区间相交的零件 %d 个（按 z 由前到后）：' % len(hits))
    for nm, xmin, xmax, zmin, zmax, W_ in sorted(hits, key=lambda h: -h[4]):
        print('  %-46s x %+7.3f…%+7.3f  宽 %.3f   z %+7.3f…%+7.3f' %
              (nm, xmin, xmax, W_, zmin, zmax))

    # 一条水平横切线，看覆盖是否连续
    step = 0.02
    print('\n沿 +x 扫描（步长 %.2f），每点最靠前的件：' % step)
    for xx in np.arange(0.0, xb + 1e-9, step):
        best = None
        for nm, W, F in L:
            if not (W[:, 0].min() - 1e-6 <= xx <= W[:, 0].max() + 1e-6):
                continue
            if W[:, 1].min() - 1e-6 > y or W[:, 1].max() + 1e-6 < y:
                continue
            s = slice_xz(W, F, y)
            if s is None or not (s[0] - 1e-6 <= xx <= s[1] + 1e-6):
                continue
            if best is None or s[3] > best[1]:
                best = (nm, s[3])
        print('  x=%+.2f → %s' % (xx, ('%s (z=%+.3f)' % best) if best else '—— 空，透到背景'))


if __name__ == '__main__':
    main()
