"""
r3d.py — 微型软件 3D 渲染器（纯 numpy + PIL 光栅化）

管线：节点层级 -> 世界空间多边形 -> 相机变换 -> 背面剔除 ->  painters 深度排序
      -> 透视投影 -> 赛璐璐分级着色 -> 雾化 -> 多边形填充 -> Bloom -> HUD

设计取向：不做物理正确的 PBR，只做"游戏感"的卡通分级着色 + 强对比轮廓，
因为目标是伪 3D 概念片，不是写实。
"""
import math
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

D2R = math.pi / 180.0


# ---------------------------------------------------------------- 矩阵工具

def T(x=0.0, y=0.0, z=0.0):
    m = np.eye(4)
    m[0, 3], m[1, 3], m[2, 3] = x, y, z
    return m


def S(x=1.0, y=None, z=None):
    y = x if y is None else y
    z = x if z is None else z
    m = np.eye(4)
    m[0, 0], m[1, 1], m[2, 2] = x, y, z
    return m


def Rx(deg):
    a = deg * D2R
    c, s = math.cos(a), math.sin(a)
    m = np.eye(4)
    m[1, 1], m[1, 2] = c, -s
    m[2, 1], m[2, 2] = s, c
    return m


def Ry(deg):
    a = deg * D2R
    c, s = math.cos(a), math.sin(a)
    m = np.eye(4)
    m[0, 0], m[0, 2] = c, s
    m[2, 0], m[2, 2] = -s, c
    return m


def Rz(deg):
    a = deg * D2R
    c, s = math.cos(a), math.sin(a)
    m = np.eye(4)
    m[0, 0], m[0, 1] = c, -s
    m[1, 0], m[1, 1] = s, c
    return m


def chain(*ms):
    out = np.eye(4)
    for m in ms:
        out = out @ m
    return out


def look_at(eye, target, up=(0.0, 1.0, 0.0), roll=0.0):
    eye = np.asarray(eye, float)
    target = np.asarray(target, float)
    up = np.asarray(up, float)
    fwd = target - eye
    fwd /= (np.linalg.norm(fwd) + 1e-12)
    right = np.cross(fwd, up)
    if np.linalg.norm(right) < 1e-6:
        right = np.cross(fwd, np.array([0.0, 0.0, 1.0]))
    right /= (np.linalg.norm(right) + 1e-12)
    cam_up = np.cross(right, fwd)
    m = np.eye(4)
    m[0, :3], m[1, :3], m[2, :3] = right, cam_up, -fwd
    m[:3, 3] = -m[:3, :3] @ eye
    if roll:
        m = chain(Rz(roll), m)
    return m


# ---------------------------------------------------------------- 几何图元
# 每个图元返回 (verts(N,3) float64, faces list[list[int]])

def g_box(w, h, d, center=(0, 0, 0)):
    x, y, z = w / 2, h / 2, d / 2
    cx, cy, cz = center
    v = np.array([
        [cx - x, cy - y, cz - z], [cx + x, cy - y, cz - z],
        [cx + x, cy - y, cz + z], [cx - x, cy - y, cz + z],
        [cx - x, cy + y, cz - z], [cx + x, cy + y, cz - z],
        [cx + x, cy + y, cz + z], [cx - x, cy + y, cz + z],
    ], float)
    f = [[0, 1, 2, 3], [7, 6, 5, 4], [4, 5, 1, 0],
         [5, 6, 2, 1], [6, 7, 3, 2], [7, 4, 0, 3]]
    return v, f


def g_tube(r0, r1, h, sides=8, center=(0, 0, 0), phase=0.0):
    """沿 Y 轴的棱柱/锥台。r0 底（y 小），r1 顶（y 大）。返回侧壁 quad + 端盖。"""
    cx, cy, cz = center
    v = []
    for i in range(sides):
        a = 2 * math.pi * i / sides + phase
        v.append([cx + r0 * math.cos(a), cy - h / 2, cz + r0 * math.sin(a)])
    for i in range(sides):
        a = 2 * math.pi * i / sides + phase
        v.append([cx + r1 * math.cos(a), cy + h / 2, cz + r1 * math.sin(a)])
    f = []
    for i in range(sides):
        j = (i + 1) % sides
        f.append([i, j, sides + j, sides + i])
    f.append(list(range(sides - 1, -1, -1)))
    f.append(list(range(sides, 2 * sides)))
    return np.array(v, float), f


