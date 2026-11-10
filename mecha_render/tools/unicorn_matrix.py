"""tools/unicorn_matrix.py — 把外壳体做成一整张矩阵：高度 × 方位 × 半径

为什么要有这个文件
  前面的尺子都只在**一条剖面**上取值：
    `silhouette_ruler` 只量 ±x（正投影宽），`depth_map` / `curve_ruler` 只量 ±z（侧投影深）。
  各投影各量一次，等于把一个三度形体压成两条曲线 —— 这正是「刻画维度不够」。
  真正独立的信息只有一张：**R[高度][方位] = 该方位该高度的最外半径**。
  正投影、侧投影、斜 45°、背面，全都是这张矩阵的**切片**；反过来不成立。

  R 是 (200 × 180) 的矩阵：0.5% 机高 × 2° 方位。
  从它上面再做两件前面做不到的事：
    ① **棱线提取**：R 沿方位方向的局部极大 = 「这个高度上最凸出去的方位」。
       把每层的极大值沿高度串起来，就是一条**从脚走到头的棱线**（有起点、有终点、
       有方位漂移量、有半径变化量）。这才是「线条」的量化定义。
    ② **ΔR 矩阵**：我们与参考的逐格差。前面只能说「50–60% 这一段浅 0.71」，
       现在能说「浅在哪个方位、哪一格」。

方法（以及它的局限）
  - 采样：顶点 + 三条边的中点，投到 (y, θ, r) 网格里取 max r。参考模型 19 万三角，
    顶点密度足够；★ 但大平面片上的顶点稀疏，可能**低估**该格半径。
    这一条必须说清楚：矩阵是**下界估计**，不是精确包络。
  - 轴向：不用 bbox 中心（我们的背包会把中心推后）。用**双腿质心**的 (x, z)
    作为竖轴 —— 两具模型都用「腿站在哪儿」对齐，这比 bbox 中心讲得通。
  - θ = 0 朝 +z（前），θ 增大转向 +x（机体左侧）。

用法
  python3 tools/unicorn_matrix.py            # 参考 + 我们 + ΔR，出三张图
  python3 tools/unicorn_matrix.py --no-ours  # 只做参考
"""
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'tools'))

import refview as RV                                       # noqa: E402
import s2_graybox as S                                     # noqa: E402
import unicorn_trunk as UT                                 # noqa: E402

OUT = os.path.join(HERE, 'out', 'ref')
FONT = '/System/Library/Fonts/Hiragino Sans GB.ttc'
NB, NA = 200, 180          # 0.5% 机高 × 2° 方位
H_M = 7.930


# ---------------------------------------------------------------- 数据
def ref_soup():
    V, tris, gf, sets = UT.load_obj_grouped(UT.SRC)
    Vn, _ = RV.normalize(V)
    keep = np.ones(len(tris), bool)
    for tok in UT.REMOVE:
        keep &= ~UT.face_in(gf, sets, tok)
    return Vn[tris[keep]]


def ours_soup():
    S.CLEAN = True
    _root, mesh = S.build()
    P = np.array(mesh.P, np.float32).reshape(-1, 3) * (10.0 / H_M)
    return P


def densify(P):
    """顶点 + 三边中点。三角面片上取中点能把「大面上的空 bin」补掉一半。"""
    F = P.reshape(-1, 3, 3)
    M = [P.reshape(-1, 3)]
    for i, j in ((0, 1), (1, 2), (2, 0)):
        M.append(0.5 * (F[:, i] + F[:, j]))
    return np.concatenate(M, 0)


def leg_axis(Q):
    """双腿质心的 (x, z)：y < 30% 的顶点。竖轴用「腿站在哪儿」，不用 bbox 中心。"""
    y = Q[:, 1]
    lo, hi = y.min(), y.max()
    m = y < lo + 0.30 * (hi - lo)
    return float(np.median(Q[m, 0])), float(np.median(Q[m, 2]))


