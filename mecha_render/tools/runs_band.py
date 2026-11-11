"""tools/runs_band.py — 逐高度带量「剪影断成几块」，定位必须开缝的高度区间。

★ 为什么需要它
  visual_ruler 的 V7 给出一个全局数：每行覆盖段数 我们 1.90 / 参考 3.50。
  「平均 1.9 段」的意思是**大部分高度带上左右臂与躯干是连在一起的**，
  而参考在这个高度带是「臂 | 空隙 | 躯干 | 空隙 | 臂」三段。
  全局数不能告诉我们在哪开缝，所以按高度分带量。

输出
  每 0.02 H 一带：我们段数 / 参考段数 / 我们覆盖宽度 / 参考覆盖宽度，
  并标出「参考 ≥3 段而我们 ≤2 段」的高度带（= 必须开缝的区间）。
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'tools'))

import visual_ruler as VR                                    # noqa: E402
from leg_ab import shade                                     # noqa: E402

PANEL = VR.PANEL
NB = 50


def band(cov):
    """返回每带的 (段数, 覆盖宽/H, 空隙宽/H)。y 从上到下。"""
    H, W = cov.shape
    ys = np.where(cov.any(1))[0]
    y0, y1 = int(ys.min()), int(ys.max())
    Hn = float(y1 - y0 + 1)
    out = []
    for b in range(NB):
        ya = y0 + int(Hn * b / NB)
        yb = max(ya + 1, y0 + int(Hn * (b + 1) / NB))
        sub = cov[ya:yb]
        runs, covw, voidw = [], [], []
        for r in range(sub.shape[0]):
            row = sub[r]
            if not row.any():
                continue
            xs = np.where(row)[0]
            # 归一化到 H 单位（横向也用 H，才能与参考同尺度比较）
            d = np.diff(np.concatenate(([0], row.astype(np.int8), [0])))
            runs.append(int((d == 1).sum()))
            covw.append(float(row.sum()) / Hn)
            voidw.append(float(xs.max() - xs.min() + 1 - row.sum()) / Hn)
        if not runs:
            out.append((0, 0.0, 0.0))
        else:
            out.append((float(np.mean(runs)), float(np.mean(covw)), float(np.mean(voidw))))
    return out, Hn


def main():
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
    from leg_ab import Soup
    a_img, a_cov = shade(Soup(Q.reshape(-1, 3, 3), mi, base), 0.0, PANEL)
    b_img, b_cov = shade(VR.ref(), 0.0, PANEL)
    A, _ = band(a_cov)
    B, _ = band(b_cov)

    print('=' * 78)
    print('高度带（0=头顶 1=脚底）  我们段数 参考段数 ｜ 我们覆盖宽 参考覆盖宽 ｜ 判读')
    print('=' * 78)
    todo = []
    for i in range(NB - 1, -1, -1):          # 从上往下打印（图上是上）
        h = 1.0 - (i + 0.5) / NB
        ra, ca, va = A[i]
        rb, cb, vb = B[i]
        flag = ''
        if rb >= 3.0 and ra <= 2.0:
            flag = '★ 开缝'
            todo.append((h, ra, rb))
        elif rb - ra >= 1.5:
            flag = '△ 欠缝'
        print('  y=%.3f  %5.2f  %5.2f  ｜  %.3f  %.3f  %s' % (h, ra, rb, ca, cb, flag))
    print('\n必须开缝的高度带（参考 ≥3 段、我们 ≤2 段）：')
    if not todo:
        print('  无')
    for h, ra, rb in todo:
        print('  y/H = %.3f   我们 %.2f 段 → 参考 %.2f 段' % (h, ra, rb))
    print('\n段数均值：我们 %.2f  参考 %.2f' % (np.mean([a[0] for a in A]),
                                              np.mean([b[0] for b in B])))


if __name__ == '__main__':
    main()
