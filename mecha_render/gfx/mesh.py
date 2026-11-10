"""
gfx/mesh.py — 图元 → 带顶点法线的三角形（M1 地基）

为什么需要这一层：
  现有 r3d.collect() 只输出「面法线」，一个多边形一个常量法线。这导致
  cel_shade() 只能 per-face 调用，也就是一个面一个颜色 —— 这是「平涂」的根源。
  逐像素着色要求每个顶点带法线，靠重心坐标插值出表面渐变。

两种法线：
  flat  —— 盒子/楔形/薄板。每个三角形独立用面法线，保住硬边（工业件必须硬边）。
  smooth—— 圆柱侧面。相邻面共享顶点法线，消除棱面（8 边棱柱看起来是圆柱）。

外法线定向沿用 r3d 的规则：法线必须背离图元自身中心。因为 g_box/g_wedge 绕序
朝外、g_tube 侧面绕序朝内，靠绕序判断背面不可靠。
"""
import numpy as np

EPS = 1e-9


def _norm(v):
    l = np.linalg.norm(v)
    return v / l if l > EPS else v


def poly_normal(p):
    """Newell 法求多边形法线，对非平面四边形也稳定（纯叉积会偏）。"""
    n = np.zeros(3)
    m = len(p)
    for i in range(m):
        a, b = p[i], p[(i + 1) % m]
        n[0] += (a[1] - b[1]) * (a[2] + b[2])
        n[1] += (a[2] - b[2]) * (a[0] + b[0])
        n[2] += (a[0] - b[0]) * (a[1] + b[1])
    return _norm(n)


class Mesh:
    """三角形集合。数组化后交给 gbuffer 批量处理。"""

    def __init__(self):
        self.P = []    # 顶点位置 (3,3)
        self.N = []    # 顶点法线 (3,3)
        self.T = []    # 顶点 UV (3,2)，M1 为占位
        self.M = []    # 材质对象引用
        self.F = []    # 面 id（调试与描边用）
        self._fid = 0

    def add(self, p, n, uv, mat):
        self.P.append(p)
        self.N.append(n)
        self.T.append(uv)
        self.M.append(mat)
        self.F.append(self._fid)
        self._fid += 1

    def mat_table(self):
        """按 id 去重（同色板常量被数百个节点共享，去重后只有十几个材质）。"""
        seen, mats, midx = {}, [], []
        for m in self.M:
            k = id(m)
            if k not in seen:
                seen[k] = len(mats)
                mats.append(m)
            midx.append(seen[k])
        base = np.array([[m.rgb[0], m.rgb[1], m.rgb[2]] for m in mats], np.float32) \
            if mats else np.zeros((0, 3), np.float32)
        emis = np.array([m.emissive for m in mats], np.float32) \
            if mats else np.zeros((0,), np.float32)
        return np.array(midx, np.int32), base, emis

    def mat_prop_table(self):
        """返回 (spec, rim) —— 每材质的高光/边缘光系数。

        v1 起 Mat.spec / Mat.rim 就预留了字段，但调色板从未赋值、shade() 也没接，
        于是全系 0.0。三视图要验「金属扎实感」，必须把这两个通道接上，
        否则渲染再干净也只是塑料。
        """
        _, mats = self._mats()
        if not mats:
            return np.zeros((0,), np.float32), np.zeros((0,), np.float32)
        return (np.array([getattr(m, 'spec', 0.0) for m in mats], np.float32),
                np.array([getattr(m, 'rim', 0.0) for m in mats], np.float32))

    def _mats(self):
        seen, mats, midx = {}, [], []
        for m in self.M:
            k = id(m)
            if k not in seen:
                seen[k] = len(mats); mats.append(m)
            midx.append(seen[k])
        return midx, mats

    def arrays(self):
        """返回 (P, N, T, midx, F, mat_rgb, mat_emis)"""
        if not self.P:
            z3 = np.zeros((0, 3, 3), np.float32)
            return (z3, z3, np.zeros((0, 3, 2), np.float32),
                    np.zeros((0,), np.int32), np.zeros((0,), np.int32),
                    np.zeros((0, 3), np.float32), np.zeros((0,), np.float32))
        P = np.array(self.P, np.float32)
        N = np.array(self.N, np.float32)
        T = np.array(self.T, np.float32)
        midx, base, emis = self.mat_table()
        F = np.array(self.F, np.int32)
        return P, N, T, midx, F, base, emis

    def __len__(self):
        return len(self.P)


