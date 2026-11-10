"""tools/struct_ruler.py — 「结构 vs 萝卜」的尺子：截面积 / 周长 / 等周比 / 件数

为什么必须有这一把，而前面所有尺子都不行
  ---------------------------------------------------------------
  ★ 径向包络 R(y,θ) 是一个 **max 投影算子**：
        R(y,θ) = max{ r : 该方向有料 }
    它对「r 以内怎么分布」完全免疫。**一根实心萝卜与一个镂空笼子，
    只要有同样的外壳，R 逐格相等。** 也就是说：

        结构住在 R 的核（kernel）里，而不在 R 的像（image）里。

    所以「把包络对齐」这条路，在数学上**不可能**修好「萝卜」这个问题。
    无论我把 46 段折线拟合到多准，R 都看不见内部 —— 这不是精度问题，
    是算子丢掉了那一维。刻画维度不够，缺的正是「半径 r 这一维的内部」。

  ---------------------------------------------------------------
  这把尺子补的就是那一维。它每个高度带切一刀，在截面上量四个数：

  1. A_solid  截面上**实心**的面积（m²）—— 射线奇偶填充计数
  2. P        截面的**周长**（m）—— 每个三角与平面的交段长度之和（精确）
  3. φ = A_solid / A_hull     **填充率**。萝卜 φ→0.9+；笼子 φ→0.2–0.4
  4. σ = P / (2√(π·A_solid))  **等周比**（无量纲）。
       等面积圆的周长 → σ=1。萝卜（近似凸）σ≈1.0–1.4；
       四片独立甲片围一圈：面积小、周长长，σ→3–6。
       ★ 这一条是「比表面」的严格版本，只跟**形状**有关，与机高、缩放、
         网格密度都无关 —— 这是它比 A 或 P 单独用更可靠的原因。
  5. k        该高度上**互不相连的实体岛数**（4 连通）。
       萝卜 k=1；「前/外/内/后四片 + 骨架」k≥3。
  6. n̄        沿 12 个方位从竖轴往外打，平均**穿越几层**材料。
       实心 1 层；带缝的三层叠甲 3 层；有空腔 2 层且中间有空洞。

  ---------------------------------------------------------------
  每个标量都只回答一个问题，也必须说清它对什么瞎：
    A/P/φ/σ/k/n 全部对**表面起伏**瞎（那是 curve_ruler 的活），
    对「这件甲是不是同一块料」瞎（那是件数/连通分量的活，我们靠命名）。
    R 对内部瞎；σ 对包络瞎。**两把一起用，才能同时管住壳和内。**

  实现上踩过的坑（都写在这里，免得下一轮重犯）
    · 平面恰好穿过顶点会让奇偶填充漏填 → 每带取样高度加一个 0.0137 的错位
      （0.137% 机高，不是整格，保证每次都错开）。
    · 行扫描用「段跨过该行」判据，半开区间 [min,max)，否则顶点处的段被数两次
      → 奇偶翻转错误、整条带反向填色。
    · 参考模型要先剔除浮游炮/翼/盾/枪（UT.REMOVE），否则 40–70% 高度带量到的
      是翼盒而不是躯干。
    · 归一化用**全机**高度（RV.normalize 到 H=10），不用件自己的高度。

用法
  python3 tools/struct_ruler.py              # 参考 vs 我们，出表 + 图 + JSON
  python3 tools/struct_ruler.py --only ours  # 只量我们
"""
import json
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'tools'))

import refview as RV                                       # noqa: E402
import s2_graybox as S                                     # noqa: E402
import unicorn_trunk as UT                                 # noqa: E402

OUT = os.path.join(HERE, 'out', 'ref')
FONT = '/System/Library/Fonts/Hiragino Sans GB.ttc'
NB = 40                    # 高度带数（2.5% 机高/带）
GRID = 220                 # 截面栅格边长
JIT = 0.0137               # 取样高度错位（%H），避开顶点
H_M = 7.930                # 我们模型的真实机高（米）


