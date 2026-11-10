"""tools/fbx_geo.py — 最小 FBX 7.x 二进制几何解析器（只取网格，不碰骨骼/动画/材质）

为什么自己写
  本机没有 blender / assimp / trimesh，只有 numpy。而 FBX 的二进制结构其实很规整：
  每个节点是「4 个定长头 + 名字 + 属性数组 + 子节点」，属性数组用 zlib 压缩。
  参考模型只需要顶点和多边形索引，不需要蒙皮与动画，所以实现量可控。

覆盖范围（够用即可，不做通用库）
  · 节点树递归解析（13 字节空记录表示无子节点）
  · 属性类型 Y/C/I/F/D/L/f/d/l/i/b/S/R
  · Objects/Geometry 的 Vertices、PolygonVertexIndex
  · Objects/Model 的本地变换（Properties70 里的 Lcl Translation/Rotation/Scaling）
  · Connections 的 OO 关系（Model→Geometry 与 Model 的父子链）

不覆盖
  · 7.5+ 的 64 位节点头（本文件实测为 7400，走 32 位分支）
  · LayerElementUV / Normal / Material
  · 变形器、蒙皮、动画曲线

用法
  from fbx_geo import load_fbx
  V, tris, info = load_fbx('model.fbx')
"""
import struct
import zlib

import numpy as np

_ARRAY_T = {'f': ('f', 4), 'd': ('d', 8), 'l': ('q', 8), 'i': ('i', 4), 'b': ('b', 1)}
_SCALAR_T = {'Y': ('h', 2), 'C': ('?', 1), 'I': ('i', 4), 'F': ('f', 4),
             'D': ('d', 8), 'L': ('q', 8)}


class _Node:
    __slots__ = ('name', 'props', 'kids')

    def __init__(self, name):
        self.name = name
        self.props = []
        self.kids = []

    def find(self, name):
        for k in self.kids:
            if k.name == name:
                return k
        return None

    def all(self, name):
        return [k for k in self.kids if k.name == name]


def _read_prop(buf, off):
    t = chr(buf[off])
    off += 1
    if t in _SCALAR_T:
        fmt, sz = _SCALAR_T[t]
        v = struct.unpack_from('<' + fmt, buf, off)[0]
        return v, off + sz
    if t in _ARRAY_T:
        n, enc, clen = struct.unpack_from('<III', buf, off)
        off += 12
        raw = buf[off:off + clen]
        off += clen
        fmt, sz = _ARRAY_T[t]
        if enc == 1:
            raw = zlib.decompress(raw)
        a = np.frombuffer(raw, dtype='<' + fmt, count=n)
        return a, off
    if t in ('S', 'R'):
        n = struct.unpack_from('<I', buf, off)[0]
        off += 4
        v = bytes(buf[off:off + n])
        return (v.decode('utf-8', 'replace') if t == 'S' else v), off + n
    raise ValueError(f'未知属性类型 {t!r} @ {off}')


def _read_node(buf, off, wide):
    if wide:
        end, nprop, plen = struct.unpack_from('<QQQ', buf, off)
        hdr = 25
        nlen = struct.unpack_from('<B', buf, off + 24)[0]
    else:
        end, nprop, plen = struct.unpack_from('<III', buf, off)
        hdr = 13
        nlen = buf[off + 12]
    if end == 0:
        return None, 0
    name = buf[off + hdr:off + hdr + nlen].decode('ascii', 'replace')
    node = _Node(name)
    p = off + hdr + nlen
    for _ in range(nprop):
        v, p = _read_prop(buf, p)
        node.props.append(v)
    p = off + hdr + nlen + plen
    while p < end:
        kid, used = _read_node(buf, p, wide)
        if used == 0:
            p += 25 if wide else 13
            break
        node.kids.append(kid)
        p += used
    return node, end - off


def _parse(buf):
    if not buf.startswith(b'Kaydara FBX Binary'):
        raise ValueError('不是二进制 FBX（可能是 ASCII 版）')
    ver = struct.unpack_from('<I', buf, 23)[0]
    wide = ver >= 7500
    off = 27
    root = _Node('root')
    while off < len(buf):
        n, used = _read_node(buf, off, wide)
        if used == 0:
            break
        root.kids.append(n)
        off += used
    return root, ver


