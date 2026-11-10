"""tools/prop_ruler.py — 大比例尺：把「比例和 Unicorn 有差距」拆成可量的横线差

为什么又做一把尺子
  前面已经有 silhouette_ruler（侧影曲线）、trunk_ruler（躯干比例）、
  crevice_ruler（缝/断崖）。它们都在量**局部形**。
  但用户这一轮的第一句是「**比例**还是和 Unicorn 有差距」，第二句才是肩和脚。
  比例不是形，比例是**几条横线的高度**：髋线、手末端、裙底、腰最窄、肩甲上下沿。
  这几条线错 0.5–1.0 H，任何局部造型都救不回来 —— 所以要先单独量它。

判据只有一条
  同一把尺子（H = 10、脚底 y = 0、x/z 同缩放）下，逐条比这几根横线的**高度**，
  以及每一段高度带里的**宽度**。读数全给绝对值差，不给比值（比值会把「谁做分母」藏起来）。

★ 为什么必须出图
  横线差 0.8 H 在数字上是 8%，在剪影上是「腿短一截」。
  只报数字会让人以为差得不多 —— 这张图就是防这个的。
  图上每 1 H 一条细线、关键线加粗带标签，两行（我们 / 参考）**同一像素比例**。

用法
  python3 tools/prop_ruler.py            # 出图 + 表
  python3 tools/prop_ruler.py --no-fig   # 只出表
"""
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'tools'))

import refview as RV                                        # noqa: E402
import s2_graybox as S                                      # noqa: E402
import unicorn_trunk as UT                                  # noqa: E402
from leg_ab import Soup, shade, to_h10                      # noqa: E402

OUT = os.path.join(HERE, 'out', 'ref')
FONT = '/System/Library/Fonts/Hiragino Sans GB.ttc'
H10 = 10.0


# ---------------------------------------------------------------- 两条来源
def ours():
    S.CLEAN = True
    root, mesh = S.build()
    P = np.array(mesh.P, np.float32).reshape(-1, 3)
    y0 = float(P[:, 1].min())
    k = H10 / (float(P[:, 1].max()) - y0)
    Q = P * k
    Q[:, 1] = (P[:, 1] - y0) * k
    mi, base, _e = mesh.mat_table()
    # ★ mat_table 是**逐面**给索引，而 P 是逐顶点 ×3；两者本应相等，实测差 1 个面
    #   （某个基本体把 4 点当 3 点写了）。Soup 里 keep 是按三角数算的，
    #   长度不一致会直接 boolean index 报错 —— 这里补齐/截齐，并断言差距只有个位数。
    nt = len(mesh.P)          # ☆ mesh.P 是「三角个数」（每个元素是 3×3），不要再除 3
    if len(mi) != nt:
        assert abs(len(mi) - nt) < 8, '材质面数差 %d，不是 1–2 个退化面' % (len(mi) - nt)
        mi = np.pad(mi, (0, max(0, nt - len(mi))))[:nt]
    nodes = {}
    for c in root.children:
        mb = S.Mesh()
        S.collect2(c, mb)
        if len(mb) == 0:
            continue                    # CLEAN 下 wings 是空节点
        R = np.array(mb.P, np.float32).reshape(-1, 3) * k
        R[:, 1] = (np.array(mb.P, np.float32).reshape(-1, 3)[:, 1] - y0) * k
        nodes[c.name] = (R[:, 0].min(), R[:, 0].max(), R[:, 1].min(), R[:, 1].max(),
                         R[:, 2].min(), R[:, 2].max())
    return Q, mi, base, nodes, k


def ref():
    V, tris, gf, sets = UT.load_obj_grouped(UT.SRC)
    Vn, _ = RV.normalize(V)
    keep = np.ones(len(tris), bool)
    for t in UT.REMOVE:
        keep &= ~UT.face_in(gf, sets, t)
    P = Vn[tris[keep]].astype(np.float32)
    asm = {}
    for tok in ('shoulder_armor_assy_G', 'r_shoulder_assy_G', 'r_arm_assy_G',
                'r_leg_assy_G', 'feet_assy_G', 'body_assy_G', 'head_assy_G',
                'waist_assy_G', 'L_rear_skirt_assy_G', 'L_front_skirt_assy_G'):
        m = UT.face_in(gf, sets, tok) & keep
        if not m.any():
            continue
        v = np.unique(tris[m].ravel())
        q = Vn[v]
        asm[tok] = (q[:, 0].min(), q[:, 0].max(), q[:, 1].min(), q[:, 1].max(),
                    q[:, 2].min(), q[:, 2].max())
    return P, asm


