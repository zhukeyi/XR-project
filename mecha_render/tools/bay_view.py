"""tools/bay_view.py — 背包审图：只框背部区域，绕四个机位各出一张

为什么要单独一个工具：三视图的取景是按**全机包络**开的，背包只占画面 1/4，
浮游炮挂在哪、有没有穿模，在那个尺度下根本判不了。这个工具把相机高度
压到 y 4.3–8.0 的窗口，绕四个方位角出图，专门给背包和挂载做判图。

  python3 tools/bay_view.py             # 出 4 张 out/bay/bay_<yaw>.png
  python3 tools/bay_view.py --y 4.3 8.0 # 改窗口

★ 窗口是**世界坐标**的 y 区间，不是件的局部 y —— 第一版浮游炮特写就是在
  这里栽过一次（拿了件内部坐标去开世界窗口，整格空白，见 parts_lib 注释）。
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'tools'))

import s2_graybox as S                                   # noqa: E402
import render_relief as RR                              # noqa: E402
from PIL import Image, ImageDraw                         # noqa: E402


def main():
    arg = sys.argv[1:]
    y0, y1 = 4.30, 8.00
    if '--y' in arg:
        i = arg.index('--y')
        y0, y1 = float(arg[i + 1]), float(arg[i + 2])
    root, mesh = S.build()
    base = S.meta_for(mesh)
    # ★ Wfig/zf/zback 置 0：只要竖向窗口，否则会被「横向比竖向宽」拉回整机比例
    meta = dict(base, H=(y1 - y0) * 1.06, cy=0.5 * (y0 + y1),
                Wfig=0.0, zf=0.0, zback=0.0)
    vm = S.view_meta(meta, (760, 760))
    outd = os.path.join(HERE, 'out', 'bay')
    os.makedirs(outd, exist_ok=True)
    yaws = (0.0, 145.0, 180.0, 215.0)
    ims = []
    for yw in yaws:
        p = os.path.join(outd, 'bay_%03d.png' % int(yw))
        RR.render(mesh, vm, yw, p, size=(760, 760), bg_lv=0.55)
        ims.append(Image.open(p))
    sheet = Image.new('RGB', (760 * 4, 760 + 26), (40, 40, 44))
    d = ImageDraw.Draw(sheet)
    for i, im in enumerate(ims):
        sheet.paste(im, (760 * i, 0))
        d.text((760 * i + 12, 768), 'yaw %d' % int(yaws[i]), fill=(225, 228, 235))
    sp = os.path.join(outd, 'bay_sheet.png')
    sheet.save(sp)
    print(f'  窗口 y {y0:.2f}..{y1:.2f} → {sp}')


if __name__ == '__main__':
    main()
