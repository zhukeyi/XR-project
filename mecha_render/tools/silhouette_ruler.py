"""tools/silhouette_ruler.py — 侧影曲线：沿高度逐带量「半宽」，并归因到装配

为什么要这一把尺子
  §27 建立了 W/H、D/W、最宽处高度这几个**整机**标量。但「最宽处 0.788H（我们）
  vs 0.637H（Unicorn）」只说了「重心颠倒」，没说**每一层高度上差多少、差在谁身上**。
  而肩甲要收多少、前臂要放多少，恰恰是逐层的量。

  所以这里量一件事：把机高切成 100 带，每带取 max|x| 当**半宽**，
  再问「这个 max 是哪一件贡献的」。得到两张曲线：

      Unicorn 主干   半宽曲线 + 每段的归属件
      我们主干       半宽曲线 + 每段的归属件

  两条曲线叠在一起，「谁在哪一层凸出去」就不再是感觉。

为什么用 max 而不是分位数
  上一版 trunk_ruler.measure() 用 99.5 分位，是为了压掉孤立顶点造成的毛刺。
  但侧影曲线要的正是**外轮廓**：分位数会把肩甲外缘、肘外甲这些「一层只有几十个
  顶点」的薄件削掉，而那正是要看的。这里改用 max，同时**按带宽聚合法**降噪
  （每带内先算每件的 max|x|，再取各件最大者），孤立顶点最多污染 1% 的一带，
  在 100 带曲线上是可见的尖刺，能认出来。

为什么必须归一化到同一个 H
  见 trunk_ruler.py 的说明：B 用 A 的、D 用 C 的，否则剥掉的体量会被放大回去。

用法
  python3 tools/silhouette_ruler.py                 # 打印 100 带表 + 出图
  python3 tools/silhouette_ruler.py --step 2        # 每 2% 打一行
"""
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'tools'))

import refview as RV                                     # noqa: E402
import s2_graybox as S                                   # noqa: E402
import unicorn_trunk as UT                               # noqa: E402

OUT = os.path.join(HERE, 'out', 'ref')
FONT = '/System/Library/Fonts/Hiragino Sans GB.ttc'
H = 10.0
NB = 100                     # 100 带 = 每带 1% 机高


# ---------------------------------------------------------------- 归一化
def norm_fit(P):
    V = P.reshape(-1, 3)
    lo, hi = V.min(0), V.max(0)
    s = H / max(float(hi[1] - lo[1]), 1e-9)
    cx, cz = 0.5 * (lo[0] + hi[0]), 0.5 * (lo[2] + hi[2])
    return np.array([-cx, -lo[1], -cz], np.float32), s


def apply(V, off, s):
    """只对**顶点**做（不是三角形汤），因为归属要按件算。"""
    return (V + off) * s


# ---------------------------------------------------------------- 我们的：按件
def our_parts(clean):
    """返回 [(件名, 顶点(N,3))]，已归一化到 H=10。"""
    S.CLEAN = bool(clean)
    root, _ = S.build()
    rows = []
    for c in root.children:
        mb = S.Mesh()
        S.collect2(c, mb)
        if not mb.P:
            continue
        rows.append((c.name, np.asarray(mb.P, np.float64).reshape(-1, 3)))
    allV = np.concatenate([r[1] for r in rows], 0)
    off, s = norm_fit(allV)
    return [(n, apply(V, off, s)) for n, V in rows]


# ---------------------------------------------------------------- Unicorn：按装配
def _labels(sets):
    """375 个 g 组 → 数量可控的装配标签。

    `sets[i]` 是一个 g 行的**全部 token**，而 token 是**层级路径**：
        {'UNICORN_GUNDAM_MOD_G', 'main_assy_G', 'body_assy_G',
         'upper_body_assy_G', 'shoulder_armor_assy_G', 'R_shoulder_armor_G'}
    所以「最深的那个 token」才是这块的真实归属。深度的代理指标是**出现次数**
    （祖先必然覆盖更多组），取 `_assy_G` 结尾里出现次数最少的那个。
    """
    from collections import Counter
    cnt = Counter()
    for s in sets:
        for t in s:
            cnt[t] += 1
    out = []
    for s in sets:
        cand = [t for t in s if t.endswith('_assy_G') and t != 'main_assy_G']
        pool = cand if cand else [t for t in s if t != 'UNICORN_GUNDAM_MOD_G']
        out.append(min(pool, key=lambda t: (cnt[t], -len(t))) if pool else 'root')
    return out


