"""tools/trunk_ruler.py — 用 Unicorn 的主干当尺子，量我们自己的主干

为什么要有这个文件
  §26 把自己的模型剥干净之后，得到了「主干」，但**没有判据**——
  D/W 0.5614 到底算深还是算浅？肩宽 0.565H 算宽还是算窄？
  上一轮用的锚点 W/H 0.561 / D/W 0.627 是从 `UNICORN_GUNDAM_OBJ.obj`
  量出来的，但那两个数量的是**含背包的 Unicorn**。拿含背包的参考去要求
  不含背包的机体，方向从一开始就是错的。

  所以这个脚本做一件事：**把两个模型放进同一个归一化、同一台相机、同一套定义里量**。

      A  Unicorn 原素材         （含背包 / 肩炮 / 推进器）
      B  Unicorn 主干           （剥掉 4 组装配）
      C  我们 · 现构型           （--clean 关）
      D  我们 · 主干构型         （--clean 开）

  四个都归一到「机高 = 10、脚底 y = 0」，缩放与站位一致，横排可直接叠着看。

关键：两套归一化必须各用各的 **full** bbox
  如果用每个变体自己的 bbox 归一，剥掉背包后模型会被重新放大回同样的高度，
  「少了什么」就看不出来了 —— 这正是比较类可视化最常见的作弊方式。
  所以 B 用 A 的归一化、D 用 C 的归一化，剥掉的体量会如实体现为「变矮/变薄」。

用法
  python3 tools/trunk_ruler.py
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
PANEL = (360, 600)
VIEWS = [('正', 0.0), ('3/4', 35.0), ('侧', 90.0), ('背', 180.0)]


# ---------------------------------------------------------------- mesh 适配
def bare(P):
    """三角形汤 (n,3,3) → refview 需要的 arrays() 接口。"""
    P = np.asarray(P, np.float32).reshape(-1, 3, 3)
    n = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
    L = np.linalg.norm(n, axis=1, keepdims=True)
    keep = L[:, 0] > 1e-12
    P = P[keep]
    n = n[keep] / L[keep]
    N = np.repeat(n[:, None, :], 3, 1)
    T_ = np.zeros((len(P), 3, 2), np.float32)
    mi = np.zeros((len(P),), np.int32)
    Fi = np.arange(len(P), dtype=np.int32)
    base = np.array([[0.78, 0.79, 0.80]], np.float32)
    emis = np.zeros((1,), np.float32)

    class _B:
        def arrays(self):
            return P, N, T_, mi, Fi, base, emis

        def __len__(self):
            return len(P)

    return _B()


def our_tris(clean):
    S.CLEAN = bool(clean)
    root, mesh = S.build()
    P = np.array(mesh.P, np.float32).reshape(-1, 3, 3)
    return root, P


def norm_fit(P):
    """把一整块（full）三角形汤归一化：脚底 y=0、高=H、x/z 以 bbox 中心居中。"""
    V = P.reshape(-1, 3)
    lo, hi = V.min(0), V.max(0)
    s = H / max(float(hi[1] - lo[1]), 1e-9)
    cx, cz = 0.5 * (lo[0] + hi[0]), 0.5 * (lo[2] + hi[2])
    return np.array([-cx, -lo[1], -cz], np.float32), s, (hi - lo) * s


def apply(P, off, s):
    Q = P.copy()
    Q += off
    Q *= s
    return Q


# ---------------------------------------------------------------- 量
def measure(P, tag):
    V = P.reshape(-1, 3)
    lo, hi = V.min(0), V.max(0)
    W, Hh, D = hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]
    # 肩宽：|x| 最大值出现在全高的哪一段（用作「最宽处」的定性）
    y_at = None
    wmax = 0.0
    for k in range(40):
        a = lo[1] + Hh * k / 40
        b = lo[1] + Hh * (k + 1) / 40
        m = (V[:, 1] >= a) & (V[:, 1] <= b)
        if m.sum() < 8:
            continue
        w = np.percentile(np.abs(V[m, 0]), 99.5) * 2
        if w > wmax:
            wmax, y_at = w, (a + b) * 0.5
    return dict(tag=tag, W=W, H=Hh, D=D, WH=W / Hh, DW=D / W,
                wmax=wmax, wmax_y=(y_at - lo[1]) / Hh if y_at else None)


def bands(P, n=20):
    """沿高度分 n 带，返回每带的 (相对高度, 宽, 深) —— 用来画「体量曲线」。"""
    V = P.reshape(-1, 3)
    lo, hi = V.min(0), V.max(0)
    Hh = hi[1] - lo[1]
    out = []
    for k in range(n):
        a = lo[1] + Hh * k / n
        b = lo[1] + Hh * (k + 1) / n
        m = (V[:, 1] >= a) & (V[:, 1] <= b)
        if m.sum() < 8:
            out.append((k / n, 0, 0))
            continue
        x = np.percentile(V[m, 0], [0.5, 99.5])
        z = np.percentile(V[m, 2], [0.5, 99.5])
        out.append((((a + b) * 0.5 - lo[1]) / Hh, float(x[1] - x[0]),
                    float(z[1] - z[0])))
    return out


# ---------------------------------------------------------------- 出图
def build_sheet(rows, path):
    gap, hdr, lb = 10, 96, 26
    w, h = PANEL
    W = gap + (w + gap) * len(VIEWS)
    Ht = hdr + (lb + h + gap) * len(rows)
    cv = Image.new('RGB', (W, Ht), (255, 255, 255))
    d = ImageDraw.Draw(cv)
    d.text((gap + 6, 12), 'Unicorn 主干 vs 我们主干 · 同一归一化 / 同一机位 / 同一光照',
           font=ImageFont.truetype(FONT, 28), fill=(22, 22, 22))
    d.text((gap + 6, 46), '四个模型均归一到「机高 = 10、脚底 y = 0」；'
                          'B 用 A 的归一化、D 用 C 的归一化 —— 剥掉的体量如实体现，不重新放大',
           font=ImageFont.truetype(FONT, 16), fill=(110, 110, 110))
    d.text((gap + 6, 68), 'A Unicorn 原素材 / B Unicorn 主干 / C 我们现构型 / D 我们主干',
           font=ImageFont.truetype(FONT, 16), fill=(110, 110, 110))
    y = hdr
    for label, panels in rows:
        d.text((gap + 6, y + 2), label, font=ImageFont.truetype(FONT, 19), fill=(16, 16, 16))
        for k, p in enumerate(panels):
            cv.paste(Image.fromarray(p), (gap + k * (w + gap), y + lb))
        y += lb + h + gap
    cv.save(path)
    return cv.size


def main():
    os.makedirs(OUT, exist_ok=True)

    # ---- Unicorn
    V, tris, gf, sets = UT.load_obj_grouped(UT.SRC)
    Vn, meta = RV.normalize(V)
    keep = np.ones(len(tris), bool)
    removed = []
    for tok in UT.REMOVE:
        m = UT.face_in(gf, sets, tok)
        if m.any():
            keep &= ~m
            removed.append((tok, int(m.sum())))
    U_full = Vn[tris]
    U_trk = Vn[tris[keep]]

    # ---- 我们
    _, C_full = our_tris(False)
    _, C_trk = our_tris(True)

    models = [
        ('A  Unicorn 原素材（含背包 / 肩炮 / 推进器）', U_full),
        ('B  Unicorn 主干（剥掉 %d 组装配，%.1f%% 三角）'
         % (len(removed), 100.0 * sum(r[1] for r in removed) / len(tris)), U_trk),
        ('C  我们 · 现构型（含动力舱 / 浮游炮 / 折叠翼）', C_full),
        ('D  我们 · 主干构型（--clean）', C_trk),
    ]

    # 归一化：Unicorn 两个用 U_full 的 bbox；我们两个用 C_full 的 bbox
    oU, sU, dimU = norm_fit(U_full)
    oC, sC, dimC = norm_fit(C_full)
    print('归一化：Unicorn 原始 %.1f cm → %.0f（W %.2f D %.2f）'
          % (meta['raw_height'], H, dimU[0], dimU[2]))
    print('        我们   原始 %.2f m → %.0f（W %.2f D %.2f）'
          % (C_full.reshape(-1, 3)[:, 1].max(), H, dimC[0], dimC[2]))

    rows, stats = [], []
    for label, P in models:
        Q = apply(P, oU, sU) if P is U_full or P is U_trk else apply(P, oC, sC)
        m = measure(Q, label.split('  ')[0])
        stats.append(m)
        panels = []
        mesh = bare(Q)
        for _, yaw in VIEWS:
            img, _ = RV.render_view(mesh, yaw)
            panels.append(img)
        rows.append((label, panels))

    p = os.path.join(OUT, 'trunk_ruler.png')
    sz = build_sheet(rows, p)
    print('→ %s  %d × %d' % (p, sz[0], sz[1]))

    # ------------------------------------------------------------ 对照表
    print('\n' + '=' * 86)
    print('四模型同尺对照（H 归一，脚底 y=0）')
    print('=' * 86)
    print('  %-6s %8s %8s %8s %9s %9s %9s' %
          ('', 'W/H', 'D/W', 'W', 'D', '最宽处/H', '最宽处y/H'))
    for m in stats:
        print('  %-6s %8.4f %8.4f %8.3f %9.3f %9.4f %9.3f' %
              (m['tag'], m['WH'], m['DW'], m['W'], m['D'], m['wmax'] / H,
               m['wmax_y'] or 0))

    print('\n  关键读数：')
    ua, ub, ca, cb = stats
    print('  · Unicorn 剥背包：D %.3f → %.3f（D/W %.3f → %.3f）'
          % (ua['D'], ub['D'], ua['DW'], ub['DW']))
    print('    → **含背包的 0.627 不是机体比例**。Unicorn 自己剥掉之后是 %.3f。'
          % ub['DW'])
    print('  · 我们剥外挂：D %.3f → %.3f（D/W %.3f → %.3f）'
          % (ca['D'], cb['D'], ca['DW'], cb['DW']))
    print('  · 主干对主干：我们 D/W %.3f vs Unicorn %.3f → %s %.3f'
          % (cb['DW'], ub['DW'], '深' if cb['DW'] > ub['DW'] else '浅',
             abs(cb['DW'] - ub['DW'])))
    print('  · 最宽处在全高的 %.1f%%（我们主干）vs %.1f%%（Unicorn 主干）'
          % (100 * (cb['wmax_y'] or 0), 100 * (ub['wmax_y'] or 0)))

    d = os.path.join(OUT, 'trunk_ruler.json')
    with open(d, 'w') as f:
        json.dump(dict(stats=stats,
                       unicorn_removed=[[r[0], r[1]] for r in removed],
                       bands=dict(unicorn_trunk=bands(U_trk), ours_trunk=bands(C_trk))),
                  f, ensure_ascii=False, indent=2, default=float)
    print('\n→ %s' % d)


if __name__ == '__main__':
    main()
