"""geoaudit.py — 把「矩形块拼接感」与「头颈断开」从主观判断变成可测数字

为什么需要这个：用户对 M1/M2 静帧的反馈是「很浓重的矩形块拼接感」「头脖子和身体
是分开的」。这两句话如果只当作审美意见，就无法验证改造是否有效。所以先量出四个量：

  1. 法线分布 —— 表面有多少是「正轴面」，多少是「单轴斜面」，多少是「双斜面」。
     横平竖直的堆盒子模型，双斜面占比必然接近 0。这是「块感」的直接成因：
     只有正轴面时，所有面的明暗跳变只能发生在 90° 棱线上，视觉上就是积木。
  2. 顶视方位角集中度 —— 只看侧向面，它们的水平朝向分散在多少个方向。
     集中成几个方向 = 俯视看是棱柱；分散成连续 = 俯视看有曲率。
  3. 横截面宽度剖面 —— 沿 y 每 0.1 m 取一次几何的 x 跨度。头颈「断开」的判定：
     在下颌与胸甲顶之间存在一段宽度骤降且持续很长的区间，即「细管子裸奔」。
  4. 关节过渡比 —— 膝/小腿/踝、肩/上臂/肘的宽度变化幅度。真实高达是明确的
     双曲线轮廓（膝宽 > 小腿中段 < 踝），单调递减的锥台看起来就是方管。

输出全部为面积加权，避免细碎小面（格栅、贴花）把结论带偏。

用法：
  python3 tools/geoaudit.py            # 打印全部
  python3 tools/geoaudit.py --profile  # 只打印宽度剖面
"""
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import mecha_model as MM                                     # noqa: E402
from gfx.mesh import Mesh, collect2                          # noqa: E402

# 6 个正轴方向
AXES = np.array([[1, 0, 0], [-1, 0, 0], [0, 1, 0],
                 [0, -1, 0], [0, 0, 1], [0, 0, -1]], float)


# ------------------------------------------------------------------ 装载
def load(t=None):
    """t=None 用**静止姿势**审计。带姿势的数字不能写进设计文档：t=10.80 的
    head_pitch 会把整个头部子树转 -40° 左右，颈管的 z 包围盒从 ±0.52 漂到
    0.14..1.18，读出来的剖面是「某帧的形变」而不是「模型本身」。"""
    import film2 as F
    from r3d import Node
    mech = Mesh()
    root = MM.build_mecha({} if t is None else F.pose(t))
    collect2(root, mech)
    P = np.array(mech.P, np.float64)          # (T,3,3)
    N = np.array(mech.N, np.float64)          # (T,3,3)
    return root, mech, P, N


def load_torso(t=None):
    """只装躯干（去掉手臂/腿/背包/枪），否则横截面剖面会被 x=±5.5 的
    护盾与步枪污染 —— 实测会读出「腰宽 7.7 m」这种毫无意义的数。"""
    import film2 as F
    from r3d import Node
    p = {} if t is None else F.pose(t)
    root = Node('root')
    hips = MM.J(root, 'hips', (0, 9.90, 0))
    MM._waist(hips, p)
    chest = MM._chest(hips, p)
    MM._head(chest, p)
    m = Mesh()
    collect2(root, m)
    return np.array(m.P, np.float64), np.array(m.N, np.float64)


def tri_stats(P):
    """每三角的面积与面法线（用顶点法线均值也行，但面积要用真实叉积）"""
    e1 = P[:, 1] - P[:, 0]
    e2 = P[:, 2] - P[:, 0]
    cr = np.cross(e1, e2)
    a = 0.5 * np.linalg.norm(cr, axis=1)
    return a


def node_bbox(root, xform=None):
    """逐节点世界包围盒，用来做「部件级」的测量（头/胸/颈各自多大）"""
    out = {}

    def rec(node, xf):
        m = node.local() if xf is None else xf @ node.local()
        if node.prim is not None:
            v = node.prim[0]
            vw = (m @ np.hstack([v, np.ones((len(v), 1))]).T).T[:, :3]
            out.setdefault(node.name or '?', []).append(
                (vw.min(axis=0), vw.max(axis=0)))
        for c in node.children:
            rec(c, m)

    rec(root, xform)
    return {k: (np.min([b[0] for b in v], axis=0), np.max([b[1] for b in v], axis=0))
            for k, v in out.items()}