def g_wedge(w, h, d, taper=0.45, center=(0, 0, 0)):
    """前后收窄的楔形（胸甲 / 肩甲 / 裙甲用）。+Z 面窄。"""
    x, y, z = w / 2, h / 2, d / 2
    cx, cy, cz = center
    tx = x * taper
    ty = y * 0.85
    v = np.array([
        [cx - x, cy - y, cz - z], [cx + x, cy - y, cz - z],
        [cx + x, cy - y, cz + z], [cx - x, cy - y, cz + z],
        [cx - tx, cy + ty, cz - z], [cx + tx, cy + ty, cz - z],
        [cx + tx, cy + ty, cz + z], [cx - tx, cy + ty, cz + z],
    ], float)
    f = [[0, 1, 2, 3], [7, 6, 5, 4], [4, 5, 1, 0],
         [5, 6, 2, 1], [6, 7, 3, 2], [7, 4, 0, 3]]
    return v, f


def g_plate(pts, thick, axis='x'):
    """由 2D 轮廓（xy 或 yz）挤出的薄板，用于翼状推进器、刀身。"""
    pts = np.asarray(pts, float)
    n = len(pts)
    v = []
    for t in (-thick / 2, thick / 2):
        for p in pts:
            if axis == 'x':
                v.append([t, p[0], p[1]])
            elif axis == 'y':
                v.append([p[0], t, p[1]])
            else:
                v.append([p[0], p[1], t])
    v = np.array(v, float)
    f = []
    if axis == 'x':  # 轮廓在 (y,z)，法线沿 x
        f.append(list(range(n - 1, -1, -1)))
        f.append(list(range(n, 2 * n)))
    elif axis == 'y':
        f.append(list(range(n)))
        f.append(list(range(2 * n - 1, n - 1, -1)))
    else:
        f.append(list(range(n)))
        f.append(list(range(2 * n - 1, n - 1, -1)))
    for i in range(n):
        j = (i + 1) % n
        f.append([i, j, n + j, n + i])
    return v, f


def g_chamfer(w, h, d, c=None, center=(0, 0, 0)):
    """倒角盒（chamfer / 面取り）—— 本管线唯一能造出「钝角棱」的图元。

    ★ 为什么必须有它：审计实测，现有 4 个图元造出的 5736 条棱里，二面角落在
      8°~30°（倒角斜面）的占 **0.00%**，落在 75°~105°（近直角）的占 39.7%。
      也就是说模型上**一条倒角都没有**，全是积木边。而真实装甲板的裸露外棱
      一律是倒角或折边 —— 这是「矩形块拼接感」最直接的成因。

    几何：8 个角沿三条边各退 c，得到 24 个顶点；6 个主面（缩成四边形）
          + 12 条棱上的倒角斜条 + 8 个角三角 = 26 面。
          所有外棱二面角 = 135°（落进 8°~30° 之外的「折面」带需要 c 更大，
          取 c≈0.09×最小边时斜条与主面夹角约 152°，与 图元核 夹角 135°）。

    绕序不做要求：prim_to_tris 用「法线必须背离图元重心」重新定向，
    这对凸体是可靠的。

    c 的取法：特写帧实测 62 px/m，屏幕 2 px ≈ 0.032 m。取 c = 0.06~0.09×最小边，
    并保证不小于 0.035 m，否则倒角在成片里看不见（会退化成亚像素闪烁）。
    """
    x, y, z = w / 2.0, h / 2.0, d / 2.0
    m = min(w, h, d)
    if c is None:
        c = 0.075 * m
    c = min(max(c, 0.0), 0.42 * m)
    cx, cy, cz = center
    hx, hy, hz = x - c, y - c, z - c

    v = []
    A = {}
    B = {}
    C = {}
    for sx in (-1, 1):
        for sy in (-1, 1):
            for sz in (-1, 1):
                A[(sx, sy, sz)] = len(v)
                v.append([cx + sx * x, cy + sy * hy, cz + sz * hz])
                B[(sx, sy, sz)] = len(v)
                v.append([cx + sx * hx, cy + sy * y, cz + sz * hz])
                C[(sx, sy, sz)] = len(v)
                v.append([cx + sx * hx, cy + sy * hy, cz + sz * z])

    f = []
    for sx in (-1, 1):                      # 左右主面
        f.append([A[(sx, -1, -1)], A[(sx, 1, -1)], A[(sx, 1, 1)], A[(sx, -1, 1)]])
    for sy in (-1, 1):                      # 上下主面
        f.append([B[(-1, sy, -1)], B[(1, sy, -1)], B[(1, sy, 1)], B[(-1, sy, 1)]])
    for sz in (-1, 1):                      # 前后主面
        f.append([C[(-1, -1, sz)], C[(1, -1, sz)], C[(1, 1, sz)], C[(-1, 1, sz)]])
    for sy in (-1, 1):                      # 沿 x 的 4 条棱
        for sz in (-1, 1):
            f.append([B[(-1, sy, sz)], B[(1, sy, sz)], C[(1, sy, sz)], C[(-1, sy, sz)]])
    for sx in (-1, 1):                      # 沿 y 的 4 条棱
        for sz in (-1, 1):
            f.append([A[(sx, -1, sz)], A[(sx, 1, sz)], C[(sx, 1, sz)], C[(sx, -1, sz)]])
    for sx in (-1, 1):                      # 沿 z 的 4 条棱
        for sy in (-1, 1):
            f.append([A[(sx, sy, -1)], A[(sx, sy, 1)], B[(sx, sy, 1)], B[(sx, sy, -1)]])
    for k, a in A.items():                  # 8 个角三角
        f.append([a, B[k], C[k]])

    # 统一绕序：逐面用 Newell 法算外法线，与「面重心 − 体心」同向才保留。
    # 不统一的话渲染仍然正确（prim_to_tris 会按「背离重心」重新定向），
    # 但任何依赖绕序的计算（体积、法线贴花、双面渲染）都会错。
    vv = np.array(v, float)
    piv = vv.mean(axis=0)
    out = []
    for face in f:
        p = vv[face]
        n = np.zeros(3)
        for i in range(len(p)):
            a, b = p[i], p[(i + 1) % len(p)]
            n[0] += (a[1] - b[1]) * (a[2] + b[2])
            n[1] += (a[2] - b[2]) * (a[0] + b[0])
            n[2] += (a[0] - b[0]) * (a[1] + b[1])
        out.append(face if n @ (p.mean(axis=0) - piv) > 0 else face[::-1])
    return vv, out