def unicorn_parts():
    """返回 ([(装配名, 顶点(N,3))], meta)，剥掉 REMOVE 的 4 组，已归一化到 H=10。

    ★ 归一化用**含外挂的 bbox**（A 的口径），与 trunk_ruler 一致。
    """
    V, tris, gf, sets = UT.load_obj_grouped(UT.SRC)
    Vn_raw, meta = RV.normalize(V)          # 原素材自带的归一化
    U_full = Vn_raw[tris]
    off2, s2 = norm_fit(U_full)             # 再拉到 H=10

    keep = np.ones(len(tris), bool)
    for tok in UT.REMOVE:
        keep &= ~UT.face_in(gf, sets, tok)

    lab_of_g = _labels(sets)
    groups = {}
    for i in np.nonzero(keep)[0]:
        groups.setdefault(lab_of_g[gf[i]], []).append(i)

    out = []
    for name, fi in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        fi = np.array(fi, np.int64)
        out.append((name, apply(Vn_raw[tris[fi]].reshape(-1, 3), off2, s2)))
    return out, meta


# ---------------------------------------------------------------- 曲线
def profile(parts, nb=NB):
    """返回 (半宽[nb], 归属[nb])。

    ★ 必须用**边插值**，不能用顶点采样。
      我们的件是「按层放样」的：一个 0.4 m 高的筒身只在上下两层有顶点，
      中间 0.4 m 内一个顶点都没有。顶点采样会在层与层之间读出**真空带**——
      第一版就踩了这个坑：65.5%H 处我们的手臂整带掉到 0.391（读到的是腰），
      而实际手臂在那里是 2.53。那不是模型缺肉，是尺子漏肉。

      正确做法：半宽是**侧影**，任意高度上的 max|x| 必然落在某条三角形边上
      （三角形内部是顶点的凸组合，不可能超过边的极值）。所以把所有边按高度
      裁到 [ylo, yhi] 区段，看这条小段两端的 x —— x 沿边线性，极值必在端点。
    """
    half = np.zeros(nb)
    who = ['—'] * nb
    dy_span = H / nb
    for name, V in parts:
        F = V.reshape(-1, 3, 3)
        E = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]], 0)
        x0, y0 = E[:, 0, 0], E[:, 0, 1]
        x1, y1 = E[:, 1, 0], E[:, 1, 1]
        lo = np.minimum(y0, y1)
        hi = np.maximum(y0, y1)
        d = y1 - y0
        d = np.where(np.abs(d) < 1e-12, 1e-12, d)
        loc = np.full(nb, -1.0)
        for k in range(nb):
            ylo = k * dy_span
            yhi = ylo + dy_span
            m = (hi >= ylo) & (lo <= yhi)
            if not m.any():
                continue
            ya = np.maximum(lo[m], ylo)
            yb = np.minimum(hi[m], yhi)
            ok = yb >= ya
            if not ok.any():
                continue
            ya, yb = ya[ok], yb[ok]
            xa0, dy0, dx0 = x0[m][ok], d[m][ok], (x1[m] - x0[m])[ok]
            xa = xa0 + (ya - y0[m][ok]) * dx0 / dy0
            xb = xa0 + (yb - y0[m][ok]) * dx0 / dy0
            loc[k] = max(np.abs(xa).max(), np.abs(xb).max())
        better = loc > half
        half[better] = loc[better]
        for k in np.nonzero(better)[0]:
            who[k] = name
    return half, who


def short(name):
    """把装配名压到能进表格的宽度。"""
    n = name.replace('_assy_G', '').replace('_G', '')
    n = n.replace('shoulder_armor', 'shldr').replace('shoulder', 'shldr')
    n = n.replace('r_arm', 'arm').replace('r_leg', 'leg')
    n = n.replace('back_pack', 'pack').replace('rear_waist_thruster', 'waist_thr')
    return n[:16]


