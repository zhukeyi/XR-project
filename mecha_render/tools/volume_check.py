"""tools/volume_check.py — 体量门：专门用来判死「一块薄板」的验收

一、为什么需要这个文件
  上一版验收用的是 剪影 IoU（99.4%）、墨线 chamfer 距离（中位 0.00 px）、
  板面/板缝亮度对比（11:1）、转角剪影宽度变化（1.065x）。
  这四项**对一块薄板全部满分** —— 因为「剪影挤出」这种构造，输出剪影按定义
  就等于输入剪影，IoU 恒等成立。拿它验收「这是不是 3D」，在数学上不可能失败。
  那不是验收，是自证。

  所以本文件只回答一个问题：**这东西有没有体量**。

二、三个候选判据被实测否掉（留档，避免以后重犯）
  ✗ 「行截面比 = 该行 z 跨度 / 该行宽」
      薄板实测 0.34，接近阈值。原因是薄板 z 跨度恒等于板厚，而窄行（手臂）
      行宽很小，比值反被抬高 —— 这个判据**奖励薄板**。
      教训：凡以「局部宽度」为分母的量都可能反向加分，分母必须用图高这类全局尺度。
  ✗ 「3/4 面积增益 = Area(30°)/Area(0°)」
      薄板实测 1.33，合成实体只有 1.02，方向完全反了。
      原因是复杂剪影一转动，手臂与躯干之间的**背景空隙被侧面填满**，面积暴涨，
      这是纯 2D 的补洞效应，与体量无关。
  ✗ 「侧视实心度 = 侧视面积 / 侧视凸包面积」
      薄板侧视 = 竖直条带，本身就是凸的，实测 1.00，零区分度。

三、为什么原来的 V1「侧视厚度比」也被撤掉（这条最反直觉，必须留档）
  侧视厚度比 = 侧视剪影宽 / 机高。薄板实测 0.137，看着很低，好像能判死。
  但**类人形机体的上限就是 0.139**：躯干宽约 200 px、圆形截面时深度≈宽度，
  200/1437 = 0.139。也就是说这个判据在类人形上**根本不可能分辨**——
  它不是在测「有没有体量」，是在测「是不是一个胖球」。
  我最初的阳性对照是一个 10 高 / 3 深 的胖椭球（0.536），它对类人形毫无代表性。
  教训：阳性对照的**形状类别必须与被测对象一致**，否则会校准出一个
  「只有胖球能过」的阈值。

四、最终三条（各自不同的机制，都在阳性对照上验过）
  V1 边缘收边率   = 剪影边缘内 5% 处的相对深度（0=最靠前，1=最靠后）
       薄板 1.000 | 合成实体 0.448 | 阈值 ≤ 0.60（下降方向）
       含义：体量必须在剪影边界处收边（高度场边界归零）。板上边缘与中心
       一样靠前，因为它就是一整面平的；曲面则必然在边缘退到后面去。
       行内深度范围≈0 的行直接判 1.0（没有体量可收，语义正确）。

  V2 法线多样性   = 可见像素中 法线与视轴夹角 > 30° 的占比
       薄板 0.70% | 合成实体 33.7% | 阈值 ≥ 25%
       含义：靠近剪影边缘的表面必须转向侧面。板只有一圈侧壁超过 30°。
       这条最锋利（48 倍），且与材质/贴图/光照全部无关，纯几何。

  V3 边闭合率     = 被恰好两个三角形共享的边 / 全部唯一边
       薄板 0.460 | 合成实体 1.000 | 阈值 ≥ 0.90
       含义：**实体 vs 壳**。板件是开放壳（有板面、有侧壁、没有背面），
       一半以上的边是边界边；真正的实体每个零件都闭合。
       拓扑判据，与前两条（收边、朝向）互不相关。

四、阳性对照为什么必须做
  `--selftest` 用一个合成的超椭圆截面实体跑同一套判据。
  没有它，我就可能又设计出一个「谁都过不了」的指标 —— 那和「谁都过得了」
  的指标一样无用。上面被否掉的三条，全都是被这一步抓出来的。

用法：
  python3 tools/volume_check.py              # 量 trace3d 的当前产物
  python3 tools/volume_check.py --selftest   # 先验阳性对照，再量当前产物
  python3 tools/volume_check.py --json out/volume.json
"""
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'tools'))

import trace3d as T                                      # noqa: E402
from gfx.gbuffer import rasterize                        # noqa: E402
from gfx.mesh import Mesh                                # noqa: E402
from r3d import Mat, Renderer, look_at                   # noqa: E402
import render_relief as RR                               # noqa: E402

