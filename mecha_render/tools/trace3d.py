"""tools/trace3d.py — 把一张线稿反推成真正的 3D 网格（不丢细节）

核心思路（也是唯一能同时满足「不丢细节」和「可视频化」的做法）：
  线稿里每一个**封闭白区**就是一块装甲板。把它的轮廓取成多边形、按厚度场挤出成
  实体，缝隙（原来的墨线）自然变成板与板之间的沟槽 —— 所以正面剪影和每一条分割线
  都被原样保留，而它确实是一个能旋转、能打光、能出视频的网格。

  厚度场：用「到剪影外缘的距离」做枕头式充气（内部厚、边缘薄），这样侧视不会是
  一张纸片，而是有体积的轮廓。

依赖：只有 numpy + PIL（本机没有 scipy / cv2），所以下面自己实现了
  ① 行游程 + 并查集的连通域  ② Moore 邻域边界追踪  ③ Douglas-Peucker 简化

用法：
  python3 tools/trace3d.py --stats          # 只统计区域，不建网格
"""
import json
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(HERE, 'out', 'seed_sketch',
                   '把输入的黑色剪影当作结构控制图_重绘成一张原创_SEED_系_2026-11-07T07-57-29.png')


# ------------------------------------------------------------------ 掩码
def load_masks(path=SRC, ink_thr=110):
    g = np.asarray(Image.open(path).convert('L'), np.uint8)
    ink = g < ink_thr
    white = ~ink
    # 从画布四边向内泛洪，把「外面的白」标出来；剩下的白就是封闭内区
    out = np.zeros_like(white, bool)
    out[0, :] = white[0, :]; out[-1, :] = white[-1, :]
    out[:, 0] |= white[:, 0]; out[:, -1] |= white[:, -1]
    while True:
        grew = out.copy()
        grew[1:, :] |= out[:-1, :]; grew[:-1, :] |= out[1:, :]
        grew[:, 1:] |= out[:, :-1]; grew[:, :-1] |= out[:, 1:]
        grew &= white
        if grew.sum() == out.sum():
            break
        out = grew
    inner = white & ~out
    figure = ink | inner
    return ink, inner, figure


def cc_label(mask):
    """连通域：逐行取游程 → 相邻行游程相叠就并到同一类。返回 (labels, n)。"""
    H, W = mask.shape
    parent = []

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    runs_prev, runs_cur = [], []
    all_runs = []
    for y in range(H):
        row = mask[y]
        if not row.any():
            runs_prev, runs_cur = [], []
            all_runs.append([])
            continue
        d = np.diff(np.concatenate(([0], row.view(np.int8), [0])))
        starts = np.nonzero(d == 1)[0]
        ends = np.nonzero(d == -1)[0] - 1
        runs_cur = []
        for s, e in zip(starts, ends):
            idx = len(parent); parent.append(idx)
            runs_cur.append((int(s), int(e), idx))
        for cs, ce, ci in runs_cur:
            for ps, pe, pi in runs_prev:
                if cs <= pe and ps <= ce:
                    union(ci, pi)
        all_runs.append(runs_cur)
        runs_prev = runs_cur
    labels = np.full(mask.shape, -1, np.int32)
    roots = {}
    for runs in all_runs:
        for s, e, idx in runs:
            r = find(idx)
            if r not in roots:
                roots[r] = len(roots)
            labels[s:e + 1] = roots[r] if False else labels[s:e + 1]
    # 上面那行只为了保持行结构；真正的写入在下面一次性做完
    labels[:] = -1
    for y, runs in enumerate(all_runs):
        for s, e, idx in runs:
            labels[y, s:e + 1] = roots[find(idx)]
    return labels, len(roots)


