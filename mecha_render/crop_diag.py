"""crop_diag.py — 裁剪前景主体后放大做 ASCII 预览，用于检查装甲分割/涂装分布。"""
import sys
import numpy as np
from PIL import Image

RAMP = " .:-=+*#%@"


def ascii_of(im, cols=100):
    w, h = im.size
    rows = max(8, int(cols * h / w / 2.1))
    g = im.convert('L').resize((cols, rows), Image.LANCZOS)
    a = np.asarray(g, float) / 255.0
    idx = (np.clip(a, 0, 1) * (len(RAMP) - 1)).round().astype(int)
    return "\n".join("".join(RAMP[i] for i in r) for r in idx)


def main():
    p = sys.argv[1]
    im = Image.open(p).convert('RGB')
    a = np.asarray(im, float)
    h, w, _ = a.shape
    lum = a.mean(axis=2)

    # 前景：与画面整体中位数偏离
    med = np.median(lum)
    fg = np.abs(lum - med) > 22
    # 去噪：要求 4px 邻域内也有前景
    # 纯 numpy 腐蚀（3 次 3x3），替代 scipy.ndimage.binary_opening
    for _ in range(2):
        e = fg.copy()
        e[1:, :] &= fg[:-1, :]
        e[:-1, :] &= fg[1:, :]
        e[:, 1:] &= fg[:, :-1]
        e[:, :-1] &= fg[:, 1:]
        fg = e

    rows = np.where(fg.sum(axis=1) > w * 0.01)[0]
    cols = np.where(fg.sum(axis=0) > h * 0.01)[0]
    if not len(rows):
        print('no foreground'); return

    y0, y1 = rows[0], rows[-1]
    x0, x1 = cols[0], cols[-1]
    print('%s  fg bbox x %d-%d (%.0f%%-%.0f%%)  y %d-%d (%.0f%%-%.0f%%)  w=%d h=%d'
          % (p.split('/')[-1], x0, x1, x0 / w * 100, x1 / w * 100,
             y0, y1, y0 / h * 100, y1 / h * 100, x1 - x0, y1 - y0))

    pad = 6
    cx0, cy0 = max(0, x0 - pad), max(0, y0 - pad)
    cx1, cy1 = min(w, x1 + pad), min(h, y1 + pad)
    crop = im.crop((cx0, cy0, cx1, cy1))
    print(ascii_of(crop, cols=int(sys.argv[2]) if len(sys.argv) > 2 else 96))

    # 裁剪区内涂装占比
    c = np.asarray(crop, float)
    r, g, b = c[:, :, 0], c[:, :, 1], c[:, :, 2]
    white = ((r > 120) & (g > 120) & (b > 115)).mean() * 100
    blue = ((b > r + 22) & (b > 55)).mean() * 100
    red = ((r > g + 30) & (r > b + 30) & (r > 70)).mean() * 100
    print('  crop paint: white=%.1f%%  blue=%.1f%%  red=%.1f%%' % (white, blue, red))


if __name__ == '__main__':
    main()