# ---------------------------------------------------------------- 判据阈值
V1_MAX = 0.60      # 边缘收边率（越小越好）
V2_MIN = 25.0      # 法线偏转 > 30° 的可见像素占比（%）——**已降级为诊断项**
# V3 用**两个真实对照**夹出来，不是拍的：
#   旧薄板（线稿挤出，真正的「一块板」）实测 0.0987
#   万代 Unicorn 第三方 OBJ（真实生产资产）实测 0.3490
# 阈值取 0.20 —— 在两者之间，离开板约 2 倍、离真资产留 43% 余量。
V3_MIN = 0.20
# 结构门用**三个锚点**标定，不是拍脑袋：
#   失败锚：气球 / 当前浮雕 = 1 件（一张覆盖全身的闭合皮）
#   及格锚：硬表面粗模 = 19 件（头/颈/胸/腰/骨盆/2 肩/2 上臂/2 前臂/2 手/2 大腿
#           /2 小腿/2 脚，正是类人形机甲的最低可行分件）
#   上限锚：万代 Unicorn 第三方 OBJ（377k 三角）= 679 件
# 阈值取 12：低于最低可行分件（19）但远高于 1。
# **曾错误地取 40** —— 那是照着成品资产 679 画的线，结果把 19 件的粗模判死。
# 与 V7 是同一条教训：门槛要对齐「最低可接受交付」而不是「最好的参考」。
V6_MIN_PARTS = 12
# V7 平面门**已撤出判定**，只留诊断。原因与上面 V6 完全对称：
#   真实 Unicorn 资产实测平面面积占比仅 10.78%，而我原先设的门槛是 90%。
#   硬表面箱体样本能拿 97.68%，是因为它只有 19 个正交箱、法线只有 6 个朝向；
#   真实机甲有大量倒角、弧面、刻线台阶，法线天然发散。
#   教训与文件头第 3 节是同一条：**阳性对照的形状类别必须与被测对象一致**。
#   10.78% 这个数字本身也不能反转成「新门槛」—— 它只说明这条判据
#   在「细节丰富度」上是单调的，不区分「硬表面」与「曲面」。
V7_MIN = 90.0      # 仅供参考，不参与 pass

VH = 900           # 评审用竖向分辨率（统计够用，比出图低）


# ---------------------------------------------------------------- 取景
def _frame(meta):
    """三个角度共用同一取景，保证面积/宽度可比、不裁切。

    取景宽度必须按「转动后」的最大横向范围算：W·cos30 + D·sin30。
    第一版只按 W 开框，30° 视图被裁掉一截，面积比直接失真。
    """
    Hm = meta['H']
    Wm = max(meta['Wfig'] * meta['scale'], 1e-6)
    Dm = abs(meta.get('zback', 0.0)) + abs(meta.get('zf', 0.0))
    ext_w = max(Wm, Dm, Wm * math.cos(math.radians(30)) + Dm * 0.5) * 1.10
    ext_h = Hm * 1.12
    hp = VH
    wp = max(32, int(round(hp * ext_w / ext_h)))
    return wp, hp, Hm, ext_h


def _render(mesh, meta, yaw, fr):
    """渲一遍，返回 (覆盖掩码, 深度, 单位法线, 每像素世界尺寸)。"""
    wp, hp, Hm, ext_h = fr
    dist = (ext_h * 0.5) / math.tan(math.radians(RR.FOV / 2))
    cy = float(meta.get('cy', Hm * 0.5))     # 局部裁切时必须给出真实竖向中心
    rd = Renderer(wp, hp, ss=2, fov=RR.FOV)
    cm = look_at((0, cy, dist), (0, cy, 0), roll=0)
    P, N, T_, mi, Fi, b, e = RR.rot_mesh(mesh, yaw)
    gb, _ = rasterize(P, N, T_, mi, Fi, cm, RR.FOV, rd.WS, rd.HS)
    nn = gb.nrm.copy()
    ln = np.linalg.norm(nn, axis=-1, keepdims=True)
    nn = nn / np.maximum(ln, 1e-9)
    wpp = 2.0 * dist * math.tan(math.radians(RR.FOV / 2)) / rd.HS
    return (gb.midx >= 0), gb.depth, nn, wpp


def _bbox(m):
    ys, xs = np.nonzero(m.any(1))[0], np.nonzero(m.any(0))[0]
    return None if len(ys) == 0 else (ys.min(), ys.max(), xs.min(), xs.max())


