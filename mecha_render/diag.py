"""diag.py — 把渲染结果转成可读的 ASCII 预览 + 数值诊断，用于无显卡环境下的构图自检。"""
import sys
import numpy as np
from PIL import Image

RAMP = " .:-=+*#%@"


def ascii_preview(path, cols=104, rows=44, gamma=1.0):
    im = Image.open(path).convert('L')
    w, h = im.size
    # 保持字符长宽比（字符高约等于宽 2 倍）
    rows = max(8, int(cols * h / w / 2.1))
    im = im.resize((cols, rows), Image.LANCZOS)
    a = np.asarray(im, float) / 255.0
    a = np.clip(a, 0, 1) ** gamma
    idx = (a * (len(RAMP) - 1)).round().astype(int)
    lines = ["".join(RAMP[i] for i in row) for row in idx]
    return "\n".join(lines)


def stats(path):
    im = Image.open(path).convert('RGB')
    a = np.asarray(im, float)
    h, w, _ = a.shape
    lum = a.mean(axis=2)
    # 背景估计：四角均值
    cor = np.concatenate([lum[:6, :6].ravel(), lum[:6, -6:].ravel(),
                          lum[-6:, :6].ravel(), lum[-6:, -6:].ravel()])
    bg = cor.mean()
    fg = np.abs(lum - bg) > 26
    # 高亮（发光体）
    hot = lum > 235
    out = [f'size={w}x{h}  bg_lum={bg:.1f}  mean_lum={lum.mean():.1f}  '
           f'max_lum={lum.max():.0f}  contrast(std)={lum.std():.1f}',
           f'fg_ratio={fg.mean()*100:.1f}%  hot_px={hot.sum()}']
    for i, nm in enumerate('RGB'):
        out.append(f'  {nm}: mean={a[:,:,i].mean():6.1f} p99={np.percentile(a[:,:,i],99):6.1f}')
    # 白/蓝/红占比（机体配色自检）
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    white = (r > 130) & (g > 130) & (b > 130) & (np.abs(r - b) < 40)
    blue = (b > r + 25) & (b > 60)
    red = (r > g + 35) & (r > b + 35) & (r > 80)
    out.append(f'  white={white.mean()*100:.2f}%  blue={blue.mean()*100:.2f}%  '
               f'red={red.mean()*100:.2f}%')
    # 每行前景宽度（判断构图重心）
    rows = np.where(fg.any(axis=1))[0]
    colsx = np.where(fg.any(axis=0))[0]
    if len(rows):
        out.append(f'  fg bbox rows {rows[0]}-{rows[-1]} ({rows[0]/h*100:.0f}%-{rows[-1]/h*100:.0f}%), '
                   f'cols {colsx[0]}-{colsx[-1]} ({colsx[0]/w*100:.0f}%-{colsx[-1]/w*100:.0f}%)')
    return "\n".join(out)


if __name__ == '__main__':
    p = sys.argv[1]
    print(stats(p))
    print('-' * 104)
    print(ascii_preview(p, gamma=float(sys.argv[2]) if len(sys.argv) > 2 else 1.0))
