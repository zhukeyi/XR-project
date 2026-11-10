"""tools/leg_ab.py — 大腿「萝卜版 / 结构版」A/B 对照（同机位、同光照、同比例）

为什么必须单独出图
  `s2_graybox.py --views` 每次覆写 out/s2/*，改完就再也拿不出改前。
  而用户这次的判据是「**机体有明显改善、不再是大萝卜**」——
  这是一个 A/B 判断题，必须同机位并排看，不能靠日志里的件数说话。

  A = LEG_V2=False：一根 `L()` 闭合放样管 + 外侧刀口 + 前贴片 + 5 组贴花
  B = LEG_V2=True ：基体（暗）+ 髋/膝轭 + 前甲上下两片（横缝底有肋）
                    + 外甲刀口 + 内甲 + 后甲 + 后外象限的液压（缸+杆）
  C = 参考 Unicorn 的同高度段（**同一把尺子的标定行**）

★ 取景必须「留全，只推近」而不是「裁到只剩大腿」
  第一版按 y 带裁剪三角再渲染，结果大腿底部的**甲片侧壁**在空白背景上读成
  四片「飞刺」——它们本来被膝/小腿挡住，是裁剪自己把遮挡物拿掉了。
  **裁剪会制造缺陷**，所以这里改成：全部几何都留着，只把相机取景推到
  大腿高度（k = 10/view_h 的等比放大 + 平移）。同一比例尺，A/B/C 三行通用。

三张图各有分工，缺一不可
  leg_ab_thigh.png  大腿特写 3 行（A/B/参考）× 4 视角 —— 判「缝里读不读得出内构」
  leg_ab_full.png   整条腿 2 行 × 2 视角              —— 判「换掉大腿后腿还连不连得上」
  leg_ab_body.png   全身 3/4  A vs B                  —— 判「局部改善有没有破坏整体读法」
  ★ 第三张是防自欺的：局部特写最容易骗人，缝很好看但整机变成「拼装玩具」也是失败。

用法
  python3 tools/leg_ab.py
"""
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'tools'))

import refview as RV                                        # noqa: E402
import s2_graybox as S                                      # noqa: E402
import unicorn_trunk as UT                                   # noqa: E402
from gfx.gbuffer import rasterize                            # noqa: E402
from r3d import Renderer, look_at                             # noqa: E402

OUT = os.path.join(HERE, 'out', 'ref')
FONT = '/System/Library/Fonts/Hiragino Sans GB.ttc'
H10 = 10.0                    # 归一化机高（世界单位）


# ---------------------------------------------------------------- 取几何
def soup_of(root, name):
    """取某个分组节点的三角 + **材质索引/色板**。

    ★ 必须带材质：`shade()` 若只算法线明度，FRAME(0.215) 与 ARMOR(0.90) 渲染成
      同一个灰 —— 「缝里是暗的」这条判断就完全看不出来。第一版就是这么出的图，
      结论是「新结构跟旧的一模一样」，其实是渲染器把材质丢了。
    """
    for c in root.children:
        if c.name == name:
            mb = S.Mesh()
            S.collect2(c, mb)
            P = np.array(mb.P, np.float32)
            mi, base, _e = mb.mat_table()
            return P, mi, base
    raise KeyError(name)


def build(leg_v2):
    S.CLEAN = True                 # 只留主干（无浮游炮/折叠翼），对照更干净
    S.LEG_V2 = leg_v2
    root, mesh = S.build()
    return root, mesh


def to_h10(P):
    """米 → 「机高 = 10」世界单位，**按全机 7.930 m 换算**，脚底 0、x/z 居中。

    ★ 不能拿「这条腿自己的 bbox」去归一化：腿高 4.34 m 会被拉到 10，
      于是同一个 view_h 在不同版本上代表不同的真实尺寸（踩过一次）。
      比例尺只能来自**整机**，否则 A/B 看起来的粗细差就变成缩放差。
    """
    Q = np.asarray(P, np.float32).reshape(-1, 3) * (H10 / 7.930)
    return Q.reshape(-1, 3, 3), H10 / 7.930