def g_loft(secs, sides=14, expo=3.0, cap=True):
    """沿 Y 轴的超椭圆放样体 —— 用「一圈一圈的截面」代替「堆盒子」。

    为什么这是「块感」的主解：一个 14 边、指数 3.0 的超椭圆断面，
    相邻侧面法线相差 360/14 ≈ 25.7°，正好落进 8°~30° 的倒角带。
    也就是说**放样体周身都是钝角折面**，视觉上就是「方中带圆的装甲」，
    而且这些折面是分部在整圈上的（审计里「顶视方位桶数」会从 36 冲到 100+）。

    secs : [(y, rx, rz), ...] 或 [(y, rx, rz, cx, cz), ...]，按 y 递增
    expo : 2.0=椭圆；3.0~4.5=装甲断面（方中带圆）；6+=接近矩形
    sides: 边数。14 是折面感与面数的平衡（14 边 → 每个折面 25.7°）
    cap  : 是否封两端

    注意：故意**不走平滑法线**。smooth 会把 25.7° 的折面抹成渐变，
    那就回到「一块有渐变的板」了 —— SEED 的装甲是明确的分面，不是圆角。
    """
    n = len(secs)
    p2 = 2.0 / expo
    v = []
    for s in secs:
        yy, rx, rz = s[0], s[1], s[2]
        ox = s[3] if len(s) > 3 else 0.0
        oz = s[4] if len(s) > 4 else 0.0
        for i in range(sides):
            t = 2.0 * math.pi * i / sides
            co, si = math.cos(t), math.sin(t)
            px = math.copysign(abs(co) ** p2, co) * rx
            pz = math.copysign(abs(si) ** p2, si) * rz
            v.append([ox + px, yy, oz + pz])
    f = []
    for k in range(n - 1):
        b0, b1 = k * sides, (k + 1) * sides
        for i in range(sides):
            j = (i + 1) % sides
            f.append([b0 + i, b0 + j, b1 + j, b1 + i])
    if cap:
        f.append(list(range(sides - 1, -1, -1)))
        f.append(list(range((n - 1) * sides, n * sides)))
    return np.array(v, float), f


# ---------------------------------------------------------------- 节点

