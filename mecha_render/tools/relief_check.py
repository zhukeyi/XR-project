"""tools/relief_check.py — 线稿反推 3D 的数值验收（不靠肉眼）

四个必须用数字回答的问题：
  ① 外轮廓有没有丢   → 剪影 IoU（按包围盒归一，只比形状）
  ② 内部墨线有没有丢 → 板缝材质（M_SEAM）像素占剪影的比例，对上原稿「墨/剪影」
                      —— 这是「不丢细节」的真正含义，剪影一致只证明外轮廓
  ③ 线条读不读得出来 → 板缝亮度 vs 板面亮度之比（对比度）
  ④ 是不是真 3D      → 顶点 z 跨度 + 转角时剪影宽度是否随之变化
                      （旋转宽度恒定 = 贴纸，不是网格）

★ 这里踩过两个坑，别再犯：
  · gbuffer 的掩码是**超采样分辨率**（WS×HS），最终图是 W×H。拿 rm 的行列号去裁
    img0 会得到错位图，于是「板面亮度」量出来是一半板面一半板缝的双峰。
  · 早期的「背板」逐行铺满整个剪影，于是剪影 IoU 恒等于 100% —— 指标被量体本身
    喂饱了，什么都测不出来。现在剪影由板件+机身的真实侧面交集决定，IoU 才有意义。
"""
import json
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'tools'))

import trace3d as T                                   # noqa: E402
import render_relief as R                             # noqa: E402

OUT = R.OUT


def norm_mask(m, size=(420, 1000)):
    ys, xs = np.nonzero(m.any(1))[0], np.nonzero(m.any(0))[0]
    sub = m[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    im = Image.fromarray((sub * 255).astype(np.uint8)).resize(size, Image.BILINEAR)
    return np.asarray(im) > 127


def main():
    mesh, meta = R.make_mesh()
    fig = meta['fig']
    ink, inner, _ = T.load_masks()

    # ---------- ① 剪影 IoU
    rm, img0 = R.render(mesh, meta, 0, os.path.join(OUT, 'r_000.png'), size=R.STILL)
    iou = float((norm_mask(rm) & norm_mask(fig)).sum()) / \
        float((norm_mask(rm) | norm_mask(fig)).sum())
    print(f'① 剪影 IoU              = {iou*100:.2f}%      (目标 >95%)')

    # ---------- ② 墨线保留度（距离指标，不用 IoU）
    # 细线对「宽度差 1 px」极端敏感，IoU 会把好结果读成 46%。改用「每个原稿墨线
    # 像素到最近渲染暗线的距离」：中位数 + 成片丢失率才说明细节有没有丢。
    a = np.asarray(img0.convert('L'), np.float32)
    cov = a < 250
    ry, rx = np.nonzero(cov.any(1))[0], np.nonzero(cov.any(0))[0]
    ys, xs = np.nonzero(fig.any(1))[0], np.nonzero(fig.any(0))[0]
    y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
    bw, bh = x1 - x0 + 1, y1 - y0 + 1
    L = np.asarray(Image.fromarray(a[ry.min():ry.max() + 1, rx.min():rx.max() + 1]
                                   .astype(np.uint8))
                   .resize((bw, bh), Image.BILINEAR), np.float32)
    figb = fig[y0:y1 + 1, x0:x1 + 1]
    inkb = ink[y0:y1 + 1, x0:x1 + 1]
    plate_lum = float(np.percentile(L[figb], 70))
    dR = L < 0.45 * plate_lum
    dd = T.chamfer_dt(~dR)
    # 内部墨线：两侧都是封闭白区的墨（真正决定「结构细节」的那些）
    d2 = np.zeros_like(fig)
    d2[1:] |= inner[:-1]; d2[:-1] |= inner[1:]
    d2[:, 1:] |= inner[:, :-1]; d2[:, :-1] |= inner[:, 1:]
    mi = (ink & d2)[y0:y1 + 1, x0:x1 + 1]
    lab, _ = T.cc_label(mi & (dd > 1.5))
    ar = np.bincount(lab[lab >= 0])
    ar = ar[ar > 0]
    big = np.isin(lab, np.nonzero(ar > 20)[0]) if ar.size else np.zeros_like(lab, bool)
    lost = float((mi & (dd > 1.5) & big).sum()) / float(mi.sum())
    print(f'② 内部墨线保留          = 中位距离 {np.median(dd[mi]):.2f} px，'
          f'1 px 内 {(dd[mi]<=1).mean()*100:.1f}%，2 px 内 {(dd[mi]<=2).mean()*100:.1f}%')
    print(f'   成片丢失(>20px 的块)  = {lost*100:.2f}%   (目标 <3%)')

    # ---------- ③ 线条对比度
    Lf = L[figb]
    seam_lum = float(np.percentile(Lf, 8))
    print(f'③ 板面亮度              = {plate_lum:5.1f}/255')
    print(f'   板缝亮度              = {seam_lum:5.1f}/255   '
          f'对比 {plate_lum/max(seam_lum,1):.1f}:1   (目标 >4:1)')
    dark = float((Lf < 0.40 * plate_lum).mean())
    print(f'   暗于 0.40×板面的占比  = {dark*100:.1f}%   '
          f'(原稿墨线/剪影 = {inkb[figb].mean()*100:.1f}%)')

    # ---------- ④ 真 3D 证据
    Hm = meta['H']
    P, N, Tt, mii, Fi, b, e = mesh.arrays()
    z = P[:, :, 2].ravel()
    print(f'④ 顶点 z 范围            = [{z.min():+.2f}, {z.max():+.2f}]  总厚 '
          f'{z.max()-z.min():.2f} = 机高 {(z.max()-z.min())/Hm*100:.1f}%')
    ws = []
    for yaw in (-24, -12, 0, 12, 24):
        m, _ = R.render(mesh, meta, yaw, os.path.join(OUT, f'chk_{yaw:+03d}.png'))
        col = np.nonzero(m.any(0))[0]
        ws.append(int(col.max() - col.min() + 1))
    print(f'   剪影宽度随转角        = {ws}   '
          f'变化 {max(ws)/min(ws):.3f}×  (恒等=贴纸)')

    json.dump(dict(iou=round(iou, 4), ink_median_px=float(np.median(dd[mi])),
                   ink_1px=round(float((dd[mi] <= 1).mean()), 4),
                   ink_2px=round(float((dd[mi] <= 2).mean()), 4),
                   lost_blob=round(lost, 4),
                   plate_lum=round(plate_lum, 1), seam_lum=round(seam_lum, 1),
                   z_range=[round(float(z.min()), 3), round(float(z.max()), 3)],
                   tris=int(len(mesh)), widths=ws),
              open(os.path.join(OUT, 'verify.json'), 'w'), indent=1)
    print(f'\n-> {os.path.join(OUT, "verify.json")}')


if __name__ == '__main__':
    main()
