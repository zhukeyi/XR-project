"""
tools/painter_ref.py — v1 画家算法的「参考实现」，输出逐像素面 id 图

为什么要单独写一份：
  要比对「结构是否一致」，不能拿颜色比 —— 着色模型本来就改动了（逐像素法线）。
  正确做法是把两边的「这个像素属于哪个三角」拿出来对，id 对得上才是结构一致。

两个方向都支持：
  far_first=True  —— 正确画家算法（远先画，近覆盖）。应为 z-buffer 的等价物
  far_first=False —— r3d.py 现在的行为（近先画，远覆盖）。用来量化它的错误量

结论（实测，t=1.583 机甲单件）：
  r3d.py 的 order = argsort(-cam_cen[:,2]) 是反的，应为 argsort(cam_cen[:,2])。
"""
import math

import numpy as np
from PIL import Image, ImageDraw

from gfx.gbuffer import _clip_near


def painter_id_map(P, N, cam_m, fov, W, H, far_first=True, near=0.6,
                   backface_eps=-1e-6):
    """返回 (H,W) int32，值是三角在入参数组里的下标；-1 表示背景。

    完全复刻 r3d.Renderer.render() 的剔除与排序，只把「填色」换成「填 id」。
    """
    cam = np.asarray(cam_m, np.float64)
    Tn = len(P)
    ph = np.concatenate([P.reshape(-1, 3), np.ones((Tn * 3, 1))], axis=1)
    Vc = (cam @ ph.T).T[:, :3].reshape(Tn, 3, 3)
    Nc = (np.asarray(N, np.float64).reshape(-1, 3) @ cam[:3, :3].T).reshape(Tn, 3, 3)

    Ts = np.zeros((Tn, 3, 2), np.float32)
    Ms = np.arange(Tn, dtype=np.int32)
    Fs = np.arange(Tn, dtype=np.int32)

    zc = -Vc[:, :, 2]
    cross = np.any(zc <= near, axis=1)
    if cross.any():
        Vc, Nc, Ts, Ms, Fs, _ = _clip_near(Vc, Nc, Ts, Ms, Fs, near, cross)

    cen = Vc.mean(axis=1)
    fn = np.cross(Vc[:, 1] - Vc[:, 0], Vc[:, 2] - Vc[:, 0])
    fl = np.linalg.norm(fn, axis=1)
    fn = fn / np.maximum(fl, 1e-9)[:, None]
    avg = Nc.mean(axis=1)
    fn[(fn * avg).sum(axis=1) < 0] *= -1.0
    view = cen / np.maximum(np.linalg.norm(cen, axis=1), 1e-9)[:, None]

    # backface_eps=-1e-6 与 gbuffer 对齐；传 -0.015 才是 r3d 的原始行为
    ok = (fn * view).sum(axis=1) < backface_eps
    ok &= (fl >= 1e-9)

    z = -Vc[:, :, 2]
    f = 1.0 / math.tan(fov * math.pi / 360.0)
    fc = f * (H * 0.5)
    cx, cy = W * 0.5, H * 0.5
    sx = (Vc[:, :, 0] / z) * fc + cx
    sy = cy - (Vc[:, :, 1] / z) * fc
    ok &= (sx.max(axis=1) > -8) & (sx.min(axis=1) < W + 8)
    ok &= (sy.max(axis=1) > -8) & (sy.min(axis=1) < H + 8)

    # r3d 的距离用面中心到相机原点的欧氏距离，但排序键是 cam_cen[:,2]
    key = cen[:, 2]
    idx = np.nonzero(ok)[0]
    # far_first：z 最负（最远）的先画
    order = idx[np.argsort(key[idx])] if far_first else idx[np.argsort(-key[idx])]

    img = Image.new('I', (W, H), -1)
    d = ImageDraw.Draw(img)
    for i in order:
        poly = [(float(sx[i, k]), float(sy[i, k])) for k in range(3)]
        d.polygon(poly, fill=int(Fs[i]))
    return np.asarray(img, np.int32)