def ref_leg():
    """参考 Unicorn 主干，H=10，只取**右腿**（x>0.55，避开两腿中缝与裙甲）。"""
    V, tris, gf, sets = UT.load_obj_grouped(UT.SRC)
    Vn, _ = RV.normalize(V)
    keep = np.ones(len(tris), bool)
    for tok in UT.REMOVE:
        keep &= ~UT.face_in(gf, sets, tok)
    P = Vn[tris[keep]].astype(np.float32)
    c = P.mean(1)
    # 大腿高度带 2.75–5.05（H=10），x>0.5 → 单侧
    m = (c[:, 1] > 2.60) & (c[:, 1] < 5.15) & (c[:, 0] > 0.50)
    # 但要保留跨界的三角，否则底部会出现「切口」
    return P[m]


class Soup:
    def __init__(self, P, mi=None, base=None):
        P = np.asarray(P, np.float32).reshape(-1, 3, 3)
        n = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
        L = np.linalg.norm(n, axis=1, keepdims=True)
        keep = L[:, 0] > 1e-12
        nt = len(P)                       # ★ 过滤**之前**的三角数
        if mi is None:
            mi, base = np.zeros((nt,), np.int32), \
                np.array([[0.80, 0.81, 0.82]], np.float32)
        mi = np.asarray(mi, np.int32)
        if len(mi) != nt:                 # 材质表是逐面的，退化面会让它多一个
            mi = np.pad(mi, (0, max(0, nt - len(mi))))[:nt]
        P, n = P[keep], n[keep] / L[keep]
        self.P = P
        self.N = np.repeat(n[:, None, :], 3, 1)
        self.T = np.zeros((len(P), 3, 2), np.float32)
        self.mi = mi[keep]
        self.base = np.asarray(base, np.float32)
        self.Fi = np.arange(len(P), dtype=np.int32)
        self.emis = np.zeros(len(self.base), np.float32)

    def arrays(self):
        return self.P, self.N, self.T, self.mi, self.Fi, self.base, self.emis

    def __len__(self):
        return len(self.P)


def frame(P, cy, view_h, cx=None, cz=None):
    """等比推近：view_h（世界单位）撑满面板竖向的 0.72 段，焦点落中。

    ★ 不做任何裁剪 —— 见文件头：「裁剪会制造缺陷」。
    cx/cz 缺省取 y 带内的均值（每条腿各自居中）；A/B 两行必须传**同一个** cx，
      否则横向的细微平移会被误读成造型变化。
    """
    V = P.reshape(-1, 3)
    if cx is None or cz is None:
        m = (V[:, 1] > cy - 0.5 * view_h) & (V[:, 1] < cy + 0.5 * view_h)
        if cx is None:
            cx = float(V[m, 0].mean()) if m.any() else 0.0
        if cz is None:
            cz = float(V[m, 2].mean()) if m.any() else 0.0
    k = H10 / view_h
    Q = V.copy()
    Q[:, 0] = (Q[:, 0] - cx) * k
    Q[:, 1] = (Q[:, 1] - cy) * k + H10 * 0.5
    Q[:, 2] = (Q[:, 2] - cz) * k
    return Q.reshape(-1, 3, 3), (k, cx, cz)