class Node:
    """层级节点：局部变换 = T @ Rx @ Ry @ Rz @ S"""

    def __init__(self, name='', prim=None, mat=None, pos=(0, 0, 0),
                 rot=(0, 0, 0), scl=1.0, parent=None, hide=False, smooth=None):
        self.name = name
        self.prim = prim
        self.mat = mat or MAT['armor_w']
        self.pos = np.asarray(pos, float)
        self.rot = np.asarray(rot, float)
        self.scl = scl
        self.parent = parent
        self.hide = hide
        self.smooth = smooth      # None=硬边 | 'tube'=侧面平滑（M1 顶点法线用）
        self.children = []
        if parent is not None:
            parent.children.append(self)

    def local(self):
        if np.isscalar(self.scl):
            s = S(self.scl)
        else:
            s = S(*self.scl)
        return chain(T(*self.pos), Rx(self.rot[0]), Ry(self.rot[1]),
                     Rz(self.rot[2]), s)

    def world(self):
        m = self.local()
        p = self.parent
        while p is not None:
            m = p.local() @ m
            p = p.parent
        return m


# ---------------------------------------------------------------- 材质

class Mat:
    def __init__(self, rgb, emissive=0.0, rim=0.0, spec=0.0):
        self.rgb = np.array(rgb, float)
        self.emissive = emissive
        self.rim = rim
        self.spec = spec


MAT = {
    # 机体：白主色 + 蓝 + 红点缀（方案 4.1 造型语法）
    'armor_w':   Mat((0.905, 0.918, 0.938)),          # 主装甲白
    'armor_w2':  Mat((0.780, 0.800, 0.830)),          # 次级白（分块）
    'armor_blue': Mat((0.118, 0.286, 0.545)),         # 蓝装甲
    'armor_blu2': Mat((0.075, 0.196, 0.400)),
    'armor_red': Mat((0.706, 0.157, 0.157)),          # 红点缀
    'frame':     Mat((0.235, 0.251, 0.278)),          # 裸露骨架深灰
    'frame_d':   Mat((0.152, 0.165, 0.188)),
    'thrust':    Mat((0.180, 0.210, 0.260)),
    'visor':     Mat((0.35, 0.92, 1.0), emissive=1.0),   # 双眼传感器
    'sensor':    Mat((1.0, 0.62, 0.22), emissive=0.9),   # 橙警示灯
    'beam':      Mat((0.55, 0.95, 1.0), emissive=1.0),   # 光束
    'saber':     Mat((0.62, 0.97, 1.0), emissive=1.0),
    'flame':     Mat((1.0, 0.72, 0.35), emissive=1.0),
    'flame_b':   Mat((0.45, 0.85, 1.0), emissive=1.0),
    'city_warm': Mat((0.30, 0.27, 0.27)),
}


# ---------------------------------------------------------------- 场景收集

class Tris:
    """收集世界空间多边形（含已定向的外法线）。"""

    def __init__(self):
        self.pts = []      # list of (N,3) arrays
        self.cols = []     # list of (r,g,b) 0-1
        self.emis = []     # list of float
        self.cens = []     # list of (3,)
        self.nrms = []     # list of (3,) 已定向外法线

    def add(self, world_pts, rgb, emissive, nrm=None):
        self.pts.append(world_pts)
        self.cols.append(rgb)
        self.emis.append(emissive)
        self.cens.append(world_pts.mean(axis=0))
        self.nrms.append(nrm if nrm is not None else np.array([0.0, 1.0, 0.0]))

    def merge(self, other):
        self.pts += other.pts
        self.cols += other.cols
        self.emis += other.emis
        self.cens += other.cens
        self.nrms += other.nrms

    def __len__(self):
        return len(self.pts)


def collect(node, out, mat_override=None, xform=None):
    """递归把节点树展开成世界多边形。

    外法线定向规则：法线必须指向背离该图元自身中心的方向。
    这比依赖顶点绕序可靠——box / tube / wedge 的绕序并不统一。
    """
    if node.hide:
        return
    m = node.local() if xform is None else xform @ node.local()
    if node.prim is not None:
        v, faces = node.prim
        vw = (m @ np.hstack([v, np.ones((len(v), 1))]).T).T[:, :3]
        pivot = vw.mean(axis=0)
        mat = mat_override or node.mat
        for f in faces:
            pts = vw[f]
            n = np.cross(pts[1] - pts[0], pts[2] - pts[0])
            ln = np.linalg.norm(n)
            if ln < 1e-9:
                continue
            n = n / ln
            if n @ (pts.mean(axis=0) - pivot) < 0:
                n = -n
            out.add(pts, mat.rgb, mat.emissive, n)
    for c in node.children:
        collect(c, out, mat_override, m)


