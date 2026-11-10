"""tools/relief_v2.py — 路线 C v2.1：把剪影重建成**单张闭合高程曲面**

两个旧病，一句话各说清：

  ① 「就是一块板」——所有板件顶面共用一个常数前平面，深度信息熵为零。
  ② 侧面「错位」——板件是独立闭合盒（cap + skirt + cap），基底又是逐矩形
     独立盒，所有内部侧壁都留着。从侧视看，那些壁（法线 ±X）全部正对镜头，
     在画面中间叠成一条灰白竖带；板厚 0.62 时每条板边还是一堵 31px 的竖墙。

v2.1 把两者一起删掉，改成单张高程场，**没有侧壁这个概念**：

    前表面  z_front(x,y) = 体量项 + 板面项
            体量项 = KAPPA · R · (1 - (1 - D/R)^n)^(1/n)
                     D = 到剪影轮廓的 chamfer 距离，R = D 的邻域最大值
                     n>2 的超椭圆截面 ⇒ 顶面平、肩部转得急（装甲感，非有机）
            板面项 = 该像素所属零件的高差（按面积分 3 档，缝里为 0）
    后表面  z_back = -LAM · 体量项（不含板面项）

前片与后片**共用同一套顶点**（每个网格节点一个），剪影最外一圈 z 强制归零，
于是两片在边界处位置重合 → 网格自然闭合，一片侧壁都不需要。

外法线由高程场梯度解析给出（n ∝ (-∂z/∂X, -∂z/∂Y, 1)），不靠绕序判断 ——
渲染器 gbuf.rasterize 本来就是拿面法线去和插值顶点法线对齐后按法线剔除的。

墨线怎么来：墨 = 板面高差为 0 的那条缝 + 深色材质。因为板面项逐像素取值，
缝的宽度就是原稿墨线的宽度，不靠多边形拟合，也不会把线加粗。
"""
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'tools'))

import trace3d as T                                    # noqa: E402
from gfx.mesh import Mesh                              # noqa: E402

SCALE = T.SCALE            # 1 px → 0.02 世界单位

# ---------------------------------------------------------------- 形状参数
G = 2              # 高程网格步长（px）。2px 是墨线保真的下限：本图墨线中位
                   # 宽度约 6px，2px 网格给到 3 格；3px 就只剩 2 格，线会抖。
KAPPA = 0.90       # 脊线高度 = KAPPA × 局部内切半径
SUPER_N = 2.4      # 超椭圆指数：2=正圆，>2 顶面更平、肩部更急
LAM = 0.62         # 背面 / 正面深度比
R_WIN = 10         # 局部内切半径的窗口半径（px）—— 小窗口才跟得上局部宽度
R_BLUR = 10        # 内切半径的模糊半径（px）—— 抹掉 max 的 argmax 切换台阶

# 板面处理：两条路，默认走「开沟」。
#
#   GROOVE_D > 0（默认）—— 沿**墨线**开一道沟，所有板同高。
#     为什么改掉「按面积分 3 档抬高」：抬高让每块板整体处于不同高度，正面光照
#     下整块板就变成一种独立的灰调，画面是一张拼布被 —— 实测三档高差下，
#     相邻板之间差 2.7px 高度就足以让灰调分成三色，看上去「脏」。
#     而真实装甲的分块读法不是「板高低不同」，是「同一平面 + 一道缝」。
#     开沟正好等价于那道缝：板面颜色统一，只有墨线处有阴影，且沟与墨线重合，
#     不新增任何视觉元素。
#
#   GROOVE_D <= 0 —— 退回旧的分档抬高（保留以便对照）。
GROOVE_D = 0.038          # 沟深（世界单位 ≈ 1.9px）
GROOVE_BLUR = 2           # 沟壁的柔和半径（px，整数），0 会得到刀切一样的硬沟

RLEV = (0.0, 0.055, 0.100, 0.145)
LEV_EDGE = (240, 1400)     # 面积分档阈值（px²）

MIN_AREA = 10