def stats(path=SRC):
    ink, inner, fig = load_masks(path)
    ys = np.nonzero(fig.any(1))[0]; xs = np.nonzero(fig.any(0))[0]
    print(f'画布 {fig.shape[1]}x{fig.shape[0]}  墨 {ink.mean()*100:.1f}%  '
          f'封闭内区 {inner.mean()*100:.1f}%  剪影 {fig.mean()*100:.1f}%')
    print(f'剪影 bbox  x[{xs.min()},{xs.max()}] y[{ys.min()},{ys.max()}]  '
          f'宽 {xs.max()-xs.min()+1}  高 {ys.max()-ys.min()+1}')
    lab, n = cc_label(inner)
    areas = np.bincount(lab[lab >= 0])
    print(f'封闭区域数 {n}   面积中位 {np.median(areas):.0f} px  '
          f'最大 {areas.max()}  最小 {areas.min()}')
    big = (areas > 200).sum()
    print(f'其中 >200 px 的板件 {big} 块（其余是通风口/刻线这类小件）')


if __name__ == '__main__':
    if '--stats' in sys.argv:
        stats()


# ------------------------------------------------------------------ 轮廓
DIRS = [(-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1)]


def trace_contour(m):
    """Moore 邻域边界追踪。m 是单个区域的 bool 掩码（已裁到 bbox）。

    为什么不用「逐行取左右边界」那种简化写法：那种只对**行凸**的形状成立，
    L 形/环形装甲板会直接画错。线稿里的板件有一堆 L 形与凹口。
    """
    H, W = m.shape
    if not m.any():
        return []
    y0 = int(np.argmax(m.any(axis=1)))
    x0 = int(np.argmax(m[y0]))
    start = (x0, y0)
    cur = start
    back = (x0 - 1, y0)          # 起点西侧必定是背景
    pts = [start]
    for _ in range(4 * H * W):
        bx, by = back[0] - cur[0], back[1] - cur[1]
        k = DIRS.index((bx, by)) if (bx, by) in DIRS else 0
        nxt = None
        for i in range(1, 9):
            dx, dy = DIRS[(k + i) % 8]
            nx, ny = cur[0] + dx, cur[1] + dy
            if 0 <= nx < W and 0 <= ny < H and m[ny, nx]:
                nxt = (nx, ny)
                back = (cur[0] + DIRS[(k + i - 1) % 8][0],
                        cur[1] + DIRS[(k + i - 1) % 8][1])
                break
        if nxt is None:
            break
        if nxt == start and len(pts) > 2:
            break
        pts.append(nxt)
        cur = nxt
    return pts


