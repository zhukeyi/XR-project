"""
gfx/gbuffer.py — z-buffer 光栅化，输出 G-buffer（M1 核心）

替代 v1 的画家算法。画家算法按面中心 z 排序，相交或套叠的面必然排错 —— 这是
v1 在手臂与躯干交汇处出现穿模的根因。z-buffer 用逐像素深度测试，天然正确。

三个必须做对的地方：
  1. 透视校正插值：屏幕空间重心坐标不能直接插值属性，必须除以 w 再加权。
     不做这一步，贴图与法线会有明显透视扭曲（近大远小的梯度错）。
  2. 背面剔除用法线不用绕序：g_box 绕序朝外、g_tube 侧面绕序朝内，不统一。
     用「面法线与顶点法线对齐后，再与视线比较」才可靠。
  3. 像素中心 +0.5：避免半像素偏移导致边缘发虚。

近平面：跨近平面的三角形做 Sutherland–Hodgman 裁剪（1→1 或 1→2 三角），不再
整块丢弃。城市地面是一整块大四边形，横跨相机后方，丢弃会让地面凭空破洞。
"""
import math
import numpy as np

EPS = 1e-9


class GBuffer:
    """渲染目标：五个通道。M2 会在此加 tangent/rough/metal。"""

    __slots__ = ('W', 'H', 'depth', 'nrm', 'uv', 'midx', 'fid')

    def __init__(self, W, H):
        self.W, self.H = W, H
        self.depth = np.full((H, W), np.inf, np.float32)
        self.nrm = np.zeros((H, W, 3), np.float32)
        self.uv = np.zeros((H, W, 2), np.float32)
        self.midx = np.full((H, W), -1, np.int16)
        self.fid = np.full((H, W), -1, np.int32)

    @property
    def mask(self):
        return self.fid >= 0

    def coverage(self):
        return float((self.fid >= 0).mean())


class RasterStats:
    def __init__(self):
        self.total = 0
        self.backfaced = 0
        self.near_clipped = 0
        self.clipped_out = 0
        self.offscreen = 0
        self.degenerate = 0
        self.drawn = 0
        self.pixels = 0

    def __repr__(self):
        return ('三角 %d → 近平面裁剪 %d(→%d) / 背面剔除 %d / 出屏 %d / 退化 %d → '
                '绘制 %d，覆盖像素 %d'
                % (self.total, self.near_clipped, self.clipped_out,
                   self.backfaced, self.offscreen, self.degenerate,
                   self.drawn, self.pixels))


def _clip_near(Vc, Nc, Ts, Ms, Fs, near, cross):
    """对跨近平面的三角形做 Sutherland–Hodgman 裁剪（相机空间，保留 z <= -near）。

    只在少数三角形上跑（城市地面、贴脸的特效件），Python 循环成本可忽略。
    法线与 UV 沿边线性插值，材质与面 id 直接继承。
    """
    zn = -near
    outV, outN, outT, outM, outF = [], [], [], [], []
    nout = 0
    for i in np.nonzero(cross)[0]:
        p = Vc[i]
        nn = Nc[i]
        tt = Ts[i]
        poly = []           # 元素 (pos, nrm, uv)
        for k in range(3):
            a = k
            b = (k + 1) % 3
            ina = p[a][2] <= zn
            inb = p[b][2] <= zn
            if ina:
                poly.append((p[a], nn[a], tt[a]))
            if ina != inb:
                den = p[a][2] - p[b][2]
                if abs(den) < EPS:
                    continue
                s = (p[a][2] - zn) / den
                poly.append((p[a] + (p[b] - p[a]) * s,
                             nn[a] + (nn[b] - nn[a]) * s,
                             tt[a] + (tt[b] - tt[a]) * s))
        if len(poly) < 3:
            continue
        for k in range(1, len(poly) - 1):
            for v in (poly[0], poly[k], poly[k + 1]):
                outV.append(v[0])
                outN.append(v[1])
                outT.append(v[2])
            outM.append(Ms[i])
            outF.append(Fs[i])
            nout += 1
    if nout == 0:
        return Vc, Nc, Ts, Ms, Fs, 0
    keep = ~cross
    return (np.concatenate([Vc[keep], np.array(outV, np.float32).reshape(-1, 3, 3)]),
            np.concatenate([Nc[keep], np.array(outN, np.float32).reshape(-1, 3, 3)]),
            np.concatenate([Ts[keep], np.array(outT, np.float32).reshape(-1, 3, 2)]),
            np.concatenate([Ms[keep], np.array(outM, np.int32)]),
            np.concatenate([Fs[keep], np.array(outF, np.int32)]),
            nout)