def prim_to_tris(mesh, v, faces, xform, mat, smooth=None):
    """把一个图元展开成三角形写进 mesh。

    xform   : 4x4 世界矩阵
    smooth  : None 或 'tube'（圆柱侧面平滑）
    """
    vw = (xform @ np.hstack([v, np.ones((len(v), 1))]).T).T[:, :3]
    pivot = vw.mean(axis=0)

    # --- 面法线（含定向）
    fns = []
    for f in faces:
        p = vw[f]
        n = poly_normal(p)
        if n @ (p.mean(axis=0) - pivot) < 0:
            n = -n
        fns.append(n)

    # --- 平滑面判定：圆柱的侧面是 4 顶点四边形，端盖是多边形
    is_smooth = np.zeros(len(faces), bool)
    if smooth == 'tube':
        for i, f in enumerate(faces):
            if len(f) == 4:
                is_smooth[i] = True

    # --- 顶点法线累加（只累平滑面）
    vacc = np.zeros_like(vw)
    vcnt = np.zeros(len(vw))
    for i, f in enumerate(faces):
        if is_smooth[i]:
            for k in f:
                vacc[k] += fns[i]
                vcnt[k] += 1
    vnrm = np.zeros_like(vw)
    for k in range(len(vw)):
        vnrm[k] = _norm(vacc[k]) if vcnt[k] > 0 else fns[0]

    # --- 三角化（扇形），并给出顶点 UV 占位
    for i, f in enumerate(faces):
        p = vw[f]
        n_face = fns[i]
        for k in range(1, len(f) - 1):
            idx = (f[0], f[k], f[k + 1])
            tp = np.stack([p[0], p[k], p[k + 1]])
            if is_smooth[i]:
                tn = np.stack([vnrm[idx[0]], vnrm[idx[1]], vnrm[idx[2]]])
            else:
                tn = np.stack([n_face, n_face, n_face])
            # UV 占位：用世界坐标的平面投影，M2 会替换为真实展开
            uv = np.stack([[tp[j][0] * 0.15, tp[j][2] * 0.15] for j in range(3)])
            mesh.add(tp, tn, uv, mat)


def from_tris(tris, mesh=None, cache=None):
    """把 v1 的 Tris（逐面颜色，无节点树）适配成 Mesh。

    城市模块 build_city() 直接返回 Tris，没有节点树可递归，所以需要这条通道。
    面法线直接用 Tris 里已定向好的 nrms，顶点法线三个顶点同值（硬边）。
    """
    from r3d import Mat
    mesh = mesh or Mesh()
    cache = {} if cache is None else cache
    for i in range(len(tris)):
        p = np.asarray(tris.pts[i], np.float64)
        n = np.asarray(tris.nrms[i], np.float64)
        c = tris.cols[i]
        e = tris.emis[i]
        k = (round(float(c[0]), 4), round(float(c[1]), 4),
             round(float(c[2]), 4), round(float(e), 4))
        mat = cache.get(k)
        if mat is None:
            mat = Mat(c, emissive=e)
            cache[k] = mat
        uv = np.stack([[p[j][0] * 0.15, p[j][2] * 0.15] for j in range(3)])
        for t in range(1, len(p) - 1):
            tp = np.stack([p[0], p[t], p[t + 1]])
            mesh.add(tp, np.stack([n, n, n]), uv, mat)
    return mesh


def collect2(node, mesh, xform=None):
    """递归展开节点树，输出带法线的三角形。结构与 r3d.collect 一致。"""
    if getattr(node, 'hide', False):
        return
    m = node.local() if xform is None else xform @ node.local()
    if node.prim is not None:
        prim = node.prim
        v, faces = prim[0], prim[1]
        prim_to_tris(mesh, v, faces, m, node.mat, getattr(node, 'smooth', None))
    for c in node.children:
        collect2(c, mesh, m)