# ---------------------------------------------------------------- 数据
def ref_soup():
    V, tris, gf, sets = UT.load_obj_grouped(UT.SRC)
    Vn, _ = RV.normalize(V)
    keep = np.ones(len(tris), bool)
    for tok in UT.REMOVE:
        keep &= ~UT.face_in(gf, sets, tok)
    return Vn[tris[keep]]


def ours_soup():
    S.CLEAN = True
    _root, mesh = S.build()
    P = np.array(mesh.P, np.float32).reshape(-1, 3) * (10.0 / H_M)
    return P


# ---------------------------------------------------------------- 截面
def slice_segs(F, y):
    """三角形与平面 y=const 的交段。返回 (m,4) 的 [x0,z0,x1,z1]。

    ★ 第一版这里写错过：拿「跨过平面的那条边的另一个顶点」当第二端点，
      于是每条交段被拉到一个真实顶点上 —— 周长虚高 10 倍（参考 114 m / 3.6 m²），
      等周比直接报废成 17。正确做法：**三条边各求一次交点，再按 (0,1)(1,2)(2,0)
      配对**，一个三角恰好贡献 2 个交点组成的 1 段。
    """
    d = F[:, :, 1] - y
    E = ((0, 1), (1, 2), (2, 0))
    pt = []
    for i, j in E:
        di, dj = d[:, i], d[:, j]
        m = (((di > 1e-12) & (dj < -1e-12)) |
             ((di < -1e-12) & (dj > 1e-12)))
        den = np.where(m, di - dj, 1.0)
        t = np.where(m, di / den, 0.0)
        a = F[:, i, :]
        b = F[:, j, :]
        pt.append((m, a + (b - a) * t[:, None]))
    out = []
    for k1, k2 in ((0, 1), (1, 2), (2, 0)):
        m = pt[k1][0] & pt[k2][0]
        if m.any():
            p1, p2 = pt[k1][1][m], pt[k2][1][m]
            out.append(np.stack([p1[:, 0], p1[:, 2], p2[:, 0], p2[:, 2]], 1))
    if not out:
        return np.zeros((0, 4))
    return np.concatenate(out, 0)


def scan_fill(segs, lo, hi, n=GRID):
    """奇偶行扫描填充。返回 (mask, xs, zs, cell)。

    lo/hi 是整个机体在该带的 (xmin,zmin)/(xmax,zmax)，留 4% 边。
    """
    x0, z0 = lo
    x1, z1 = hi
    ex, ez = 0.04 * (x1 - x0) + 1e-3, 0.04 * (z1 - z0) + 1e-3
    x0, x1 = x0 - ex, x1 + ex
    z0, z1 = z0 - ez, z1 + ez
    dx, dz = (x1 - x0) / n, (z1 - z0) / n
    mask = np.zeros((n, n), bool)
    sx0, sz0, sx1, sz1 = segs[:, 0], segs[:, 1], segs[:, 2], segs[:, 3]
    zmin = np.minimum(sz0, sz1)
    zmax = np.maximum(sz0, sz1)
    for r in range(n):
        zc = z0 + (r + 0.5) * dz
        m = (zc >= zmin) & (zc < zmax)
        if not m.any():
            continue
        t = (zc - sz0[m]) / (sz1[m] - sz0[m])
        xs = np.sort(sx0[m] + (sx1[m] - sx0[m]) * t)
        i0 = np.floor((xs - x0) / dx).astype(np.int32)
        for k in range(0, len(i0) - 1, 2):               # 逐对填 [x_i, x_i+1)
            a, b = max(i0[k], 0), min(i0[k + 1], n)
            if b > a:
                mask[r, a:b] = True
    return mask, x0, z0, dx, dz