def radial_matrix(P):
    Q = densify(P)
    ax, az = leg_axis(Q)
    x, y, z = Q[:, 0] - ax, Q[:, 1], Q[:, 2] - az
    lo, hi = float(y.min()), float(y.max())
    r = np.hypot(x, z)
    th = np.arctan2(x, z)                      # 0 = +z(前)，+π/2 = +x
    hi_i = np.clip(((y - lo) / (hi - lo) * NB).astype(np.int32), 0, NB - 1)
    ti = (np.clip(((th + np.pi) / (2 * np.pi) * NA).astype(np.int32), 0, NA - 1)) % NA
    M = np.zeros((NB, NA), np.float32)
    np.maximum.at(M, (hi_i, ti), r.astype(np.float32))
    # 补空 bin：先沿方位（环形）用相邻有效值填，再沿高度填
    for _ in range(3):
        empty = M <= 1e-6
        if not empty.any():
            break
        roll = np.roll(M, 1, 1)
        roll2 = np.roll(M, -1, 1)
        fill = np.where((M <= 1e-6) & (roll > 0), roll,
                        np.where((M <= 1e-6) & (roll2 > 0), roll2, M))
        M = fill
    for _ in range(3):
        empty = M <= 1e-6
        if not empty.any():
            break
        up = np.vstack([M[1:], M[-1:]])
        dn = np.vstack([M[:1], M[:-1]])
        M = np.where(empty & (up > 0), up, np.where(empty & (dn > 0), dn, M))
    return M, (lo, hi), (ax, az)


# ---------------------------------------------------------------- 棱线
def ridges(M, prom=0.035, win=6):
    """逐层找 R(θ) 的环形局部极大；返回 {层: [(θ°, r), ...]}。"""
    out = {}
    for h in range(M.shape[0]):
        row = M[h]
        cand = []
        for a in range(NA):
            sl = [(a + d) % NA for d in range(-win, win + 1)]
            seg = row[sl]
            if row[a] < seg.max() - 1e-9:
                continue
            if row[a] - seg.min() < prom:       # 不显著
                continue
            cand.append(a)
        # 合并相邻候选（同一座峰的两侧）
        merged = []
        for a in cand:
            if merged and (a - merged[-1][-1]) <= 2 or (merged and a + NA - merged[-1][-1] <= 2):
                merged[-1].append(a)
            else:
                merged.append([a])
        peaks = []
        for grp in merged:
            best = max(grp, key=lambda q: row[q])
            peaks.append((360.0 * best / NA, float(row[best])))
        out[h] = peaks
    return out


def track(peaks, tol=6.0, min_len=30):
    """把逐层峰值沿高度串成线。tol = 允许的方位漂移（度/层）。"""
    live, done = [], []
    for h in range(NB):
        used = set()
        for tr in live:
            th_last = tr['pts'][-1][1]
            best, bd = None, 1e9
            for i, (th, r) in enumerate(peaks.get(h, [])):
                if i in used:
                    continue
                d = abs((th - th_last + 180) % 360 - 180)
                if d < bd:
                    best, bd = i, d
            if best is not None and bd <= tol:
                th, r = peaks[h][best]
                tr['pts'].append((h, th, r))
                used.add(best)
            else:
                tr['gap'] = tr.get('gap', 0) + 1
        for i, (th, r) in enumerate(peaks.get(h, [])):
            if i not in used:
                live.append(dict(pts=[(h, th, r)], gap=0))
        keep = []
        for tr in live:
            if tr.get('gap', 0) > 3:
                done.append(tr)
            else:
                keep.append(tr)
        live = keep
    done += live
    return [t for t in done if len(t['pts']) >= min_len]


# ---------------------------------------------------------------- 出图
def ramp(v, lo=0.0, hi=2.6):
    """浅色主题：白 → 蓝（值大 = 半径大）。"""
    t = np.clip((v - lo) / (hi - lo), 0, 1)[..., None]
    c0 = np.array([252, 252, 250], np.float32)
    c1 = np.array([28, 62, 120], np.float32)
    return (c0 + (c1 - c0) * t ** 0.85).astype(np.uint8)


