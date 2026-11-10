"""
test_m1.py — M1 验收：v1（画家算法）vs v2（z-buffer + 延迟着色）

判据不是「像素差多少」，那没有意义 —— 着色模型本来就被有意改动了
（逐像素法线 vs 逐面法线）。真正的判据是四件事：

  1 结构一致   逐像素比较「这个像素属于哪个三角形」的 id，不看颜色
  2 无穿模     不一致的像素里，z-buffer 显示的表面是否一律比画家算法更近
               （单边检验：若 100% 更近，则错的是画家算法，z-buffer 是对的）
  3 无空洞     前景内部被完全包围的空白像素（floodfill 从边框灌，灌不到的就是洞）
  4 性能       单帧 ≤ 800 ms

第一条的参考基线是 tools/painter_ref.py 提供的「正确画家算法」重放。
它自己也只做到 ~82% —— 剩下 18% 是面与面相互穿插，任何排序都解决不了，
这正是 v1 画质天花板的来源，也是 M1 存在的理由。

用法：
  python3 test_m1.py            # t=38/24，与 frames/f_0038.png 同帧
  python3 test_m1.py 5.5        # 指定时间
  python3 test_m1.py 1.583 --ss 1
"""
import math
import os
import sys
import time

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import film2 as F
import mecha_model as MM
from r3d import Renderer, Tris, collect, look_at
from gfx.mesh import Mesh, collect2, from_tris
from gfx.gbuffer import rasterize
from gfx import shade as SH
from tools.painter_ref import painter_id_map

FOG = dict(fog_col=(0.132, 0.158, 0.198), fog_a=0.0016, fog_b=0.000008)
SKY = dict(top=(0.030, 0.040, 0.070), bot=(0.215, 0.243, 0.292),
           horizon_y=0.55, sun=(0.78, 0.46, 0.34), sun_k=0.42)


# ---------------------------------------------------------------- 工具
def sky_float(rd):
    return np.asarray(rd.sky(**SKY), np.float32) / 255.0


def dilate(m, r=1):
    """方形结构元膨胀，纯 numpy，避免 scipy 依赖。"""
    out = m.copy()
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if dy == 0 and dx == 0:
                continue
            s = np.zeros_like(m)
            s[max(0, dy):m.shape[0] + min(0, dy),
              max(0, dx):m.shape[1] + min(0, dx)] = \
                m[max(0, -dy):m.shape[0] + min(0, -dy),
                  max(0, -dx):m.shape[1] + min(0, -dx)]
            out |= s
    return out


def holes(mask):
    """前景内部被包围的空白像素 —— 行程 + 并查集的四连通判定，全分辨率精确。

    不能降采样：机体上 1~2px 的散热缝在 1/4 分辨率下会被挤掉，误判成洞
    （实测 685 → 26476，差 38 倍）。也不能用 Pillow 的 floodfill，它在
    这版 Python 上对 'L' 图不生效（实测调用后像素零变化）。

    做法：每行把背景切成若干行程（run），上下相邻行的行程若在 x 区间相交即连通，
    并查集合并。碰到图像边界的连通块 = 外部，其余即空洞。
    """
    bg = ~mask
    H, W = bg.shape
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

    rows = []          # 每行: (starts, ends, ids)
    for y in range(H):
        row = bg[y]
        d = np.diff(np.concatenate(([0], row.astype(np.int8), [0])))
        st = np.nonzero(d == 1)[0]
        en = np.nonzero(d == -1)[0]
        ids = []
        for s, e in zip(st.tolist(), en.tolist()):
            ids.append(len(parent))
            parent.append(len(parent))
        rows.append((st, en, ids))

    outside = set()
    for y in range(H):
        st, en, ids = rows[y]
        for k, (s, e) in enumerate(zip(st.tolist(), en.tolist())):
            if s == 0 or e == W or y == 0 or y == H - 1:
                outside.add(find(ids[k]))
        if y + 1 >= H:
            continue
        st2, en2, ids2 = rows[y + 1]
        for k, (s, e) in enumerate(zip(st.tolist(), en.tolist())):
            # 与下一行各行程求区间相交（四连通：相交即连通）
            lo = np.searchsorted(en2, s + 1)
            for j in range(lo, len(st2)):
                if st2[j] >= e:
                    break
                union(ids[k], ids2[j])

    out_roots = {find(r) for r in outside}
    tot = 0
    for st, en, ids in rows:
        for s, e, i in zip(st.tolist(), en.tolist(), ids):
            if find(i) not in out_roots:
                tot += e - s
    return tot


def erode(m, r=1):
    return ~dilate(~m, r)


