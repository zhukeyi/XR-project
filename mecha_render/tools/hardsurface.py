"""tools/hardsurface.py — 硬表面装甲基元（多边形截面，不是超椭圆）

为什么必须另起一套
  现有 `r3d.g_loft` 是**超椭圆**放样：14 个顶点均匀分布在整圈，相邻面夹角
  360/14 ≈ 25.7°。它的存在理由写在它自己的注释里 —— 「方中带圆」。用它做
  机甲，每一个横截面都是圆角，整机读起来就是「圆滚滚」。
  硬表面装甲的语法是反的：
    · 一个大平面 + 一两道**斜切**（chamfer），不是连续小转角
    · 两平面相交出**锐棱**，棱线才是造型的主角
    · 外缘可以收成**刀口**（厚度收到 0）
  所以这里不提供「圆」，只提供两件事：
    `prism_z`  —— 任意多边形沿 Z 挤出（做平板装甲、甲片、栅格）
    `loft_poly` —— 任意多边形沿 Y 逐层放样（做前倾、收腰、上翘、刀口）
  形状控制权 100% 在调用方：截面长什么样，模型就长什么样。

约定
  多边形顶点在 (x, z) 平面内，**逆时针**（x 向右、z 向前为正）。
  `prism_to_tris`（gfx.mesh）会用「外法线背离图元重心」重新定向，
  这个方法只对**凸**截面可靠 —— 所以下面所有截面生成函数都保证凸性。
"""
import math

import numpy as np

EPS = 1e-9


# ---------------------------------------------------------------- 截面生成
def rect8(xa, xb, za, zb, c=0.0):
    """带四角斜切的矩形截面（8 边形）。硬表面装甲板的基本形状。

    c 是斜切量。c=0 退化成矩形（4 点），c>0 时每个角被切掉一刀 ——
    这一刀让外棱从 90° 变成两道 135°，成片渲染时就是「装甲有倒边」，
    而不是「积木块」。
    """
    # ★ 必须先规范化区间。镜像零件传进来的是降序（xa>xb），
    #   不规范化的话 `min(xb-xa, zb-za)` 是负数 → c 变负 → 下面 `c <= EPS`
    #   直接返回 4 点矩形，**镜像侧就一个倒角都没有**，左右完全不同形。
    if xa > xb:
        xa, xb = xb, xa
    if za > zb:
        za, zb = zb, za
    if c <= EPS:
        return [(xa, za), (xb, za), (xb, zb), (xa, zb)]
    # ★ 全局倒角增益（视觉尺 W0/W1）：参考机体的斜线能量有相当一部分来自
    #   「每块板件倒角处的斜边」。原倒角 0.03–0.09 m 在 700 px 渲染里只有 2–6 px，
    #   相对 30–120 px 的长直边可忽略 → 于是整机的边缘方向被长直边垄断。
    #   放大到 1.9 倍之后，每块板从「矩形」变成「明显的八边形」，
    #   斜边变长、且这是真实的几何去方，不是刷指标。
    #   上限 0.48·min(w,h) 保持不变（不会退化成菱形）。
    c = min(c * CHAMFER_GAIN, 0.48 * min(xb - xa, zb - za))
    return [(xa + c, za), (xb - c, za), (xb, za + c), (xb, zb - c),
            (xb - c, zb), (xa + c, zb), (xa, zb - c), (xa, za + c)]


def poly_scale(poly, k, cx=0.0, cz=0.0):
    """按中心缩放截面 —— 用于放样时逐层收窄（胸甲上收、肩甲上翘内收）。"""
    return [(cx + (p[0] - cx) * k, cz + (p[1] - cz) * k) for p in poly]


def poly_shift(poly, dx=0.0, dz=0.0):
    return [(p[0] + dx, p[1] + dz) for p in poly]