# ---------------------------------------------------------------- 变换
def _p70(node, key):
    """在 Properties70 里取某个 P 记录的 (x,y,z)。"""
    p70 = node.find('Properties70')
    if p70 is None:
        return None
    for p in p70.kids:
        if p.name == 'P' and p.props and p.props[0] == key and len(p.props) >= 7:
            return np.array(p.props[4:7], np.float64)
    return None


def _euler_xyz(r):
    """FBX 默认旋转序 XYZ（度）：R = Rz·Ry·Rx。"""
    a, b, c = np.radians(r)
    Rx = np.array([[1, 0, 0], [0, np.cos(a), -np.sin(a)], [0, np.sin(a), np.cos(a)]])
    Ry = np.array([[np.cos(b), 0, np.sin(b)], [0, 1, 0], [-np.sin(b), 0, np.cos(b)]])
    Rz = np.array([[np.cos(c), -np.sin(c), 0], [np.sin(c), np.cos(c), 0], [0, 0, 1]])
    return Rz @ Ry @ Rx


def load_fbx(path):
    with open(path, 'rb') as f:
        buf = f.read()
    root, ver = _parse(buf)
    objs = root.find('Objects')
    if objs is None:
        raise ValueError('没有 Objects 节点')

    models = {int(m.props[0]): m for m in objs.all('Model')}
    geos = {int(g.props[0]): g for g in objs.all('Geometry')}

    # 连接关系：OO, 子 → 父
    parent = {}
    conn = root.find('Connections')
    if conn is not None:
        for c in conn.all('C'):
            if len(c.props) >= 3 and c.props[0] == 'OO':
                parent[int(c.props[1])] = int(c.props[2])

    def world_mtx(mid, depth=0):
        m = models.get(mid)
        M = np.eye(4)
        if m is not None:
            t = _p70(m, 'Lcl Translation')
            r = _p70(m, 'Lcl Rotation')
            s = _p70(m, 'Lcl Scaling')
            T = np.eye(4)
            if t is not None:
                T[:3, 3] = t
            R = np.eye(4)
            if r is not None:
                R[:3, :3] = _euler_xyz(r)
            S = np.eye(4)
            if s is not None:
                S[:3, :3] = np.diag(s)
            M = T @ R @ S
        par = parent.get(mid)
        if par is not None and par in models and depth < 16:
            M = world_mtx(par, depth + 1) @ M
        return M

    Vs, Ts, used = [], [], []
    for gid, g in geos.items():
        vn = g.find('Vertices')
        pn = g.find('PolygonVertexIndex')
        if vn is None or pn is None:
            continue
        V = np.array(vn.props[0], np.float64).reshape(-1, 3)
        idx = np.array(pn.props[0], np.int64)
        # 负数取反再减 1 表示多边形结束
        end = idx < 0
        idx = np.where(end, -idx - 1, idx)
        tris = []
        start = 0
        for e in np.nonzero(end)[0]:
            poly = idx[start:e + 1]
            for k in range(1, len(poly) - 1):
                tris.append((poly[0], poly[k], poly[k + 1]))
            start = e + 1
        if not tris:
            continue
        # 找到引用这块 Geometry 的 Model，套上它的世界变换
        owner = [mid for mid, par in parent.items() if par == gid and mid in models]
        M = world_mtx(owner[0]) if owner else np.eye(4)
        Vw = (M @ np.hstack([V, np.ones((len(V), 1))]).T).T[:, :3]
        Vs.append(Vw)
        Ts.append(np.array(tris, np.int64) + sum(len(v) for v in Vs[:-1]))
        used.append(g.props[1] if len(g.props) > 1 else '')

    if not Vs:
        raise ValueError('没解析到网格')
    V = np.vstack(Vs)
    T = np.vstack(Ts)
    return V, T, dict(version=ver, meshes=len(Vs), names=used,
                      models=len(models), geometries=len(geos))