# ---------------------------------------------------------------- 光照

LIGHT_KEY = np.array([0.42, 0.72, 0.55])
LIGHT_KEY /= np.linalg.norm(LIGHT_KEY)
LIGHT_FILL = np.array([-0.62, 0.30, -0.72])
LIGHT_FILL /= np.linalg.norm(LIGHT_FILL)
C_KEY = np.array([1.0, 0.97, 0.90])
C_FILL = np.array([0.42, 0.62, 0.92])

LEVELS = np.array([0.42, 0.60, 0.78, 0.94, 1.0])


def cel_shade(nrm, base, emis, rim_k):
    """赛璐璐分级：漫反射量化到离散档位 + 冷暖补光 + 逆光边缘。"""
    d_key = max(0.0, float(nrm @ LIGHT_KEY))
    d_fill = max(0.0, float(nrm @ LIGHT_FILL))
    lam = d_key * 0.80 + d_fill * 0.25 + 0.42
    q = LEVELS[np.argmin(np.abs(LEVELS - lam))]
    shade = 0.62 * q + 0.38 * lam
    col = base * shade
    col = col + base * d_fill * 0.16 * C_FILL
    if rim_k > 0:
        col = col + np.array([0.34, 0.55, 0.78]) * rim_k * (1.0 - d_key) * 0.62
    if emis > 0:
        col = base * (0.40 + 0.60 * emis) + base * emis * 0.75
    return np.clip(col, 0, 4.0)


# ---------------------------------------------------------------- 渲染器

def _clip_near(p, near_c):
    """Sutherland–Hodgman 近平面裁剪（相机空间，保留 z <= near_c）。"""
    n = len(p)
    out = []
    for i in range(n):
        a = p[i]
        b = p[(i + 1) % n]
        ina = a[2] <= near_c
        inb = b[2] <= near_c
        if ina:
            out.append(a)
        if ina != inb:
            denom = b[2] - a[2]
            if abs(denom) < 1e-9:
                continue
            t = (near_c - a[2]) / denom
            out.append(a + (b - a) * t)
    if len(out) < 3:
        return None
    return np.array(out)