# ---------------------------------------------------------------- V3 拓扑
def manifold_stats(mesh, tol=1e-4):
    """按**连通分量**判「实体 vs 壳」。

    为什么不用全局边比例：全局比例测的是「整块拼图能不能拼严」。
    相邻零件如果共享面（或共享顶点但细分不同，形成 T 形接点），
    一条边会被 4 个三角形共用，全局比例就掉下来 —— 但每个零件其实都闭合。
    板上一次就是这样：底板壳本身完美闭合（1.0000），
    基底却因为相邻矩形块的重合侧壁把全局比例拖到 0.927。
    那是拼装方式的问题，不是「有没有体量」的问题。

    这里改成：先按顶点位置合并、再把共边的三角形并成连通分量，
    然后看**每个分量内部有没有只被一个三角形用到的边**（边界边）。
    有 = 这个零件是开放壳（板）；没有 = 这个零件是实心体。
    返回 (闭合分量占比, 分量数, 全局边闭合率)。
    """
    P = mesh.arrays()[0].reshape(-1, 3)
    key = np.round(P / tol).astype(np.int64)
    _, inv = np.unique(key, axis=0, return_inverse=True)
    F = inv.reshape(-1, 3)
    Tn = len(F)

    parent = np.arange(len(np.unique(F)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for a, b, c in F.tolist():
        ra, rb, rc = find(a), find(b), find(c)
        if rb != ra:
            parent[rb] = ra
        if rc != ra:
            parent[rc] = ra

    e = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]], 0)
    e = np.sort(e, 1)
    e = e[e[:, 0] != e[:, 1]]
    uq, cnt = np.unique(e, axis=0, return_counts=True)

    comp_of = np.array([find(i) for i in range(len(parent))])
    ecomp = comp_of[uq[:, 0]]
    bad = cnt == 1
    comps = np.unique(ecomp)
    closed = 0
    for c in comps:
        m = ecomp == c
        if not bad[m].any():
            closed += 1
    return (closed / max(len(comps), 1), int(len(comps)),
            float((cnt == 2).mean()))


# ---------------------------------------------------------------- V1 收边
def rim_ratio(cov, dep, frac=0.05):
    """边缘收边率：剪影边缘内 5% 处的相对深度。

    0 = 边缘和中心一样靠前（平的一张板）
    1 = 边缘退到整行的最后面（曲面在边界归零）
    行内深度范围≈0 的行（没有任何体量）直接计 1.0。
    """
    vals, wts = [], []
    for y in np.nonzero(cov.any(1))[0]:
        xs = np.nonzero(cov[y])[0]
        if len(xs) < 12:
            continue
        xa, xb = xs[0], xs[-1]
        w = xb - xa + 1
        k = max(1, int(round(w * frac)))
        d = dep[y, xs]
        d = d[np.isfinite(d)]
        if len(d) < 4:
            continue
        rng = float(d.max() - d.min())
        if rng < 1e-3:                    # 该行没有体量可收
            vals.append(1.0)
            wts.append(w)
            continue
        dmin = float(d.min())
        de = (float(dep[y, xa + k]) - dmin) / rng
        dr = (float(dep[y, xb - k]) - dmin) / rng
        vals.append(0.5 * (min(max(de, 0.0), 1.0) + min(max(dr, 0.0), 1.0)))
        wts.append(w)
    return float(np.average(vals, weights=wts)) if vals else 1.0


