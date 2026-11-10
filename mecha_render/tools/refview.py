"""tools/refview.py — 把外部参考模型（OBJ）转成侧背设计的**正交视图 + 截面尺**

为什么需要这个文件
  选定方案 A（补侧背参考）后，「参考」不能只是看图：单视图重建真正缺的是
  **每个高度上的宽深比**——躯干多厚、上臂多粗、小腿前后多长。
  外部生产模型正好带着这个先验，把它量出来，S2 的多截面放样才有数可依。

它做三件事
  1. 读 OBJ（三角化、去重、居中、缩放到机高 10 世界单位）；
  2. 出 0/90/180/270/俯视/30° 六格正交图（灰模无贴图，只看结构）；
  3. 沿高度切 40 带，量每带的 x 宽度、z 深度、宽深比，存 JSON。

单位约定
  OBJ 是 3ds Max 导出、厘米单位、Y 轴向上。脚本内部一律换成
  「机高 = 10、脚底 = y0、+z 朝观察者」，与 relief_v2 的 world 尺度一致。

用法
  python3 tools/refview.py <model.obj> <tag>
  产物 out/ref/<tag>_sheet.png、out/ref/<tag>_profile.json
"""
import json
import math
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'tools'))

from gfx.gbuffer import rasterize                    # noqa: E402
from gfx.mesh import Mesh                            # noqa: E402
from r3d import Mat, Renderer, look_at               # noqa: E402

OUT = os.path.join(HERE, 'out', 'ref')
os.makedirs(OUT, exist_ok=True)

H_WORLD = 10.0          # 归一化后机高
PANEL = (470, 760)      # 单格宽高


# ---------------------------------------------------------------- 读 OBJ
def load_obj(path):
    """只取 v / f。f 支持 `v`、`v/t`、`v//n`、`v/t/n`，多边形按扇形三角化。"""
    V, tris = [], []
    with open(path, 'r', errors='ignore') as f:
        for line in f:
            if line.startswith('v '):
                p = line.split()
                V.append((float(p[1]), float(p[2]), float(p[3])))
            elif line.startswith('f '):
                idx = []
                for tok in line.split()[1:]:
                    s = tok.split('/')[0]
                    if not s:
                        continue
                    i = int(s)
                    idx.append(i - 1 if i > 0 else len(V) + i)
                for k in range(1, len(idx) - 1):
                    tris.append((idx[0], idx[k], idx[k + 1]))
    return np.array(V, np.float64), np.array(tris, np.int64)


def normalize(V):
    """居中 + 缩放到机高 H_WORLD，返回 (V', meta)。脚底落 y=0，水平居中到 x/z 中心。"""
    lo, hi = V.min(0), V.max(0)
    h = float(hi[1] - lo[1])
    s = H_WORLD / max(h, 1e-9)
    cx, cz = 0.5 * (lo[0] + hi[0]), 0.5 * (lo[2] + hi[2])
    V2 = V.copy()
    V2[:, 0] = (V[:, 0] - cx) * s
    V2[:, 1] = (V[:, 1] - lo[1]) * s
    V2[:, 2] = (V[:, 2] - cz) * s
    meta = dict(raw_height=h, scale=s,
                width=float((hi[0] - lo[0]) * s),
                depth=float((hi[2] - lo[2]) * s))
    return V2, meta


# ---------------------------------------------------------------- 截面尺
def profile(V, nb=40):
    """沿高度切 nb 带，量每带的 x 宽、z 深。返回 [(u, width, depth, w/d)]。

    u = 0 在脚底、1 在头顶。宽度取 0.5%~99.5% 分位，避开个别飞点。
    """
    y0, y1 = float(V[:, 1].min()), float(V[:, 1].max())
    H = max(y1 - y0, 1e-9)
    rows = []
    for k in range(nb):
        a = y0 + H * k / nb
        b = y0 + H * (k + 1) / nb
        m = (V[:, 1] >= a) & (V[:, 1] <= b)
        if m.sum() < 8:
            rows.append((round((a + b) * 0.5 / H, 3), 0.0, 0.0, 0.0))
            continue
        x = np.percentile(V[m, 0], [0.5, 99.5])
        z = np.percentile(V[m, 2], [0.5, 99.5])
        w, d = float(x[1] - x[0]), float(z[1] - z[0])
        rows.append((round(float((a + b) * 0.5 - y0) / H, 3), round(w, 4),
                     round(d, 4), round(d / w, 3) if w > 1e-6 else 0.0))
    return rows