class Renderer:
    def __init__(self, W=1280, H=720, ss=2, fov=40.0):
        self.W, self.H, self.ss, self.fov = W, H, ss, fov
        self.WS, self.HS = W * ss, H * ss
        self.f = 1.0 / math.tan(fov * D2R / 2)
        self._vig = None

    # ---- 背景：天空渐变（含地平线光晕）
    def sky(self, top=(0.055, 0.075, 0.115), bot=(0.42, 0.50, 0.60),
            horizon_y=0.62, sun=None, sun_col=(1.0, 0.62, 0.35), sun_k=0.5):
        W, H = self.WS, self.HS
        y = np.linspace(0, 1, H)[:, None]
        t = np.clip(y / max(horizon_y, 1e-3), 0, 1)[:, :] ** 1.35
        img = (np.array(top)[None, None, :] * (1 - t[:, :, None])
               + np.array(bot)[None, None, :] * t[:, :, None])
        img = np.repeat(img, W, axis=1)
        # 地平线亮带
        band = np.exp(-((y[:, 0] - horizon_y) ** 2) / (2 * 0.05 ** 2))
        img += band[:, None, None] * (np.array([0.10, 0.088, 0.078])[None, None, :] * sun_k * 2)
        if sun:
            sx, sy, sr = sun
            xx = np.arange(W)[None, :] / W
            yy = y
            d = np.sqrt((xx - sx) ** 2 + ((yy - sy) * H / W) ** 2)
            glow = np.exp(-(d ** 2) / (2 * sr ** 2)) * 0.30 + \
                np.exp(-(d ** 2) / (2 * (sr * 3.4) ** 2)) * 0.46
            img += glow[:, :, None] * np.array(sun_col)[None, None, :] * sun_k
        return Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8))

    def render(self, tris, cam_m, base=None, fog_col=(0.34, 0.40, 0.49),
              fog_a=0.0026, fog_b=0.00005, near=0.6, glow_radius=14,
              glow_gain=1.0, vignette=0.35, clip=True, exposure=1.0):
        W, H, SS = self.W, self.H, self.ss
        WS, HS = self.WS, self.HS
        img = base if base is not None else self.sky()
        if img.size != (WS, HS):
            img = img.resize((WS, HS), Image.BILINEAR)
        dr = ImageDraw.Draw(img)
        glow = Image.new('RGB', (WS, HS), (0, 0, 0))
        dg = ImageDraw.Draw(glow)

        if len(tris) == 0:
            return img.resize((W, H), Image.LANCZOS)

        nr = len(tris)
        cam_pts = [(cam_m @ np.hstack([p, np.ones((len(p), 1))]).T).T[:, :3]
                   for p in tris.pts]
        cam_cen = (cam_m @ np.hstack([np.array(tris.cens),
                                      np.ones((nr, 1))]).T).T[:, :3]
        # 法线只做旋转
        R3 = cam_m[:3, :3]
        cam_nrm = np.array(tris.nrms) @ R3.T

        # ★ 排序方向修正（2026-11-06）：原为 argsort(-z)，即 z 降序 = 近的先进队列，
        #   远的后画并覆盖近的 —— 整帧是反的。实测 t=1.583 有 79328 个像素
        #   （机体投影的 87%）显示的是被遮挡的背面表面。相机空间 z 前为负，
        #   所以「远先画」= z 升序。
        order = np.argsort(cam_cen[:, 2])
        scx, scy = WS / 2, HS / 2
        fc = self.f * HS / 2
        fog_arr = np.array(fog_col)
        near_c = -near

        for i in order:
            cen = cam_cen[i]
            if cen[2] > near_c:
                continue
            n = cam_nrm[i]
            view = cen / (np.linalg.norm(cen) + 1e-12)
            if n @ view > -0.015:      # 背面剔除
                continue
            p = cam_pts[i]
            if np.all(p[:, 2] > near_c):
                continue
            if not np.all(p[:, 2] <= near_c):
                if not clip:
                    continue
                p = _clip_near(p, near_c)
                if p is None:
                    continue
            z = -p[:, 2]
            sx = (p[:, 0] / z) * fc + scx
            sy = scy - (p[:, 1] / z) * fc
            if sx.max() < -8 or sx.min() > WS + 8 or sy.max() < -8 or sy.min() > HS + 8:
                continue
            dist = float(np.linalg.norm(cen))
            fogf = min(0.97, 1.0 - math.exp(-fog_a * dist - fog_b * dist * dist))
            emis = tris.emis[i]
            base_col = tris.cols[i]
            rim = min(1.0, max(0.0, 1.0 - abs(float(n @ view)) * 3.0))
            col = cel_shade(n, base_col, emis, rim if emis < 0.5 else 0.0)
            if emis < 0.5:
                col = col * (1 - fogf) + fog_arr * fogf
            else:
                col = col + fog_arr * fogf * 0.22
            rgb = tuple(int(min(255, max(0, c * 255))) for c in col[:3])
            poly = list(zip(sx.tolist(), sy.tolist()))
            if emis >= 0.5:
                dg.polygon(poly, fill=rgb)
                dr.polygon(poly, fill=rgb)
            else:
                dr.polygon(poly, fill=rgb,
                           outline=tuple(int(c * 0.60) for c in rgb))

        if glow_gain > 0:
            g = glow.filter(ImageFilter.GaussianBlur(glow_radius))
            g2 = glow.filter(ImageFilter.GaussianBlur(glow_radius * 3.4))
            arr = (np.asarray(img, float)
                   + np.asarray(g, float) * glow_gain * 0.80
                   + np.asarray(g2, float) * glow_gain * 0.60)
        else:
            arr = np.asarray(img, float)

        if vignette > 0:
            if self._vig is None or self._vig.shape[:2] != (HS, WS):
                yy, xx = np.mgrid[0:HS, 0:WS]
                dx = (xx - WS / 2) / (WS / 2)
                dy = (yy - HS / 2) / (HS / 2)
                v = 1.0 - vignette * np.clip((dx ** 2 * 0.75 + dy ** 2 * 1.0) - 0.15, 0, 1.4)
                self._vig = v[:, :, None]
            arr = arr * self._vig
            if exposure != 1.0:
                arr = arr * exposure

        out = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
        return out.resize((W, H), Image.LANCZOS)