def hull_area(pts):
    """单调链凸包面积。pts (m,2)。"""
    P = np.unique(pts, axis=0)
    if len(P) < 3:
        return 0.0
    P = P[np.lexsort((P[:, 1], P[:, 0]))]

    def half(Ps):
        out = []
        for p in Ps:
            while len(out) >= 2 and ((out[-1][0] - out[-2][0]) * (p[1] - out[-2][1])
                                     - (out[-1][1] - out[-2][1]) * (p[0] - out[-2][0])) <= 0:
                out.pop()
            out.append(p)
        return out
    h = half(P)[:-1] + half(P[::-1])[:-1]
    if len(h) < 3:
        return 0.0
    a = 0.0
    for i in range(len(h)):
        j = (i + 1) % len(h)
        a += h[i][0] * h[j][1] - h[j][0] * h[i][1]
    return abs(a) * 0.5


def islands(mask, amin_cells=12):
    """4 连通的实体岛。返回 (labels, areas)。0 = 背景，k = 第 k 个岛。

    ★ 第一版把「面积」与「件数」分开报，于是 k 被几十条 4 mm 的分缝/螺栓撑到 55
      —— 那不是「55 个件」，是「一个件上挂了 54 条毛刺」。件数必须**按面积过滤**，
      阈值 12 格 ≈ 0.004 m²（≈ 6 cm 见方），低于这个的读不出是件。
    """
    n = mask.shape[0]
    lab = np.zeros(mask.shape, np.int32)
    areas = [0]
    for r0 in range(n):
        for c0 in range(n):
            if not mask[r0, c0] or lab[r0, c0]:
                continue
            idx = len(areas)
            st = [(r0, c0)]
            lab[r0, c0] = idx
            cnt = 0
            while st:
                r, c = st.pop()
                cnt += 1
                for rr, cc in ((r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)):
                    if 0 <= rr < n and 0 <= cc < n and mask[rr, cc] and not lab[rr, cc]:
                        lab[rr, cc] = idx
                        st.append((rr, cc))
            areas.append(cnt)
    # 面积过小的岛直接抹成背景（不计入件数，也不计入 φ 的分子）
    for k in range(1, len(areas)):
        if areas[k] < amin_cells:
            lab[lab == k] = 0
            areas[k] = 0
    return lab, areas


def rho_profile(mask, x0, z0, dx, dz, axis, nb=16):
    """**径向质量分布 ρ(τ)**：把该带每格实体按「离竖轴的半径」归一化后计数。

    τ = r / R_band（该带实体的最大半径）。这不是包络 —— 恰恰相反：
    包络只保留每个方位的最外一格，ρ 保留**从轴到皮之间料长在哪**。
    萝卜：ρ(τ) 在 0–0.8 近似常数（体积是实的）；
    壳：ρ 在 τ→1 处尖峰、中间接近 0。
    """
    r_ = mask.sum()
    if r_ == 0:
        return np.zeros(nb)
    rr, cc = np.nonzero(mask)
    x = x0 + (cc + 0.5) * dx - axis[0]
    z = z0 + (rr + 0.5) * dz - axis[1]
    r = np.hypot(x, z)
    R = float(r.max())
    if R <= 1e-6:
        return np.zeros(nb)
    h, _ = np.histogram(r / R, bins=nb, range=(0.0, 1.0))
    return h.astype(float) / max(h.sum(), 1)


def crossings(mask, x0, z0, dx, dz, cx=0.0, cz=0.0, nray=12):
    """从 (cx,cz) 沿 nray 个方位向外走，数「实体段的个数」并取平均。"""
    n = mask.shape[0]
    R = 0.5 * n
    cnt = 0
    tot = 0
    for a in range(nray):
        th = 2 * math.pi * a / nray
        runtime, prev, runs = 0, False, 0
        for t in np.arange(0, R, 0.5):
            xx = cx + t * math.sin(th)
            zz = cz + t * math.cos(th)
            c = int((xx - x0) / dx)
            r = int((zz - z0) / dz)
            if not (0 <= r < n and 0 <= c < n):
                break
            cur = bool(mask[r, c])
            if cur and not prev:
                runs += 1
            prev = cur
        if runs:
            cnt += runs
            tot += 1
    return cnt / max(tot, 1)


