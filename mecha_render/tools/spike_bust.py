"""tools/spike_bust.py — 路线 C 躯干局部验证：双门 + 出图

产出 out/spike/ 下：−28° / 正视 / +28° / 侧视 单帧、放大裁切、三格拼版。
两道门：
  体量门  V2 法线多样性 ≥25%、V3 分量闭合率 ≥0.90（tools/volume_check.py）
  保真门  渲染剪影 vs 原稿剪影 IoU ≥99%
"""
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'tools'))

import relief_v2 as R                                  # noqa: E402
import render_relief as RR                             # noqa: E402
import trace3d as T                                    # noqa: E402
import volume_check as VC                              # noqa: E402

OUT = os.path.join(HERE, 'out', 'spike')
os.makedirs(OUT, exist_ok=True)

TAG = os.environ.get('SPIKE_TAG', 'v11')


def main():
    y0, y1 = 40, 700
    mesh, meta = R.build(y0, y1, 2, verbose=True)
    print(f'总三角 {len(mesh)}')

    r = VC.measure(mesh, meta, label='路线 C v2.2 · 胸像')

    line = RR.load_line_art()
    ld = meta['dist']

    shots = []
    yaw_list = ((-40, 'a'), (-20, 'b'), (0, 'f'), (20, 'c'), (40, 'd'), (90, 's'))
    for yaw, tag in yaw_list:
        p = os.path.join(OUT, f'{TAG}_{tag}.png')
        mask, img = RR.render(mesh, meta, yaw, p, size=(760, 1180),
                              line=line, line_dist=ld)
        shots.append((yaw, img, mask))
        print(f'  {tag} yaw={yaw:+d} 覆盖 {int(mask.sum())}px → {os.path.basename(p)}')

    # 保真门：正视 IoU
    src = T.load_masks()[2][y0:y1]
    iou = RR.iou(shots[2][2], src)
    print(f'保真门 · 正视剪影 IoU = {iou*100:.2f}%   (阈值 ≥99%)   '
          f'{"PASS" if iou >= 0.99 else "FAIL"}')
    print(f'双门汇总：体量 {"PASS" if r["all_pass"] else "FAIL"} / '
          f'保真 {"PASS" if iou >= 0.99 else "FAIL"}')

    # --- 放大裁切：问题区（头顶天线、侧视轮廓中段）必须 2~3× 才看得清
    f_img = shots[2][1]
    f_img.crop((180, 80, 480, 380)).resize((600, 600), Image.LANCZOS).save(
        os.path.join(OUT, f'{TAG}_z_head.png'))
    s_img = shots[5][1]
    s_img.crop((250, 330, 400, 830)).resize((450, 1500), Image.LANCZOS).save(
        os.path.join(OUT, f'{TAG}_z_seam.png'))
    print(f'  放大裁切 → {TAG}_z_head.png / {TAG}_z_seam.png')

    # --- 拼版（五个视角，不含 90° 退化视角）
    Wp, Hp = shots[0][1].size
    sheet = Image.new('RGB', (Wp * 5, Hp), '#f6f4ef')
    for k in range(5):
        sheet.paste(shots[k][1], (k * Wp, 0))
    d = ImageDraw.Draw(sheet)
    for k, lab in enumerate(('-40°', '-20°', '正视 0°', '+20°', '+40°')):
        d.text((k * Wp + 16, 14), lab, fill='#333')
    sp = os.path.join(OUT, f'{TAG}_sheet.png')
    sheet.save(sp)
    print(f'  → {sp}')


if __name__ == '__main__':
    main()
