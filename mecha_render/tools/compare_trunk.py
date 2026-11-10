#!/usr/bin/env python3
"""主干剥离对照图：同一机位 / 同一光照 / 同一比例，A 现构型 vs B 主干构型。

★ 为什么必须同机位同比例：两张图分开看，「去掉外挂」这个动作是感受不到的 ——
  人的视觉会把每张图各自归一化，觉得「都挺满」。只有并排、且相机与缩放完全一致，
  「少掉的东西」才会变成可读的差异。

用法：python3 tools/compare_trunk.py
"""
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'out'
VIEWS = ['front', 'q35', 'side', 'back']
LBL = {'front': '正视', 'q35': '3/4', 'side': '侧视', 'back': '背视'}
FONT = '/System/Library/Fonts/Hiragino Sans GB.ttc'

ROWS = [
    ('A', 'A  现构型：核动力 · 含动力舱 / 三浮游炮 / 折叠翼', 's2', 's2_'),
    ('B', 'B  主干构型：剥掉全部外挂，只留机体主干', 's2c', 's2c_'),
]


def main():
    for row in ROWS:
        _, _, d, pre = row
        for v in VIEWS:
            p = OUT / d / (pre + v + '.png')
            if not p.exists():
                print('缺图：%s' % p)
                return 1
    f_t = ImageFont.truetype(FONT, 40)
    f_l = ImageFont.truetype(FONT, 26)
    f_v = ImageFont.truetype(FONT, 22)

    im0 = Image.open(OUT / 's2' / 's2_front.png')
    W0, H0 = im0.size
    sw, sh = int(W0 * 0.74), int(H0 * 0.74)
    TITLE, LBLH, GAP, PAD = 62, 40, 20, 16
    CW = PAD * 5 + sw * 4
    CH = TITLE + (LBLH + sh) * 2 + GAP + PAD

    canvas = Image.new('RGB', (CW, CH), (236, 236, 236))
    d = ImageDraw.Draw(canvas)
    d.text((PAD * 2, PAD + 2), '主干剥离对照 · 同一机位 / 同一光照 / 同一比例',
           font=f_t, fill=(28, 28, 28))

    for r, (tag, label, sub, pre) in enumerate(ROWS):
        yb = TITLE + r * (LBLH + sh + GAP)
        d.text((PAD * 2, yb + 6), label, font=f_l, fill=(20, 20, 20))
        y0 = yb + LBLH
        for c, v in enumerate(VIEWS):
            x0 = PAD + c * (sw + PAD)
            im = Image.open(OUT / sub / (pre + v + '.png')).convert('RGB')
            im = im.resize((sw, sh), Image.LANCZOS)
            canvas.paste(im, (x0, y0))
            d.rectangle([x0, y0, x0 + sw - 1, y0 + sh - 1], outline=(176, 176, 176))
            d.text((x0 + 8, y0 + 6), LBL[v], font=f_v, fill=(70, 70, 70))

    out = OUT / 'compare_trunk.png'
    canvas.save(out)
    print('已存 %s  %d × %d' % (out, CW, CH))
    return 0


if __name__ == '__main__':
    sys.exit(main())