def cam_plane_depth(Vc, Nc, pid, xs, ys, fov, W, H):
    """求「画家算法选中的那个三角形所在平面」在该像素处的深度。

    解析求交：像素方向 d=(dx,dy,-1)，平面 n·(X-p0)=0 → t=(n·p0)/(n·d)，深度即 t。
    """
    tri = pid[ys, xs]
    n = Nc[tri].mean(axis=1)
    n = n / np.maximum(np.linalg.norm(n, axis=1), 1e-9)[:, None]
    p0 = Vc[tri].mean(axis=1)
    f = 1.0 / math.tan(fov * math.pi / 360.0)
    fc = f * (H * 0.5)
    dxv = (xs.astype(np.float32) + 0.5 - W * 0.5) / fc
    dyv = -(ys.astype(np.float32) + 0.5 - H * 0.5) / fc
    den = n[:, 0] * dxv + n[:, 1] * dyv - n[:, 2]
    num = (n * p0).sum(axis=1)
    return num / np.where(np.abs(den) < 1e-9, 1e-9, den)


# ---------------------------------------------------------------- 主流程
def main():
    t = float(sys.argv[1]) if len(sys.argv) > 1 else 38 / 24.0
    ss = 2
    if '--ss' in sys.argv:
        ss = int(sys.argv[sys.argv.index('--ss') + 1])
    W, H = 1280, 720
    rd = Renderer(W, H, ss=ss, fov=40)
    eye, tgt, fov, roll = F.camera(t)
    cm = look_at(eye, tgt, roll=roll)
    bg = sky_float(rd)
    bg_img = Image.fromarray((bg * 255).astype(np.uint8))

    # ---- v1（画家算法，排序方向已修正）
    city = F.build_city()
    all_tris = Tris()
    all_tris.merge(city)
    collect(MM.build_mecha(F.pose(t)), all_tris)
    en = Tris()
    if t > 6.6:
        collect(MM.build_enemy(F.enemy_pose(t)), en)
        all_tris.merge(en)
    t0 = time.perf_counter()
    v1 = rd.render(all_tris, cm, base=bg_img.copy(), **FOG, exposure=1.0)
    t_v1 = (time.perf_counter() - t0) * 1000

    # ---- v2
    mech = Mesh()
    collect2(MM.build_mecha(F.pose(t)), mech)
    enm = Mesh()
    if len(en):
        collect2(MM.build_enemy(F.enemy_pose(t)), enm)
    meshes = [from_tris(city), mech] + ([enm] if len(en) else [])

    Ps, Ns, Ts, MIs, FIs, bases, emis = [], [], [], [], [], [], []
    moff = foff = 0
    for m in meshes:
        P, N, T, midx, Fid, b, e = m.arrays()
        Ps.append(P)
        Ns.append(N)
        Ts.append(T)
        MIs.append(midx + moff)
        FIs.append(Fid + foff)
        bases.append(b)
        emis.append(e)
        moff += len(b)
        foff += len(Fid)
    P = np.concatenate(Ps)
    N = np.concatenate(Ns)
    T = np.concatenate(Ts)
    midx = np.concatenate(MIs)
    Fid = np.concatenate(FIs)
    base_col = np.concatenate(bases)
    mat_emis = np.concatenate(emis)

    t0 = time.perf_counter()
    gb, st = rasterize(P, N, T, midx, Fid, cm, fov, rd.WS, rd.HS)
    t_r = (time.perf_counter() - t0) * 1000
    t0 = time.perf_counter()
    hdr, glow = SH.shade(gb, base_col, mat_emis, cm, bg=bg, fov=fov, **FOG)
    t_s = (time.perf_counter() - t0) * 1000
    t0 = time.perf_counter()
    v2 = SH.to_image(hdr, glow, glow_radius=14, glow_gain=1.0,
                     vignette_k=0.35).resize((W, H), Image.LANCZOS)
    t_f = (time.perf_counter() - t0) * 1000
    t_v2 = t_r + t_s + t_f

    a1 = np.asarray(v1, np.float32)
    a2 = np.asarray(v2, np.float32)

    # ---- 1/2 结构与穿模：另跑一遍 ss=1，与画家 id 图逐像素对齐
    zb, _ = rasterize(P, N, T, midx, Fid, cm, fov, W, H)
    zid, zdep = zb.fid, zb.depth
    p_far = painter_id_map(P, N, cm, fov, W, H, far_first=True)
    p_near = painter_id_map(P, N, cm, fov, W, H, far_first=False)

    both = (zid >= 0) & (p_far >= 0)
    agree = float((zid == p_far)[both].mean())
    dis = (zid >= 0) & (p_far >= 0) & (zid != p_far)

    ph = np.concatenate([P.reshape(-1, 3), np.ones((len(P) * 3, 1))], 1)
    Vc = (cm @ ph.T).T[:, :3].reshape(-1, 3, 3)
    Nc = (N.reshape(-1, 3) @ cm[:3, :3].T).reshape(-1, 3, 3)
    ys, xs = np.nonzero(dis)
    v2_nearer = 0.0
    if len(ys):
        pd = cam_plane_depth(Vc, Nc, p_far, xs, ys, fov, W, H)
        ok = np.isfinite(pd) & (pd > 0)
        if ok.any():
            v2_nearer = float((zdep[ys[ok], xs[ok]] < pd[ok] - 0.01).mean())
    # 只统计「整块面」上的分歧：边界 1px 内深度比较无意义
    core = erode(dis, 2)
    ysc, xsc = np.nonzero(core)
    v2_nearer_core = 0.0
    if len(ysc):
        pdc = cam_plane_depth(Vc, Nc, p_far, xsc, ysc, fov, W, H)
        ok = np.isfinite(pdc) & (pdc > 0)
        if ok.any():
            v2_nearer_core = float((zdep[ysc[ok], xsc[ok]] < pdc[ok] - 0.01).mean())

    # ---- 3 轮廓与空洞（两边都取几何前景，避开 Bloom 光晕污染颜色掩膜）
    m1 = p_far >= 0          # 画家算法认为有不透明面
    m2 = zid >= 0            # z-buffer 认为有不透明面
    iou = (m1 & m2).sum() / max(1, (m1 | m2).sum())
    tol = int((m1 & ~dilate(m2, 1)).sum())
    # 空洞按最终输出分辨率统计（ss=2 的 mask 折叠成 1 像素），这才对得上眼睛看到的
    m2_img = gb.mask.reshape(H, ss, W, ss).any(axis=(1, 3))
    nh = holes(m2_img)
    nh1 = holes(m2)

    # ---- 4 着色差异（仅说明，不作判据）
    l1, l2 = a1.mean(axis=2), a2.mean(axis=2)
    bb = m1 & m2
    d = np.abs(l1 - l2)[bb] if bb.any() else np.zeros(1)

    print(f'=== t={t:.3f}  ss={ss}  {W}x{H} ===')
    print(f'  v1 面 {len(all_tris)}   v2 三角 {st.total}（三角化后）→ 绘制 {st.drawn}')
    print(f'  光栅：{st!r}')
    print(f'  [1] 结构：z-buffer vs 正确画家 id 一致率 {agree * 100:.2f}%'
          f'（画家算法上限，剩余为相互穿插）')
    print(f'      用 v3 原来的反向排序，一致率仅 '
          f'{float((zid == p_near)[both].mean()) * 100:.2f}%')
    print(f'  [2] 穿模：{int(dis.sum())} 像素两者不同（整块分歧 {int(core.sum())}），'
          f'其中 z-buffer 显示更近表面的比例 全域 {v2_nearer * 100:.2f}% / '
          f'整块 {v2_nearer_core * 100:.2f}%')
    print(f'  [3] 几何前景 IoU {iou * 100:.2f}%，容差 1px 后仅剩 {tol} px'
          f'（画家 {m1.sum()} / z-buffer {m2.sum()}）')
    print(f'      内部空洞：输出分辨率 {nh} px（ss=1 逐像素 {nh1} px，差额是掠射地面的亚像素薄片）')
    print(f'      着色差异 平均 {d.mean():.1f} 中位 {np.median(d):.1f}'
          f'（逐像素法线是有意改动：v1 一面一色，v2 连续渐变）')
    print(f'  [4] 耗时 v1 {t_v1:.0f} ms | v2 {t_v2:.0f} ms'
          f'（光栅 {t_r:.0f} + 着色 {t_s:.0f} + 合成 {t_f:.0f}）'
          f'  {"✓ 达标" if t_v2 <= 800 else "✗ 超 800ms"}')

    out = os.path.join(HERE, 'out')
    os.makedirs(out, exist_ok=True)
    v1.save(os.path.join(out, 'm1_v1.png'))
    v2.save(os.path.join(out, 'm1_v2.png'))
    dv = np.clip(np.abs(a1 - a2).max(axis=2) * 3, 0, 255).astype(np.uint8)
    Image.fromarray(dv).save(os.path.join(out, 'm1_diff.png'))
    Image.fromarray(np.where(dis, 255, 0).astype(np.uint8)).save(
        os.path.join(out, 'm1_zbuf_only.png'))
    print('  -> out/m1_v1.png  m1_v2.png  m1_diff.png  m1_zbuf_only.png')


if __name__ == '__main__':
    main()