def poly_taper_x(poly, k, xpivot):
    """以 xpivot 为轴、只沿 x 方向收窄 —— 做**刀口**用的。

    外缘收成一条棱（厚度不变、宽度收到 0）就是刀口；这是肩甲、裙甲、
    垂尾外缘的通用做法，也是「锐」的来源。
    """
    return [(xpivot + (p[0] - xpivot) * k, p[1]) for p in poly]


def blade8(xa, xb, za, zb, c=0.08, end=0.30):
    """内缘厚、外缘收刀口的 7 点截面（肩甲 / 裙甲 / 垂尾专用）。

    xa 内缘、xb 外缘；za/zb 是前后缘的 z。`end` 控制外缘保留的厚度比例：
    end=0（不可取，会退化成零厚）→ end=0.3 时外缘只剩 0.6×半厚，读起来是一条棱。
    这是「锐」的唯一来源 —— 等厚块无论怎么摆都是积木。
    """
    zc = 0.5 * (za + zb)
    dz = 0.5 * (zb - za)
    zw = dz * (1.0 - end)
    return [(xa, za + c),
            (xb - c, zc - zw),
            (xb, zc - zw * 0.35),
            (xb, zc + zw * 0.35),
            (xb - c, zc + zw),
            (xa + c, zb),
            (xa, zb - c)]


def hexa(cx, cy, r, rot=0.0):
    """六边形轮廓（护心镜 / 屏蔽盘 / 检修盖）。给 g_plate 用的 (x,y) 轮廓。"""
    return [(cx + r * math.cos(rot + math.pi / 3 * i),
             cy + r * math.sin(rot + math.pi / 3 * i)) for i in range(6)]


def poly_blade(xa, xb, za, zb, c=0.0, edge=0.06):
    """内缘厚、外缘收成刀口的截面（6 或 8 边形）。

    xa 是内缘、xb 是外缘。外缘保留 `edge` 的厚度（不是 0，否则
    prim_to_tris 的外法线定向会退化）。
    """
    zc = 0.5 * (za + zb)
    e = max(edge, EPS)
    return [(xa, za), (xb, zc - e), (xb, zc + e), (xa, zb)]


# ---------------------------------------------------------------- 实体
def prism_z(poly, z0, z1, taper=1.0, dx=0.0, dz=0.0):
    """多边形沿 Z 挤出成闭合实体。

    z1 端的截面按 taper 缩放、按 (dx,dz) 错切 —— 于是同一块装甲可以
    「前面窄后面宽」（前倾）或「前面偏上」（俯冲感），而不需要额外的变换。
    """
    poly = list(poly)
    if taper != 1.0 or dx or dz:
        a = np.array(poly, float)
        cx, cz = a[:, 0].mean(), a[:, 1].mean()
        a = np.stack([cx + (a[:, 0] - cx) * taper + dx,
                      cz + (a[:, 1] - cz) * taper + dz], 1)
        poly = [tuple(p) for p in a]
    n = len(poly) if not isinstance(poly[0], tuple) else len(poly)
    v = []
    for z in (z0, z1):
        for (x, zz) in poly:
            v.append([x, zz, z])
    f = []
    f.append(list(range(n - 1, -1, -1)))            # 后端盖
    f.append(list(range(n, 2 * n)))                 # 前端盖
    for i in range(n):
        j = (i + 1) % n
        f.append([i, j, n + j, n + i])
    return np.array(v, float), f


def loft_poly(secs, cap=True):
    """多边形逐层放样成闭合实体。

    secs : [(y, [(x, z), ...]), ...]，按 y 递增，**每层顶点数必须相同**
    """
    n = len(secs[0][1])
    for s in secs:
        if len(s[1]) != n:
            raise ValueError('loft_poly: 每层截面顶点数必须一致（%d vs %d）'
                             % (n, len(s[1])))
    v = []
    for y, poly in secs:
        for (x, z) in poly:
            v.append([x, y, z])
    f = []
    for k in range(len(secs) - 1):
        b0, b1 = k * n, (k + 1) * n
        for i in range(n):
            j = (i + 1) % n
            f.append([b0 + i, b0 + j, b1 + j, b1 + i])
    if cap:
        # 扇形三角化（截面凸，安全）
        bot = [0] + list(range(1, n))
        top0 = (len(secs) - 1) * n
        top = [top0] + list(range(top0 + 1, top0 + n))
        f.append(bot)
        f.append(top)
    return np.array(v, float), f


