"""tools/runs_probe.py — 在指定高度带上打印覆盖区间（左右边界），直接读出「缝有多宽/有没有」。

用法：python3 tools/runs_probe.py 0.80 0.55 0.30
   参数是「离地高度 / 总高」，可给多个。
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'tools'))

import visual_ruler as VR                                    # noqa: E402
from leg_ab import Soup, shade                               # noqa: E402


def intervals(row, Hn):
    xs = np.where(row)[0]
    if len(xs) == 0:
        return []
    out = []
    a = xs[0]
    p = xs[0]
    for x in xs[1:]:
        if x - p > 1:
            out.append((a, p))
            a = x
        p = x
    out.append((a, p))
    # 转成「以剪影中心为 0、以 H 为单位」的坐标
    cx = 0.5 * (xs.min() + xs.max())
    return [((l - cx) / Hn, (r - cx) / Hn, (r - l + 1) / Hn) for l, r in out]


def main():
    hs = [float(x) for x in sys.argv[1:]] or [0.80, 0.55, 0.30]
    S = VR.S
    S.CLEAN = True
    root, mesh = S.build()
    P = np.array(mesh.P, np.float32).reshape(-1, 3)
    y0 = float(P[:, 1].min())
    k = VR.H10 / (float(P[:, 1].max()) - y0)
    Q = P * k
    Q[:, 1] = (P[:, 1] - y0) * k
    mi, base, _e = mesh.mat_table()
    nt = len(mesh.P)
    if len(mi) != nt:
        mi = np.pad(mi, (0, max(0, nt - len(mi))))[:nt]
    a_img, a_cov = shade(Soup(Q.reshape(-1, 3, 3), mi, base), 0.0, VR.PANEL)
    b_img, b_cov = shade(VR.ref(), 0.0, VR.PANEL)

    for cov, nm in ((a_cov, '我们'), (b_cov, '参考')):
        ys = np.where(cov.any(1))[0]
        print('\n%s  y0=%d y1=%d  H=%.0fpx' % (nm, ys.min(), ys.max(), ys.max() - ys.min() + 1))
        Hn = float(ys.max() - ys.min() + 1)
        for h in hs:
            # h = 离地高度比（0=脚底 1=头顶）
            y = int(ys.max() - h * Hn)
            iv = intervals(cov[y], Hn)
            tot = sum(i[2] for i in iv)
            print('  h=%.2f  y=%4d  段数 %2d  覆盖 %.3f H' % (h, y, len(iv), tot))
            for l, r, w in iv:
                print('      [%+.3f, %+.3f]  宽 %.3f H' % (l, r, w))


if __name__ == '__main__':
    main()