def dramp(v, cap=0.8):
    """ΔR：蓝 = 我们更窄，红 = 我们更宽。"""
    t = np.clip(v / cap, -1, 1)
    out = np.full(t.shape + (3,), 250, np.uint8)
    pos = t > 0
    neg = t < 0
    out[pos] = (np.stack([np.full(t[pos].shape, 200),
                          np.full(t[pos].shape, 60 + 60 * (1 - t[pos])),
                          np.full(t[pos].shape, 60)], -1)).astype(np.uint8)
    out[neg] = (np.stack([np.full(t[neg].shape, 40),
                          np.full(t[neg].shape, 90 + 60 * (1 + t[neg])),
                          np.full(t[neg].shape, 190)], -1)).astype(np.uint8)
    return out


def draw_matrix(M, out, title, sub, trs=None, delta=False):
    cell_w, cell_h = 3, 3
    W = NA * cell_w + 150
    H = NB * cell_h + 130
    cv = Image.new('RGB', (W, H), (255, 255, 255))
    d = ImageDraw.Draw(cv)
    f20 = ImageFont.truetype(FONT, 20)
    f13 = ImageFont.truetype(FONT, 13)
    f12 = ImageFont.truetype(FONT, 12)
    d.text((16, 12), title, font=f20, fill=(20, 20, 20))
    yy = 40
    for line in sub.split('\n'):
        d.text((16, yy), line, font=f13, fill=(110, 110, 110))
        yy += 18
    x0, y0 = 84, 104
    img = dramp(M) if delta else ramp(M)
    # 行 0 = 脚底 → 画到最下面
    img = img[::-1]
    cv.paste(Image.fromarray(img), (x0, y0))
    # 方位刻度（0 = 前，90 = 左，180 = 后，270 = 右）
    for a in range(0, 360, 30):
        x = x0 + int(a / 360 * NA) * cell_w
        d.line([(x, y0 - 4), (x, y0 + 3)], fill=(120, 120, 120))
        if a % 90 == 0:
            lab = {0: '0 前', 90: '90 左', 180: '180 后', 270: '270 右'}[a]
            d.text((x - 14, y0 - 22), lab, font=f12, fill=(90, 90, 90))
    # 高度刻度
    for pc in range(0, 101, 10):
        y = y0 + NB * cell_h - int(pc / 100 * NB) * cell_h
        d.line([(x0 - 4, y), (x0 + 3, y)], fill=(120, 120, 120))
        d.text((x0 - 40, y - 7), '%d%%' % pc, font=f12, fill=(120, 120, 120))
    # 棱线
    if trs:
        cols = [(214, 120, 30), (30, 120, 200), (150, 60, 160), (40, 150, 90),
                (200, 60, 60), (90, 90, 40)]
        trs = sorted(trs, key=lambda t: -len(t['pts']))[:6]
        for k, tr in enumerate(trs):
            pts = [(x0 + int(th / 360 * NA) * cell_w,
                    y0 + NB * cell_h - h * cell_h) for h, th, _r in tr['pts']]
            if len(pts) > 1:
                d.line(pts, fill=cols[k % 6], width=2)
        yy = y0 + NB * cell_h + 8
        for k, tr in enumerate(trs):
            p0, p1 = tr['pts'][0], tr['pts'][-1]
            d.text((x0, yy), 'L%d  %5.1f%%→%5.1f%%   方位 %5.1f°→%5.1f°（漂 %+5.1f°）   r %.2f→%.2f'
                   % (k + 1, 100 * p0[0] / NB, 100 * p1[0] / NB, p0[1], p1[1],
                      (p1[1] - p0[1] + 180) % 360 - 180, p0[2], p1[2]),
                   font=f12, fill=cols[k % 6])
            yy += 15
    cv.save(out)
    return out, cv.size