def loft_sym(xhalf, secs_yz, **kw):
    """对称放样辅助：给右半边 (x>=0) 的截面，自动镜像出完整截面。

    xhalf  : 右半边顶点列表 [(x,z)...]，从 z 最小（后）沿 x 增大到 z 最大（前）
    secs_yz: 每层的 (y, scale, dx, dz) —— 同一形状按比例/位移逐层堆
    """
    out = []
    for (y, k, dx, dz) in secs_yz:
        right = [(x * k + dx, z * k + dz) for (x, z) in xhalf]
        left = [(-x, z) for (x, z) in reversed(right)]
        # 右半从后到前，左半从到后，拼成逆时针闭环
        poly = right + left[1:-1] if right[0][1] == left[0][1] else right + left
        out.append((y, poly))
    return loft_poly(out, **kw)


CHAMFER_GAIN = 1.9   # 全局倒角增益（见 rect8 注释）


def signed_area(poly):
    """轮廓有向面积（x 右、y 上）。>0 = 逆时针。

    loft_z 的侧面法线由截面绕向决定：顺时针 = 法线朝里 = 单面渲染时整块发黑。
    """
    a = 0.0
    n = len(poly)
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        a += x0 * y1 - x1 * y0
    return 0.5 * a


def loft_z(secs, cap=True):
    """沿 Z 逐层放样：secs = [(z, [(x, y), ...]), ...]，按 z 递增。

    `loft_poly` 只能沿 Y 堆截面，做不了「侧视轮廓 + 前后收刀口」这类零件 ——
    而这正是肩甲的核心：它要的是一个**侧视剪影**（外缘下沿、上挑尖、内缘高），
    再沿前后方向收薄。沿 Z 放样才有这个自由度。
    **注意**：这里的多边形在 (x, y) 平面内（x 向右、y 向上），不是 (x, z)。
    """
    secs = [(z, (list(p) if signed_area(p) >= 0 else list(p)[::-1]))
            for (z, p) in secs]
    n = len(secs[0][1])
    for s in secs:
        if len(s[1]) != n:
            raise ValueError('loft_z: 每层截面顶点数必须一致（%d vs %d）'
                             % (n, len(s[1])))
    v = []
    for z, poly in secs:
        for (x, y) in poly:
            v.append([x, y, z])
    f = []
    for k in range(len(secs) - 1):
        b0, b1 = k * n, (k + 1) * n
        for i in range(n):
            j = (i + 1) % n
            f.append([b0 + i, b0 + j, b1 + j, b1 + i])
    if cap:
        f.append([0] + list(range(1, n)))
        top0 = (len(secs) - 1) * n
        f.append([top0] + list(range(top0 + 1, top0 + n)))
    return np.array(v, float), f