# ---------------------------------------------------------------- 横线表
# (标签, 我们这边怎么取, 参考那边怎么取)
LINES = [
    ('头顶',        lambda n: n['head'][3],              lambda a: a['head_assy_G'][3]),
    ('头底',        lambda n: n['head'][2],              lambda a: a['head_assy_G'][2]),
    ('肩甲顶',      lambda n: max(n['sh_L'][3], n['sh_R'][3]),
                    lambda a: a['shoulder_armor_assy_G'][3]),
    ('胸顶',        lambda n: n['chest'][3],             lambda a: a['body_assy_G'][3]),
    ('肩甲底',      lambda n: min(n['sh_L'][2], n['sh_R'][2]),
                    lambda a: a['shoulder_armor_assy_G'][2]),
    ('手末端',      lambda n: min(n['arm_L'][2], n['arm_R'][2]),
                    lambda a: a['r_arm_assy_G'][2]),
    ('胸底',        lambda n: n['chest'][2],             lambda a: a['body_assy_G'][2]),
    ('髋线（腿顶）', lambda n: max(n['leg_L'][3], n['leg_R'][3]),
                    lambda a: a['r_leg_assy_G'][3]),
    ('裙底',        lambda n: n['skirt'][2],             lambda a: a['waist_assy_G'][2]),
    ('脚底',        lambda n: min(n['leg_L'][2], n['leg_R'][2]),
                    lambda a: a['feet_assy_G'][2]),
]


