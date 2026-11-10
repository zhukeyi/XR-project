"""tools/curve_ruler.py — 把机体轮廓拆成**折线段**，量每段的角度与长度

为什么要有这个文件
  §29 之前所有的比较都是「逐高度带的极值差」：
  「50–60% 这一带比你浅 0.71」。它能说明**差多少**，说明不了**为什么**。
  而「为什么」只能从**曲线的语法**里读出来 —— 参考机体的侧面轮廓不是一个盒子，
  是一串角度递变的折线：

      小腿 → 膝 → 大腿 → 裙 → 腰 → 胸 → 肩

  每一段有自己的角度（对垂直线的偏角）和长度。角度决定「这张皮往哪儿走」，
  长度决定「这个节奏多长一拍」。**抄造型 = 抄这两列数，不是抄总体 bbox。**

它做什么
  1. 逐 0.5% 机高取三条包络：前脸 z、后脸 z、（正视图里的）半宽 |x|；
     ★ 用**边插值**取极值（层的放样件只在上下两层有顶点，顶点采样会读真空带）。
  2. 把每条包络用 RDP（Ramer–Douglas–Peucker）压成折线，转折点即「造型节点」。
  3. 每段输出：高度区间 / Δz / 段长 / 与垂直线的夹角（度）。
  4. 出图：侧视包络 + 正视频宽，段中点标角度。

口径
  - 参考（Unicorn 主干）：H=10 单位，脚底 y=0，+z 朝前。
  - 我们：米制，除以 H_M 换算到 H=10，与参考可直接比。
  - `--group <token>`：只量参考里某个装配（如 waist_assy_G），用来单独看裙。

用法
  python3 tools/curve_ruler.py                 # 参考主干 + 我们的裙，两张表
  python3 tools/curve_ruler.py --group waist_assy_G
  python3 tools/curve_ruler.py --ours          # 只量我们自己
"""
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
H_M = 7.930
NB = 200                     # 0.5% 机高
TOL = 0.070                  # RDP 容差（H=10 单位）= 0.7% 机高
# ★ 0.03 时前脸被切成 46 段 —— 每个零部件的出挑各算一段，读不出「语法」。
#   0.07 是把「同一张皮上的小台阶」并掉、只留**造型节点**的档位（≈55 mm @8 m）。


# ---------------------------------------------------------------- 包络
def envelope(P, y0, y1, nb=NB):
    """返回 (fz 前脸, bz 后脸, hw 半宽)，各 nb 段；极值按**边插值**取。"""
    F = P.reshape(-1, 3, 3)
    # ★ 端点对必须成对拼（depth_map 第一版在这里翻过车）
    A = np.concatenate([F[:, i] for i, _ in ((0, 1), (1, 2), (2, 0))], 0)
    B = np.concatenate([F[:, j] for _, j in ((0, 1), (1, 2), (2, 0))], 0)
    ya, yb = A[:, 1], B[:, 1]
    zc, xa, xb = 1, 0, 0
    step = (y1 - y0) / nb
    fz = np.full(nb, np.nan)
    bz = np.full(nb, np.nan)
    hw = np.full(nb, np.nan)
    vert = ya == yb                       # 水平边：整条落在一条带里
    for k in range(nb):
        a, b = y0 + k * step, y0 + (k + 1) * step
        m = (np.maximum(ya, yb) >= a) & (np.minimum(ya, yb) <= b) & ~vert
        zv, xv = [], []
        if m.any():
            t0 = np.clip((a - ya[m]) / (yb[m] - ya[m]), 0, 1)
            t1 = np.clip((b - ya[m]) / (yb[m] - ya[m]), 0, 1)
            for t in (t0, t1):
                zv.append(A[m, 2] + t * (B[m, 2] - A[m, 2]))
                xv.append(A[m, 0] + t * (B[m, 0] - A[m, 0]))
        mv = vert & (ya >= a) & (ya <= b)
        if mv.any():
            zv.append(A[mv, 2]); zv.append(B[mv, 2])
            xv.append(A[mv, 0]); xv.append(B[mv, 0])
        if zv:
            z = np.concatenate([np.atleast_1d(q) for q in zv])
            x = np.concatenate([np.atleast_1d(q) for q in xv])
            fz[k], bz[k], hw[k] = z.max(), z.min(), np.abs(x).max()
    return fz, bz, hw