# ---------------------------------------------------------------- 出图
def _to_mesh(V, tris):
    """把三角数组包成 arrays() 接口，绕过逐三角 add（37 万面逐条 append 会慢一个量级）。

    不能直接给 Mesh 塞 ndarray：arrays() 里有 `if not self.P` 的列表判空，
    对 ndarray 会抛 ValueError。这里用一个只有 arrays() 的轻量替身。
    """
    P = V[tris]                                       # (n,3,3)
    n = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
    L = np.linalg.norm(n, axis=1, keepdims=True)
    keep = (L[:, 0] > 1e-12)
    P = P[keep].astype(np.float32)
    n = (n[keep] / L[keep]).astype(np.float32)
    N = np.repeat(n[:, None, :], 3, 1)
    T_ = np.zeros((len(P), 3, 2), np.float32)
    mi = np.zeros((len(P),), np.int32)
    Fi = np.arange(len(P), dtype=np.int32)
    base = np.array([[0.78, 0.79, 0.80]], np.float32)
    emis = np.zeros((1,), np.float32)

    class _Bare:
        def arrays(self):
            return P, N, T_, mi, Fi, base, emis

        def __len__(self):
            return len(P)

    return _Bare()


def _rot(P, N, yaw, pitch=0.0):
    cy, sy = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    cp, sp = math.cos(math.radians(pitch)), math.sin(math.radians(pitch))
    Rx = np.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]])
    R = Rx @ Ry
    return P @ R.T, N @ R.T


def render_view(mesh, yaw, pitch=0.0, label=''):
    """正交视图：相机拉远 + 窄 FOV ≈ 正交。灰模型 lambert + 半球环境光。"""
    W, H = PANEL
    dist = 30.0 * H_WORLD
    fov = 2.0 * math.degrees(math.atan((H_WORLD * 0.72) / dist))
    rd = Renderer(W, H, ss=1, fov=fov)
    cy = H_WORLD * 0.5
    cm = look_at((0.0, cy, dist), (0.0, cy, 0.0), roll=0)

    P, N, T_, mi, Fi, base, _ = mesh.arrays()
    Pr, Nr = _rot(P, N, yaw, pitch)
    gb, _ = rasterize(Pr, Nr, T_, mi, Fi, cm, fov, rd.WS, rd.HS)

    cov = gb.midx >= 0
    nn = gb.nrm.copy()
    nn /= np.maximum(np.linalg.norm(nn, axis=-1, keepdims=True), 1e-9)
    L = np.array([-0.42, 0.58, 0.70])
    L /= np.linalg.norm(L)
    lam = np.clip(nn @ L, 0, 1)
    amb = 0.5 + 0.28 * np.clip(nn[..., 1], -1, 1)      # 半球环境：天光下亮
    g = 0.24 + 0.62 * lam + 0.24 * amb
    img = np.clip(g * 255, 0, 255).astype(np.uint8)
    out = np.full((H, W, 3), 255, np.uint8)
    out[cov] = img[cov][:, None].repeat(3, 1)
    # 轮廓描一道深灰，便于看剪影
    er = cov.copy()
    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        er &= np.roll(np.roll(cov, dy, 0), dx, 1)
    edge = cov & ~er
    out[edge] = (60, 64, 68)
    return out, int(cov.sum())


def sheet(path, panels, gap=10):
    h = max(p.shape[0] for p in panels)
    w = sum(p.shape[1] for p in panels) + gap * (len(panels) - 1)
    canvas = np.full((h, w, 3), 246, np.uint8)
    x = 0
    for p in panels:
        canvas[:p.shape[0], x:x + p.shape[1]] = p
        x += p.shape[1] + gap
    Image.fromarray(canvas).save(path)
    return path


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return
    src, tag = sys.argv[1], sys.argv[2]
    V, tris = load_obj(src)
    print(f'读入 {len(V)} 顶点 / {len(tris)} 三角')
    Vn, meta = normalize(V)
    print(f'原始高 {meta["raw_height"]:.1f} → 归一化 {H_WORLD}；'
          f'宽 {meta["width"]:.2f} 深 {meta["depth"]:.2f}（世界单位）')

    mesh = _to_mesh(Vn, tris)
    print(f'有效三角 {len(mesh)}')

    views = [(0, 0, 'front'), (90, 0, 'side_R'), (180, 0, 'back'),
             (270, 0, 'side_L'), (0, 90, 'top'), (30, 0, 'q34')]
    panels = []
    for yaw, pitch, name in views:
        img, px = render_view(mesh, yaw, pitch, name)
        panels.append(img)
        print(f'  {name:<7} yaw={yaw:>3} pitch={pitch:>2}  覆盖 {px}px')

    p = sheet(os.path.join(OUT, f'{tag}_sheet.png'), panels)
    print(f'  → {p}')

    prof = profile(Vn, 40)
    jp = os.path.join(OUT, f'{tag}_profile.json')
    with open(jp, 'w') as f:
        json.dump(dict(meta=meta, profile=prof), f, ensure_ascii=False, indent=1)
    print(f'  → {jp}')
    print('\n高度带截面（u=脚底0→头顶1）：')
    for u, w, d, r in prof[::2]:
        bar = '#' * int(round(w * 12))
        print(f'  u={u:.2f}  宽 {w:5.2f}  深 {d:5.2f}  深/宽 {r:4.2f}  {bar}')


if __name__ == '__main__':
    main()