def widths(P, bands):
    """每个高度带里的 W / D。

    ★ 必须按**面重心**选带，不能按顶点：参考模型里有若干长条薄三角，
      顶点散落在极远处（例如一个顶点在 y 0.12、x 2.8），
      按顶点选带会让「y 0.12 处的宽度」读成 5.6 —— 比双脚外缘 4.3 还宽，
      于是得出「我们脚太窄」这种假结论（实测 CHECK：该带里 |x|>2.2 的面数为 0）。
    """
    P = np.asarray(P, np.float32).reshape(-1, 3, 3)
    c = P.mean(1)
    out = []
    for yy in bands:
        m = (c[:, 1] >= yy) & (c[:, 1] < yy + 0.25)
        if m.sum() < 20:
            out.append((None, None))
            continue
        q = P[m].reshape(-1, 3)
        out.append((float(q[:, 0].max() - q[:, 0].min()),
                    float(q[:, 2].max() - q[:, 2].min())))
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    O, mi, base, nodes, k = ours()
    R, asm = ref()

    print('=' * 86)
    print('大比例尺（H = 10，脚底 y = 0，同一份缩放）')
    print('=' * 86)
    print('  %-14s %8s %8s %8s   %s' % ('横线', '我们', '参考', '差', '判读'))
    rows = []
    for tag, fo, fr in LINES:
        a, b = float(fo(nodes)), float(fr(asm))
        d = a - b
        note = '' if abs(d) < 0.20 else ('我们偏高' if d > 0 else '我们偏低')
        rows.append((tag, a, b, d, note))
        print('  %-14s %8.3f %8.3f %+8.3f   %s' % (tag, a, b, d, note))

    print('\n  每段高度（差 = 我们 − 参考，正 = 我们这一段更长）')
    segs = [('头', '头底', '头顶'), ('胸', '胸底', '胸顶'), ('肩甲', '肩甲底', '肩甲顶'),
            ('腰+裙（髋线以上）', '髋线（腿顶）', '胸底'), ('腿', '脚底', '髋线（腿顶）'),
            ('臂', '手末端', '肩甲顶')]
    d_ = dict((r[0], r[1]) for r in rows)
    r_ = dict((r[0], r[2]) for r in rows)
    for nm, lo, hi in segs:
        print('  %-18s 我们 %6.3f   参考 %6.3f   差 %+6.3f'
              % (nm, d_[hi] - d_[lo], r_[hi] - r_[lo], (d_[hi] - d_[lo]) - (r_[hi] - r_[lo])))

    bands = np.arange(0.0, 9.75, 0.25)
    wo = widths(O, bands)
    wr = widths(R, bands)
    print('\n  高度带剖面（每 0.25 H；D 为前后纵深）')
    print('   y带    我们W  参考W    ΔW    |  我们D  参考D    ΔD')
    bad = []
    for i, yy in enumerate(bands):
        if wo[i][0] is None or wr[i][0] is None:
            continue
        dw = wo[i][0] - wr[i][0]
        dd = wo[i][1] - wr[i][1]
        flag = ''
        if abs(dw) > 0.30:
            flag = '窄' if dw < 0 else '宽'
            bad.append((float(yy + 0.125), dw, dd))
        print('  %5.2f  %6.3f %6.3f %+6.3f  | %6.3f %6.3f %+6.3f  %s'
              % (yy + 0.125, wo[i][0], wr[i][0], dw, wo[i][1], wr[i][1], dd, flag))

    out = dict(lines=[dict(tag=t, ours=a, ref=b, d=d) for t, a, b, d, _n in rows],
               bands=[dict(y=float(b + 0.125), wo=wo[i][0], wr=wr[i][0],
                           do=wo[i][1], dr=wr[i][1])
                      for i, b in enumerate(bands)
                      if wo[i][0] is not None and wr[i][0] is not None])
    p = os.path.join(OUT, 'prop_ruler.json')
    with open(p, 'w') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print('\n→ %s' % p)

    if '--no-fig' in sys.argv:
        return

    # ------------------------------------------------------------ 出图
    PAN = (430, 900)
    half = views(PAN)

    W = 20 + (PAN[0] + 14) * 4
    Hh = 96 + PAN[1] + 30
    cv = Image.new('RGB', (W, Hh), (255, 255, 255))
    d = ImageDraw.Draw(cv)
    d.text((24, 14), '大比例尺 · 我们 vs Unicorn 主干（H = 10，同像素比例）',
           font=ImageFont.truetype(FONT, 22), fill=(20, 20, 22))
    d.text((24, 46), '细线每 1 H 一条；彩色粗线是关键横线（颜色在两侧一致）。'
                     '两行共用同一比例尺，不重排、不裁剪。',
           font=ImageFont.truetype(FONT, 13), fill=(112, 112, 116))

    COL = {'头顶': (40, 40, 44), '肩甲顶': (176, 40, 40), '肩甲底': (176, 40, 40),
           '手末端': (150, 90, 20), '髋线（腿顶）': (40, 96, 168),
           '胸底': (40, 130, 90), '裙底': (120, 60, 150), '头底': (150, 150, 154)}

    for ri, (P, m_, b_, title, ln) in enumerate((
            (O, mi, base, '我们（CLEAN 主干）', d_),
            (R, None, None, '参考 Unicorn 主干', r_))):
        x0 = 20 + ri * (PAN[0] * 2 + 28)
        d.text((x0 + 6, 76), title, font=ImageFont.truetype(FONT, 16), fill=(20, 20, 22))
        for ci, yaw in enumerate((0.0, 90.0)):
            img, cov = shade(Soup(P, m_, b_), yaw, PAN)
            im = Image.fromarray(img)
            cv.paste(im, (x0 + ci * (PAN[0] + 8), 96))
            dd = ImageDraw.Draw(cv)
            for hh in range(0, 11):
                yy = 96 + PAN[1] - int(hh / H10 * PAN[1])
                dd.line([(x0 + ci * (PAN[0] + 8), yy),
                         (x0 + ci * (PAN[0] + 8) + PAN[0], yy)], fill=(226, 226, 230))
                dd.text((x0 + ci * (PAN[0] + 8) + 2, yy - 12), '%d' % hh,
                        font=ImageFont.truetype(FONT, 10), fill=(170, 170, 174))
            for tag, y in ln.items():
                if tag not in COL:
                    continue
                yy = 96 + PAN[1] - int(y / H10 * PAN[1])
                dd.line([(x0 + ci * (PAN[0] + 8), yy),
                         (x0 + ci * (PAN[0] + 8) + PAN[0], yy)], fill=COL[tag], width=2)
                dd.text((x0 + ci * (PAN[0] + 8) + PAN[0] - 4, yy - 11), tag,
                        font=ImageFont.truetype(FONT, 10), fill=COL[tag], anchor='ra')

    cv.save(os.path.join(OUT, 'prop_ab.png'))
    print('→ %s  %d × %d' % (os.path.join(OUT, 'prop_ab.png'), cv.size[0], cv.size[1]))


def views(panel):
    """取景参数：与 shade 里一致（1.24·H 可见高度、焦点在 H/2）。"""
    return panel


if __name__ == '__main__':
    main()