def band_stats(F, y, lo, hi, axis):
    segs = slice_segs(F, y)
    if not len(segs):
        return None
    P = float(np.sum(np.hypot(segs[:, 2] - segs[:, 0], segs[:, 3] - segs[:, 1])))
    mask, x0, z0, dx, dz = scan_fill(segs, lo, hi)
    lab, ar = islands(mask)
    A = float(sum(ar)) * dx * dz
    if A <= 1e-6:
        return None
    # ★ φ 必须**逐岛**算再按面积加权：整带一起算的话，两腿之间那一大片空隙
    #   会把 φ 从 0.6 稀释到 0.1（实测 u=0.325 我们 0.109 / 参考 0.396，
    #   而单看一条腿两边都是 0.55 左右）—— 比的是「料实不实」，不是「腿分得开不开」。
    num = den = 0.0
    k = 0
    for idx in range(1, len(ar)):
        if ar[idx] < 25:                     # 0.008 ㎡ 以下不参与 φ（读不出件）
            continue
        rr, cc = np.nonzero(lab == idx)
        if len(rr) < 3:
            continue
        pts = np.stack([x0 + (cc + 0.5) * dx, z0 + (rr + 0.5) * dz], 1)
        ah = hull_area(pts)
        if ah <= 1e-9:
            continue
        a_s = ar[idx] * dx * dz
        num += a_s * (a_s / ah)
        den += a_s
        k += 1
    phi = num / den if den > 0 else 0.0
    ends = np.concatenate([segs[:, :2], segs[:, 2:]], 0)
    Ah = hull_area(ends)
    nr = crossings(mask, x0, z0, dx, dz, axis[0], axis[1])
    return dict(A=A, P=P, A_hull=Ah,
                phi=phi,
                sigma=P / max(2.0 * math.sqrt(math.pi * A), 1e-9),
                k=k, n=nr,
                rho=rho_profile(mask, x0, z0, dx, dz, axis),
                _mask=mask, _lo=(x0, z0))


def run(P, tag):
    F = P.reshape(-1, 3, 3)
    V = P.reshape(-1, 3)
    ylo, yhi = float(V[:, 1].min()), float(V[:, 1].max())
    # 竖轴：双腿质心（与 unicorn_matrix 同口径）
    m = V[:, 1] < ylo + 0.30 * (yhi - ylo)
    axis = (float(np.median(V[m, 0])), float(np.median(V[m, 2])))
    rows = []
    for b in range(NB):
        y = ylo + (yhi - ylo) * (b + JIT * 0.01) / NB
        sl = (V[:, 1] >= y) & (V[:, 1] <= y + (yhi - ylo) / NB)
        if sl.sum() < 12:
            continue
        Q = V[sl]
        lo = (float(Q[:, 0].min()), float(Q[:, 2].min()))
        hi = (float(Q[:, 0].max()), float(Q[:, 2].max()))
        st = band_stats(F, y, lo, hi, axis)
        if st is None:
            continue
        st['u'] = (y - ylo) / (yhi - ylo)
        rows.append(st)
    print('  %s：%d 带（%d 三角）' % (tag, len(rows), len(F)))
    return rows, axis