# ---------------------------------------------------------------- 折线拟合
def rdp(y, v, tol=TOL):
    """Ramer–Douglas–Peucker：返回保留下来的下标。"""
    idx = [0, len(y) - 1]
    keep = [True] * len(y)
    changed = True
    while changed:
        changed = False
        for i in range(len(idx) - 1):
            i0, i1 = idx[i], idx[i + 1]
            if i1 - i0 < 2:
                continue
            ys, vs = y[i0], v[i0]
            ye, ve = y[i1], v[i1]
            dy, dv = ye - ys, ve - vs
            L = np.hypot(dy, dv) or 1e-9
            yy, vv = y[i0 + 1:i1], v[i0 + 1:i1]
            d = np.abs(dv * (yy - ys) - dy * (vv - vs)) / L
            j = int(np.argmax(d))
            if d[j] > tol:
                idx.insert(i + 1, i0 + 1 + j)
                changed = True
    return idx


def segments(y, v, tol=TOL):
    """→ [(y0,y1,v0,v1,len,deg)]，deg 为对垂直线的偏角（朝 +v 为负）。"""
    ok = ~np.isnan(v)
    if ok.sum() < 4:
        return []
    yi, vi = y[ok], v[ok]
    idx = rdp(yi, vi, tol)
    out = []
    for i0, i1 in zip(idx, idx[1:]):
        dy, dv = yi[i1] - yi[i0], vi[i1] - vi[i0]
        out.append((yi[i0], yi[i1], vi[i0], vi[i1],
                    float(np.hypot(dy, dv)),
                    float(np.degrees(np.arctan2(dv, dy)))))
    return out


def show(name, segs, unit='H'):
    if not segs:
        print('  （无数据）')
        return
    print('  %-4s %-13s %-15s %8s %8s' % ('#', '高度 %', 'Δ值', '段长', '角度°'))
    for i, (y0, y1, v0, v1, ln, dg) in enumerate(segs, 1):
        print('  %-4d %5.1f–%5.1f   %+6.2f→%+6.2f  %8.3f  %+7.1f'
              % (i, 100 * y0 / 10, 100 * y1 / 10, v0, v1, ln, dg))


# ---------------------------------------------------------------- 出图
def chart(panels, out, title, sub):
    """两格并排：每格有自己的 z 轴（−2.4 … +2.4）与统一的 0–100% 高度轴。
    ★ 第一版三格挤在一个函数里、px() 用了全局宽度，结果曲线全挤在左半格、
      刻度与曲线对不上。**一格一套坐标，别共用。**"""
    W, H = 1400, 940
    cv = Image.new('RGB', (W, H), (255, 255, 255))
    d = ImageDraw.Draw(cv)
    f22 = ImageFont.truetype(FONT, 22)
    f14 = ImageFont.truetype(FONT, 14)
    f13 = ImageFont.truetype(FONT, 13)
    d.text((24, 16), title, font=f22, fill=(20, 20, 20))
    yy = 50
    for line in sub.split('\n'):
        d.text((24, yy), line, font=f14, fill=(110, 110, 110))
        yy += 20

    n = len(panels)
    colw = (W - 48) // n
    for k, (lab, Y, fz, bz, hw, sf, sb) in enumerate(panels):
        x0 = 24 + k * colw
        L, R = x0 + 44, x0 + colw - 24
        ytop, ybot = 150, H - 60
        pw, ph = R - L, ybot - ytop

        def py(y):
            return ybot - (y / 10.0) * ph

        def px(z):
            return L + (z + 2.4) / 4.8 * pw
        for pc in range(0, 101, 10):
            d.line([(L, py(pc / 10)), (R, py(pc / 10))], fill=(234, 234, 234))
            d.text((x0, py(pc / 10) - 7), '%d%%' % pc, font=f13, fill=(150, 150, 150))
        d.line([(px(0), ytop), (px(0), ybot)], fill=(205, 205, 205))
        d.text((L, ytop - 24), lab, font=f14, fill=(40, 40, 40))
        for arr, col in ((fz, (60, 110, 190)), (bz, (200, 96, 60))):
            pts = [(px(v), py(y)) for y, v in zip(Y, arr) if not np.isnan(v)]
            if len(pts) > 2:
                d.line(pts, fill=col, width=3)
        for segs, col, sgn in ((sf, (60, 110, 190), +1), (sb, (200, 96, 60), -1)):
            for (ya, yb, va, vb, _ln, dg) in segs:
                if abs(dg) < 8:
                    continue
                mx = px(0.5 * (va + vb)) + sgn * 26
                my = py(0.5 * (ya + yb))
                d.text((mx - 14, my - 9), '%+.0f°' % dg, font=f13, fill=col)
        d.text((L, ybot + 8), '← 后  z  → 前', font=f13, fill=(140, 140, 140))
    d.text((24, H - 28),
           '蓝 = 前脸 z   橙 = 后脸 z   标注 = 该段对垂直线的偏角（|角| < 8° 的短台阶不标）',
           font=f13, fill=(120, 120, 120))
    cv.save(out)
    return out, cv.size