# ------------------------------------------------------------------ 1 法线
def flat_cluster(P, N, A):
    """平坦面（顶点法线三顶点相同）的 1° 法线聚类。

    为什么不用「与最近正轴的夹角」：圆柱侧面的法线是水平向的连续扇面，
    按最近轴判会全部落进「斜面」，把结论稀释掉。这里先按「顶点法线是否
    相同」把 smooth 与 flat 分开，只对硬表面做聚类 —— 硬表面才是「块感」的来源。
    """
    same = (np.abs(N[:, 0] - N[:, 1]).max(axis=1) < 1e-6) & \
           (np.abs(N[:, 0] - N[:, 2]).max(axis=1) < 1e-6)
    a_flat = A[same]
    n_flat = N[same, 0]
    a_sm = A[~same]
    print('\n[1] 硬表面 vs 平滑面')
    print('    平坦面（硬边）  %6.2f%% 面积  %8.2f m²  %d 三角'
          % (a_flat.sum() / A.sum() * 100, a_flat.sum(), same.sum()))
    print('    平滑面（圆柱侧）%6.2f%% 面积  %8.2f m²  %d 三角'
          % (a_sm.sum() / A.sum() * 100, a_sm.sum(), (~same).sum()))

    nn = n_flat / np.maximum(np.linalg.norm(n_flat, axis=1, keepdims=True), 1e-9)
    key = ((np.round(nn, 2) + 1.0) * 50).astype(int)      # 0.02 量化 ≈ 1°
    key = key[:, 0] * 1000000 + key[:, 1] * 1000 + key[:, 2]
    uk, inv = np.unique(key, return_inverse=True)
    area = np.bincount(inv, weights=a_flat, minlength=len(uk))
    order = np.argsort(-area)
    tot = a_flat.sum()
    print('    硬表面不同朝向数：%d（0.02 量化）' % len(uk))
    print('    前 10 个朝向占硬表面面积：%.1f%%'
          % (area[order[:10]].sum() / tot * 100))
    print('    前 30 个朝向占硬表面面积：%.1f%%'
          % (area[order[:30]].sum() / tot * 100))
    print('    单一方位覆盖最大面积占比：%.1f%%  （一个面 = 一整块平板）'
          % (area[order[0]] / tot * 100))
    print('    面积 > 1%% 的"大平板"数量：%d' % int((area / tot > 0.01).sum()))

    # 这些大平板里，朝向与正轴的关系
    big = order[area / tot > 0.005]
    nbig = np.array([[((k // 1000000) % 1000) - 50,
                      ((k // 1000) % 1000) - 50,
                      (k % 1000) - 50] for k in uk[big]], float) / 50.0
    with np.errstate(invalid='ignore'):
        ang = np.degrees(np.arccos(np.clip(np.abs(nbig) @
                                          np.array([1, 0, 0], float), -1, 1)))
    print('    按 |n·x| 分：<10° %.0f%%  >80° %.0f%%'
          % ((ang < 10).mean() * 100, (ang > 80).mean() * 100))
    return same, area, tot


def normal_classes(P, N, A):
    """面积加权的法线分类。

    分类依据是法线与正轴的关系，不是与「最近轴」的角度 —— 后者会把双斜面
    误判成单斜面。判据：
      A 正轴面  : 两个分量 |n| < 3e-2（一个分量 ≈ ±1）
      B 单斜面  : 恰好一个分量 |n| < 3e-2（法线落在某个坐标平面内）
      C 双斜面  : 三个分量都 >= 3e-2
    """
    nn = N[:, 0] / np.maximum(np.linalg.norm(N[:, 0], axis=1, keepdims=True), 1e-9)
    small = np.abs(nn) < 3e-2
    ns = small.sum(axis=1)
    cls = np.where(ns >= 2, 0, np.where(ns == 1, 1, 2))
    tot = A.sum()
    names = ['A 正轴面（法线≈±x/±y/±z）',
             'B 单斜面（法线在一个坐标平面内，如只绕 z 倾）',
             'C 双斜面（三个分量都非零，真正的自由朝向）']
    print('\n[1] 法线分类（面积加权）')
    for k in range(3):
        m = cls == k
        print('    %-46s %6.2f%%   %8.2f m²' % (names[k], A[m].sum() / tot * 100,
                                                A[m].sum()))
    # 正轴面里再分「六向是否均衡」
    m0 = cls == 0
    if m0.any():
        idx = np.abs(nn[m0]).argmax(axis=1)
        cnt = np.bincount(idx, weights=A[m0], minlength=3)
        print('    正轴面按轴：x %.1f%%  y %.1f%%  z %.1f%%'
              % (cnt[0] / cnt.sum() * 100, cnt[1] / cnt.sum() * 100,
                 cnt[2] / cnt.sum() * 100))
    return cls, tot


def topview_spread(P, N, A):
    """侧向面的水平朝向分散度。只取 |n_y| < 0.35 的面（排除顶/底面）。"""
    m = np.abs(N[:, 0, 1]) < 0.35
    nn = N[m, 0]
    az = np.degrees(np.arctan2(nn[:, 2], nn[:, 0])) % 360.0
    w = A[m]
    # 1° 桶，面积占比 > 0.2% 才算「实际存在的朝向」
    b = np.bincount((az / 1.0).astype(int) % 360, weights=w, minlength=360)
    occ = (b / b.sum() > 0.002).sum()
    # 集中度：最大 5° 扇区占多大面积
    c5 = np.array([b[i:i + 5].sum() for i in range(0, 360, 5)])
    print('\n[2] 顶视方位角分散度（仅侧向面，|n_y|<0.35，面积 %.1f m²）'
          % w.sum())
    print('    实际占据的 1° 朝向桶：%d / 360' % occ)
    print('    最大 5° 扇区面积占比：%.1f%%（越高越像棱柱）'
          % (c5.max() / b.sum() * 100))
    print('    前 6 个扇区：%s' % ', '.join(
        '%d°:%.1f%%' % (i * 5, c5[i] / b.sum() * 100)
        for i in np.argsort(-c5)[:6]))
    return occ, c5.max() / b.sum()


# ------------------------------------------------------------------ 3 剖面
def width_profile(P, y0=9.0, y1=18.0, step=0.10):
    """横截面 x 跨度剖面。三角形跨越某 y 平面时，按其与平面的交线段取 x 范围。

    比「顶点落在 bin 内」稳：细管只有 8 个侧面，顶点可能全在 bin 之外。
    """
    rows = []
    y = y0
    while y <= y1 + 1e-9:
        xs, zs = [], []
        for i in range(len(P)):
            p = P[i]
            ys = p[:, 1]
            if ys.max() < y or ys.min() > y:
                continue
            # 三条边与平面 y 求交
            for a, b in ((0, 1), (1, 2), (2, 0)):
                ya, yb = ys[a], ys[b]
                if (ya - y) * (yb - y) <= 0 and abs(ya - yb) > 1e-12:
                    t = (y - ya) / (yb - ya)
                    q = p[a] + t * (p[b] - p[a])
                    xs.append(q[0])
                    zs.append(q[2])
        if xs:
            rows.append((y, min(xs), max(xs), max(xs) - min(xs),
                         max(zs) - min(zs)))
        y += step
    return rows


def print_profile(rows):
    print('\n[3] 躯干横截面宽度剖面（y↑，单位 m；w = x 跨度，d = z 跨度）')
    print('      y      xmin    xmax      w       d    bar')
    for y, x0, x1, w, d in rows:
        bar = '#' * int(w * 4)
        mark = ''
        if w < 1.6:
            mark = '  ← 细颈'
        print('   %6.2f  %6.2f  %6.2f  %6.2f  %6.2f  %s%s' % (y, x0, x1, w, d, bar, mark))


# ------------------------------------------------------------------ 4 部件
def part_report(bb):
    print('\n[4] 关键部件世界包围盒（x0..x1, y0..y1, z0..z1 → 尺寸）')
    keys = ['hips', 'chest', 'head', 'neck_tube', 'neck_ring_a', 'neck_ring_b',
            'collar', 'core', 'chest_up1', 'chest_up-1', 'pauldron1',
            'skull_top', 'skull_back', 'brow', 'visor_frame', 'jaw1']
    for k in keys:
        if k not in bb:
            continue
        lo, hi = bb[k]
        s = hi - lo
        print('    %-14s x %6.2f..%6.2f  y %6.2f..%6.2f  z %6.2f..%6.2f'
              '  → %.2f × %.2f × %.2f' % (k, lo[0], hi[0], lo[1], hi[1],
                                          lo[2], hi[2], s[0], s[1], s[2]))


def main():
    prof_only = '--profile' in sys.argv
    root, mech, P, N = load()
    A = tri_stats(P)
    print('=' * 74)
    print('mega 几何审计  三角 %d  面部件 %d  表面积 %.1f m²'
          % (len(P), len(mech.M), A.sum()))
    lo = P.reshape(-1, 3).min(axis=0)
    hi = P.reshape(-1, 3).max(axis=0)
    print('世界包围盒 x %.1f..%.1f  y %.1f..%.1f  z %.1f..%.1f  → %.1f×%.1f×%.1f'
          % (lo[0], hi[0], lo[1], hi[1], lo[2], hi[2],
             hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]))

    if not prof_only:
        flat_cluster(P, N, A)
        topview_spread(P, N, A)

    Pt, Nt = load_torso()
    rows = width_profile(Pt)
    print_profile(rows)

    if not prof_only:
        bb = node_bbox(root)
        part_report(bb)
        # 头颈比
        if 'head' in bb:
            hl, hh = bb['head']
            print('\n[5] 比例')
            print('    全高 %.2f m，头部包围盒 %.2f × %.2f × %.2f m，头高/全高 = 1:%.1f'
                  % (hi[1], hh[0] - hl[0], hh[1] - hl[1], hh[2] - hl[2],
                     hi[1] / max(hh[1] - hl[1], 1e-6)))
        if 'neck_tube' in bb and 'chest_up1' in bb:
            nl, nh = bb['neck_tube']
            cl, ch = bb['chest_up1']
            print('    颈管直径 %.2f m，胸甲单侧宽 %.2f m，颈/胸 = 1:%.1f'
                  % (nh[0] - nl[0], ch[0] - cl[0],
                     (ch[0] - cl[0]) / max(nh[0] - nl[0], 1e-6)))
            print('    颈管底 y=%.2f，胸甲顶 y=%.2f，差 %.2f m（正=颈根裸露在胸甲之上）'
                  % (nl[1], ch[1], nl[1] - ch[1]))
        # 头宽 / 肩宽 —— SEED 实机约 22~25%，这是「头太小」的判据
        if 'head' in bb and 'pauldron1' in bb:
            hl, hh = bb['head']
            pl, ph = bb['pauldron1']
            pl2, ph2 = bb['pauldron-1']
            sw = ph2[0] - pl[0]
            print('    头宽 %.2f m，肩全宽 %.2f m，头宽/肩宽 = %.1f%%（SEED 实机 22~25%%）'
                  % (hh[0] - hl[0], sw, (hh[0] - hl[0]) / sw * 100))
            print('    若要把头宽/肩宽做到 24%%，头宽需 %.2f m（现值 %.2f m，需放 %.0f%%）'
                  % (sw * 0.24, hh[0] - hl[0],
                     (sw * 0.24 / (hh[0] - hl[0]) - 1) * 100))


if __name__ == '__main__':
    main()
