"""tools/shoulder_ab.py — 肩甲「改前 / 改后」对照 + 前视剪影叠合

为什么单独出一个
  `s2_graybox.py --views` 每次都会覆写 out/s2c 里的四视角图。
  §26 就是因此丢掉了基线：现在这张图比完，下一次渲图就再也拿不出「改前」。
  所以对照必须**当场生成、另存**，而不是「等会儿再跑一遍」。

  A = `SH_SQUEEZE=False`（肩甲等比原尺寸：0.563H）
  B = `SH_SQUEEZE=True` （三轴映射到参考实测：0.431H）

三列 = 正 / 3-4 / 侧。底部两组数字直接标在图上，避免「看图 + 翻日志」两头对。
第三张是**前视剪影叠合**：A 用灰、B 用红描边，重合处即「没变的地方」。

用法
  python3 tools/shoulder_ab.py
"""
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'tools'))

import refview as RV                                     # noqa: E402
import s2_graybox as S                                   # noqa: E402

OUT = os.path.join(HERE, 'out', 'ref')
FONT = '/System/Library/Fonts/Hiragino Sans GB.ttc'
PANEL = (350, 620)
VIEWS = [('正', 0.0), ('3/4', 35.0), ('侧', 90.0)]


class Soup:
    def __init__(self, P):
        P = np.asarray(P, np.float32).reshape(-1, 3, 3)
        n = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
        L = np.linalg.norm(n, axis=1, keepdims=True)
        keep = L[:, 0] > 1e-12
        P, n = P[keep], n[keep] / L[keep]
        self.P = P
        self.N = np.repeat(n[:, None, :], 3, 1)
        self.T = np.zeros((len(P), 3, 2), np.float32)
        self.mi = np.zeros((len(P),), np.int32)
        self.Fi = np.arange(len(P), dtype=np.int32)
        self.base = np.array([[0.64, 0.65, 0.67]], np.float32)
        self.emis = np.zeros((1,), np.float32)

    def arrays(self):
        return self.P, self.N, self.T, self.mi, self.Fi, self.base, self.emis

    def mat_prop_table(self):        # render_relief 会问材质的 spec/rim
        return np.zeros((1,), np.float32), np.zeros((1,), np.float32)

    def __len__(self):
        return len(self.P)


def build(clean=True, shk=True):
    S.CLEAN = clean
    S.SH_SQUEEZE = shk
    root, mesh = S.build()
    return np.array(mesh.P, np.float32), root


def sh_bbox(root):
    """肩甲自己的 bbox —— 不用「某高度段里的 max|x|」去猜。
    ★ 第一版就是这么猜的：0.74–0.95H 这一段里上臂顶（0.828H）也在，
      于是「肩甲 2.825H」量到的其实是肩甲，判对了纯属巧合；改后再量成了 2.558
      —— 那是手臂。**能点名到件就不要用高度带过滤。**"""
    for c in root.children:
        if c.name == 'sh_L':
            mb = S.Mesh()
            S.collect2(c, mb)
            P = np.array(mb.P, np.float32).reshape(-1, 3)
            P = P[P[:, 0] > 0]
            lo, hi = P.min(0), P.max(0)
            # ★ 一律返回**真实米**。第一版在这里乘了 10/7.93 转成 H 单位，
            #   下游又除了一次 10、一次 0.793 —— 于是「肩甲 0.12 × 0.15 m」，
            #   把一个 0.94 m 的件报小了 8 倍。**单位只在一个地方转换。**
            return dict(x0=lo[0], x1=hi[0], y0=lo[1], y1=hi[1],
                        w=hi[0] - lo[0], h=hi[1] - lo[1], d=0.0)
    return None


def measure(P):
    """与 silhouette_ruler 同口径：H 归一到 10 之后按 max|x| 取。"""
    V = P.reshape(-1, 3)
    lo, hi = V.min(0), V.max(0)
    s = 10.0 / float(hi[1] - lo[1])
    Q = (V - np.array([0.5 * (lo[0] + hi[0]), lo[1],
                       0.5 * (lo[2] + hi[2])])) * s
    W = float(np.ptp(Q[:, 0]))
    # 最宽处：40 段里的 argmax（与 trunk_ruler 的 measure 一致）
    best, yat = 0.0, 0.0
    for k in range(40):
        a, b = 10.0 * k / 40, 10.0 * (k + 1) / 40
        m = (Q[:, 1] >= a) & (Q[:, 1] <= b)
        if m.sum() < 8:
            continue
        w = np.percentile(np.abs(Q[m, 0]), 99.5) * 2
        if w > best:
            best, yat = w, (a + b) * 0.5 / 10.0
    # 最宽处用**半宽**报（与 silhouette_ruler 同口径），上面 best 是 99.5 分位×2
    return dict(WH=W / 10.0, half=best * 0.5, wy=yat)