# 法线平滑：2px 网格上直接用逐节点梯度求法线，会把每一个台阶都放大成噪点 ——
# 实测出来的画面是「表面糊一层砂铆、轮廓锯齿发光」。法线改用模糊后的高程，
# 几何本身不动（体积、板缝都还在），只是不让 2px 的量化进入光照。
ZBLUR = 2          # 体量项的模糊半径（节点）。压掉 chamfer 距离场的方块状台阶
NBLUR = 3          # 求法线用的高程模糊半径（节点）
RBLUR = 6          # 板面高差的模糊半径（px）。不模糊会沿板件轮廓长出梳齿
SNAP = 1.0         # 边界亚像素吸附强度（0=关，1=吸附到 0.5 等值面）
RIM_ON = True      # 是否发射边缘带（对照用）
RIM_T = 0.022      # 边缘半厚（世界单位≈1.1px）。取 0 会让前后片在轮廓处相切,
                   # 侧视 z-buffer 打架，画面上是一条竖直白色梳齿带（拉链）
RIM_DBL = False    # 是否发双面边缘带（对照用）。实测 True/False 渲染结果**逐字节相同**
                   #   —— 曾经以为「同位置两份只差法线的重合面会 z-fighting 出梳齿」，
                   #   消融否掉了：md5 一致。默认 False 只为省 3484 个三角。

_ZUV = np.zeros((3, 2), np.float32)


def _blur1(a, r, axis):
    if r < 1:
        return a
    pad = [(0, 0), (0, 0)]
    pad[axis] = (r, r)
    p = np.pad(a, pad, mode='edge')
    k = 2 * r + 1
    z = np.zeros_like(np.take(p, [0], axis=axis))
    c = np.concatenate([z, np.cumsum(p, axis)], axis)   # 前置 0，窗口和 = c[i+k]-c[i]
    if axis == 0:
        hi, lo = c[k:], c[:-k]
    else:
        hi, lo = c[:, k:], c[:, :-k]
    return (hi - lo) / k


def _blur2(a, r):
    return _blur1(_blur1(a, r, 0), r, 1)


# ---------------------------------------------------------------- 距离场
def max_filter(a, r):
    """精确的可分离滑动最大值（方形窗口 2r+1），纯 numpy。

    ★ 不要再用「倍增技巧」（k=1,2,4,8… 每次取 ±k 的 max）——那不是窗口最大值，
      是**稀疏点集**的最大值：偏移只落在 {0,±1,±2,±4,±8,±16,±32}，等价于一个
      8 角星形窗口。实测这个错误让内切半径 R 长出以 32px 为间距的星芒和横条，
      再经由 z = R·f(D/R) 直接进几何，正面上就是一片一片的灰斑（像拼布被）。
      逐 k 平移取 max 是 O(r) 次 numpy 运算，r=46 时 0.3 s 量级，完全可接受。
    """
    out = a
    for k in range(1, r + 1):
        m = out.copy()
        m[k:, :] = np.maximum(m[k:, :], out[:-k, :])
        m[:-k, :] = np.maximum(m[:-k, :], out[k:, :])
        out = m
    for k in range(1, r + 1):
        m = out.copy()
        m[:, k:] = np.maximum(m[:, k:], out[:, :-k])
        m[:, :-k] = np.maximum(m[:, :-k], out[:, k:])
        out = m
    return out