# ---------------------------------------------------------------- 出图
def montage(Pr, Po, rows_r, rows_o, path, targets=(0.10, 0.30, 0.45, 0.62, 0.80)):
    """把两个模型在若干高度上**横切一刀**，按同一米/像素画出来。

    为什么不能只报数字：k 与 φ 都是积分的结论，读不出「料的形状」。
    剖面图能一眼看出：参考是「一圈薄片 + 中间空」，我们是「一块实心」。
    """
    PW, PH = 300, 260
    SPAN = 4.8                               # 每格横向覆盖 4.8 m（全机最宽 4.13）
    mpp = SPAN / PW
    W = 40 + PW * len(targets) + 12
    H = 96 + PH * 2 + 20
    im = Image.new('RGB', (W, H), (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.text((18, 14), '同一高度横切一刀：截面线段（等比例，灰=参考 / 蓝=我们）', font=ImageFont.truetype(FONT, 20),
           fill=(24, 24, 24))
    d.text((18, 42), '虚线 = 每格的中轴（双腿质心）。φ = 逐岛「实心/凸包」按面积加权；k = ≥0.008 m² 的独立岛数',
           font=ImageFont.truetype(FONT, 14), fill=(120, 120, 120))
    f13 = ImageFont.truetype(FONT, 13)
    for row, (P, rows, colr, tag, yy0) in enumerate(
            ((Pr, rows_r, (150, 150, 150), '参考', 96),
             (Po, rows_o, (40, 90, 200), '我们', 96 + PH + 8))):
        V = P.reshape(-1, 3)
        ylo, yhi = float(V[:, 1].min()), float(V[:, 1].max())
        F = P.reshape(-1, 3, 3)
        m = V[:, 1] < ylo + 0.30 * (yhi - ylo)
        ax, az = float(np.median(V[m, 0])), float(np.median(V[m, 2]))
        d.text((18, yy0 + 4), tag, font=ImageFont.truetype(FONT, 15), fill=colr)
        for i, u in enumerate(targets):
            y = ylo + u * (yhi - ylo)
            segs = slice_segs(F, y)
            cx0 = 40 + i * PW
            d.rectangle([cx0, yy0, cx0 + PW, yy0 + PH], outline=(228, 228, 228))
            ox, oy = cx0 + PW * 0.5, yy0 + PH * 0.5
            d.line([(ox, yy0 + 6), (ox, yy0 + PH - 6)], fill=(236, 236, 236))
            for s in segs:
                d.line([(ox + (s[0] - ax) / mpp, oy - (s[1] - az) / mpp),
                        (ox + (s[2] - ax) / mpp, oy - (s[3] - az) / mpp)],
                       fill=colr, width=1)
            hit = [r for r in rows if abs(r['u'] - u) < 1.5 / NB]
            txt = ('%d%%H' % (100 * u)) + ('   φ %.2f  k %d' % (hit[0]['phi'], hit[0]['k']) if hit else '')
            d.text((cx0 + 6, yy0 + 5), txt, font=f13, fill=(90, 90, 90))
    im.save(path)
    print('→ %s  %d × %d' % (path, W, H))


def chart(ref, ours, path):
    W, H = 1520, 940
    im = Image.new('RGB', (W, H), (255, 255, 255))
    d = ImageDraw.Draw(im)
    f22 = ImageFont.truetype(FONT, 22)
    f15 = ImageFont.truetype(FONT, 15)
    f13 = ImageFont.truetype(FONT, 13)
    d.text((26, 16), '结构尺：逐岛填充率 φ / 独立件数 k / 径向密度 ρ(τ)', font=f22, fill=(24, 24, 24))
    d.text((26 + 700, 22), '★ φ 与 k 实测失效（见 §3.4 / §3.5），此图留作失败记录',
           font=f13, fill=(190, 90, 60))
    d.text((26, 46), 'φ 与 k 回答「这层料是实心还是壳」；ρ(τ) 回答「料长在离轴多远」。'
                     '三者都看不到包络起伏 —— 那是 curve_ruler 的活。',
           font=f15, fill=(120, 120, 120))

    pads = dict(l=96, r=36, t=104, b=64)
    gw = (W - pads['l'] - pads['r'] - 60) / 2
    gh = (H - pads['t'] - pads['b'] - 56) / 2
    panels = [('填充率 φ（逐岛实心 / 凸包，面积加权）  灰=参考 蓝=我们',
               'phi', (0.0, 1.0), (60, 110, 210), 'u'),
              ('独立件数 k（≥0.008 平方米）  灰=参考 绿=我们',
               'k', (0, 45), (40, 140, 90), 'u')]
    for pi, (title, key, yr, col, axis_key) in enumerate(panels):
        cx0 = pads['l'] + (pi % 2) * (gw + 60)
        cy0 = pads['t']
        d.rectangle([cx0, cy0, cx0 + gw, cy0 + gh], outline=(215, 215, 215))
        d.text((cx0 + 8, cy0 - 26), title, font=f15, fill=(30, 30, 30))
        lo, hi = yr
        for t in range(5):
            v = lo + (hi - lo) * t / 4.0
            yy = cy0 + gh - gh * t / 4.0
            d.line([(cx0, yy), (cx0 + gw, yy)], fill=(238, 238, 238))
            d.text((cx0 - 44, yy - 8), ('%.2f' % v) if hi < 2 else '%d' % round(v),
                   font=f13, fill=(140, 140, 140))
        for u in (0.25, 0.5, 0.75):
            xx = cx0 + gw * u
            d.line([(xx, cy0), (xx, cy0 + gh)], fill=(245, 245, 245))
            d.text((xx - 12, cy0 + gh + 6), '%d%%' % (100 * u), font=f13, fill=(150, 150, 150))
        for rows, colr, wid in ((ref, (150, 150, 150), 3), (ours, col, 3)):
            pts = [(cx0 + gw * r[axis_key],
                    cy0 + gh - gh * (min(max(r[key], lo), hi) - lo) / (hi - lo))
                   for r in rows if r[key] is not None]
            if len(pts) > 1:
                d.line(pts, fill=colr, width=wid)
    # 左下图：ρ(τ) 径向密度；右下图：失效原因（看图时不必再翻正文）
    cx0 = pads['l']
    cy0 = pads['t'] + gh + 56
    d.rectangle([cx0, cy0, cx0 + gw, cy0 + gh], outline=(215, 215, 215))
    d.text((cx0 + 8, cy0 - 26), '径向密度 ρ(τ)，τ = r / 该带最大半径（面积加权全高度平均）',
           font=f15, fill=(30, 30, 30))
    def agg(rows):
        a = np.zeros(16)
        for r in rows:
            a += np.array(r['rho']) * r['A']
        return a / max(a.sum(), 1e-9)
    pr, po = agg(ref), agg(ours)
    vmax = max(pr.max(), po.max()) * 1.15
    for t in range(3):
        v = vmax * t / 2.0
        yy = cy0 + gh - gh * v / vmax
        d.line([(cx0, yy), (cx0 + gw, yy)], fill=(238, 238, 238))
        d.text((cx0 - 44, yy - 8), '%.2f' % v, font=f13, fill=(140, 140, 140))
    for rows, colr, nn in ((pr, (150, 150, 150), '参考'), (po, (200, 70, 60), '我们')):
        pts = [(cx0 + gw * (i + 0.5) / 16, cy0 + gh - gh * v / vmax) for i, v in enumerate(rows)]
        d.line(pts, fill=colr, width=3)
        for p in pts:
            d.ellipse([p[0] - 3, p[1] - 3, p[0] + 3, p[1] + 3], fill=colr)
    for u in (0.25, 0.5, 0.75):
        xx = cx0 + gw * u
        d.line([(xx, cy0), (xx, cy0 + gh)], fill=(245, 245, 245))
    d.text((cx0 + 6, cy0 + gh + 6), 'τ=0（竖轴）', font=f13, fill=(150, 150, 150))
    d.text((cx0 + gw - 90, cy0 + gh + 6), 'τ=1（外皮）', font=f13, fill=(150, 150, 150))
    d.text((cx0 + gw - 140, cy0 + 8), '灰=参考  红=我们', font=f13, fill=(160, 160, 160))
    # 右下：为什么这两项不能当判据
    bx = pads['l'] + gw + 60
    by = pads['t'] + gh + 56
    d.rectangle([bx, by, bx + gw, by + gh], outline=(232, 216, 208))
    lines = [
        ('三项截面标量的失效原因', 15, (170, 80, 50)),
        ('φ  游戏资产是闭合壳，壳内一律算实 → 0.94 / 0.92，无差异', 13, (70, 70, 70)),
        ('σ  被 4 mm 刻线与螺栓撑起（加周长不加面积）→ 我们反而更大', 13, (70, 70, 70)),
        ('k  奇偶填充在开放边上漏 → 参考单带 41 个岛，目视只 4–5 块', 13, (70, 70, 70)),
        ('ρ(τ)  被姿态污染：量到的是「肢体离轴多远」，不是「料长在哪」', 13, (70, 70, 70)),
        ('', 10, (0, 0, 0)),
        ('共同点：都是空间积分量，而「缝」是局部高频量。', 14, (170, 80, 50)),
        ('一条 4 cm 的缝在 0.5 平方米截面上只占 1% 面积 → 被积分抹平。', 13, (70, 70, 70)),
        ('→ 判定力改用渲染空间局部统计（crevice_ruler.py）', 14, (30, 90, 190)),
    ]
    yy = by + 16
    for txt, sz, col in lines:
        if txt:
            d.text((bx + 16, yy), txt, font=ImageFont.truetype(FONT, sz), fill=col)
        yy += sz + 16
    im.save(path)
    print('→ %s  %d × %d' % (path, W, H))
    print('\n  ρ(τ) 聚合（面积加权）')
    print('  τ      ' + ''.join('%6.2f' % ((i + 0.5) / 16) for i in range(16)))
    print('  参考   ' + ''.join('%6.3f' % v for v in pr))
    print('  我们   ' + ''.join('%6.3f' % v for v in po))


# ---------------------------------------------------------------- 主
def main():
    only = '--only' in sys.argv
    print('读参考…')
    Pr = ref_soup()
    ref, ax_r = run(Pr, '参考')
    print('读我们…')
    Po = ours_soup()
    ours, ax_o = run(Po, '我们')

    # ---- 控制台表
    keys = ('phi', 'sigma', 'k', 'n', 'A')
    print('\n  逐带对照（u = 高度 %H）')
    print('  %-7s' % 'u' + ''.join('%14s' % (k + '(R)') for k in keys)
          + ''.join('%12s' % (k + '(O)') for k in keys))
    for i in range(0, NB, 2):
        rr = [r for r in ref if abs(r['u'] - (i + 0.5) / NB) < 1.5 / NB]
        oo = [r for r in ours if abs(r['u'] - (i + 0.5) / NB) < 1.5 / NB]
        if not rr or not oo:
            continue
        r, o = rr[0], oo[0]
        print('  %-7.3f' % r['u']
              + ' %13.3f' % r['phi'] + ' %13.3f' % r['sigma']
              + ' %13d' % r['k'] + ' %13.2f' % r['n'] + ' %13.3f' % r['A']
              + ' %11.3f' % o['phi'] + ' %11.3f' % o['sigma']
              + ' %11d' % o['k'] + ' %11.2f' % o['n'] + ' %11.3f' % o['A'])

    def avg(rows, key, a=0.0, b=1.0):
        v = [r[key] for r in rows if a <= r['u'] < b]
        return float(np.mean(v)) if v else 0.0

    print('\n  分段均值（同一高度区间）')
    print('  段            φ(R)   φ(O)   σ(R)   σ(O)   k(R) k(O)  n(R) n(O)')
    for name, a, b in (('0–30% 腿脚', 0.00, 0.30), ('30–55% 髋腿', 0.30, 0.55),
                       ('55–75% 胸腹', 0.55, 0.75), ('75–92% 肩头', 0.75, 0.92)):
        print('  %-12s %6.3f %6.3f %6.3f %6.3f %5.1f %4.1f  %4.2f %4.2f'
              % (name, avg(ref, 'phi', a, b), avg(ours, 'phi', a, b),
                 avg(ref, 'sigma', a, b), avg(ours, 'sigma', a, b),
                 avg(ref, 'k', a, b), avg(ours, 'k', a, b),
                 avg(ref, 'n', a, b), avg(ours, 'n', a, b)))

    os.makedirs(OUT, exist_ok=True)
    chart(ref, ours, os.path.join(OUT, 'struct_ruler.png'))
    montage(Pr, Po, ref, ours, os.path.join(OUT, 'struct_slices.png'))
    for r in ref + ours:
        r.pop('_mask', None)
    with open(os.path.join(OUT, 'struct_ruler.json'), 'w') as f:
        json.dump(dict(ref=ref, ours=ours, axis_ref=ax_r, axis_ours=ax_o), f,
                  indent=1, default=lambda o: o.tolist() if hasattr(o, 'tolist') else float(o))


if __name__ == '__main__':
    main()