def trim(img, pad=6):
    """裁掉渲染面板四周的白边。
    ★ `refview.render_view` 的竖向取景 = 1.44·H_WORLD，机体只占 69%，
      350×620 的面板里上下各留 95 px 白，两行叠起来就是 380 px 死白
      —— 第一版成图整体发「空」，就是这个原因。裁边后再统一缩放。"""
    a = np.asarray(img)
    m = (a < 250).any(2)
    ys, xs = np.nonzero(m)
    if not len(ys):
        return Image.fromarray(a)
    y0, y1 = max(0, ys.min() - pad), min(a.shape[0], ys.max() + 1 + pad)
    x0, x1 = max(0, xs.min() - pad), min(a.shape[1], xs.max() + 1 + pad)
    return Image.fromarray(a[y0:y1, x0:x1])


def front_mask(P, path, size=(420, 760)):
    import render_relief as RR
    sz = Soup(P)
    V = np.asarray(P).reshape(-1, 3)
    lo, hi = V.min(0), V.max(0)
    s = 10.0 / float(hi[1] - lo[1])
    Q = (V - np.array([0.5 * (lo[0] + hi[0]), lo[1],
                       0.5 * (lo[2] + hi[2])])) * s
    vm = dict(H=10.3, Wfig=float(np.ptp(Q[:, 0])), zf=0.0, zback=0.0,
              scale=1.0, cy=5.0, bbox=(0, 0, 0, 10, 0, 0))
    sz2 = Soup(Q.reshape(-1, 3, 3))
    m, _ = RR.render(sz2, vm, 0.0, path, size=size, bg_lv=0.55)
    a = np.asarray(m)
    return a > 0.5 if a.dtype != bool else a