# ---------------------------------------------------------------- 度量
def measure(mesh, meta, verbose=True, label='被测对象'):
    fr = _frame(meta)
    cov0, dep0, nrm0, _ = _render(mesh, meta, 0.0, fr)

    b0 = _bbox(cov0)
    if b0 is None:
        raise RuntimeError('正视没有任何覆盖像素')
    h_px = b0[1] - b0[0] + 1

    # ---- V1 边缘收边率
    V1 = rim_ratio(cov0, dep0)

    # ---- V2 法线多样性
    cosv = np.clip(nrm0[..., 2][cov0], -1.0, 1.0)
    ang = np.degrees(np.arccos(np.abs(cosv)))
    V2 = float((ang > 30.0).mean() * 100.0)
    med_ang = float(np.median(ang))

    # ---- V3 分量闭合率
    V3, ncomp, edge_ok = manifold_stats(mesh)

    # ---- V6 结构门（零件数与闭合质量）
    V6, V6_s = structure_gate(ncomp, V3)

    # ---- V7 平面门（网格层，与渲染无关）
    V7, V7_deg = planar_area_ratio(mesh)

    # ---- V8 台阶密度（仅诊断）
    V8 = step_density(cov0, dep0, meta['H'])

    res = dict(label=label,
               V1_rim_ratio=round(V1, 4),
               V2_normal_div_pct=round(V2, 2),
               V3_manifold_ratio=round(V3, 4),
               V6_parts=V6_s,
               V7_planar_pct=round(V7, 2),
               V8_step_density=round(V8, 3),
               median_normal_deg=round(med_ang, 2),
               V7_mean_cone_deg=round(V7_deg, 1),
               n_components=int(ncomp),
               global_edge_ok=round(edge_ok, 4),
               front_px=int(cov0.sum()), fig_height_px=int(h_px))
    # V2 降级为诊断项：它的阈值 25% 是在超椭圆椭球（阳性对照）上校准的，而
    # 一个纯硬表面箱体装配实测只有 0.45% —— 方向反了，它会判死正确的重建。
    # V1 同理（深度量级类判据在类人形上不可分，见文件头第 3 节）。
    # V7 已撤出判定（真实资产 10.78% vs 门槛 90%，见阈值块注释）。
    # 现役两条判定，机制互不重叠：
    #   V6 结构门   零件数 —— 判「熔成一张皮」（气球/浮雕 = 1 件）
    #   V3 闭合率   —— 判「整机是开放壳拼的」（旧薄板 9.87%，真实资产 34.9%）
    # 两条缺一不可：旧薄板零件数 3930（V6 数量够）但闭合只有 9.87%（V3 挂）；
    # 气球 V3=1.0000 但只有 1 件（V6 挂）。
    res['pass'] = dict(V6=bool(V6), V3=bool(V3 >= V3_MIN))
    res['all_pass'] = all(res['pass'].values())

    if verbose:
        g = lambda ok: 'PASS' if ok else 'FAIL'
        print('=' * 70)
        print(f'结构 / 硬表面门 · {label}')
        print('=' * 70)
        print(f'  V6 结构门       {V6_s:<24s} {g(V6)}'
              f'   （判定项，≥{V6_MIN_PARTS} 件）')
        print(f'  V3 分量闭合率   {V3:7.4f}  ≥{V3_MIN:.2f}   {g(V3 >= V3_MIN)}'
              f'   （判定项）')
        print('-' * 70)
        print(f'  V7 平面面积     {V7:7.2f}%   诊断项（原门槛 {V7_MIN:.0f}%，'
              f'真实资产仅 10.8% → 已撤出判定）')
        print('-' * 70)
        print(f'  V1 边缘收边率   {V1:7.4f}   诊断项')
        print(f'  V2 法线多样性   {V2:7.2f}%   诊断项（中位偏转 {med_ang:.1f}°）')
        print(f'  V8 台阶密度     {V8:7.3f}    诊断项')
        print('-' * 70)
        print(f'  判定：{"通过" if res["all_pass"] else "不合格"}')
    return res


# ---------------------------------------------------------------- V6 结构门
def structure_gate(ncomp, closed_ratio, min_parts=None):
    """V6 结构门 = 独立连通分量数 ≥ min_parts。

    这条是整组判据里唯一**不可能被大形糊弄**的：
    只要零件是「一张覆盖全身的闭合皮」，分量数必然 = 1，无论它鼓得多圆。
    它直接对应评审 P0-3「整体熔成一个气球体」，而不是绕着体量打转。

    为什么**不再**要求闭合率 ≥95%（2026-11-07 被实测推翻）：
      我原先写 `min_closed=0.95`，认为「真零件都闭合」。拿真实生产资产一测：
      万代 Unicorn 第三方 OBJ（377328 三角）**679 个分量，闭合仅 34.9%**。
      原因很实在 —— 游戏/建模资产为了 UV 展开、材质分组、法线硬化，
      在每条 UV 缝上都会把顶点拆开，几何上就不再闭合。95% 这条线
      会把任何真实资产判死，属于「只有我手搓的样本能过」的假门槛。
      闭合率现在交给 V3 单独判，阈值 0.20（在旧薄板 0.0987 与真资产 0.349
      之间），职责分开：V6 管「有没有分件」，V3 管「分件是不是开放壳」。

    为什么不能只看零件数：旧薄板 3930 件（数量远超 40），但闭合 9.87%
    —— 那是一堆互不相连的侧壁薄片，不是分件。所以 V3 必须同时在场。
    """
    mp = V6_MIN_PARTS if min_parts is None else min_parts
    ok = bool(ncomp >= mp)
    return ok, f'{ncomp} 件 / 闭合 {closed_ratio * 100:.1f}%'


# ---------------------------------------------------------------- V7 平面门
def _face_normals_area(mesh):
    """从网格取每面法线与面积（世界单位），用于在**网格层**判硬表面。"""
    P = mesh.arrays()[0].reshape(-1, 3, 3)
    n = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
    a = 0.5 * np.linalg.norm(n, axis=1)
    L = np.linalg.norm(n, axis=1, keepdims=True)
    n = n / np.maximum(L, 1e-12)
    return n, a