def main():
    grp = None
    if '--group' in sys.argv:
        grp = sys.argv[sys.argv.index('--group') + 1]

    V, tris, gf, sets = UT.load_obj_grouped(UT.SRC)
    Vn, _ = RV.normalize(V)
    keep = np.ones(len(tris), bool)
    for tok in UT.REMOVE:
        keep &= ~UT.face_in(gf, sets, tok)
    if grp:
        keep &= UT.face_in(gf, sets, grp)
    Pt = Vn[tris[keep]].reshape(-1, 3)
    y0, y1 = float(Pt[:, 1].min()), float(Pt[:, 1].max())
    Y = np.linspace(y0 + 0.5 * (y1 - y0) / NB, y1 - 0.5 * (y1 - y0) / NB, NB)
    fz, bz, hw = envelope(Pt, y0, y1)

    tag = ('Unicorn 主干 · %s' % grp) if grp else 'Unicorn 主干'
    print('\n=== %s ===' % tag)
    print('\n[前脸 z]（正 = 朝前）')
    sf = segments(Y, fz)
    show('前', sf)
    print('\n[后脸 z]')
    sb = segments(Y, bz)
    show('后', sb)
    print('\n[半宽 |x|]')
    sw = segments(Y, hw)
    show('宽', sw)

    ours = []
    if True:
        S.CLEAN = True
        root, mesh = S.build()
        ps = []
        for c in root.children:
            if c.name not in ('skirt',):
                continue
            mb = S.Mesh(); S.collect2(c, mb)
            ps.append(np.array(mb.P, np.float32).reshape(-1, 3))
        if ps:
            Po = np.concatenate(ps, 0) / H_M * 10.0
            oy0, oy1 = float(Po[:, 1].min()), float(Po[:, 1].max())
            oY = np.linspace(oy0 + 0.5 * (oy1 - oy0) / NB, oy1 - 0.5 * (oy1 - oy0) / NB, NB)
            ofz, obz, ohw = envelope(Po, oy0, oy1)
            print('\n=== 我们的 skirt ===')
            print('\n[前脸 z]')
            sof = segments(oY, ofz)
            show('前', sof)
            print('\n[后脸 z]')
            sob = segments(oY, obz)
            show('后', sob)
            print('\n[半宽 |x|]')
            sow = segments(oY, ohw)
            show('宽', sow)
            ours = [(oY, ofz, obz, ohw, sof, sob)]

    panels = [(('参考 ' + grp) if grp else '参考主干', Y, fz, bz, hw, sf, sb)]
    if ours:
        o = ours[0]
        panels.append(('我们 skirt', o[0], o[1], o[2], o[3], o[4], o[5]))
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, 'curve_ruler.png')
    p, size = chart(panels, p,
                    '轮廓折线：每段的角度与长度',
                    'RDP 容差 %.3f H（≈ %.0f mm @8 m）；折线转折点 = 造型节点\n'
                    '角度为正 = 该段向 +z（前）倾；为负 = 向 −z（后）倾'
                    % (TOL, TOL / 10 * 8000))
    print('\n→ %s  %d × %d' % (p, size[0], size[1]))


if __name__ == '__main__':
    main()