def dp_simplify(pts, tol):
    """Douglas-Peucker：把上千个像素级边界点压到几十个，保留所有转角。"""
    if len(pts) < 3:
        return pts
    P = np.asarray(pts, float)
    keep = np.zeros(len(P), bool)
    keep[0] = keep[-1] = True
    stack = [(0, len(P) - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        a, b = P[i], P[j]
        ab = b - a
        L = np.hypot(*ab)
        rel = P[i + 1:j] - a
        if L < 1e-9:
            d = np.hypot(rel[:, 0], rel[:, 1])
        else:
            # numpy 2.x 去掉了二维 cross，手写叉积
            d = np.abs(ab[0] * rel[:, 1] - ab[1] * rel[:, 0]) / L
        k = int(np.argmax(d))
        if d[k] > tol:
            m = i + 1 + k
            keep[m] = True
            stack.append((i, m)); stack.append((m, j))
    return [tuple(p) for p in P[keep]]


def clean_poly(pts):
    """去掉相邻重复点与共线点。Moore 追踪在细结构上会回折，产生零长度边，
    直接送进耳切会因「退化耳」判定失败（实测 66/243 块卡在这里）。"""
    out = []
    for p in pts:
        if not out or (abs(p[0] - out[-1][0]) > 1e-9 or abs(p[1] - out[-1][1]) > 1e-9):
            out.append(p)
    if len(out) > 2 and out[0] == out[-1]:
        out.pop()
    if len(out) < 3:
        return out
    res = []
    n = len(out)
    for i in range(n):
        a, b, c = out[i - 1], out[i], out[(i + 1) % n]
        cr = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        if abs(cr) > 1e-9:
            res.append(b)
    return res if len(res) >= 3 else out


def fan_tri(poly):
    """兜底三角化：以重心为中心扇形切。对凹多边形不是最优，但一定出得结果，
    好过整块板直接消失（线稿里少一块板就是「改了细节」）。"""
    cen = _centroid(poly) if '_centroid' in globals() else np.mean(np.asarray(poly, float), 0)
    idx = list(range(len(poly)))
    if poly_area(poly) < 0:
        idx.reverse()
    return [(idx[i], idx[(i + 1) % len(idx)]) for i in range(len(idx))]


def poly_area(poly):
    p = np.asarray(poly, float)
    return 0.5 * float(np.sum(p[:, 0] * np.roll(p[:, 1], -1) -
                             np.roll(p[:, 0], -1) * p[:, 1]))


def ear_clip(poly):
    """耳切三角化。返回**顶点下标**三元组列表；自交或病态多边形返回 None。

    ★ 这里出过一次严重 bug：早期版本把 idx.reverse() 之后仍用顶点下标去索引
    重排后的点表 P，只有「多边形本来就是逆时针」（idx 恰好等于 range(n)）时才碰巧
    正确 —— 于是面积符号为负的那一半板件被乱切，三角盖不满，渲染出来一半板面缺失。
    正确做法：P 用**位置**索引（pos），返回时再映射回 poly 的顶点下标。
    """
    n = len(poly)
    if n < 3:
        return None
    order = list(range(n))
    if poly_area(poly) < 0:
        order.reverse()                     # 统一成逆时针
    P = [poly[i] for i in order]            # P[k] 对应顶点 order[k]
    pos = list(range(n))                    # 仍参与计算的位置下标（在 P 上）

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    def inside(p, a, b, c):
        return (cross(a, b, p) >= 0 and cross(b, c, p) >= 0 and cross(c, a, p) >= 0)

    out, guard = [], 0
    while len(pos) > 3 and guard < 6 * n * n:
        guard += 1
        clipped = False
        m = len(pos)
        for i in range(m):
            i0, i1, i2 = pos[i - 1], pos[i], pos[(i + 1) % m]
            a, b, c = P[i0], P[i1], P[i2]
            if cross(a, b, c) <= 0:
                continue
            ok = True
            for j in pos:
                if j in (i0, i1, i2):
                    continue
                if inside(P[j], a, b, c):
                    ok = False
                    break
            if ok:
                out.append((i0, i1, i2))
                pos.pop(i)
                clipped = True
                break
        if not clipped:
            break
    if len(pos) == 3:
        out.append(tuple(pos))
    if len(pos) > 3:
        return None                         # 卡住了就别交半成品，交给兜底
    return [(order[a], order[b], order[c]) for a, b, c in out]


def chamfer_dt(mask):
    """倒角距离变换（3-4 两遍），替代 scipy.ndimage.distance_transform_edt。

    用途：给每块板一个「离剪影外缘有多深」的量，决定它挤出多厚 ——
    内部厚、边缘薄，侧视才不是一张纸片。
    """
    BIG = 1e6
    d = np.where(mask, BIG, 0.0).astype(np.float64)
    H, W = d.shape
    for y in range(H):
        row = d[y]
        for x in range(1, W):
            row[x] = min(row[x], row[x - 1] + 3)
    for y in range(1, H):
        row, up = d[y], d[y - 1]
        for x in range(W):
            v = row[x]
            v = min(v, up[x] + 3)
            if x > 0:
                v = min(v, up[x - 1] + 4)
            if x < W - 1:
                v = min(v, up[x + 1] + 4)
            row[x] = v
    for y in range(H - 2, -1, -1):
        row, dn = d[y], d[y + 1]
        for x in range(W - 1, -1, -1):
            v = row[x]
            v = min(v, dn[x] + 3)
            if x > 0:
                v = min(v, dn[x - 1] + 4)
            if x < W - 1:
                v = min(v, dn[x + 1] + 4)
            row[x] = v
    for y in range(H - 1, -1, -1):
        row = d[y]
        for x in range(W - 2, -1, -1):
            row[x] = min(row[x], row[x + 1] + 3)
    return d / 3.0


# ------------------------------------------------------------------ 建网格
# 结构分两层（这是做过一次返工才定下来的）：
#
#   ① 机身实体 body  —— 整个剪影按行游程挤出的实心块，前表面在 z=Z_BODY、后表面
#      在 Z_BACK。它负责「有体积、侧视不是纸片、转角时剪影会变」。
#   ② 装甲板 plate   —— 每个封闭白区抬到 z=Z_FRONT，厚 GAP。它负责「正面与线稿
#      逐像素一致」。
#
# 于是板与板之间那道 2~3 px 的缝，看到的是机身实体**前表面**（极深色 M_SEAM），
# 读起来就是原来那条墨线 —— 而不是靠「背板托底」去挡白。
#
# 早一版把每块板按「到剪影外缘的距离」挤出 0.05~0.55×图宽，实测厚度顶到机高的
# 28.5%：那不是浮雕，是一排深浅不一的柱子，一转角就露馅。前平面统一才成立。
from gfx.mesh import Mesh                      # noqa: E402
from r3d import Mat                            # noqa: E402

M_CAP = Mat((0.905, 0.898, 0.880), spec=0.80, rim=0.35)   # 板面
M_EDGE = Mat((0.420, 0.440, 0.480), spec=0.60, rim=0.30)  # 板侧壁（转角才看得到）
M_SEAM = Mat((0.075, 0.085, 0.105), spec=0.15, rim=0.10)  # 板缝 = 墨线
# 机身侧面/背面。★ 不能压到 0.16：±30° 时它要占 27% 像素，暗下去整台机像描了黑边。
# 它是「背光侧」而不是「缝隙」，靠受光差异读体积，所以给中灰。
M_WAL = Mat((0.320, 0.335, 0.365), spec=0.35, rim=0.25)

SCALE = 0.02          # 1 px → 0.02 世界单位（机高 1437 px → 28.74）
DP_TOL = 1.6          # 多边形简化容差（px）
MIN_AREA = 10         # 小于这个面积的区域当噪点丢掉

# 深度预算：按机高比例给，换分辨率也不用改数字。
#   总厚 = DP_GAP + DP_BACK（DP_FRONT 只是把板面摆在 z=0 上方，不计入厚度）
#   前平面 7.5% / 板厚 3.2% / 机身再往后 10.5%  ⇒ 总厚 13.7%
#   13.7% 是按人体「前后厚/身高 ≈ 0.13~0.15」取的：再薄，转 30° 就像一块纸板。
DP_FRONT = 0.075
DP_GAP = 0.032
DP_BACK = 0.105


def _centroid(poly):
    p = np.asarray(poly, float)
    a = poly_area(poly)
    if abs(a) < 1e-9:
        return p.mean(0)
    x = np.sum((p[:, 0] + np.roll(p[:, 0], -1)) *
               (p[:, 0] * np.roll(p[:, 1], -1) - np.roll(p[:, 0], -1) * p[:, 1]))
    y = np.sum((p[:, 1] + np.roll(p[:, 1], -1)) *
               (p[:, 0] * np.roll(p[:, 1], -1) - np.roll(p[:, 0], -1) * p[:, 1]))
    return np.array([x, y]) / (6 * a)


_UV0 = np.zeros((3, 2), np.float32)


def _add_tri(mesh, p3, mat, ref):
    """写入一个三角形，并**显式给逐顶点法线**。

    为什么必须在这里算：gfx.gbuffer.rasterize 要的是 (Tn,3,3) 逐顶点法线，
    而 Mesh.add 传 normals=None 只会存成 (Tn,) 的 None 数组，光栅化直接 reshape 报错。
    又因为背面剔除是「面法线与顶点法线对齐后再与视线比较」，法线方向决定生死，
    所以这里用 ref（该板件的中轴点）做定向基准：法线必须背离中轴外侧。

    ref 取「板件中轴在中等厚度处的一点」，对三种面都成立：
      正面盖（z=zf，最高）  → 法线主要 +Z
      倒角环（z 0.72d~d）   → 法线 +Z 带外倾
      侧壁（z -0.3d~0.72d） → 质心接近中轴高度，法线以外倾为主
    """
    p = np.asarray(p3, np.float64)
    n = np.cross(p[1] - p[0], p[2] - p[0])
    L = np.linalg.norm(n)
    if L < 1e-9:
        return False                     # 退化三角直接丢，别污染 z-buffer
    n = n / L
    if float(n @ (p.mean(axis=0) - ref)) < 0.0:
        n = -n
    mesh.add(p, np.repeat(n[None, :], 3, axis=0), _UV0, mat)
    return True


def _ring(outer, inner, z0, z1, flip=False):
    """外圈到内圈、z0→z1 的一圈四边形（倒角环）。"""
    out = []
    n = len(outer)
    for i in range(n):
        j = (i + 1) % n
        a, b = outer[i], outer[j]
        c, d = inner[j], inner[i]
        t = [(a[0], a[1], z0), (b[0], b[1], z0), (c[0], c[1], z1)]
        u = [(a[0], a[1], z0), (c[0], c[1], z1), (d[0], d[1], z1)]
        out.extend([t, u] if not flip else [t[::-1], u[::-1]])
    return out


def strip_rects(mask):
    """逐行游程 → 矩形，并把相邻行**完全相同**的游程合并。

    返回 [(x0, x1, y0, y1)]，含端点。合并把 1437 行压到几百个矩形，
    是机身实体能低三角数铺满复杂剪影的关键（否则光正面就要上万三角）。
    """
    H = mask.shape[0]
    rows = []
    for y in range(H):
        row = mask[y]
        if not row.any():
            rows.append([])
            continue
        d = np.diff(np.concatenate(([0], row.view(np.int8), [0])))
        s = np.nonzero(d == 1)[0].tolist()
        e = (np.nonzero(d == -1)[0] - 1).tolist()
        rows.append(list(zip(s, e)))
    rects, opened = [], {}
    for y in range(H):
        cur = set(rows[y])
        for k in list(opened.keys()):
            if k not in cur:
                rects.append((k[0], k[1], opened.pop(k), y - 1))
        for k in cur:
            opened.setdefault(k, y)
    for k, y0 in opened.items():
        rects.append((k[0], k[1], y0, H - 1))
    return rects


def build_ink(mesh, ink, bot, cx, scale, z, verbose=False):
    """把原稿墨线本身铺成一层极薄的面片，压在板面之上（z 略高于 zf）。

    为什么必须有这一层 —— 这是「一条细节都不许丢」的唯一可靠做法：
      白区是**连通域**。一条「一端断在板面内部」的线并不把白区分开，两侧仍属同一
      块板。要在一块多边形里表示这种线，多边形必须沿着线的一侧下去再原路返回，
      也就是一条**零宽缝**。任何简化（DP 容差 1.6→0.4 都试过）都会先把这条缝合上，
      于是线被板面盖掉：实测腿内侧那根 1 px 竖线整段消失，成片丢失占墨线 7.6%，
      而且降容差只能从 8.9% 勉强救到 7.6%，代价是多 70% 三角。
      改成「墨线单独成层、按逐行游程精确铺满」之后，每个墨线像素都有对应几何，
      与多边形怎么简化再无关系。
    """
    rects = strip_rects(ink)
    ref = np.array([0.0, 0.0, z - 1.0])
    for (x0, x1, y0, y1) in rects:
        X0, X1 = (x0 - cx) * scale, (x1 + 1 - cx) * scale
        Y0, Y1 = (bot - y1 - 1) * scale, (bot - y0) * scale
        _add_tri(mesh, [(X0, Y0, z), (X1, Y0, z), (X1, Y1, z)], M_SEAM, ref)
        _add_tri(mesh, [(X0, Y0, z), (X1, Y1, z), (X0, Y1, z)], M_SEAM, ref)
    if verbose:
        print(f'墨线层 {len(rects)} 个矩形')
    return len(rects)


def build_body(mesh, fig, bot, cx, scale, zf, zb, verbose=False):
    """机身实体：把整个剪影按矩形挤成实心块（6 面都出）。

    zf = 前表面（板缝露出来的那一面，极深色）、zb = 后表面。
    侧面保留 1 px 的阶梯：这是「剪影逐像素挤出」的必然形状，也是它和线稿
    一模一样的原因；转角时能看到真实的侧壁厚度。
    """
    rects = strip_rects(fig)
    zc = 0.5 * (zf + zb)
    # 定向基准必须放在要被判定的那面**背后**：_add_tri 的规则是「法线背离 ref」。
    # 早一版把 front_ref 放在前面（zf+1），结果正面法线被判成 -Z，整块机身正面
    # 被背面剔除掉，板缝位置露出来的是机身内部的侧面 —— 实测板缝材质像素 0%。
    front_ref = np.array([0.0, 0.0, zf - 1.0])
    back_ref = np.array([0.0, 0.0, zb + 1.0])
    for (x0, x1, y0, y1) in rects:
        X0, X1 = (x0 - cx) * scale, (x1 + 1 - cx) * scale
        Y0, Y1 = (bot - y1 - 1) * scale, (bot - y0) * scale   # Y0 下、Y1 上
        mid = np.array([0.5 * (X0 + X1), 0.5 * (Y0 + Y1), zc])
        # 前 / 后
        f = [(X0, Y0, zf), (X1, Y0, zf), (X1, Y1, zf), (X0, Y1, zf)]
        b = [(X0, Y0, zb), (X1, Y0, zb), (X1, Y1, zb), (X0, Y1, zb)]
        _add_tri(mesh, [f[0], f[1], f[2]], M_SEAM, front_ref)
        _add_tri(mesh, [f[0], f[2], f[3]], M_SEAM, front_ref)
        _add_tri(mesh, [b[0], b[1], b[2]], M_WAL, back_ref)
        _add_tri(mesh, [b[0], b[2], b[3]], M_WAL, back_ref)
        # 四个侧面（法线背离矩形中轴）
        for a, c in (((X0, Y0), (X0, Y1)), ((X1, Y0), (X1, Y1)),
                     ((X0, Y0), (X1, Y0)), ((X0, Y1), (X1, Y1))):
            q = [(a[0], a[1], zf), (c[0], c[1], zf),
                 (c[0], c[1], zb), (a[0], a[1], zb)]
            _add_tri(mesh, [q[0], q[1], q[2]], M_WAL, mid)
            _add_tri(mesh, [q[0], q[2], q[3]], M_WAL, mid)
    if verbose:
        print(f'机身实体 {len(rects)} 个矩形')
    return len(rects)


def build(path=SRC, scale=SCALE, verbose=True):
    ink, inner, fig = load_masks(path)
    lab, n = cc_label(inner)
    ys, xs = np.nonzero(fig.any(1))[0], np.nonzero(fig.any(0))[0]
    top, bot, xl, xr = ys.min(), ys.max(), xs.min(), xs.max()
    cx = 0.5 * (xl + xr)
    Wfig = xr - xl + 1
    Hfig = bot - top + 1
    zf = DP_FRONT * Hfig * scale            # 板面前平面
    zb = zf - DP_GAP * Hfig * scale         # 机身实体前表面 = 板底面
    zback = zb - DP_BACK * Hfig * scale     # 机身实体后表面

    mesh = Mesh()
    build_body(mesh, fig, bot, cx, scale, zb, zback, verbose)
    n_body = len(mesh)

    kept, skipped, tot_area, fan_n = 0, 0, 0, 0
    for k in range(n):
        sel = lab == k
        a = int(sel.sum())
        if a < MIN_AREA:
            skipped += 1
            continue
        yy, xx = np.nonzero(sel)
        y0, y1, x0, x1 = yy.min(), yy.max(), xx.min(), xx.max()
        sub = sel[y0:y1 + 1, x0:x1 + 1]
        pts = clean_poly(trace_contour(sub))
        if len(pts) < 3:
            skipped += 1
            continue
        pts = clean_poly(dp_simplify(pts, DP_TOL))
        if len(pts) < 3 or abs(poly_area(pts)) < MIN_AREA * 0.5:
            skipped += 1
            continue
        poly = [(px + x0, py + y0) for px, py in pts]
        tris = ear_clip(poly)
        if not tris:                          # 耳切失败：先试更细的简化
            fine = clean_poly(dp_simplify(clean_poly(trace_contour(sub)), 0.9))
            if len(fine) >= 3:
                fine = [(px + x0, py + y0) for px, py in fine]
                tris = ear_clip(fine)
                if tris:
                    poly = fine
        if not tris:                          # 还不行就用条带精确铺满（保证不漏）
            fan_n += 1
            for (rx0, rx1, ry0, ry1) in strip_rects(sel[y0:y1 + 1, x0:x1 + 1]):
                X0 = (rx0 + x0 - cx) * scale
                X1 = (rx1 + 1 + x0 - cx) * scale
                Y0 = (bot - (ry1 + y0) - 1) * scale
                Y1 = (bot - (ry0 + y0)) * scale
                _add_tri(mesh, [(X0, Y0, zf), (X1, Y0, zf), (X1, Y1, zf)],
                         M_CAP, np.array([0.0, 0.0, zb - 1.0]))
                _add_tri(mesh, [(X0, Y0, zf), (X1, Y1, zf), (X0, Y1, zf)],
                         M_CAP, np.array([0.0, 0.0, zb - 1.0]))
            kept += 1
            tot_area += a
            continue

        def W(p, z):
            return ((p[0] - cx) * scale, (bot - p[1]) * scale, z)

        cen = _centroid(poly)
        axis = np.array(W(cen, 0.5 * (zf + zb)))     # 法线定向基准（板件中轴）
        back_ref = np.array([0.0, 0.0, zb - 1.0])
        for (i, j, m) in tris:
            _add_tri(mesh, [W(poly[i], zf), W(poly[j], zf), W(poly[m], zf)],
                     M_CAP, back_ref)
        # 板侧壁：zf → zb 的一圈四边形（转角时才看得到，正对时是硬边）
        for tri in _ring(poly, poly, zb, zf):
            _add_tri(mesh, [W(p, p[2]) for p in tri], M_EDGE, axis)
        kept += 1
        tot_area += a
    if verbose:
        print(f'板件 {kept} 块（丢弃 {skipped} 块碎点，条带兜底 {fan_n} 块）  '
              f'三角 {len(mesh)}（机身 {n_body} + 板件 {len(mesh)-n_body}）  '
              f'板面覆盖 {tot_area} px = 剪影的 {tot_area/fig.sum()*100:.0f}%')
    # 墨线层压在最上面（比板面高 0.02），保证每个墨线像素都有几何
    build_ink(mesh, ink, bot, cx, scale, zf + 0.02, verbose)
    if verbose:
        print(f'总计 {len(mesh)} 三角   深度 z: 前 {zf:.2f} / 板底 {zb:.2f} / 后 {zback:.2f}')
    return mesh, dict(bot=bot, Wfig=Wfig, cy=0.5 * (top + bot) * scale,
                      H=(bot - top + 1) * scale, fig=fig, lab=lab,
                      zf=zf, zb=zb, zback=zback, cx=cx, scale=scale)



def build_backing(fig, bot, cx, scale, z_plane):
    """深色背板：铺满整个剪影，位于所有板件之后。

    为什么必须有它：板件之间不接触（那 2~3 px 的缝就是原稿的墨线）。如果不托底，
    从正面看缝里会直接漏出背景 —— 墨线就变成白线了。托一层深灰，缝才读成黑线。
    做法用「逐行游程铺条带」而不是再走一遍多边形三角化：剪影形状很复杂，
    而这块板永远被前面的装甲盖住，只要保证不露白即可。
    """
    tris = []
    H, W = fig.shape
    for y in range(H):
        row = fig[y]
        if not row.any():
            continue
        d = np.diff(np.concatenate(([0], row.view(np.int8), [0])))
        starts = np.nonzero(d == 1)[0]
        ends = np.nonzero(d == -1)[0]
        for s, e in zip(starts, ends):
            x0, x1 = float(s), float(e)
            p = [((x0 - cx) * scale, (bot - y) * scale),
                 ((x1 - cx) * scale, (bot - y) * scale),
                 ((x1 - cx) * scale, (bot - y - 1) * scale),
                 ((x0 - cx) * scale, (bot - y - 1) * scale)]
            q = [(a, b, z_plane) for a, b in p]
            tris.append([q[0], q[1], q[2]])
            tris.append([q[0], q[2], q[3]])
    return tris