def _kmeans_dirs(n, w, K=12, iters=30):
    """按面积加权的方向聚类（最远点初始化 + Lloyd）。

    只在最远点采样里用不加权的方向，均值用面积加权 —— 大装甲板才有投票权，
    小铆钉不会把主朝向拉偏。
    """
    sub = n
    C = [sub[int(np.argmax(w))]]
    d = 1.0 - sub @ C[0]
    for _ in range(K - 1):
        i = int(np.argmax(d * w))
        C.append(sub[i])
        d = np.minimum(d, 1.0 - sub @ sub[i])
    C = np.array(C, np.float64)
    for _ in range(iters):
        a = (n @ C.T).argmax(1)
        moved = False
        for k in range(K):
            m = a == k
            if not m.any():
                continue
            v = (n[m] * w[m, None]).sum(0)
            L = np.linalg.norm(v)
            if L < 1e-12:
                continue
            v = v / L
            if float(v @ C[k]) < 0.9999999:
                moved = True
            C[k] = v
        if not moved:
            break
    return C


def planar_area_ratio(mesh, K=12, cone_deg=4.0):
    """V7 平面面积占比 = 表面总面积中，法线落在 12 个主朝向 4° 锥内的比例。

    为什么必须在**网格层**算、不能用渲染出的 G-buffer：
      实测 G-buffer 的法线是逐三角形常量（同三角形内相邻像素夹角恒 0），
      于是「相邻像素法线夹角」量的其实是三角形大小，不是表面平不平。
      我第一版就是这样，气球拿到 95.6% —— 假判据，已废弃。
    这里直接读面法线与面积，与着色方式、采样率、视角全部无关。

    硬表面（平板 + 倒角）：>90%；气球 / 高度场鼓面：远低于 50%。
    """
    n, a = _face_normals_area(mesh)
    if len(n) < 8 or a.sum() <= 0:
        return 0.0, 0.0
    C = _kmeans_dirs(n, a, K)
    best = (n @ C.T).max(1)
    cov = float(a[best >= math.cos(math.radians(cone_deg))].sum() / a.sum() * 100.0)
    mean_deg = float(np.degrees(np.arccos(np.clip(best, -1.0, 1.0))).mean())
    return cov, mean_deg


# ---------------------------------------------------------------- V8 台阶（诊断）
def step_density(cov, dep, Hm, thr_rel=0.0015, k=8.0):
    """V8 深度台阶密度（**诊断项，不判死**）= 每 100 px 扫描宽度上的真台阶数。

    第一版用「|Δz| 超绝对阈值」，气球反而拿到 2.29 而硬表面只有 0.28 ——
    因为掠射面上 dz/dx → ∞，被误判成台阶。现在改用**局部梯度对比**：
    真台阶的跳变远大于左右 2 px 的梯度，光滑面则与邻居同量级。

    即便如此它也不能单独判死：旧薄板 0.545 高于硬表面 0.210（因为 167 块板
    的侧壁本身是台阶）。它的用途是反向确认「有没有零件」，判定交给 V6。
    """
    thr = thr_rel * abs(Hm)
    tot = cnt = 0
    for y in np.nonzero(cov.any(1))[0]:
        xs = np.nonzero(cov[y])[0]
        if len(xs) < 12:
            continue
        d = dep[y, xs]
        fine = np.isfinite(d)
        adj = (np.diff(xs) == 1) & fine[:-1] & fine[1:]
        if int(adj.sum()) < 8:
            continue
        g = np.abs(np.diff(d))
        gg = np.where(adj, g, 0.0)
        loc = np.zeros_like(gg)
        for off in (-2, -1, 1, 2):
            loc += np.roll(gg, off)
        loc /= 4.0
        st = (gg > thr) & (gg > k * np.maximum(loc, 1e-9)) & adj
        tot += int(adj.sum())
        cnt += int(st.sum())
    return cnt / max(tot, 1) * 100.0


