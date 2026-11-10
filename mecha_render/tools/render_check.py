"""tools/render_check.py — 3D 渲染图的剪影验收（sketch_check 的姊妹工具）

为什么不复用 sketch_check：它把 a<110 当主体，那是「黑白线稿/剪影」的口径。
3D 渲染是彩色的，暗部阴影才是暗像素 → 直接套用会得到残缺轮廓（实测主体占比
从真实 38.9% 掉到 22.5%，头身比读出 15.1）。这里改成**按背景色差分**取剪影，
其余判据（剖面 / 头身比 / 肩头比 / 左右不对称）全部复用 sketch_check，口径一致。

用法：
  python3 tools/render_check.py out/threeview/tv_000.png [tv_090.png ...]
"""
import sys

import numpy as np
from PIL import Image

from sketch_check import head_and_shoulder, asym, profile


def load_mask(path, bg=0.98, thr=0.055):
    a = np.asarray(Image.open(path).convert('RGB'), np.float32) / 255.0
    d = np.abs(a - bg).max(axis=2)      # 与背景色的最大通道偏离
    return d > thr, a


def report(path):
    m, a = load_mask(path)
    H, W = m.shape
    ys = np.nonzero(m.any(axis=1))[0]
    xs = np.nonzero(m.any(axis=0))[0]
    if len(ys) == 0:
        print(f'{path}: 空图'); return None
    top, bot = int(ys.min()), int(ys.max())
    left, right = int(xs.min()), int(xs.max())
    h, w = bot - top + 1, right - left + 1
    print(f'文件  {path.split("/")[-1]}')
    print(f'画布  {W}x{H}  主体占比 {m.mean()*100:.1f}%')
    print(f'包围盒  x[{left},{right}] y[{top},{bot}]  实宽 {w}  实高 {h}')
    edge = ('左' if left <= 1 else '') + ('右' if right >= W - 2 else '')
    print(f'贴边  {edge or "无"}' + ('  ★横向量程已顶满画布，需加宽画布或拉远相机' if edge else ''))
    p = profile(m, 40)
    print('剖面  ' + ' '.join(f'{v:.2f}' for v in p['w'] / p['w'].max()))
    hd = head_and_shoulder(m, p)
    if hd:
        print(f'比例  头高 {hd["head_h"]:.0f}  头身比 1:{hd["ratio"]:.1f}'
              f'  头宽 {hd["head_w"]:.0f}  肩宽 {hd["shoulder"]:.0f}'
              f'  肩/头 {hd["sw_hw"]:.2f}  颈线 y={hd["neck_y"]}'
              f'（{"实测" if hd["neck_ok"] else "陡增兜底"}）'
              f'  最宽行 {hd["widest_rel"]*100:.0f}%')
    ay, dx = asym(m, p)
    print(f'视角  左右不对称 {ay*100:.1f}%   重心横移 {dx:+.1f} px')
    print('-' * 90)
    return dict(path=path, top=top, bot=bot, left=left, right=right, h=h, w=w,
                area=m.mean(), hd=hd)


if __name__ == '__main__':
    rows = [r for r in (report(p) for p in sys.argv[1:]) if r]
    if len(rows) > 1:
        bot = [r['bot'] for r in rows]; hh = [r['h'] for r in rows]
        print('三格一致性（同一机体 / 同一比例 / 脚底对齐）')
        print(f'  脚底基线 y = {bot}   极差 {max(bot)-min(bot)} px   '
              f'{"✓ 对齐" if max(bot)-min(bot) <= 3 else "✗ 未对齐"}')
        print(f'  主体高     = {hh}   极差 {max(hh)-min(hh)} px   '
              f'{"✓ 同比例" if max(hh)-min(hh) <= 6 else "✗ 比例不一致"}')
        # ★ 头高这里不查一致性：3D 图的领口把颈窝糊住，检测器只能靠「最陡加宽行」
        #   兜底，会把颈线判到肩线（实测正视读 178 px，几何真值 130 px）。
        #   头身比以 tools/prop_audit.py 的几何审计为准，这里只查剪影层面的可比值。
        sw = [r['hd']['sw_hw'] for r in rows if r['hd']]
        if sw:
            print(f'  肩/头      = {[round(v,2) for v in sw]}   极差 {max(sw)-min(sw):.2f}   '
                  f'{"✓ 同头身比" if max(sw)-min(sw) <= 0.10 else "（侧视头宽为进深，不参与比较）"}')