def shade(sz, yaw, panel, pad=1.02):
    """正交近似渲一张**带材质明度**的灰模（lambert + 半球环境 + 深度雾 + 轮廓线）。

    ★ albedo 必须进画面：整份设计的读数就靠 ARMOR 0.90 / FRAME 0.215 的对比，
      把材质丢掉等于把要验的东西丢了。
    """
    W, H = panel
    dist = 30.0 * H10
    fov = 2.0 * math.degrees(math.atan((H10 * 0.72 * pad) / dist))
    rd = Renderer(W, H, ss=1, fov=fov)
    cy = H10 * 0.5
    cm = look_at((0.0, cy, dist), (0.0, cy, 0.0), roll=0)
    P, N, T_, mi, Fi, base, _e = sz.arrays()
    Pr, Nr = RV._rot(P, N, yaw, 0.0)
    gb, _ = rasterize(Pr, Nr, T_, mi, Fi, cm, fov, rd.WS, rd.HS)
    cov = gb.fid >= 0
    nn = gb.nrm.copy()
    nn /= np.maximum(np.linalg.norm(nn, axis=-1, keepdims=True), 1e-9)
    L = np.array([-0.42, 0.58, 0.70])
    L /= np.linalg.norm(L)
    lam = np.clip(nn @ L, 0, 1)
    amb = 0.5 + 0.28 * np.clip(nn[..., 1], -1, 1)
    g = 0.22 + 0.60 * lam + 0.26 * amb
    dep = np.where(cov, gb.depth, np.nan)
    d0 = np.nanpercentile(dep, 3)
    fog = np.clip((dep - d0) / (0.55 * H10), 0, 1)
    g = g * (1.0 - 0.35 * fog)
    midx = np.clip(np.where(cov, gb.midx, 0), 0, len(base) - 1)
    alb = np.asarray(base, np.float32)[midx]
    rgb = np.clip(np.nan_to_num(g)[..., None] * alb * 1.18 * 255, 0, 255).astype(np.uint8)
    out = np.full((H, W, 3), 255, np.uint8)
    out[cov] = rgb[cov]
    er = cov.copy()
    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        er &= np.roll(np.roll(cov, dy, 0), dx, 1)
    out[cov & ~er] = (58, 62, 66)
    return out, cov


def curv_stats(sz, yaw, panel):
    """曲率突变率 + 断崖率（与 crevice_ruler 同口径，但用 **|∇²d|**）。

    ★ 符号：lap = (f(+1)+f(−1)+f(+u)+f(−u) − 4f)/4。合成测试（平板 + 凹槽）
      给出 [.. +4, −4, 0, 0, −4, +4 ..] —— 说明**凹槽底与凸唇两侧都给同量级的
      正负值**，只取正号会漏掉一半（且把「凸边的多少」当成「缝的多少」）。
      缝的特征是「两侧有唇、中间有底」= 曲率在两个方向上都突变，
      所以取绝对值才是不偏心的判据。这在 A/B 上不改变结论（两边同算子），
      但让读数可以拿去跟参考比。
    """
    W, H = panel
    dist = 30.0 * H10
    fov = 2.0 * math.degrees(math.atan((H10 * 0.72) / dist))
    rd = Renderer(W, H, ss=1, fov=fov)
    cm = look_at((0.0, H10 * 0.5, dist), (0.0, H10 * 0.5, 0.0), roll=0)
    P, N, T_, mi, Fi, _b, _e = sz.arrays()
    Pr, Nr = RV._rot(P, N, yaw, 0.0)
    gb, _ = rasterize(Pr, Nr, T_, mi, Fi, cm, fov, rd.WS, rd.HS)
    cov = gb.fid >= 0
    if cov.sum() == 0:
        return dict(curv=0.0, step=0.0, mask=cov, cov=cov)
    d = np.where(cov, gb.depth, np.nanmedian(gb.depth[cov])) * 80.0     # → cm
    okn = cov.copy()
    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        okn &= np.roll(np.roll(cov, dy, 0), dx, 1)
    lap = (np.roll(d, 1, 1) + np.roll(d, -1, 1)
           + np.roll(d, 1, 0) + np.roll(d, -1, 0) - 4.0 * d) / 4.0
    m = (np.abs(lap) > 0.45) & okn
    s = np.zeros_like(cov)
    s[:, :-1] |= np.abs(np.diff(d, axis=1)) > 2.4
    s[:-1, :] |= np.abs(np.diff(d, axis=0)) > 2.4
    s &= cov
    n = max(int(cov.sum()), 1)
    return dict(curv=float(m.sum()) / n, step=float(s.sum()) / n,
                mask=m & cov, cov=cov)


def trim(img, pad=4):
    a = np.asarray(img)
    m = (a < 250).any(2)
    ys, xs = np.nonzero(m)
    if not len(ys):
        return Image.fromarray(a)
    return Image.fromarray(a[max(0, ys.min() - pad):ys.max() + 1 + pad,
                              max(0, xs.min() - pad):xs.max() + 1 + pad])


