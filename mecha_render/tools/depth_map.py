"""tools/depth_map.py — 纵深归谁了：逐件 z 占用 + 逐高度带的「最前 / 最后」归属

为什么要有这个文件
  §28 把肩甲收完之后，W/H 掉到 0.5210，D/W 反而涨到 0.6088。
  但那是个**比值**，它同时受分子分母影响 —— 拿它当「纵深太大」的证据不够。
  真正要回答的是：**2.515 m 的纵深，是哪些件撑出来的，各自几米。**

  参考口径（out/ref/unicorn_trunk.json · 主干，已剥背包/火神炮/推进器）：
      W 5.607 · D 2.894 · D/W 0.516 · D/H 0.289
  我们（H 归一 10）：W 5.209 · D 3.171 · D/W 0.609 · D/H 0.317

  也就是说 W 窄了 7%（肩甲刚收，故意的），D 却**实打实厚了 9.6%**。
  这 9.6% 折成米是 0.22 m。要先知道这 0.22 m 挂在哪几个件上，才知道能不能砍。

口径
  ★ 逐件用**子节点 bbox**，不用「高度带里取极值」—— 高度带会把邻近件混进来
    （shoulder_ab.py 第一版就这么错，把上臂算成肩甲）。
  纵向归一是「机高 = 10」；米制换算用实测 H = 7.930 m。

用法
  python3 tools/depth_map.py                 # 改后（SH_SQUEEZE=True）
  python3 tools/depth_map.py --no-shk        # 改前
  python3 tools/depth_map.py --ref           # 只打参考表
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'tools'))

import refview as RV                                       # noqa: E402
import s2_graybox as S                                     # noqa: E402
import unicorn_trunk as UT                                 # noqa: E402

OUT = os.path.join(HERE, 'out', 'ref')
H_M = 7.930          # 实测机高（米）
U = 10.0 / H_M       # 1 m = U 个 H 单位


def parts(root):
    """顶层子节点逐个取 bbox（真实米）。空节点（纯变换壳）跳过。"""
    out = []
    for c in root.children:
        mb = S.Mesh()
        try:
            S.collect2(c, mb)
        except Exception:
            continue
        if not len(mb.P):
            continue
        P = np.array(mb.P, np.float32).reshape(-1, 3)
        lo, hi = P.min(0), P.max(0)
        out.append(dict(name=c.name or '(unnamed)', P=P,
                        x=(lo[0], hi[0]), y=(lo[1], hi[1]), z=(lo[2], hi[2]),
                        tris=len(P) // 3))
    return out


def band_z(P, ylo, yhi, nb=10):
    """逐高度带的 max z / min z，**边插值**（与 silhouette_ruler 同理：
    我们的件按层放样，一个 0.4 m 高的筒身只在上下两层有顶点）。"""
    F = P.reshape(-1, 3, 3)
    # ★ 端点对必须成对拼，不能「A 用 (0,1)、(1,2)、(2,0)，B 用 (1,2)、(2,0)、(0,1)」
    #   —— 那样 A[i] 与 B[i] 不是同一条边的两端，算出来的 z 全是垃圾
    #   （第一版就是这样，背包被报成「0%–90% 全高度都在最后面」）。
    A = np.concatenate([F[:, i] for i, _ in ((0, 1), (1, 2), (2, 0))], 0)
    B = np.concatenate([F[:, j] for _, j in ((0, 1), (1, 2), (2, 0))], 0)
    # ★ 高度带必须用**全机**的 ylo/yhi，不能用件自己的
    #   —— 第一版按件归一，每个件都从自己的脚底数起，
    #     于是背包（y 5.1–7.1）被报成「0%–90% 全高度都在最后面」。
    step = (yhi - ylo) / nb
    fz = np.full(nb, -9.0)
    bz = np.full(nb, 9.0)
    for k in range(nb):
        a, b = ylo + k * step, ylo + (k + 1) * step
        ya, yb, za, zb = A[:, 1], B[:, 1], A[:, 2], B[:, 2]
        m = (np.maximum(ya, yb) >= a) & (np.minimum(ya, yb) <= b) & (ya != yb)
        if not m.any():
            continue
        t0 = np.clip((a - ya[m]) / (yb[m] - ya[m]), 0, 1)
        t1 = np.clip((b - ya[m]) / (yb[m] - ya[m]), 0, 1)
        z0 = za[m] + t0 * (zb[m] - za[m])
        z1 = za[m] + t1 * (zb[m] - za[m])
        fz[k] = max(fz[k], max(z0.max(), z1.max()))
        bz[k] = min(bz[k], min(z0.min(), z1.min()))
        # 水平边（ya==yb）单独算一次
        mh = (ya == yb) & (ya >= a) & (ya <= b)
        if mh.any():
            fz[k] = max(fz[k], za[mh].max(), zb[mh].max())
            bz[k] = min(bz[k], za[mh].min(), zb[mh].min())
    return fz, bz


def own_band(ps, ylo, yhi, nb=10):
    """逐高度带的「最前是谁 / 最后是谁」——按件归，不按高度带混。"""
    fz = np.full(nb, -9.0)
    bz = np.full(nb, 9.0)
    fn = ['-'] * nb
    bn = ['-'] * nb
    for p in ps:
        a, b = band_z(p['P'], ylo, yhi, nb)
        for k in range(nb):
            if a[k] > fz[k]:
                fz[k], fn[k] = a[k], p['name']
            if b[k] < bz[k]:
                bz[k], bn[k] = b[k], p['name']
    return fz, bz, fn, bn


def ref_trunk_tris():
    """参考主干（剥背包/肩炮/后腰·小腿推进器）的三角，H=10 归一。"""
    V, tris, gf, sets = UT.load_obj_grouped(UT.SRC)
    Vn, _ = RV.normalize(V)
    keep = np.ones(len(tris), bool)
    for tok in UT.REMOVE:
        keep &= ~UT.face_in(gf, sets, tok)
    return Vn[tris[keep]]


def main():
    S.CLEAN = True                       # 与 s2_graybox --clean 同口径（当前模型）
    if '--no-shk' in sys.argv:
        S.SH_SQUEEZE = False
    if '--ref' not in sys.argv:
        root, mesh = S.build()
        ps = parts(root)
        V = np.array(mesh.P, np.float32).reshape(-1, 3)
        lo, hi = V.min(0), V.max(0)
        W, D, Ht = hi[0] - lo[0], hi[2] - lo[2], hi[1] - lo[1]
        print('我们（%s）  %.3f × %.3f × %.3f m   W/H %.4f  D/H %.3f  D/W %.4f'
              % ('改后' if S.SH_SQUEEZE else '改前', W, Ht, D,
                 W / Ht, D / Ht, D / W))
        print('  参考主干      W/H 0.5607  D/H 0.289  D/W 0.516')
        print('  差           W %+.1f%%   D %+.1f%%'
              % (100 * (W / Ht / 0.5607 - 1), 100 * (D / Ht / 0.289 - 1)))
        print('\n  逐件纵深（按 D 降序，米；y 为离地高）')
        print('  %-14s %6s %6s %6s %6s %6s  %s'
              % ('件', 'z前', 'z后', '深', 'y下', 'y上', ''))
        for p in sorted(ps, key=lambda q: -(q['z'][1] - q['z'][0])):
            d = p['z'][1] - p['z'][0]
            bar = '#' * max(0, int(round(d / 0.05)))
            print('  %-14s %6.2f %6.2f %6.2f %6.2f %6.2f  %s'
                  % (p['name'], p['z'][1], p['z'][0], d,
                     p['y'][0], p['y'][1], bar))
        print('\n  逐高度带：最前 / 最后 归谁（z 单位米，%机高）')
        fz, bz, fn, bn = own_band(ps, lo[1], hi[1])
        for k in range(len(fz)):
            print('   %3d–%3d%%  前 %+5.2f %-14s   后 %+5.2f %-14s'
                  % (10 * k, 10 * (k + 1), fz[k], fn[k], bz[k], bn[k]))

    # ---- 逐高度带：前 / 后 / 深，我们 vs 参考（都用 H=10 单位）
    Pt = ref_trunk_tris()
    NB = 10
    tmp = Pt.reshape(-1, 3)
    ry0, ry1 = float(tmp[:, 1].min()), float(tmp[:, 1].max())
    # ★ 两边的带必须各自按**自己的** y 范围切：我们 0–7.930 米、参考 0–10 单位。
    #   第一版给我们的也传了参考的 0–10，于是 80% 以上完全没有三角，
    #   输出 −11.35 / +11.35（这就是 fz/bz 的初值 −9 / 9 乘上换算系数）。
    uf, ub, _, _ = own_band(ps, 0.0, H_M, NB)                 # 我们的（米）
    rf, rb = band_z(Pt.reshape(-1, 3, 3), ry0, ry1, NB)       # 参考（H 单位）
    print('\n  逐高度带纵深对照（H=10 单位；我们 ×%.3f 由米换算）' % U)
    print('   %-9s %13s %13s %8s' % ('高度', '我们 前/后/深', '参考 前/后/深', '深差'))
    for k in range(NB):
        a0, a1 = uf[k] * U, ub[k] * U
        print('   %3d–%3d%%   %+5.2f %+5.2f %5.2f    %+5.2f %+5.2f %5.2f   %+5.2f'
              % (10 * k, 10 * (k + 1), a0, a1, a0 - a1,
                 rf[k], rb[k], rf[k] - rb[k], (a0 - a1) - (rf[k] - rb[k])))

    # ---- 参考
    j = json.load(open(os.path.join(OUT, 'unicorn_trunk.json')))
    print('\n  参考主干逐装配（H=10 单位；×0.793 得米）')
    print('  %-28s %6s %6s %6s %6s %6s'
          % ('装配', 'z前', 'z后', '深', 'y下', 'y上'))
    rows = sorted(j['assemblies'].items(), key=lambda kv: -(kv[1]['z'][1] - kv[1]['z'][0]))
    for n, a in rows:
        print('  %-28s %6.2f %6.2f %6.2f %6.2f %6.2f'
              % (n, a['z'][1], a['z'][0], a['z'][1] - a['z'][0], a['y'][0], a['y'][1]))
    trunk = [r for r in j['ratios'] if r[0].startswith('主干')][0]
    print('  %-28s  %s   （%s）' % ('(主干合计)', trunk[1], trunk[2]))


if __name__ == '__main__':
    main()