def front_field(fig):
    """体量项高度场（世界 z）。剪影外为 0。

    做法：把剪影掩码做几遍盒模糊得到「厚度场」b，
      b = 0.5 恰好在剪影边界上（跨边缘的窗内平均就是一半），
      越往里越接近 1，而**窄的地方天然到不了 1** —— 这正好就是「局部内切半径」
      的作用，而且是连续可导的，不像滑动最大值那样有跳变。

    再套超椭圆整形：u 从 0（轮廓）到 1（厚处），
      z = Zc·(1-(1-u)^n)^(1/n)
    u=0 处 z=0 ⇒ 正投影严格等于剪影；u=1 处切线水平 ⇒ 脊线平、肩部转得急。

    ★ 为什么不再用 R = max_filter(D, 46)：
      ① 那个 max_filter 是「倍增技巧」写的，实际算的是稀疏点集的最大值
         （偏移只有 0,±1,±2,±4,…,±32），等于一个八角星窗口 —— R 上长出 32px
         间距的星芒和横条，经 z=R·f(D/R) 直接进几何，正面上是一片片灰斑。
      ② 就算换成精确的滑动最大值也不行：窗口 46 相对胸像尺度太大，R 恒等于
         全局最大值 176.67（实测），整个剪影退化成一根等截面的柱体。
      掩码模糊同时解决这两件事，且不需要任何近似。
    """
    D = T.chamfer_dt(fig)
    D = np.where(fig, D, 0.0)

    # 局部内切半径 R：小窗口精确滑动最大值 + 模糊。
    # 窗口只要小（R_WIN=10），R 就跟着局部宽度走：胸像躯干 R≈176，头 R≈65，
    # 手臂 R≈30 —— 正是「不同部位厚度不同」的来源。
    # 之后的模糊是为了抹掉 max 的 argmax 切换台阶（不抹，z 上就是一圈圈硬边）。
    R = max_filter(D, R_WIN)
    R = _blur2(R, R_BLUR)
    R = np.maximum(R, 1.0)
    u = np.clip(D / R, 0.0, 1.0)
    z = R * np.power(np.maximum(1.0 - np.power(1.0 - u, SUPER_N), 0.0),
                     1.0 / SUPER_N)
    z = np.where(fig, z * KAPPA * SCALE, 0.0)
    return z, D, R


# ---------------------------------------------------------------- 网格工具
def _erode1(m):
    e = m.copy()
    e[1:, :] &= m[:-1, :]; e[:-1, :] &= m[1:, :]
    e[:, 1:] &= m[:, :-1]; e[:, :-1] &= m[:, 1:]
    e[0, :] = False; e[-1, :] = False; e[:, 0] = False; e[:, -1] = False
    return e


def _nodes(lo, hi, step):
    v = list(range(lo, hi + 1, step))
    if v[-1] != hi:
        v.append(hi)
    return np.array(v, np.int32)


def _bulk(mesh, P, N, mat, UV=None):
    """批量写三角。逐条 mesh.add 在这套规模下是几十秒，必须走批量。"""
    m = len(P)
    if m == 0:
        return 0
    mesh.P.extend(list(P))
    mesh.N.extend(list(N))
    mesh.T.extend([_ZUV] * m if UV is None else list(UV))
    mesh.M.extend([mat] * m)
    f0 = mesh._fid
    mesh.F.extend(range(f0, f0 + m))
    mesh._fid = f0 + m
    return m


def _quads(p, n, uv=None):
    """(M,4,3) 四顶点 → (2M,3,3) 六顶点（0-1-2 / 0-2-3）。"""
    tp = np.stack([p[:, 0], p[:, 1], p[:, 2], p[:, 0], p[:, 2], p[:, 3]], axis=1)
    tn = np.stack([n[:, 0], n[:, 1], n[:, 2], n[:, 0], n[:, 2], n[:, 3]], axis=1)
    if uv is None:
        return tp.reshape(-1, 3, 3), tn.reshape(-1, 3, 3), None
    tu = np.stack([uv[:, 0], uv[:, 1], uv[:, 2], uv[:, 0], uv[:, 2], uv[:, 3]], axis=1)
    return (tp.reshape(-1, 3, 3), tn.reshape(-1, 3, 3),
            tu.reshape(-1, 3, 2).astype(np.float32))