def sheet(rows, titles, views, panel, path, header, sub, marks=None,
          overlay=None, row_cols=None, footer=None):
    nrow, ncol = len(rows), len(views)
    lab_h, foot_h, gap = 30, (34 if footer else 22), 10
    W = gap + (panel[0] + gap) * ncol
    Hh = 76 + (lab_h + panel[1] + foot_h + gap) * nrow
    cv = Image.new('RGB', (W, Hh), (255, 255, 255))
    d = ImageDraw.Draw(cv)
    d.text((gap + 4, 12), header, font=ImageFont.truetype(FONT, 22), fill=(20, 20, 22))
    d.text((gap + 4, 44), sub, font=ImageFont.truetype(FONT, 13), fill=(112, 112, 116))
    y = 76
    for ri, row in enumerate(rows):
        Q, mi, ba = row if len(row) == 3 else (row[0], None, None)
        col = (row_cols[ri] if row_cols else (60, 60, 64))
        d.text((gap + 4, y + 5), titles[ri], font=ImageFont.truetype(FONT, 16), fill=col)
        for ci, (vn, yaw) in enumerate(views):
            img, cov = shade(Soup(Q, mi, ba), yaw, panel)
            if overlay is not None and overlay[ri][ci] is not None:
                a = img.copy()
                gm = overlay[ri][ci]
                a[gm] = (0.50 * a[gm] + 0.50 * np.array([205, 40, 40])).astype(np.uint8)
                img = a
            im = trim(Image.fromarray(img))
            if im.width > panel[0] or im.height > panel[1]:
                sc = min(panel[0] / im.width, panel[1] / im.height)
                im = im.resize((max(1, int(im.width * sc)),
                                max(1, int(im.height * sc))), Image.BICUBIC)
            cv.paste(im, (gap + ci * (panel[0] + gap) + (panel[0] - im.width) // 2,
                          y + lab_h + (panel[1] - im.height) // 2))
            d.text((gap + ci * (panel[0] + gap) + 4, y + lab_h + panel[1] + 2),
                   vn, font=ImageFont.truetype(FONT, 12), fill=(140, 140, 144))
        if marks and marks[ri]:
            d.text((gap + panel[0] * ncol + (ncol - 1) * gap - 4, y + 5), marks[ri],
                   font=ImageFont.truetype(FONT, 13), fill=col, anchor='ra')
        y += lab_h + panel[1] + foot_h + gap
    if footer:
        d.text((gap + 4, Hh - foot_h + 2), footer, font=ImageFont.truetype(FONT, 12),
               fill=(150, 150, 154))
    cv.save(path)
    print('→ %s  %d × %d' % (path, cv.size[0], cv.size[1]))
    return path


def main():
    os.makedirs(OUT, exist_ok=True)
    rA, mA = build(False)
    rB, mB = build(True)
    PA, miA, baA = soup_of(rA, 'leg_L')
    PB, miB, baB = soup_of(rB, 'leg_L')
    LA = to_h10(PA)[0]
    LB = to_h10(PB)[0]
    RP = ref_leg()

    # 大腿取景：我们 2.36–4.24 m → H10 单位 2.98–5.35；参考按同比例尺取 2.85–5.10
    VW = 2.62                         # view_h（世界单位，≈2.1 m）
    CY_A, CY_R = 4.16, 3.95
    views4 = [('正', 0.0), ('3/4', 35.0), ('侧', 90.0), ('后 3/4', 145.0)]
    PAN = (420, 660)

    # A/B 共用同一个横向中心（取 A 的），保证「横向位移」不会被读成造型变化
    _k, CXA, CZA = frame(LA, CY_A, VW)[1]

    rows, st, gm = [], [], []
    for P, mi, ba, cy, cx, cz in (
            (LA, miA, baA, CY_A, CXA, CZA),
            (LB, miB, baB, CY_A, CXA, CZA),
            (RP, None, None, CY_R, None, None)):
        Q, _ = frame(P, cy, VW, cx, cz)
        rows.append((Q, mi, ba))
        r_g, r_s, r_m = [], [], []
        for vn, yaw in views4:
            r = curv_stats(Soup(Q), yaw, PAN)
            r_g.append(r['curv'])
            r_s.append(r['step'])
            r_m.append(r['mask'])
        st.append((float(np.mean(r_g)) * 100, float(np.mean(r_s)) * 100))
        gm.append(r_m)

    titles = ['A  LEG_V2=False  一根闭合放样管 + 贴花（萝卜版）',
              'B  LEG_V2=True   基体 + 5 片贴甲 + 液压（结构版）',
              'C  参考 Unicorn 同高度段（右腿，H=10）']
    marks = ['曲率突变 %.1f%%  断崖 %.1f%%' % st[0],
             '曲率突变 %.1f%%  断崖 %.1f%%' % st[1],
             '曲率突变 %.1f%%  断崖 %.1f%%' % st[2]]

    sheet(rows, titles, views4, PAN, os.path.join(OUT, 'leg_ab_thigh.png'),
          '大腿 A/B/C 特写 · 同比例尺 / 同机位 / 同光照（红 = 深度曲率突变像素）',
          '全部几何都留着，只把取景推近 —— 不裁剪。C 行是标定：B 的读数要往 C 靠，不是往 0 靠。',
          marks=marks, overlay=gm, row_cols=[(120, 120, 124), (176, 40, 40), (40, 96, 168)],
          footer='读数口径：深度图二阶梯度的绝对值 |∇²d| > 0.45 cm/px² 记为曲率突变；相邻像素 |Δd| > 2.4 cm 记为断崖。'
                 ' 每个视角各量一次取均值（不许只挑最好看的视角报）。')

    # 整条腿：判「换掉大腿后腿还连不连得上」
    rows2 = [(to_h10(PA)[0], miA, baA), (to_h10(PB)[0], miB, baB)]
    rows2 = [(frame(P, 5.00, 10.4)[0], mi, ba) for P, mi, ba in rows2]
    sheet(rows2, ['A  整腿（萝卜大腿）', 'B  整腿（结构大腿）'],
          [('3/4', 35.0), ('侧', 90.0)], (400, 720),
          os.path.join(OUT, 'leg_ab_full.png'),
          '整腿 A/B · 大腿以外一字未改 —— 差别只应出现在 2.40–4.24 m 这一段',
          '★ 若差异溢到膝下/踝上，说明新甲片穿模或与膝甲不接，属失败（不是「改善」）',
          row_cols=[(120, 120, 124), (176, 40, 40)])

    # 全身：判「局部改善有没有破坏整体读法」
    VA = to_h10(np.array(mA.P, np.float32))[0]
    VB = to_h10(np.array(mB.P, np.float32))[0]
    miMA, baMA, _eA = mA.mat_table()
    miMB, baMB, _eB = mB.mat_table()
    sheet([(VA, miMA, baMA), (VB, miMB, baMB)],
          ['A  全身（萝卜大腿）', 'B  全身（结构大腿）'],
          [('正', 0.0), ('3/4', 35.0)], (360, 760),
          os.path.join(OUT, 'leg_ab_body.png'),
          '全身 A/B（CLEAN 主干）· 防自欺：局部缝好看但整机变「拼装玩具」也算失败',
          '大腿只占全高 20%，这张图上「有没有改善」只能靠**明暗层次**判 —— 缝要变成一道暗线',
          row_cols=[(120, 120, 124), (176, 40, 40)])

    print('\n  大腿段读数（四视角均值）：')
    for tag, (g, s_) in zip('ABC', st):
        print('  %s  曲率突变 %5.1f%%   断崖 %5.1f%%' % (tag, g, s_))
    print('  A→B：曲率突变 %.2f×   断崖 %.2f×' % (st[1][0] / max(st[0][0], 1e-6),
                                                st[1][1] / max(st[0][1], 1e-6)))
    print('  B 相对 C（参考）：曲率突变 %.2f×   断崖 %.2f×'
          % (st[1][0] / max(st[2][0], 1e-6), st[1][1] / max(st[2][1], 1e-6)))


if __name__ == '__main__':
    main()
