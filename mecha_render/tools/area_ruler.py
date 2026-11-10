"""tools/area_ruler.py — 面积尺：把「不像 Unicorn」拆成可量的面积分布指标

为什么需要这把尺子
  已有的 prop_ruler（横线/剖面）量的是**大比例**，crevice_ruler 量的是**缝**。
  但用户问的「为什么达不到 unicorn 的程度」，答案既不在比例也不在缝 ——
  实测十根横线已经全部落在 ±0.04 H 之内，观感差距依然很大。
  真正的差距在**面积的分布**：我们的表面有 65% 是「一整块大平板」，
  参考只有 0.2%。这是任何局部造型参数都反映不出来的量，必须单独量。

判据（全部用面积，不用三角数 —— 三角数可以被无意义地堆高）
  A1 大平板面积占比  = 面积 > 0.05 m² 的三角形的面积和 / 总面积
  A2 平均三角面积    = 总面积 / 三角数
  A3 单件三角数      = 三角数 / 含 prim 的节点数
  A4 总表面积        = 所有三角面积和（米制，参考按 H=7.930/10 换算同尺）

通过线见 `DeepSeek_改造任务书_从灰模到Unicorn级.md` §6。

用法
  python3 tools/area_ruler.py            # 出表 + out/ref/area_ruler.json
"""
import collections
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'tools'))

import refview as RV                                        # noqa: E402
import s2_graybox as S                                      # noqa: E402
import unicorn_trunk as UT                                  # noqa: E402

OUT = os.path.join(HERE, 'out', 'ref')
BIG = 0.05          # m²：≈ 22 cm × 45 cm 的一块平板，肉眼在 1 m 距离上就是"空白"
H = 7.930 / 10.0    # 参考 H=10 → 我们 7.930 m


def areas(P):
    return 0.5 * np.linalg.norm(np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0]), axis=1)


def ours():
    S.CLEAN = True
    root, mesh = S.build()
    rows, Ps, nparts = [], [], 0

    def count(nd):
        c = 1 if getattr(nd, 'prim', None) is not None else 0
        for ch in nd.children:
            c += count(ch)
        return c

    for c in root.children:
        if getattr(c, 'hide', False):
            continue
        mb = S.Mesh()
        S.collect2(c, mb)
        if len(mb) == 0:
            continue
        P = np.asarray(mb.P, np.float64)
        A = areas(P)
        np_ = count(c)
        nparts += np_
        Ps.append(P)
        rows.append(dict(part=c.name, tris=len(P), area=float(A.sum()),
                         mean=float(A.mean()), big_pct=float(100 * A[A > BIG].sum() / A.sum()),
                         prims=np_))
    P = np.concatenate(Ps)
    return P, rows, nparts


def ref():
    V, tris, gf, sets = UT.load_obj_grouped(UT.SRC)
    Vn, _ = RV.normalize(V)
    keep = np.ones(len(tris), bool)
    for t in UT.REMOVE:
        keep &= ~UT.face_in(gf, sets, t)
    T = tris[keep]
    P = Vn[T].astype(np.float64) * H
    groups = len(set(str(g) for g, k in zip(gf, keep) if k))
    return P, groups


def stat(P):
    A = areas(P)
    return dict(tris=len(P), area=float(A.sum()), mean=float(A.mean()),
                median=float(np.median(A)),
                big_pct=float(100 * A[A > BIG].sum() / A.sum()),
                big_tris=int((A > BIG).sum()))


def main():
    os.makedirs(OUT, exist_ok=True)
    P, rows, nparts = ours()
    Pr, groups = ref()
    so, sr = stat(P), stat(Pr)
    so['per_part'] = so['tris'] / nparts
    sr['per_part'] = sr['tris'] / groups
    so['parts'] = nparts
    sr['parts'] = groups

    print('=' * 78)
    print('面积尺 · 我们(CLEAN 可见) vs Unicorn 主干（同尺，米）')
    print('=' * 78)
    print('%-26s %14s %14s %10s' % ('指标', '我们', '参考', '比值'))
    for k, lab, fmt in [('tris', '三角总数', '%d'), ('parts', '零件/装配数', '%d'),
                        ('per_part', '单件三角数', '%.1f'), ('area', '总表面积 m²', '%.2f'),
                        ('mean', '平均三角面积 m²', '%.5f'), ('median', '中位三角面积 m²', '%.5f'),
                        ('big_pct', '大平板面积占比 %%', '%.1f'),
                        ('big_tris', '>0.05m² 三角个数', '%d')]:
        a, b = so[k], sr[k]
        ratio = (b / a) if a else 0
        print('%-26s %14s %14s %10.2f' % (lab, fmt % a, fmt % b, ratio))
    print()
    print('%-10s %8s %10s %10s %10s %8s' % ('部件', 'tris', '面积m²', '均值m²', '大面占比%', 'prims'))
    for r in sorted(rows, key=lambda r: -r['area']):
        print('%-10s %8d %10.2f %10.5f %10.1f %8d' %
              (r['part'], r['tris'], r['area'], r['mean'], r['big_pct'], r['prims']))
    res = dict(ours=so, ref=sr, rows=rows)
    dst = os.path.join(OUT, 'area_ruler.json')
    json.dump(res, open(dst, 'w'), ensure_ascii=False, indent=1)
    print('\n→ ' + dst)


if __name__ == '__main__':
    main()