# ---------------------------------------------------------------- 总装
def build(y0=None, y1=None, cell=G, verbose=True):
    inkG, innerG, figG = T.load_masks()
    if y0 is None:
        y0, y1 = 0, figG.shape[0]
    ink, inner, fig = inkG[y0:y1], innerG[y0:y1], figG[y0:y1]
    H, W = fig.shape

    # 世界坐标：都用**全局**剪影的底边与中心，裁切只影响取景不影响几何
    ysG, xsG = np.nonzero(figG.any(1))[0], np.nonzero(figG.any(0))[0]
    bot, xl, xr = float(ysG.max()), float(xsG.min()), float(xsG.max())
    cx = 0.5 * (xl + xr)

    zt, D, R = front_field(fig)                 # 体量项
    zt = np.where(fig, _blur2(zt, ZBLUR), 0.0)  # 压掉 chamfer 距离场的方块状台阶
    lab, n = T.cc_label(inner)
    cnt = 0

    # --- 板面项
    rz = np.zeros((H, W), np.float64)
    if GROOVE_D > 0:
        # 沿墨线开沟：所有板同高，沟与墨线重合。
        rz = -GROOVE_D * _blur2(ink.astype(np.float64), GROOVE_BLUR)
    else:
        # 退回旧路：按零件面积分 3 档抬高
        lev = np.where(inner, np.int8(1), np.int8(0))
        areas = np.bincount(lab[lab >= 0].ravel(), minlength=n)
        cnt = 0
        for k in range(n):
            a = int(areas[k])
            if a < MIN_AREA:
                continue
            lv = 1 if a < LEV_EDGE[0] else (2 if a < LEV_EDGE[1] else 3)
            lev[lab == k] = lv
            cnt += 1
        for lv in (1, 2, 3):
            rz[lev == lv] = RLEV[lv]
        if RBLUR > 0:
            rz = np.where(fig, _blur2(rz, RBLUR), 0.0)

    zf = np.where(fig, zt + rz, 0.0)            # 前表面高度
    zb = np.where(fig, -LAM * zt, 0.0)          # 后表面高度（不含板面项）

    # --- 节点网格（ys 用全局像素坐标，索引裁切后的数组时减去 y0）
    ys = _nodes(y0, y1 - 1, cell)
    xs = _nodes(0, W - 1, cell)
    yl = ys - y0
    Nf = fig[np.ix_(yl, xs)]
    ny, nx = Nf.shape

    # --- 只保留**多数角落在剪影内**的格（≥2/4）。不能用「四角全在」：
    #     那会让整条轮廓内缩一格（2px），剪影面积掉 4%，保真门立刻破 99%。
    cs = (Nf[:-1, :-1].astype(np.int8) + Nf[1:, :-1] + Nf[:-1, 1:] + Nf[1:, 1:])
    ok = cs >= 2
    if not ok.any():
        raise RuntimeError('没有可用网格，检查剪影与裁切范围')

    # --- 闭合条件（这一步是 v2.1 能收严的关键）：
    #     前片与后片只在「区域边界」处重合，所以**区域边界上的每个节点 z 必须为 0**。
    #     判据：节点四周的 4 个格只要有任意一个不在 ok 里，它就是边界节点。
    #     （早前用 Nf 的腐蚀当边界，漏掉了「四邻节点都在、但对角格缺失」的台阶拐角，
    #       于是留下 1836 条只有一片用到的边，分量闭合率直接归零。）
    cb = np.zeros((ny, nx), np.int8)
    cb[1:, 1:] += ok; cb[1:, :-1] += ok; cb[:-1, 1:] += ok; cb[:-1, :-1] += ok
    bnd = cb < 4
    zg_f = zf[np.ix_(yl, xs)].copy(); zg_f[bnd] = RIM_T
    zg_b = zb[np.ix_(yl, xs)].copy(); zg_b[bnd] = -LAM * RIM_T

    # --- 顶点世界坐标
    X = (xs[None, :] - cx) * SCALE
    Y = (bot - ys[:, None]) * SCALE

    # ★ 亚像素轮廓吸附：把**边界节点**沿平滑掩码的 0.5 等值面外移，
    #   落到真实的亚像素轮廓上（一阶牛顿：x ← x − s·∇s/|∇s|²）。
    #
    #   为什么必须做：网格剪影是 2px 台阶，正视时轮廓是一圈锯齿；侧视（沿 X 看）
    #   时这圈台阶正好**正对镜头**，每一级台阶的立面反光、平面背光，画面上就是
    #   一条 2px 周期的亮齿「拉链」。实测关掉线稿仍在、提高超采样到 4× 也不消，
    #   说明它不是贴图、不是裂缝、不是法线，就是台阶本身。
    #   吸附后台阶振幅从 2px 降到 ~0.2px，两个视角同时治好，且不增加任何三角。
    #   只动边界节点，内部节点不动 ⇒ 网格拓扑不变，不会撕开。
    dxw = np.zeros((ny, nx))
    dyw = np.zeros((ny, nx))
    bf2 = _blur2(fig.astype(np.float64), 2)
    sfn = bf2[np.ix_(yl, xs)] - 0.5
    gdy, gdx = np.gradient(sfn)
    if SNAP > 0:
        g2 = np.maximum(gdx * gdx + gdy * gdy, 1e-9)
        # 牛顿步（图像坐标），再换成世界位移：dX = +dx·SCALE，dY = −dy·SCALE
        dxi = -sfn * gdx / g2
        dyi = -sfn * gdy / g2
        lim = 1.6 * cell
        dxi = np.clip(dxi, -lim, lim)
        dyi = np.clip(dyi, -lim, lim)
        dxw = np.where(bnd, dxi * SCALE * SNAP, 0.0)
        dyw = np.where(bnd, -dyi * SCALE * SNAP, 0.0)

    Pf = np.dstack([np.broadcast_to(X, (ny, nx)) + dxw,
                    np.broadcast_to(Y, (ny, nx)) + dyw, zg_f]).astype(np.float64)
    # 后片的 XY 直接抄前片。试过「后片沿轮廓内缩 1.7~4px」以求打断前后片的深度并列，
    # 实测侧视只改变 22 个像素、抖动 6.8→6.8 —— 说明那条白齿不是前后片 z-fighting，
    # 是前片自身掠射处的 2px 台阶，故不保留内缩（少一个参数、少一处风险）。
    Pb = np.dstack([Pf[..., 0], Pf[..., 1], zg_b]).astype(np.float64)

    # --- 外法线：n ∝ (-∂z/∂X, -∂z/∂Y, 1)。世界 Y 与图像 y 反向，故 ∂z/∂Y = -gy/s
    #     用模糊后的高程求法线：几何不动，但 2px 量化不进光照。
    s = SCALE * cell
    gy, gx = np.gradient(_blur2(zg_f, NBLUR) if NBLUR else zg_f)
    Nn = np.dstack([-gx / s, gy / s, np.ones_like(gx)])
    Nn /= np.linalg.norm(Nn, axis=2, keepdims=True)
    gy, gx = np.gradient(_blur2(zg_b, NBLUR) if NBLUR else zg_b)
    Nn_b = np.dstack([-gx / s, gy / s, -np.ones_like(gx)])
    Nn_b /= np.linalg.norm(Nn_b, axis=2, keepdims=True)

    # --- 轮廓法线接管：贴边一圈改用「径向朝外」的方向。
    #     2px 网格的台阶让贴边法线在水平/垂直之间反复跳，视觉上是一圈梳齿状黑边。
    #
    # ★ 朝外方向必须取自**掩码模糊的梯度**，不能取 chamfer 距离场的梯度：
    #   chamfer D 是整数场（1,2,3…），它的梯度只有「0 / ±1」两种取值，方向永远
    #   落在 ±x、±y 四条轴上 —— 沿轮廓走就是水平、竖直、水平、竖直地跳。
    #   侧视时这条边正对镜头，跳变直接表现为一条 2px 周期的亮暗梳齿（拉链），
    #   关掉线稿也照样在（实测过），说明它跟贴图无关、纯粹是法线在跳。
    #   模糊后的掩码是连续场，梯度方向沿轮廓平滑转过 90°，梳齿消失。
    bf = _blur2(fig.astype(np.float64), 4)
    bfn = bf[np.ix_(yl, xs)]
    gdy, gdx = np.gradient(bfn)
    nxw, nyw = -gdx, gdy                      # 掩码内部为 1、外部为 0 ⇒ 梯度朝内，取负朝外
    nn = np.maximum(np.sqrt(nxw * nxw + nyw * nyw), 1e-12)
    nxw = nxw / nn
    nyw = nyw / nn
    nr = np.dstack([nxw, nyw, np.full_like(nxw, 0.42)])
    nr /= np.linalg.norm(nr, axis=2, keepdims=True)
    Dn = _blur2(D[np.ix_(yl, xs)], 3)
    w = np.clip(1.0 - Dn / (2.5 * cell), 0.0, 1.0)[..., None]
    Nn = Nn * (1.0 - w) + nr * w
    Nn /= np.linalg.norm(Nn, axis=2, keepdims=True)
    Nn_b = Nn_b * (1.0 - w) + nr * np.array([1.0, 1.0, -1.0]) * w
    Nn_b /= np.linalg.norm(Nn_b, axis=2, keepdims=True)

    iy, ix = np.nonzero(ok)

    # 顶点 UV = **原稿像素坐标**。这样渲染时 gb.uv 直接就是「这个表面点对应
    # 线稿的哪一像素」，墨线可以按原稿逐像素投影上去，不经过网格量化。
    # （早前靠「墨格换深色材质」画线，2px 网格把每条线都量化成楼梯 —— 这就是
    #   放大后看到的大块锯齿。）
    UVg = np.dstack([np.broadcast_to(xs[None, :], (ny, nx)),
                     np.broadcast_to(ys[:, None], (ny, nx))]).astype(np.float64)

    def quad(P, Nn_, iy_, ix_):
        return (np.stack([P[iy_, ix_], P[iy_, ix_ + 1],
                          P[iy_ + 1, ix_ + 1], P[iy_ + 1, ix_]], axis=1),
                np.stack([Nn_[iy_, ix_], Nn_[iy_, ix_ + 1],
                          Nn_[iy_ + 1, ix_ + 1], Nn_[iy_ + 1, ix_]], axis=1),
                np.stack([UVg[iy_, ix_], UVg[iy_, ix_ + 1],
                          UVg[iy_ + 1, ix_ + 1], UVg[iy_ + 1, ix_]], axis=1))

    mesh = Mesh()
    from r3d import Mat
    # 前片只用一种亮色：墨线由投影的线稿负责（逐像素、带抗锯齿），
    # 不再靠「墨格换深色材质」—— 那会在线两侧各加一圈 2px 的粗边。
    M_PLATE = Mat((0.910, 0.902, 0.884), spec=0.80, rim=0.35)
    M_BACK = Mat((0.300, 0.315, 0.345), spec=0.32, rim=0.22)
    M_BACK.no_line = True          # 背面不投影线稿（否则转到背后会看到正面的线）
    # 边缘带**不能**用背面那个深色。边缘带在轮廓内侧占一格（2px），
    # 细长特征（头顶天线只有 ~10px 宽 = 5 格）左右各去一格，再叠上轮廓补墨，
    # 整块就被涂成黑色楔子 —— 画面上像一根插进去的黑刀片。
    # 用小倒角的中灰：读起来是「磨过的装甲边」，细特征也能保住浅色芯。
    M_RIM = Mat((0.560, 0.558, 0.545), spec=0.0, rim=0.0)
    M_RIM.seal_only = True         # 只吃轮廓密封带：投影墨线会随顶点 dist 相位跳出黑点串，
                                   # 掠射淡出会把它整条抹掉 —— 两者都不能要
    M_RIM.seal_band = 2.6          # 它只有 2px 宽、顶点 dist 落在 2~3px，带宽要放大

    qf_p, qf_n, qf_u = quad(Pf, Nn, iy, ix)
    _qf_p, _qf_n, _qf_u = _quads(qf_p, qf_n, qf_u)
    nf = _bulk(mesh, _qf_p, _qf_n, M_PLATE, _qf_u)

    # 后片
    qb_p, qb_n, qb_u = quad(Pb, Nn_b, iy, ix)
    nb = 0
    for s0 in range(0, len(qb_p), 40000):
        tp, tn, tu = _quads(qb_p[s0:s0 + 40000], qb_n[s0:s0 + 40000],
                            qb_u[s0:s0 + 40000])
        nb += _bulk(mesh, tp, tn, M_BACK, tu)

    # --- 边缘带：把前片的边沿与后片的边沿连起来
    #     前后片如果在轮廓处直接相切（零厚度刀刃），侧视时两片几乎共面，
    #     z-buffer 会打架 —— 画面上是一条竖直的白色梳齿带（「拉链」）。
    #     给边缘一个真实厚度 RIM_T 并补一条窄边带，相切消失，顺带读出一道小倒角。
    C = np.zeros((ny, nx), bool)
    C[:ok.shape[0], :ok.shape[1]] = ok
    Lp = np.zeros((ny, nx), bool); Lp[:, 1:] = C[:, :-1]
    Up = np.zeros((ny, nx), bool); Up[1:, :] = C[:-1, :]
    ve = Lp ^ C          # 竖直边（节点 (i,j)-(i+1,j)）
    he = Up ^ C          # 水平边（节点 (i,j)-(i,j+1)）

    nrim = np.dstack([nxw, nyw, np.zeros_like(nxw)])
    nn = np.linalg.norm(nrim, axis=2, keepdims=True)
    nrim = np.where(nn > 1e-9, nrim / np.maximum(nn, 1e-9), 0.0)   # 距离场平台处梯度为 0

    def rim_quads(mask, di, dj):
        a, b = np.nonzero(mask)
        p0 = np.stack([Pf[a, b], Pf[a + di, b + dj],
                       Pb[a + di, b + dj], Pb[a, b]], axis=1)
        n0 = np.stack([nrim[a, b], nrim[a + di, b + dj],
                       nrim[a + di, b + dj], nrim[a, b]], axis=1)
        u0 = np.stack([UVg[a, b], UVg[a + di, b + dj],
                       UVg[a + di, b + dj], UVg[a, b]], axis=1)
        return _quads(p0, n0, u0)

    ne = 0
    if RIM_ON:
        # 单面边缘带（RIM_DBL=True 仅作对照，见常量注释）。
        # 早期为了绕开「按法线剔除」造成的漏底而发了两份反向法线；渲染端改成
        # backface=False 之后这件事就没有必要了，双份纯属重复几何。
        signs = (1.0, -1.0) if RIM_DBL else (1.0,)
        for sgn in signs:
            tp, tn, tu = rim_quads(ve, 1, 0)
            ne += _bulk(mesh, tp, tn * sgn, M_RIM, tu)
            tp, tn, tu = rim_quads(he, 0, 1)
            ne += _bulk(mesh, tp, tn * sgn, M_RIM, tu)

    if verbose:
        print(f'区域 {"全身" if y0 == 0 and y1 == figG.shape[0] else f"y[{y0},{y1})"}  网格 {cell}px')
        print(f'前片 {nf} + 后片 {nb} + 边带 {ne} = {len(mesh)} 三角   零件 {cnt}/{n} 块')
        print(f'z 前 [{zf.min():.2f}, {zf.max():.2f}]  后 {zb.min():.2f}  '
              f'体量项最大 {zt.max():.2f}（{zt.max()/SCALE:.0f}px）')
        print(f'总厚 {(zt.max()*(1+LAM))/SCALE:.0f}px = 视图高 {H}px 的 '
              f'{(zt.max()*(1+LAM))/(H*SCALE)*100:.0f}%')

    # 距离场按**全图**尺寸存一份：UV 是全局像素坐标，裁切坐标对不上
    Dg = np.zeros(figG.shape, np.float64)
    Dg[y0:y1] = D
    Hw = (y1 - y0) * SCALE
    cyw = (bot - 0.5 * (y0 + y1 - 1)) * SCALE
    meta = dict(H=Hw, Wfig=float(xr - xl + 1), scale=SCALE,
                zf=float(zf.max()), zback=float(zb.min()),
                cx=cx, bot=bot, fig=fig, cy=cyw, dist=Dg)
    return mesh, meta


def main():
    a = sys.argv[1:]
    y0 = y1 = None
    if '--crop' in a:
        s = a[a.index('--crop') + 1]
        y0, y1 = [int(v) for v in s.split(',')]
    cell = G
    if '--cell' in a:
        cell = int(a[a.index('--cell') + 1])
    build(y0, y1, cell)


if __name__ == '__main__':
    main()
