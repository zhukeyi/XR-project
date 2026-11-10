"""tools/make_sheet.py — 把各阶段产物拼成一张验收拼版（带判据数字）

为什么要有这张图：本会话看不了图，逐张回忆每步的成功/失败很难核对；
拼版把 5 个阶段并排放，每个阶段底下压着它自己那一组指标，一眼就能看出
「哪一步守住了、哪一步漂了」。

用法：
  python3 tools/make_sheet.py out/seed_sketch/stages_sheet34.png
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

TH = 720                      # 每格缩放到的高度
GAP, PAD, LBL = 18, 26, 78    # 间距 / 外边距 / 文字区高度

PANELS = [
    ('control34.png', '1  控制剪影  SILHOUETTE',
     '肩/头 3.17 · 双腿 48~58% 肩宽'),
    ('把输入的黑色剪影当作结构控制图_严格按它的外轮廓重绘成黑白机_2026-11-07T08-13-03.png',
     '2  线稿  LINEART',
     'fid 0.93 · 9.1 头身 · 肩/头 3.68'),
    ('在这张重型机甲黑白线稿上上色_严格保持所有线条_外轮廓_比例_2026-11-07T08-18-01.png',
     '3  上色  COLOR',
     'fid 0.86 · 实宽 514 与线稿一致'),
]

CJK = ['/System/Library/Fonts/PingFang.ttc',
       '/System/Library/Fonts/Hiragino Sans GB.ttc',
       '/Library/Fonts/Arial Unicode.ttf']


def font(sz):
    for p in CJK:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, sz, index=0)
            except Exception:
                continue
    return ImageFont.load_default()


def main(out):
    base = os.path.dirname(os.path.abspath(out)) or '.'
    ims, stats = [], []
    for fn, _, _ in PANELS:
        im = Image.open(os.path.join(base, fn)).convert('RGB')
        w = int(im.width * TH / im.height)
        ims.append(im.resize((w, TH), Image.LANCZOS))

    W = PAD * 2 + sum(i.width for i in ims) + GAP * (len(ims) - 1)
    H = PAD * 2 + TH + LBL
    sheet = Image.new('RGB', (W, H), 'white')
    d = ImageDraw.Draw(sheet)
    f1, f2 = font(21), font(18)

    x = PAD
    for im, (fn, title, sub) in zip(ims, PANELS):
        sheet.paste(im, (x, PAD))
        d.rectangle([x, PAD, x + im.width - 1, PAD + TH - 1], outline=(210, 210, 210))
        d.text((x + 2, PAD + TH + 10), title, font=f1, fill=(20, 20, 20))
        d.text((x + 2, PAD + TH + 38), sub, font=f2, fill=(110, 110, 110))
        x += im.width + GAP

    sheet.save(out, quality=95)
    print('拼版 -> %s  (%d, %d)' % (out, W, H))


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'out/seed_sketch/stages_sheet34.png')