# ---------------------------------------------------------------- 出图
def draw_chart(u_half, u_who, o_half, o_who, path):
    """侧影曲线：横轴 = 半宽，纵轴 = 高度。

    ★ 第一版四个排版错误（都改掉了）：
      ① 纵轴 0.0 在上、10.0 在下 —— py() 把 t=0 映到画布顶部，读图时脚在上头在下；
      ② 右侧「归属变化」列表在 900 px 画布里排了 60 多行，直接溢出画布底部；
      ③ 两条「最宽处」标注几乎同高同 x，红字压蓝字，两行糊成一行；
      ④ 标注文字压在曲线上。
    现在：纵轴 0 在底；右侧只留图例 + 两个最宽处的读数；标注做「上下错身」避让。
    """
    padl, padr, padt, padb = 66, 236, 120, 58
    w, h = 940, 780
    cv = Image.new('RGB', (w, h), (255, 255, 255))
    d = ImageDraw.Draw(cv)
    f28 = ImageFont.truetype(FONT, 27)
    f17 = ImageFont.truetype(FONT, 17)
    f13 = ImageFont.truetype(FONT, 13)
    f14 = ImageFont.truetype(FONT, 14)

    d.text((padl, 14), '侧影曲线 · 半宽随高度（机高归一 = 10）', font=f28, fill=(20, 20, 20))
    d.text((padl, 50), '横轴 = max|x|（机高单位）；纵轴 = 高度，脚底在底。'
                       '同一高度上曲线越靠右 = 那一层越宽。', font=f17, fill=(105, 105, 105))
    d.text((padl, 74), '蓝 = Unicorn 主干，红 = 我们主干。曲线上的点 = 该机「最宽处」，'
                       '旁边注明贡献 max|x| 的件。', font=f17, fill=(105, 105, 105))

    x0, x1 = padl, w - padr
    y0, y1 = h - padb, padt          # y0 = 底部（0H），y1 = 顶部（10H）
    XMAX = 3.0

    def px(v):
        return x0 + (x1 - x0) * min(v, XMAX) / XMAX

    def py(t):                        # t = 0..1 高度；0 → 底部
        return y0 - (y0 - y1) * t

    # 网格 + 刻度（纵轴自下而上 0→10）
    for k in range(0, 11):
        t = k / 10
        yy = py(t)
        d.line([(x0, yy), (x1, yy)], fill=(234, 234, 234))
        d.text((x0 - 44, yy - 8), '%.1f' % (t * H), font=f13, fill=(145, 145, 145))
    for k in range(0, 7):
        v = k * 0.5
        xx = px(v)
        d.line([(xx, y0), (xx, y1)], fill=(234, 234, 234))
        d.text((xx - 12, y0 + 7), '%.1f' % v, font=f13, fill=(145, 145, 145))
    d.line([(x0, y0), (x1, y0)], fill=(90, 90, 90), width=1)
    d.line([(x0, y0), (x0, y1)], fill=(90, 90, 90), width=1)
    d.text((x0 + 4, y0 + 22), '半宽 (m)，机高归一 10', font=f13, fill=(150, 150, 150))

    # 曲线
    for half, col, wid in ((u_half, (52, 108, 196), 2), (o_half, (200, 48, 48), 2)):
        pts = [(px(half[k]), py((k + 0.5) / NB)) for k in range(NB)]
        d.line(pts, fill=col, width=wid)

    # 两个最宽处：图上只点两个圆点（标 U / O），读数搬到右侧面板。
    # ★ 试过在图上直接写一行完整读数：两个点只差 0.2 m、0.02H，两行字必然叠在一起，
    #   「上下错身」也只能错开 16 px，14 px 的字体照样糊成一行。读数属于表格，不属于曲线。
    ku, ko = int(np.argmax(u_half)), int(np.argmax(o_half))
    for val, k, col, tag in ((u_half[ku], ku, (52, 108, 196), 'U'),
                             (o_half[ko], ko, (200, 48, 48), 'O')):
        xx, yy = px(val), py((k + 0.5) / NB)
        d.ellipse([xx - 5, yy - 5, xx + 5, yy + 5], fill=(255, 255, 255),
                  outline=col, width=2)
        d.text((xx - 4, yy - 15), tag, font=f13, fill=col)

    # 右侧：图例 + 两个读数（不再排 60 行归属，那部分在控制台表与 JSON 里）
    lx = x1 + 26
    d.text((lx, y1), '读法', font=f17, fill=(30, 30, 30))
    yy = y1 + 30
    for col, tag in (((52, 108, 196), 'Unicorn 主干'), ((200, 48, 48), '我们主干')):
        d.line([(lx, yy + 7), (lx + 22, yy + 7)], fill=col, width=3)
        d.text((lx + 30, yy), tag, font=f14, fill=(60, 60, 60))
        yy += 24
    yy += 10
    d.text((lx, yy), '最宽处（图上圈出的两点）', font=f13, fill=(30, 30, 30))
    yy += 20
    for val, k, wn, col, tag in ((u_half[ku], ku, u_who[ku], (52, 108, 196), 'U'),
                                 (o_half[ko], ko, o_who[ko], (200, 48, 48), 'O')):
        d.text((lx, yy), '%s  %.2f @ %.0f%%H' % (tag, val, 100 * (k + 0.5) / NB),
               font=f13, fill=col)
        yy += 16
        d.text((lx + 14, yy), short(wn) + '（该点归属件）', font=f13, fill=(120, 120, 120))
        yy += 20
    yy += 12
    for line in ('· 曲线右移 = 那一层更宽',
                 '· 红色在 75–89%H 的一小段',
                 '  平台 = 肩甲（改前这',
                 '  一段就是全机最宽处）',
                 '',
                 '· 蓝线在 64%H 处最右 =',
                 '  参考机体的最宽处是',
                 '  手/前臂，不是肩',
                 '',
                 '· 0–20%H 两线都收窄：',
                 '  脚踝是最细的一层'):
        d.text((lx, yy), line, font=f13, fill=(110, 110, 110))
        yy += 19
    cv.save(path)
    return cv.size