def main():
    os.makedirs(OUT, exist_ok=True)
    A, ra_ = build(True, False)
    B, rb_ = build(True, True)
    ma, mb = measure(A), measure(B)
    sa, sb = sh_bbox(ra_), sh_bbox(rb_)

    labels = [
        ('A  改前（肩甲等比原尺寸）', A, ma, sa, (120, 120, 120)),
        ('B  改后（三轴映射到参考实测）', B, mb, sb, (176, 40, 40)),
    ]

    gap, hdr, lb, ft = 12, 128, 26, 26
    w, h = PANEL
    W = gap + (w + gap) * len(VIEWS)
    Ht = hdr + (lb + h + ft + gap) * 2
    cv = Image.new('RGB', (W, Ht), (255, 255, 255))
    d = ImageDraw.Draw(cv)
    d.text((gap + 4, 14), '肩甲 A/B · 改前 vs 改后（同一归一化 / 同一机位 / 同一光照）',
           font=ImageFont.truetype(FONT, 26), fill=(22, 22, 22))
    d.text((gap + 4, 48), '参考 Unicorn 主干：肩甲宽 0.431H、最宽处 0.64H（在手/前臂）',
           font=ImageFont.truetype(FONT, 15), fill=(110, 110, 110))
    for tag, mm, sh, col, yy in (('A', ma, sa, (120, 120, 120), 70),
                                 ('B', mb, sb, (176, 40, 40), 86)):
        d.text((gap + 4, yy),
               '%s  W/H %.4f   肩甲跨度 %.3fH（外缘 %.2f m）   单侧甲片 %.2f 宽 × %.2f 高 m   '
               '最宽半宽 %.2f @ %.0f%%H'
               % (tag, mm['WH'], 2 * sh['x1'] / 7.930, sh['x1'],
                  sh['w'], sh['h'], mm['half'], 100 * mm['wy']),
               font=ImageFont.truetype(FONT, 14), fill=col)

    # 先把 6 格渲出来、统一裁边，再算**一个**缩放比
    # ★ 每格各自缩到满高会让侧视（窄）被放大，三列就不是同一比例了，
    #   「B 比 A 窄」这种结论就变成看图看出来的错觉。
    grid = []
    for label, P, mm, sh, col in labels:
        sz_ = Soup(P)
        grid.append([trim(Image.fromarray(RV.render_view(sz_, yaw)[0]))
                     for vn, yaw in VIEWS])
    mh = max(im.height for row in grid for im in row)
    mw = max(im.width for row in grid for im in row)
    sc = min((h - 18) / mh, (w - 18) / mw)

    y = hdr
    for (label, P, mm, sh, col), row in zip(labels, grid):
        d.text((gap + 4, y + 4), label, font=ImageFont.truetype(FONT, 18), fill=col)
        for k, im in enumerate(row):
            si = im.resize((max(1, int(im.width * sc)), max(1, int(im.height * sc))),
                           Image.BICUBIC)
            cv.paste(si, (gap + k * (w + gap) + (w - si.width) // 2,
                          y + lb + (h - si.height) // 2))
        y += lb + h + ft + gap
    p = os.path.join(OUT, 'shoulder_ab.png')
    cv.save(p)
    print('→ %s  %d × %d' % (p, cv.size[0], cv.size[1]))

    # ---- 剪影叠合
    fa = front_mask(A, '/tmp/_ab_a.png')
    fb = front_mask(B, '/tmp/_ab_b.png')
    if fa.shape != fb.shape:
        fb = np.asarray(Image.fromarray(fb.astype(np.uint8) * 255)
                        .resize((fa.shape[1], fa.shape[0]), Image.NEAREST)) > 127
    hh, ww = fa.shape
    MG, MR = 78, 104                         # 左：高度标尺；右：两版最宽处标注
    canvas = np.full((hh, ww + MG + MR, 3), 255, np.uint8)
    only_a = fa & ~fb
    only_b = fb & ~fa
    both = fa & fb
    body = canvas[:, MG:MG + ww]
    body[both] = (205, 208, 212)
    body[only_a] = (232, 150, 60)            # A 多出来的部分 = 橙
    body[only_b] = (176, 40, 40)             # B 多出来的部分 = 红
    canvas[:, MG:MG + ww] = body
    im = Image.fromarray(canvas)
    d2 = ImageDraw.Draw(im)
    f16 = ImageFont.truetype(FONT, 17)
    f13 = ImageFont.truetype(FONT, 13)
    d2.text((16, 12), '前视剪影叠合（灰 = 两版共有 / 橙 = 只有改前 / 红 = 只有改后）',
            font=f16, fill=(30, 30, 30))
    # 高度标尺：机体在面板里占 10/10.3，先按实体像素还原 y0/y1 再等分
    ys, _xs = np.nonzero(fa | fb)
    y0, y1 = float(ys.min()), float(ys.max())
    d2.line([(MG - 14, y0), (MG - 14, y1)], fill=(150, 150, 150), width=1)
    for pc in range(30, 100, 10):
        yy = y1 - (y1 - y0) * pc / 100.0
        d2.line([(MG - 19, yy), (MG - 9, yy)], fill=(150, 150, 150), width=1)
        d2.text((MG - 62, yy - 8), '%d%%' % pc, font=f13, fill=(120, 120, 120))
    # 两版的「最宽处」各标一条：79% → 61% 才是这次改动的真实含义
    for pc, txt, col in ((100 * ma['wy'], 'A 最宽 79%H', (232, 150, 60)),
                         (100 * mb['wy'], 'B 最宽 61%H', (176, 40, 40))):
        yy = y1 - (y1 - y0) * pc / 100.0
        d2.line([(MG + ww - 30, yy), (MG + ww + 6, yy)], fill=col, width=2)
        d2.text((MG + ww + 10, yy - 9), txt, font=f13, fill=col)
    # 面板底部还有 ~10% 白（front_mask 的竖向取景比 10.3 更宽），裁掉
    im = im.crop((0, 0, im.width, int(y1) + 46))
    p2 = os.path.join(OUT, 'shoulder_ab_silhouette.png')
    im.save(p2)
    print('→ %s  %d × %d' % (p2, im.size[0], im.size[1]))

    print('\n  度量（H 归一到 10）：')
    for label, _, mm, sh, _col in labels:
        print('  %-2s W/H %.4f  肩甲跨度 %.3fH  单侧 %.2f×%.2f m  最宽半宽 %.3f @ %.0f%%H'
              % (label.split('  ')[0], mm['WH'], 2 * sh['x1'] / 7.930,
                 sh['w'], sh['h'], mm['half'], 100 * mm['wy']))


if __name__ == '__main__':
    main()