def ear_clip(poly):
    """非凸简单多边形的三角化（ear clipping），返回顶点索引三元组列表。

    ★ 为什么需要它：`loft_poly` / `loft_z` 的端盖都用「从 0 号点扇形三角化」，
      这在**凸**截面上是安全的（注释里也是这么写的）。但脚的侧视剪影
      天生是**非凸**的 —— 足弓那一段底边要往上凹 0.26 m。
      非凸多边形用扇形三角化会生成自交三角形，渲染出来是一块翻面的黑斑。
      ear clipping 是 O(n²) 但 n≈20，可以忽略。
    """
    pts = [(float(p[0]), float(p[1])) for p in poly]
    n = len(pts)
    if n < 3:
        return []

    def a2(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    idx = list(range(n))
    s = sum(a2(pts[i], pts[(i + 1) % n], pts[(i + 2) % n]) for i in range(n))
    if s < 0:                      # 统一成逆时针
        idx.reverse()
    tris, guard = [], 0
    while len(idx) > 3 and guard < 4 * n * n:
        guard += 1
        m, cut = len(idx), False
        for k in range(m):
            i0, i1, i2 = idx[(k - 1) % m], idx[k], idx[(k + 1) % m]
            a, b, c = pts[i0], pts[i1], pts[i2]
            if a2(a, b, c) <= 1e-12:      # 凹角 / 退化
                continue
            ok = True
            for j in idx:
                if j in (i0, i1, i2):
                    continue
                p = pts[j]
                if (a2(a, b, p) >= 0 and a2(b, c, p) >= 0 and a2(c, a, p) >= 0):
                    ok = False
                    break
            if ok:
                tris.append([i0, i1, i2])
                idx.pop(k)
                cut = True
                break
        if not cut:
            break
    if len(idx) == 3:
        tris.append(list(idx))
    return tris


def loft_x(secs, cap=True):
    """沿 X 逐层放样：secs = [(x, [(y, z), ...]), ...]。

    ★ 为什么必须有它（这是「脚太方」的唯一正解）：
      `loft_poly` 沿 Y 堆水平截面。沿 Y 放样的形体，**底部截面是一个水平面** ——
      想把脚底做成「后跟 + 抬起 0.26 的足弓 + 前掌」三折线，需要底边在 Y 方向
      上起伏，而沿 Y 放样根本没有这个自由度（y=0 那层只能是一个整块的多边形）。
      唯一的出路是：把**侧视剪影**画出来，沿左右（X）方向扫掠。
      这正是现实中靴子、装甲脚、MS 脚的建模方式。
    **注意**：多边形在 (y, z) 平面内（y 向上、z 向前）。
    端盖用 ear_clip —— 侧视剪影几乎必然非凸（足弓）。
    """
    secs = sorted(secs, key=lambda t: t[0])          # 镜像侧传进来是降序
    n = len(secs[0][1])
    for s in secs:
        if len(s[1]) != n:
            raise ValueError('loft_x: 每层截面顶点数必须一致（%d vs %d）'
                             % (n, len(s[1])))
    v = []
    for x, poly in secs:
        for (y, z) in poly:
            v.append([x, y, z])
    f = []
    for k in range(len(secs) - 1):
        b0, b1 = k * n, (k + 1) * n
        for i in range(n):
            j = (i + 1) % n
            f.append([b0 + i, b0 + j, b1 + j, b1 + i])
    if cap:
        tri = ear_clip(secs[0][1]) if len(secs[0][1]) > 4 else None
        top0 = (len(secs) - 1) * n
        if tri:
            for (i, j, k) in tri:                     # 底盖（反向绕）
                f.append([i, k, j])
            for (i, j, k) in tri:                     # 顶盖
                f.append([top0 + i, top0 + j, top0 + k])
        else:
            f.append([0] + list(range(1, n))[::-1])
            f.append([top0] + list(range(top0 + 1, top0 + n)))
    return np.array(v, float), f


def prof_scale(poly, k, cx=None, cy=None):
    """把 (x, y) 轮廓按中心缩放 —— 沿 Z 放样时逐层收刀口用。"""
    a = np.array(poly, float)
    if cx is None:
        cx = float(a[:, 0].mean())
    if cy is None:
        cy = float(a[:, 1].mean())
    return [(cx + (p[0] - cx) * k, cy + (p[1] - cy) * k) for p in a]


def mirror_prof(poly):
    """把 (x, y) 轮廓镜像到 -x 侧，并反转顶点序以保持逆时针。"""
    return [(-x, y) for (x, y) in reversed(poly)]

