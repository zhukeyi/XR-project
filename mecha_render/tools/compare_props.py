"""tools/compare_props.py — 同一相机、同一光源，渲「旧体型 vs 新体型」对照

为什么要这张图：皮肤（颜色/分割线）不变、只换体型系数，观感差异才能归因到体型。
两张图共用 make_mecha 的同一份几何，只是 PROP 参数表不同 —— 这是唯一能
把「变扎实了没有」从主观争论变成可对照比较的做法。
"""
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'tools'))

import threeview as TV

OLD = dict(sx_chest=1.0, sz_chest=1.0, sx_leg=1.0, sz_foot=1.0,
           sy_head=1.0, sx_head=1.0, sx_arm=1.0)
OUT = os.path.join(HERE, 'out', 'threeview')
OSHEET = os.path.join(HERE, 'out', 'seed_sketch')


def label(im, text, sub=''):
    d = ImageDraw.Draw(im)
    try:
        f = ImageFont.truetype('/System/Library/Fonts/PingFang.ttc', 30)
        fs = ImageFont.truetype('/System/Library/Fonts/PingFang.ttc', 22)
    except Exception:
        f = fs = ImageFont.load_default()
    d.rectangle([0, 0, im.width, 74], fill=(255, 255, 255))
    d.text((18, 12), text, fill=(20, 24, 32), font=f)
    if sub:
        d.text((18, 48), sub, fill=(96, 104, 118), font=fs)
    return im


def main():
    a = os.path.join(OUT, 'cmp_old.png')
    b = os.path.join(OUT, 'cmp_new.png')
    TV.render_view(0, a, props=OLD)
    TV.render_view(0, b, props=None)
    ia, ib = Image.open(a), Image.open(b)
    W = ia.width + ib.width + 24
    H = max(ia.height, ib.height) + 74
    sh = Image.new('RGB', (W, H), (255, 255, 255))
    sh.paste(label(ia.copy(), '旧体型  肩/机高 0.585  腿/肩 0.412  1:10.3 头身',
                   '肩过宽 + 腿过细 = 宽肩细腿'), (0, 74))
    sh.paste(label(ib.copy(), '新体型  肩/机高 0.356  腿/肩 0.627  1:8.7 头身',
                   '收上身、补双腿，两比例同时进区间'), (ia.width + 24, 74))
    out = os.path.join(OSHEET, 'props_compare.png')
    sh.save(out)
    print(f'对照图 -> {out} ({sh.width}, {sh.height})')


if __name__ == '__main__':
    main()
