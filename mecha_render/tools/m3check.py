"""m3check.py — M3 改造的验收测量（口径固定，改前改后可比）

三个坑已经踩过，这里全部写进口径定义，避免下次再读错数：

 1. **头高不能按 y 切**。背包翼片一直伸到 y=22.8，用「y>16 的最高点」当头顶
    会把翼片算进去，实测读出头身比 1:3.4 这种荒谬值。这里的做法是：找到
    head 节点，只收集它的子树，再用 head.world() 变换到世界坐标取包围盒。
 2. **颈肩宽度剖面不能用 box 过滤**。躯干左右两侧有背包翼（x≈±2）和护盾
    （x≈±5.4），用「|x|<3.2」筛三角仍会把 y=16.5 处的宽度读成 4.09 m
    （真实头宽 1.87）。这里改为重建一棵只含 waist/chest/head 的躯干树。
 3. **肩宽要按高度取**，不能用全模型 x 跨度 —— 后者含手持的枪和盾。

二面角分带沿用 edgeaudit：<8° 共面 / 8~30° 缓坡 / 30~75° 折面 /
75~105° 近直角 / >105° 锐折。g_chamfer 的倒角落在 30~75°（45° 斜条），
g_loft 的折面落 8~75° 两带，所以「近直角 ≤15% + 折面合计 ≥55%」才是判据，
单看 8~30° 这一带会把 chamfer 的功劳漏掉。
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import mecha_model as MM                                        # noqa: E402
from gfx.mesh import Mesh, collect2, prim_to_tris               # noqa: E402
from tools.edgeaudit import edges_of                            # noqa: E402
from tools.geoaudit import width_profile, tri_stats             # noqa: E402


def find(node, name):
    if node.name == name:
        return node
    for c in node.children:
        r = find(c, name)
        if r is not None:
            return r
    return None


def build_torso(pose=None, patch=None):
    """只装 waist / chest / head 的躯干树。patch 是可选的外科手术函数。"""
    from r3d import Node
    p = {} if pose is None else pose
    root = Node('root')
    hips = MM.J(root, 'hips', (0, 9.90, 0))
    MM._waist(hips, p)
    chest = MM._chest(hips, p)
    MM._head(chest, p)
    if patch is not None:
        patch(root)
    return root


def mesh_below(node, skip=None):
    """收集**子树**（不含 node 自身变换）并变换到世界。

    ★ 不能写成 collect2(node, m, node.local()) —— collect2 内部会做
      xform @ node.local()，传进去等于把 head.local() 乘了两遍。
    ★ 必须用 world() 而不是 local()：head 挂在 chest → hips 下，只乘 local()
      会得到 chest 局部坐标（y≈4.3），不是世界坐标（y≈17.1）。
    ★ skip：按名字前缀剔除子树。测「头高」时必须剔掉 neck —— 颈管挂在 head
      节点下且下探到下颌以下，不剔会把颈长算进头高（实测 1.81 → 3.40）。
    """
    skips = ()
    if skip:
        skips = (skip,) if isinstance(skip, str) else tuple(skip)
    m = Mesh()
    m0 = node.world()

    def rec(nd, xf):
        for c in nd.children:
            if any(c.name.startswith(k) for k in skips):
                continue
            cm = xf @ c.local()
            if c.prim is not None:
                prim_to_tris(m, c.prim[0], c.prim[1], cm, c.mat,
                             getattr(c, 'smooth', None))
            rec(c, cm)

    # ★ skip 必须递归生效：PoC 里颈管挂在 head_scl 下，只筛 head 的直接子节点
    #   会漏掉它，头高会从 2.22 读成 2.91。
    rec(node, m0)
    if not m.P:
        return (np.zeros((0, 3, 3)), np.zeros((0, 3, 3)), np.zeros((0,)))
    P = np.array(m.P, np.float64)
    N = np.array(m.N, np.float64)
    return P, N, tri_stats(P)


def mesh_of(node, xform=None):
    m = Mesh()
    collect2(node, m, xform)
    if not m.P:
        return (np.zeros((0, 3, 3)), np.zeros((0, 3, 3)), np.zeros((0,)))
    P = np.array(m.P, np.float64)
    N = np.array(m.N, np.float64)
    return P, N, tri_stats(P)


def band_stats(P, N, A):
    """二面角分带。**分母排除 ANG<2° 的内部共面棱**。

    理由：每个四边形被扇形三角化成 2 个三角，必然多出一条对角线，它的二面角
    恒为 0°。这部分棱在画面上完全不存在（同一块板的内部接缝），但它们的长度
    可以占到总棱长的 50% —— 放进分母会把真正的棱长占比稀释掉一半。
    所以统计「可见棱」时以 ANG>=2 为分母，内部共面另列。
    """
    L, ANG = edges_of(P, N, A)
    all_len = float(L.sum())
    vis = ANG >= 2.0
    Lv = L[vis]
    tot = float(Lv.sum())
    eps = 1e-9
    m = dict(
        n=int(vis.sum()), length=tot, all_len=all_len,
        seam=float(L[~vis].sum() / max(all_len, eps) * 100),
        flat=float(Lv[(ANG[vis] < 8)].sum() / max(tot, eps) * 100),
        ramp=float(Lv[(ANG[vis] >= 8) & (ANG[vis] < 30)].sum() / max(tot, eps) * 100),
        fold=float(Lv[(ANG[vis] >= 30) & (ANG[vis] < 75)].sum() / max(tot, eps) * 100),
        right=float(Lv[(ANG[vis] >= 75) & (ANG[vis] < 105)].sum() / max(tot, eps) * 100),
        sharp=float(Lv[(ANG[vis] >= 105)].sum() / max(tot, eps) * 100),
    )
    ANG = ANG[vis]
    L = Lv
    r = (ANG >= 75) & (ANG < 105)
    m['longest_right'] = float(L[r].max()) if r.any() else 0.0
    # 顶视方位桶（只取侧向面）
    lat = np.abs(N[:, 0, 1]) < 0.35
    if lat.any():
        nn = N[lat, 0]
        az = np.degrees(np.arctan2(nn[:, 2], nn[:, 0])) % 360.0
        b = np.bincount((az / 1.0).astype(int) % 360, weights=A[lat], minlength=360)
        m['occ'] = int((b / b.sum() > 0.002).sum())
        c5 = np.array([b[i:i + 5].sum() for i in range(0, 360, 5)])
        m['sector'] = float(c5.max() / b.sum() * 100)
    else:
        m['occ'], m['sector'] = 0, 0.0
    return m


def measure(full_root, torso_root, tag):
    Pf, Nf, Af = mesh_of(full_root)
    Pt, Nt, At = mesh_of(torso_root)

    head = find(torso_root, 'head')
    # 头高 = 下颌 → 头盔顶。剔除颈管（不算头）与天线（不算头盔高度，
    # Gundam 设定的 8 头身口径也是如此）。
    Ph, Nh, Ah = mesh_below(head, skip=('neck', 'ant', 'vfin'))
    hlo, hhi = Ph.reshape(-1, 3).min(0), Ph.reshape(-1, 3).max(0)
    head_h = float(hhi[1] - hlo[1])
    head_w = float(hhi[0] - hlo[0])

    ys = Pf.reshape(-1, 3)
    foot = float(ys[ys[:, 1] < 2.0][:, 1].min())
    stand = float(hhi[1] - foot)

    # 肩宽：只取肩高区间 y∈[13.5, 15.0] 的 x 跨度（排除手持武器与裙甲）
    sm = (Pf[:, :, 1].max(1) > 13.5) & (Pf[:, :, 1].min(1) < 15.0)
    sh = float(Pf[sm].reshape(-1, 3)[:, 0].max() - Pf[sm].reshape(-1, 3)[:, 0].min()) \
        if sm.any() else 0.0

    # 颈肩过渡：躯干树 y=14.6..17.0
    rows = width_profile(Pt, 14.6, 17.0, 0.05)
    worst, wy = 0.0, 0.0
    for i in range(1, len(rows)):
        a, b_ = rows[i - 1][3], rows[i][3]
        if a > 1e-6 and b_ > 1e-6:
            r = max(a / b_, b_ / a)
            if r > worst:
                worst, wy = r, rows[i][0]

    mt = band_stats(Pt, Nt, At)
    mf = band_stats(Pf, Nf, Af)
    # 颈肩区：本次 PoC 真正改动的范围（头 + 颈 + 领口 + 斜方肌）
    rsel = ((Pt[:, :, 1] > 14.6).all(axis=1) & (np.abs(Pt[:, :, 0]) < 3.2).all(axis=1))
    mn_ = band_stats(Pt[rsel], Nt[rsel], At[rsel]) if rsel.any() else None

    print('\n[%s]' % tag)
    print('  整机   三角 %5d  倒角 %5.1f%%  折面 %5.1f%%  近直角 %5.1f%%  '
          '最长直角棱 %4.2f m  顶视桶 %3d  最大扇区 %4.1f%%'
          % (len(Pf), mf['ramp'], mf['fold'], mf['right'],
             mf['longest_right'], mf['occ'], mf['sector']))
    print('  躯干   三角 %5d  倒角 %5.1f%%  折面 %5.1f%%  近直角 %5.1f%%  '
          '最长直角棱 %4.2f m  顶视桶 %3d  最大扇区 %4.1f%%'
          % (len(Pt), mt['ramp'], mt['fold'], mt['right'],
             mt['longest_right'], mt['occ'], mt['sector']))
    if mn_ is not None:
        print('  颈肩区 三角 %5d  倒角 %5.1f%%  折面 %5.1f%%  近直角 %5.1f%%  '
              '最长直角棱 %4.2f m  顶视桶 %3d  最大扇区 %4.1f%%'
              % (int(rsel.sum()), mn_['ramp'], mn_['fold'], mn_['right'],
                 mn_['longest_right'], mn_['occ'], mn_['sector']))
    print('  比例   站高 %5.2f  头 %.2f 高 × %.2f 宽  头身比 1:%-4.1f  '
          '头宽/肩宽 %4.1f%%  肩宽 %5.2f  颈肩跳变 %4.2f× @ y=%.2f'
          % (stand, head_h, head_w, stand / max(head_h, 1e-9),
             head_w / max(sh, 1e-9) * 100, sh, worst, wy))
    print('  剖面   y=14.7..17.0 (cm): %s'
          % ' '.join('%d' % round(w * 100) for y, x0, x1, w, d in rows))

    out = dict(mf=mf, mt=mt, mr=mn_, stand=stand, head_h=head_h, head_w=head_w,
               sh=sh, ratio=stand / max(head_h, 1e-9),
               hw=head_w / max(sh, 1e-9) * 100, jump=worst, jump_y=wy,
               tri_full=len(Pf), tri_torso=len(Pt), rows=rows)
    return out