# ---------------------------------------------------------------- 阳性对照
def _box(mesh, c, s, ry=0.0, rz=0.0, mat=None):
    """一个闭合长方体（12 三角，外法线由绕序保证）。硬表面正样本的积木。"""
    S = [(-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
         (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]
    h = np.array(s, np.float64) * 0.5
    V = np.array([[sx * h[0], sy * h[1], sz * h[2]] for sx, sy, sz in S])
    ca, sa = math.cos(math.radians(ry)), math.sin(math.radians(ry))
    cb, sb = math.cos(math.radians(rz)), math.sin(math.radians(rz))
    Ry = np.array([[ca, 0, sa], [0, 1, 0], [-sa, 0, ca]])
    Rz = np.array([[cb, -sb, 0], [sb, cb, 0], [0, 0, 1]])
    V = V @ (Rz @ Ry).T + np.array(c, np.float64)
    F = [(0, 3, 2), (0, 2, 1), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
         (2, 3, 7), (2, 7, 6), (1, 2, 6), (1, 6, 5), (0, 4, 7), (0, 7, 3)]
    for f in F:
        p = V[list(f)]
        n = np.cross(p[1] - p[0], p[2] - p[0])
        L = np.linalg.norm(n)
        if L < 1e-12:
            continue
        mesh.add(p, np.repeat((n / L)[None, :], 3, 0),
                 np.zeros((3, 2), np.float32), mat)


def _synthetic_hardsurface():
    """硬表面正样本：18 个独立闭合箱体拼成一台机甲（头/胸/腰/肩/臂/腿/脚）。

    它存在的理由是 V2 的阳性对照（超椭圆椭球）**本身就是气球**，与要判死的
    产物同类。只有加进一个「确实是硬表面」的样本，V4/V5 的阈值才有意义。

    注意各件在 z 方向刻意错开：肩甲 z=+0.45 压在胸甲（z=0）之前，
    前臂 z=+0.28，脚 z=+0.35 —— 这样正视里存在真实的零件前后遮挡，
    V5 才不会是零。
    """
    mesh = Mesh()
    m = Mat((0.62, 0.66, 0.72), spec=0.5, rim=0.3)
    parts = [
        ((0.0, 9.00, 0.15), (1.50, 1.50, 1.55), 0, 0),      # 头
        ((0.0, 8.12, 0.00), (0.62, 0.40, 0.62), 0, 0),      # 颈
        ((0.0, 7.00, 0.00), (3.40, 2.05, 2.40), 0, 0),      # 胸
        ((0.0, 5.55, 0.00), (2.55, 1.25, 2.00), 0, 0),      # 腰
        ((-2.30, 7.55, 0.45), (1.60, 1.50, 1.90), 0, 14),   # 左肩甲
        ((2.30, 7.55, 0.45), (1.60, 1.50, 1.90), 0, -14),   # 右肩甲
        ((-2.48, 6.05, 0.10), (0.95, 1.95, 1.10), 0, 0),    # 左上臂
        ((2.48, 6.05, 0.10), (0.95, 1.95, 1.10), 0, 0),
        ((-2.52, 4.35, 0.28), (1.05, 1.80, 1.25), 0, 0),    # 左前臂
        ((2.52, 4.35, 0.28), (1.05, 1.80, 1.25), 0, 0),
        ((-2.52, 3.28, 0.32), (0.80, 0.72, 0.92), 0, 0),    # 手
        ((2.52, 3.28, 0.32), (0.80, 0.72, 0.92), 0, 0),
        ((0.0, 4.72, 0.00), (2.30, 0.92, 2.10), 0, 0),      # 骨盆
        ((-0.86, 3.35, 0.00), (1.15, 2.42, 1.35), 0, 0),    # 大腿
        ((0.86, 3.35, 0.00), (1.15, 2.42, 1.35), 0, 0),
        ((-0.88, 1.10, 0.00), (1.05, 2.00, 1.20), 0, 0),    # 小腿
        ((0.88, 1.10, 0.00), (1.05, 2.00, 1.20), 0, 0),
        ((-0.90, 0.16, 0.35), (1.10, 0.52, 1.90), 0, 0),    # 脚
        ((0.90, 0.16, 0.35), (1.10, 0.52, 1.90), 0, 0),
    ]
    for c, s, ry, rz in parts:
        _box(mesh, c, s, ry, rz, m)
    return mesh, dict(H=9.8, Wfig=6.3, scale=1.0, zf=1.60, zback=-1.35)


REF_OBJ = os.path.join(HERE, 'ref_assets', 'source', 'UNICORN_GUNDAM_OBJ.obj')


def _ref_mesh(path=None):
    """真实生产资产正样本：万代 Unicorn 第三方 OBJ（377k 三角）。

    **为什么必须有这一对照**：前四个样本里有三个是我自己造的，
    我造它们的时候就知道了答案 —— 这就是「拿自己出的题自己答」。
    只有把真实资产丢进同一套判据，才能发现哪些门槛只对「我手搓的形状」成立。
    实测它就把 V7（平面面积 90%）和 V6 的闭合率 95% 两条同时打穿了。

    返回 (_Bare, meta)。_Bare 只暴露 arrays()，因为 Mesh.arrays() 里有
    `if not self.P` 的列表判空，对 ndarray 会抛 ValueError。
    """
    import refview as RV
    p = path or REF_OBJ
    if not os.path.exists(p):
        raise FileNotFoundError(p)
    V, tris = RV.load_obj(p)
    Vn, m = RV.normalize(V)

    class _Bare:
        """只实现 arrays()，返回与 Mesh 完全一致的 7 元组。

        注意 rot_mesh 是 `P, N, T_, mi, Fi, b, e = mesh.arrays()` 硬解包，
        少给一个就 ValueError: not enough values to unpack。
        """
        def __init__(self, V, tris):
            P = V[tris]
            n = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
            L = np.linalg.norm(n, axis=1)
            keep = L > 1e-12
            n = n[keep] / L[keep, None]
            nf = int(keep.sum())
            self._a = (P[keep].astype(np.float32),
                       np.repeat(n.astype(np.float32)[:, None, :], 3, 1),
                       np.zeros((nf, 3, 2), np.float32),
                       np.zeros((nf,), np.int32),
                       np.arange(nf, dtype=np.int32),
                       np.array([[0.78, 0.79, 0.80]], np.float32),
                       np.zeros((1,), np.float32))

        def arrays(self):
            return self._a

        def __len__(self):
            return len(self._a[0])

    meta = dict(H=10.0, Wfig=m['width'], scale=1.0,
                zf=0.5 * m['depth'], zback=-0.5 * m['depth'])
    return _Bare(Vn, tris), meta


def _synthetic_solid(Hm=10.0, Wm=3.6, Dm=3.0, nring=64, nsec=48, expo=2.6):
    """合成一个「确实有体量」的实体：超椭圆截面的锥形躯体。

    存在的唯一目的是证明三条判据**存在可达到的通过样本**。
    截面 |x/a|^n + |z/b|^n = 1，n=2 是椭圆，n 越大越接近方箱。
    """
    mesh = Mesh()
    mat = Mat((0.62, 0.66, 0.72), spec=0.5, rim=0.3)
    ys = np.linspace(-Hm * 0.5, Hm * 0.5, nring)
    th = np.linspace(0, 2 * np.pi, nsec, endpoint=False)

    def ring(y, s):
        cs, sn = np.cos(th), np.sin(th)
        ax, bz = (Wm * 0.5) * s, (Dm * 0.5) * s
        x = ax * np.sign(cs) * np.abs(cs) ** (2.0 / expo)
        z = bz * np.sign(sn) * np.abs(sn) ** (2.0 / expo)
        return np.stack([x, np.full_like(x, y), z], 1)

    rings = []
    for y in ys:
        u = (y + Hm * 0.5) / Hm
        s = 0.55 + 0.45 * math.sin(math.pi * min(1.0, u)) ** 0.6
        rings.append(ring(y, s))

    def add_tri(tri, ref):
        p = np.asarray(tri, np.float64)
        n = np.cross(p[1] - p[0], p[2] - p[0])
        L = np.linalg.norm(n)
        if L < 1e-12:
            return
        n = n / L
        if float(n @ (p.mean(0) - ref)) < 0.0:
            n = -n
        mesh.add(p, np.repeat(n[None, :], 3, 0), np.zeros((3, 2), np.float32), mat)

    for i in range(nring - 1):
        r0, r1 = rings[i], rings[i + 1]
        ymid = np.array([0.0, 0.5 * (ys[i] + ys[i + 1]), 0.0])
        for j in range(nsec):
            k = (j + 1) % nsec
            add_tri((r0[j], r0[k], r1[k]), ymid)
            add_tri((r0[j], r1[k], r1[j]), ymid)
    cen = np.zeros(3)
    for rr, yy in ((rings[0], ys[0]), (rings[-1], ys[-1])):
        c = np.array([0.0, yy, 0.0])
        for j in range(nsec):
            k = (j + 1) % nsec
            add_tri((c, rr[j], rr[k]), cen)
    return mesh, dict(H=Hm, Wfig=Wm, scale=1.0, zf=Dm * 0.5, zback=-Dm * 0.5)


def selftest(verbose=True):
    """三个对照 + 写死的预期结果。

    预期：
      对照 A 气球    —— V3✓（闭合）但 V6✗（只有 1 件）
      对照 B 硬表面  —— 两条全过
      对照 C 真资产  —— 两条全过（这是唯一的「非自造」样本）
    气球必须挂，因为旧版就是拿一个超椭圆椭球当阳性对照，
    而它和要判死的交付物是同一类形状。
    真资产必须过，因为它代表「实际能让甲方收货的东西长什么样」；
    它过不了，说明门槛是照着我手搓的样本画的。
    """
    rows = []
    balloon, mb = _synthetic_solid()
    rows.append(measure(balloon, mb, verbose=verbose, label='对照 A · 气球（超椭圆椭球）'))
    hard, mh = _synthetic_hardsurface()
    rows.append(measure(hard, mh, verbose=verbose, label='对照 B · 硬表面（19 件箱体）'))
    try:
        ref, mr = _ref_mesh()
        rows.append(measure(ref, mr, verbose=verbose, label='对照 C · 真资产（Unicorn OBJ）'))
        has_ref = True
    except Exception as e:                                  # noqa: BLE001
        print(f'  （对照 C 真资产跳过：{e}）')
        has_ref = False

    exp = [(True, False), (True, True)] + ([(True, True)] if has_ref else [])
    ok = all(r['pass']['V3'] == e[0] and r['pass']['V6'] == e[1]
             for r, e in zip(rows, exp))
    print('=' * 70)
    print(f'判据校准：{"符合预期" if ok else "不符合预期 —— 判据有问题，不能拿来验收"}')
    for r, e in zip(rows, exp):
        print(f'  {r["label"]:<30} 预期 V3{"✓" if e[0] else "✗"} '
              f'V6{"✓" if e[1] else "✗"}   实际 {_fmt(r["pass"])}')
    print('=' * 70)
    return rows, ok


def _fmt(p):
    return ' '.join(f'{k}{"✓" if v else "✗"}' for k, v in
                    (('V3', p['V3']), ('V6', p['V6'])))


def compare():
    """五方对照：气球 / 硬表面 / 真资产 / 旧薄板 / 当前交付物。

    前两个是自造对照（验判据的边界），第三个是真实资产（验门槛是否现实），
    后两个是待判死的产物。判据必须让检测目标分离：
      真资产、硬表面 → 通过；气球、旧薄板、当前浮雕 → 不合格。
    """
    rows = []
    balloon, mb = _synthetic_solid()
    rows.append(measure(balloon, mb, verbose=False, label='对照 A · 气球'))
    hard, mh = _synthetic_hardsurface()
    rows.append(measure(hard, mh, verbose=False, label='对照 B · 硬表面箱体'))
    try:
        ref, mr = _ref_mesh()
        rows.append(measure(ref, mr, verbose=False, label='对照 C · 真资产 Unicorn'))
    except Exception as e:                                  # noqa: BLE001
        print(f'  （真资产对照跳过：{e}）')
    board, mboard = T.build(verbose=False)
    rows.append(measure(board, mboard, verbose=False, label='旧薄板 trace3d'))
    try:
        import relief_v2 as R
        y1 = T.load_masks()[2].shape[0]
        rel, mrel = R.build(50, y1 - 1, 2, verbose=False)
        rows.append(measure(rel, mrel, verbose=False, label='当前交付 · 全身浮雕 v2.3'))
    except Exception as e:                                  # noqa: BLE001
        print(f'  （浮雕对照跳过：{e}）')

    print('=' * 100)
    print('结构 / 硬表面门校准 · 五方对照')
    print('=' * 100)
    print(f'{"对象":<26}{"V6 零件":>16}{"V3 闭合":>10}{"V7 平面":>10}'
          f'{"V8 台阶":>10}{"判定":>8}')
    print('-' * 100)
    for r in rows:
        print(f'{r["label"]:<26}{r["V6_parts"]:>16}'
              f'{r["V3_manifold_ratio"]:>10.4f}'
              f'{r["V7_planar_pct"]:>9.2f}%'
              f'{r["V8_step_density"]:>10.3f}'
              f'{("通过" if r["all_pass"] else "不合格"):>8}')
    print('-' * 100)
    print(f'  判定项：V6 ≥{V6_MIN_PARTS} 件   V3 ≥{V3_MIN:.2f}   '
          f'（V7/V8 仅诊断）')
    return rows


# ---------------------------------------------------------------- 主程序
def main():
    args = sys.argv[1:]
    if '--compare' in args:
        rows = compare()
        if '--json' in args:
            p = args[args.index('--json') + 1]
            os.makedirs(os.path.dirname(p) or '.', exist_ok=True)
            with open(p, 'w') as f:
                json.dump(rows, f, ensure_ascii=False, indent=2)
            print(f'  → {p}')
        return
    if '--selftest' in args:
        selftest()
        print()
    mesh, meta = T.build(verbose=False)
    res = measure(mesh, meta)
    if '--json' in args:
        p = args[args.index('--json') + 1]
        os.makedirs(os.path.dirname(p) or '.', exist_ok=True)
        with open(p, 'w') as f:
            json.dump(res, f, ensure_ascii=False, indent=2)
        print(f'  → {p}')


if __name__ == '__main__':
    main()
