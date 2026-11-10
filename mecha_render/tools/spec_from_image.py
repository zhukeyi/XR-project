"""tools/spec_from_image.py — 从一张「认可的图」里抽出结构规格（而不是靠肉眼描述）

为什么需要它：之前我拿「腿/肩 0.412」当瘦的判据，但 3/4 姿态下两腿前后叠合，
宽度合计被遮掉一半 —— 同一台机体在 3/4 里 0.31、在正视里 0.63。用单一数字
跨视角比较是错的。真正可比、且能描述「像不像设定图」的量是**剖面形状**：
每个高度带上的归一化宽度，以及它在哪里塌下去。

输出：specs/<name>.json —— 100 段剖面 + 关键地标（肩线/最宽行/腰/腿根/脚）
"""
import json
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, 'tools'))
from sketch_check import asym, largest_cc  # noqa: E402


def mask_of(path, thr=110):
    a = np.asarray(Image.open(path).convert('L'), float)
    m = largest_cc(a < thr)
    return m


def extract(path, n=100):
    m = mask_of(path)
    ys = np.nonzero(m.any(axis=1))[0]
    xs = np.nonzero(m.any(axis=0))[0]
    top, bot = int(ys.min()), int(ys.max())
    left, right = int(xs.min()), int(xs.max())
    H = bot - top + 1
    rows = np.linspace(top, bot, n).astype(int)
    w, L, R = [], [], []
    for y in rows:
        xx = np.nonzero(m[y])[0]
        if len(xx):
            w.append(xx.max() - xx.min() + 1); L.append(xx.min()); R.append(xx.max())
        else:
            w.append(0); L.append(np.nan); R.append(np.nan)
    w = np.array(w, float); L = np.array(L, float); R = np.array(R, float)
    wn = w / w.max()
    # 地标
    widest = int(np.argmax(wn))
    # 腿根 = 从下往上第一处宽度跌破 0.5×最宽的位置（腰/裆）
    below = np.where(wn < 0.5 * wn.max())[0]
    crotch = int(below[below > widest][0]) if len(below[below > widest]) else None
    return dict(path=os.path.basename(path), H=H, W=int(right - left + 1),
                widest_pct=widest / (n - 1) * 100,
                crotch_pct=(crotch / (n - 1) * 100) if crotch else None,
                profile=[round(float(v), 4) for v in wn],
                asym=round(asym(m, {'L': L, 'R': R})[0] * 100, 1))


if __name__ == '__main__':
    src = sys.argv[1]
    name = sys.argv[2] if len(sys.argv) > 2 else 'target'
    s = extract(src)
    d = os.path.join(HERE, 'specs'); os.makedirs(d, exist_ok=True)
    out = os.path.join(d, f'{name}.json')
    json.dump(s, open(out, 'w'), ensure_ascii=False, indent=1)
    print(f'高 {s["H"]} 宽 {s["W"]}  最宽行 {s["widest_pct"]:.0f}%  '
          f'腰部收缩点 {s["crotch_pct"]}%  左右不对称 {s["asym"]}%')
    print('剖面(每 5% 一格): ' + ' '.join(f'{s["profile"][i]:.2f}'
                                        for i in range(0, 100, 5)))
    print(f'-> {out}')