def main():
    print('读参考…')
    Pr = ref_soup()
    Mr, (ry0, ry1), rax = radial_matrix(Pr)
    print('  参考 R 矩阵 %d×%d，轴 (x,z) = (%.3f, %.3f)' % (Mr.shape[0], Mr.shape[1], *rax))
    pk = ridges(Mr)
    trs = track(pk)
    trs.sort(key=lambda t: -len(t['pts']))
    print('\n  参考：主要棱线（按长度排，前 12 条）')
    print('  %-3s %-16s %-22s %-12s' % ('#', '高度 %', '方位 °（漂移）', '半径'))
    for i, tr in enumerate(trs[:12], 1):
        p0, p1 = tr['pts'][0], tr['pts'][-1]
        dth = (p1[1] - p0[1] + 180) % 360 - 180
        print('  %-3d %5.1f→%5.1f (%4.1f)  %6.1f→%6.1f (%+5.1f)   %.2f→%.2f'
              % (i, 100 * p0[0] / NB, 100 * p1[0] / NB, 100 * (p1[0] - p0[0]) / NB,
                 p0[1], p1[1], dth, p0[2], p1[2]))

    os.makedirs(OUT, exist_ok=True)
    p, size = draw_matrix(Mr, os.path.join(OUT, 'matrix_ref.png'),
                          'Unicorn 主干 · 径向包络矩阵 R[高度 × 方位]',
                          '色深 = 该方位该高度的最外半径（H=10）。垂直线 = 从头贯到脚的棱线。\n'
                          'R 是下界估计（顶点+边中点采样，大平面片可能低估）。', trs)
    print('\n→ %s  %d × %d' % (p, size[0], size[1]))

    if '--no-ours' in sys.argv:
        return
    print('\n读我们…')
    Po = ours_soup()
    Mo, _o, oax = radial_matrix(Po)
    print('  我们 R 矩阵 %d×%d，轴 (x,z) = (%.3f, %.3f)' % (Mo.shape[0], Mo.shape[1], *oax))
    D = Mo - Mr
    p2, size2 = draw_matrix(D, os.path.join(OUT, 'matrix_delta.png'),
                            'ΔR = 我们 − 参考（同一高度轴 / 同一方位 / 同一腿轴对齐）',
                            '红 = 我们更宽（凸出），蓝 = 我们更窄（缩进）。饱和值 ±0.80。',
                            None, delta=True)
    print('→ %s  %d × %d' % (p2, size2[0], size2[1]))

    # 方位扇区统计：把 360° 切成 8 个 45° 扇区，看差在哪个方位
    print('\n  八方位扇区 ΔR（正 = 我们更宽；单位 H）')
    print('  %-16s %-10s %-10s %-10s' % ('扇区', '40–60%', '10–30%', '60–90%'))
    names = ['0 前', '45 前左', '90 左', '135 后左', '180 后', '225 后右', '270 右', '315 前右']
    for k in range(8):
        a0, a1 = k * NA // 8, (k + 1) * NA // 8
        def m(b0, b1):
            h0, h1 = int(NB * b0), int(NB * b1)
            return float(np.nanmean(D[h0:h1, a0:a1]))
        print('  %-16s %+9.3f %+9.3f %+9.3f' % (names[k], m(0.40, 0.60), m(0.10, 0.30), m(0.60, 0.90)))

    json.dump(dict(nb=NB, na=NA,
                   ref=np.round(Mr, 4).tolist(),
                   ours=np.round(Mo, 4).tolist(),
                   lines=[dict(h0=t['pts'][0][0] / NB, h1=t['pts'][-1][0] / NB,
                               th0=t['pts'][0][1], th1=t['pts'][-1][1],
                               r0=t['pts'][0][2], r1=t['pts'][-1][2]) for t in trs]),
              open(os.path.join(OUT, 'matrix.json'), 'w'))
    print('\n→ %s' % os.path.join(OUT, 'matrix.json'))


if __name__ == '__main__':
    main()