# ---------------------------------------------------------------- main
def main():
    os.makedirs(OUT, exist_ok=True)
    step = 2
    if '--step' in sys.argv:
        step = int(sys.argv[sys.argv.index('--step') + 1])

    up, umeta = unicorn_parts()
    op = our_parts(True)
    print('Unicorn 主干：%d 个装配，原始 %.1f cm' % (len(up), umeta['raw_height']))
    print('我们主干：%d 个顶层件' % len(op))

    u_half, u_who = profile(up)
    o_half, o_who = profile(op)

    # ---- 控制台表
    print('\n' + '=' * 92)
    print('侧影曲线（半宽 = max|x|，机高归一 10）')
    print('=' * 92)
    print('  %6s %10s %-16s %10s %-16s %8s' %
          ('高度%', 'U半宽', 'U 归属', 'O半宽', 'O 归属', 'Δ'))
    for k in range(NB - 1, -1, -step):
        du = u_half[k] - o_half[k]
        print('  %6.1f %10.3f %-16s %10.3f %-16s %+8.3f' %
              (100 * (k + 0.5) / NB, u_half[k], short(u_who[k]),
               o_half[k], short(o_who[k]), du))

    # ---- 关键读数
    ku, ko = int(np.argmax(u_half)), int(np.argmax(o_half))
    print('\n  关键读数：')
    print('  · 最宽处：Unicorn %.3f @ %.0f%%H（%s） / 我们 %.3f @ %.0f%%H（%s）'
          % (u_half[ku], 100 * (ku + 0.5) / NB, short(u_who[ku]),
             o_half[ko], 100 * (ko + 0.5) / NB, short(o_who[ko])))

    # ★ 按**件**取值，不按高度带。
    #   第一版按「74–95%H 这段的最大半宽」量肩层，读出来 Unicorn 2.587 ——
    #   但那个数在 74% 高度，归属是 laser_lever（手臂外侧的件），
    #   于是「肩层」这一行把手臂算进了肩膀，与上面「最宽处在 64%H 的手」自相矛盾。
    #   同一份报告里两个字段互相打架，比没有这个字段更坏。按件取就没有这个问题。
    def own_max(half, who, pred):
        ks = [k for k in range(len(half)) if pred(who[k])]
        if not ks:
            return 0.0, '—', 0.0
        k = max(ks, key=lambda j: half[j])
        return half[k], who[k], (k + 0.5) / len(half)

    u_sh, u_shn, u_shy = own_max(u_half, u_who, lambda n: 'shoulder' in n)
    o_sh, o_shn, o_shy = own_max(o_half, o_who, lambda n: n.startswith('sh_'))
    print('  · 肩甲外缘：Unicorn %.3f @%.0f%%（%s） / 我们 %.3f @%.0f%%（%s） → %+.1f%%'
          % (u_sh, 100 * u_shy, short(u_shn), o_sh, 100 * o_shy, short(o_shn),
             100 * (o_sh / u_sh - 1) if u_sh else 0))

    u_ar, u_arn, u_ary = own_max(u_half, u_who, lambda n: 'arm' in n or 'palm' in n
                                 or 'finger' in n or 'hand' in n or 'pinky' in n
                                 or 'index' in n or 'thumb' in n or 'movable' in n
                                 or 'lever' in n)
    o_ar, o_arn, o_ary = own_max(o_half, o_who, lambda n: n.startswith('arm_'))
    print('  · 臂外缘：  Unicorn %.3f @%.0f%%（%s） / 我们 %.3f @%.0f%%（%s） → %+.1f%%'
          % (u_ar, 100 * u_ary, short(u_arn), o_ar, 100 * o_ary, short(o_arn),
             100 * (o_ar / u_ar - 1) if u_ar else 0))
    print('    → 肩:臂 = Unicorn %.2f : 1 / 我们 %.2f : 1（**这个比值才决定上半身读作'
          '「宽肩」还是「窄肩宽臂」**）' % (u_sh / u_ar, o_sh / o_ar))

    p = os.path.join(OUT, 'silhouette_ruler.png')
    sz = draw_chart(u_half, u_who, o_half, o_who, p)
    print('\n→ %s  %d × %d' % (p, sz[0], sz[1]))

    d = os.path.join(OUT, 'silhouette_ruler.json')
    with open(d, 'w') as f:
        json.dump(dict(
            unicorn=dict(half=[float(v) for v in u_half], who=u_who),
            ours=dict(half=[float(v) for v in o_half], who=o_who)),
            f, ensure_ascii=False, indent=1)
    print('→ %s' % d)


if __name__ == '__main__':
    main()