def rasterize(P, N, T, midx, fid_arr, cam_m, fov, W, H, near=0.6,
              backface=True, gb=None):
    """P (Tn,3,3) 世界顶点 · N (Tn,3,3) 顶点法线 · T (Tn,3,2) UV
    midx (Tn,) 材质索引 · fid_arr (Tn,) 面 id
    返回 (GBuffer, RasterStats)
    """
    st = RasterStats()
    Tn = len(P)
    st.total = Tn
    gb = gb or GBuffer(W, H)
    if Tn == 0:
        return gb, st

    cam = cam_m.astype(np.float32)
    # --- 世界 → 相机空间
    Ph = np.concatenate([P.reshape(-1, 3), np.ones((Tn * 3, 1), np.float32)], axis=1)
    Vc = (cam @ Ph.T).T[:, :3].reshape(Tn, 3, 3)
    # --- 法线只做旋转
    R3 = cam[:3, :3]
    Nc = (N.reshape(-1, 3) @ R3.T).reshape(Tn, 3, 3)

    Ts = T.astype(np.float32)
    Ms = np.asarray(midx, np.int32).ravel()
    Fs = np.asarray(fid_arr, np.int32).ravel()

    # --- 近平面：跨平面的三角形先裁剪，不整块丢弃
    zc = -Vc[:, :, 2]
    cross = np.any(zc <= near, axis=1)
    if cross.any():
        st.near_clipped = int(cross.sum())
        Vc, Nc, Ts, Ms, Fs, nout = _clip_near(Vc, Nc, Ts, Ms, Fs, near, cross)
        st.clipped_out = nout
        Tn = len(Vc)
        if Tn == 0:
            return gb, st

    # --- 面法线 + 定向（与顶点法线对齐）
    fn = np.cross(Vc[:, 1] - Vc[:, 0], Vc[:, 2] - Vc[:, 0])
    fl = np.linalg.norm(fn, axis=1)
    st.degenerate = int((fl < 1e-9).sum())
    fn = fn / np.maximum(fl, EPS)[:, None]
    avg_n = Nc.mean(axis=1)
    flip = (fn * avg_n).sum(axis=1) < 0
    fn[flip] *= -1.0

    # --- 背面剔除：法线与视线同向则背对相机
    cen = Vc.mean(axis=1)
    view = cen / np.maximum(np.linalg.norm(cen, axis=1), EPS)[:, None]
    if backface:
        # 阈值取 -1e-6，不用 v1 的 -0.008：那个偏置是为了让 ImageDraw 少画些掠射面
        # 的细条，代价是连带剔掉掠射角的地面 —— 实测 city 有 12,473 个空洞像素，
        # 关掉剔除后归零。z-buffer 靠深度测试决胜，不需要这个偏置。
        keep = (fn * view).sum(axis=1) < -1e-6
        st.backfaced = int((~keep).sum())
    else:
        keep = np.ones(Tn, bool)
    keep &= (fl >= 1e-9)

    if not keep.any():
        return gb, st

    idx = np.nonzero(keep)[0]
    f = 1.0 / math.tan(fov * math.pi / 360.0)
    fc = f * (H * 0.5)
    cx, cy = W * 0.5, H * 0.5

    Vs = Vc[idx]
    Ns = Nc[idx]
    Ts = Ts[idx]
    zs = -Vs[:, :, 2]      # 裁剪后重新取，不能用裁剪前的 zc
    ms = Ms[idx]
    fs = Fs[idx]

    # --- 投影（向量化）
    sx = (Vs[:, :, 0] / zs) * fc + cx
    sy = cy - (Vs[:, :, 1] / zs) * fc

    xmin = np.maximum(np.floor(sx.min(axis=1)).astype(np.int32), 0)
    xmax = np.minimum(np.ceil(sx.max(axis=1)).astype(np.int32), W - 1)
    ymin = np.maximum(np.floor(sy.min(axis=1)).astype(np.int32), 0)
    ymax = np.minimum(np.ceil(sy.max(axis=1)).astype(np.int32), H - 1)
    vis = (xmax > xmin) & (ymax > ymin)
    st.offscreen = int((~vis).sum())

    depth = gb.depth
    nrm = gb.nrm
    uvb = gb.uv
    midb = gb.midx
    fidb = gb.fid
    pix = 0

    sxL, syL = sx.tolist(), sy.tolist()
    zL = zs.tolist()
    idxL = np.nonzero(vis)[0].tolist()

    # 列切片：细长斜三角的轴对齐 bbox 利用率会低到 5%（实测地面条带），
    # 光栅时间几乎全花在 bbox 里那些不属于三角的像素上。把大 bbox 按列切开，
    # 每片按三条边重算紧致的 y 范围，过画比从 5.2× 降到 ~1.4×。
    SLAB = 65536
    MAXSLAB = 48

    def _yrange(e1, e2, e3, xa, xb):
        lo, hi = 1e30, -1e30
        for x1_, y1_, x2_, y2_ in (e1, e2, e3):
            if x1_ > x2_:
                x1_, y1_, x2_, y2_ = x2_, y2_, x1_, y1_
            if x2_ < xa or x1_ > xb:
                continue
            if abs(x2_ - x1_) < 1e-12:      # 竖边
                if xa <= x1_ <= xb:
                    lo = min(lo, y1_, y2_)
                    hi = max(hi, y1_, y2_)
                continue
            dx = x2_ - x1_
            ta = (min(max(xa, x1_), x2_) - x1_) / dx
            tb = (min(max(xb, x1_), x2_) - x1_) / dx
            ya = y1_ + (y2_ - y1_) * ta
            yb = y1_ + (y2_ - y1_) * tb
            lo = min(lo, ya, yb)
            hi = max(hi, ya, yb)
        return lo, hi

    for k in idxL:
        x0, x1 = xmin[k], xmax[k]
        y0, y1 = ymin[k], ymax[k]
        ax, ay = sxL[k][0], syL[k][0]
        bx, by = sxL[k][1], syL[k][1]
        qx, qy = sxL[k][2], syL[k][2]
        den = (by - qy) * (ax - qx) + (qx - bx) * (ay - qy)
        if abs(den) < 1e-9:
            continue
        inv = 1.0 / den
        z0, z1, z2 = zL[k][0], zL[k][1], zL[k][2]
        iz0, iz1, iz2 = 1.0 / z0, 1.0 / z1, 1.0 / z2
        n0, n1, n2 = Ns[k][0], Ns[k][1], Ns[k][2]
        t0, t1, t2 = Ts[k][0], Ts[k][1], Ts[k][2]
        mk, fk = ms[k], fs[k]

        area = (x1 - x0 + 1) * (y1 - y0 + 1)
        if area > SLAB:
            nb_ = min(MAXSLAB, int(math.ceil(area / SLAB)))
            e1 = (ax, ay, bx, by)
            e2 = (bx, by, qx, qy)
            e3 = (qx, qy, ax, ay)
            step = (x1 - x0 + 1) / nb_
            boxes = []
            for s in range(nb_):
                xa = x0 + int(round(s * step))
                xb = x1 if s == nb_ - 1 else x0 + int(round((s + 1) * step)) - 1
                if xb < xa:
                    continue
                ly, hy = _yrange(e1, e2, e3, xa, xb)
                if ly > hy:
                    continue
                ya = max(y0, int(math.floor(ly)) - 1)
                yb = min(y1, int(math.ceil(hy)) + 1)
                if yb < ya:
                    continue
                boxes.append((xa, xb, ya, yb))
        else:
            boxes = ((x0, x1, y0, y1),)

        touched = False
        for xa, xb, ya, yb in boxes:
            PX = (np.arange(xa, xb + 1, dtype=np.float32) + 0.5)[None, :]
            PY = (np.arange(ya, yb + 1, dtype=np.float32) + 0.5)[:, None]
            w0 = ((by - qy) * (PX - qx) + (qx - bx) * (PY - qy)) * inv
            w1 = ((qy - ay) * (PX - qx) + (ax - qx) * (PY - qy)) * inv
            w2 = 1.0 - w0 - w1
            inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
            if not inside.any():
                continue
            # 透视校正：屏幕空间重心 → 1/z 加权
            invz = w0 * iz0 + w1 * iz1 + w2 * iz2
            np.maximum(invz, EPS, out=invz)
            zz = 1.0 / invz
            sub = depth[ya:yb + 1, xa:xb + 1]
            upd = inside & (zz < sub)
            if not upd.any():
                continue
            # np.copyto + where 比 sub[upd]=zz[upd] 少一次掩码压缩与临时数组分配
            np.copyto(sub, zz, where=upd)

            # 透视校正后的插值权重
            b0 = w0 * (iz0 * zz)
            b1 = w1 * (iz1 * zz)
            b2 = 1.0 - b0 - b1

            # 法线插值（Gouraud）
            nx = b0 * n0[0] + b1 * n1[0] + b2 * n2[0]
            ny = b0 * n0[1] + b1 * n1[1] + b2 * n2[1]
            nz = b0 * n0[2] + b1 * n1[2] + b2 * n2[2]
            ln = np.sqrt(nx * nx + ny * ny + nz * nz) + EPS
            nb = nrm[ya:yb + 1, xa:xb + 1]
            np.divide(nx, ln, out=nx)
            np.divide(ny, ln, out=ny)
            np.divide(nz, ln, out=nz)
            np.copyto(nb[:, :, 0], nx, where=upd)
            np.copyto(nb[:, :, 1], ny, where=upd)
            np.copyto(nb[:, :, 2], nz, where=upd)

            # UV 插值
            ub = uvb[ya:yb + 1, xa:xb + 1]
            np.copyto(ub[:, :, 0], b0 * t0[0] + b1 * t1[0] + b2 * t2[0], where=upd)
            np.copyto(ub[:, :, 1], b0 * t0[1] + b1 * t1[1] + b2 * t2[1], where=upd)

            np.copyto(midb[ya:yb + 1, xa:xb + 1], np.int16(mk), where=upd)
            np.copyto(fidb[ya:yb + 1, xa:xb + 1], np.int32(fk), where=upd)
            pix += int(np.count_nonzero(upd))
            touched = True
        if touched:
            st.drawn += 1

    st.pixels = pix
    return gb, st
