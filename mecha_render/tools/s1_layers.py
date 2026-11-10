"""tools/s1_layers.py — S1：把线稿的墨线按**语义**分成三类

为什么必须先做这一步
  分件重建的前提是知道「哪些线是零件边界」。当前实现把全部墨线一视同仁地
  开成同一深度的沟（GROOVE_D=0.038），于是外轮廓、零件边界、表面刻线
  在几何上完全等价 —— 这就是「一张皮」的另一半原因。
  分不开这三类，零件树就建不起来，后面 S2 全塌。

三类怎么判定（只用线稿本身的信息，不需要人工标注）
  ① 外轮廓线：墨线像素到背景的距离 ≤ 2 px。它定义剪影，唯一确定。
  ② 零件边界线（遮挡候选）：一条线的两侧属于**不同**的封闭区域。
     同一块装甲内部的刻线，两侧必然落在同一区域里。
  ③ 表面刻线：两侧属于**同一**封闭区域。

  判定"两侧"用 8 个方向的 ±2/±3 px 平移取样，取样本标签的 min/max：
  min ≠ max 且都 > 0 ⇒ 至少两侧落在不同区域。

输出
  out/s1/layers.png        三色叠加（红=外轮廓 蓝=零件边界 绿=表面刻线）
  out/s1/ink_on_gray.png   三类线画在灰度底上，便于判断分层是否可信
  out/s1/stats.json        各类像素数、区域数、区域面积分布

判读标准（写在 stats 里）
  零件边界线必须**成环**才能围出板件。若绝大多数零件边界线是不闭合的短枝，
  说明原稿的线宽/断线使区域不封闭 —— 那样 S1 判定为不通过，需要先补断点。

用法
  python3 tools/s1_layers.py
"""
import json
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'tools'))

import trace3d as T                                    # noqa: E402

OUT = os.path.join(HERE, 'out', 's1')
os.makedirs(OUT, exist_ok=True)

COL_CONT = (232, 64, 48)      # 外轮廓 —— 红
COL_PART = (40, 92, 220)      # 零件边界 —— 蓝
COL_DET = (32, 168, 96)       # 表面刻线 —— 绿


def _shift(a, dy, dx, fill):
    out = np.full_like(a, fill)
    H, W = a.shape
    ys0, ys1 = max(0, dy), min(H, H + dy)
    xs0, xs1 = max(0, dx), min(W, W + dx)
    out[ys0:ys1, xs0:xs1] = a[ys0 - dy:ys1 - dy, xs0 - dx:xs1 - dx]
    return out


def side_labels(lab, radii):
    """取墨线像素四周的样本标签，返回 (mn, mx)：mn<mx<BIG 表示两侧落在不同区域。

    ★ 半径必须大于线宽的一半，否则采样点还在墨线里（标签 -1），
      就永远判不出「两侧不同区」——第一版取 2/3 px 而线宽 6 px，结果
      零件边界 0.1%、表面刻线 74%，是假结果。
    用掩码 min/max 而不是「有几个不同值」：mn≠mx 且都有效 ⇔ 至少两个不同区域，
      这样不需要为每个标签做一次膨胀。
    """
    BIG = 1 << 30
    mn = np.full(lab.shape, BIG, np.int64)
    mx = np.full(lab.shape, -1, np.int64)
    for r in radii:
        for dy, dx in ((0, r), (0, -r), (r, 0), (-r, 0),
                       (r, r), (r, -r), (-r, r), (-r, -r)):
            s = _shift(lab, dy, dx, -1).astype(np.int64)
            ok = s >= 0
            mn = np.where(ok, np.minimum(mn, np.where(ok, s, BIG)), mn)
            mx = np.where(ok, np.maximum(mx, np.where(ok, s, -1)), mx)
    return mn, mx


def ink_width(ink):
    """墨线中位宽度（px）：对墨线求距离变换，取 2×中位深度。"""
    d = T.chamfer_dt(ink) / 3.0
    v = d[ink]
    return float(np.median(v) * 2.0) if len(v) else 3.0


def main():
    ink, inner, fig = T.load_masks()
    H, W = fig.shape
    print(f'线稿 {W}x{H}  墨线 {int(ink.sum())}px  内部区域 {int(inner.sum())}px')

    lab, n = T.cc_label(inner)
    areas = np.bincount(lab[lab >= 0].ravel(), minlength=n)
    big = areas[areas >= 40]
    print(f'封闭区域 {n} 个，其中 ≥40px 的 {len(big)} 个，'
          f'中位面积 {int(np.median(big)) if len(big) else 0}px')

    # ① 外轮廓：到背景 2px 以内
    #    chamfer_dt(m) 给的是「m 内像素到 m 外最近像素」的距离，所以要传 fig：
    #    传 bg 的话墨线像素不在 bg 里，距离恒为 0，会把全部墨线判成外轮廓（踩过）。
    d_bg = T.chamfer_dt(fig) / 3.0          # chamfer 的 3 是正交步长
    cont = ink & (d_bg <= 2.0)

    # ②③ 内部墨线按两侧区域分
    rest = ink & ~cont
    w = ink_width(ink)
    r0 = max(3, int(round(w * 0.5)) + 2)
    radii = (r0, r0 + 2, r0 + 4)
    print(f'墨线中位宽 {w:.1f}px → 两侧采样半径 {radii}')
    mn, mx = side_labels(lab, radii)
    both = rest & (mx >= 0) & (mn < mx)          # 两侧不同区 → 零件边界
    same = rest & ~both

    n_cont, n_part, n_det = int(cont.sum()), int(both.sum()), int(same.sum())
    tot = max(int(ink.sum()), 1)
    print(f'\n分层结果：')
    print(f'  ① 外轮廓    {n_cont:6d}px  {n_cont / tot * 100:5.1f}%')
    print(f'  ② 零件边界  {n_part:6d}px  {n_part / tot * 100:5.1f}%')
    print(f'  ③ 表面刻线  {n_det:6d}px  {n_det / tot * 100:5.1f}%')

    # 真正的判据：只按 ①② 切分，能切出多少块板
    # ③ 视为板内刻线、可穿过，不参与分块；若 ③ 分错了，块数会异常多或异常少
    plate_mask = fig & ~(cont | both)
    lab3, n3 = T.cc_label(plate_mask)
    a3 = np.bincount(lab3[lab3 >= 0].ravel(), minlength=n3)
    a3 = a3[a3 >= 40]
    print(f'\n分块检验：')
    print(f'  全部墨线切分     → {n} 块（含被刻线切碎的碎片）')
    print(f'  只用 ①② 切分     → {n3} 块，其中 ≥40px 的 {len(a3)} 块')
    if len(a3):
        q = np.percentile(a3, [10, 50, 90])
        print(f'  板件面积分位 10/50/90 = {int(q[0])}/{int(q[1])}/{int(q[2])} px')

    # ---- 出图
    layers = np.full((H, W, 3), 255, np.uint8)
    layers[cont] = COL_CONT
    layers[both] = COL_PART
    layers[same] = COL_DET
    p1 = os.path.join(OUT, 'layers.png')
    Image.fromarray(layers).save(p1)

    # 灰度底：区域内按面积给不同亮度，便于看边界线是否贴在区域交界
    g = np.full((H, W), 238, np.uint8)
    shade = (40 + 170 * (np.arange(n) % 7) / 6.0).astype(np.uint8)
    m = lab >= 0
    g[m] = shade[lab[m]]
    g[fig & ~inner & ~ink] = 225
    rgb = np.stack([g, g, g], -1)
    for cls, col in ((cont, COL_CONT), (both, COL_PART), (same, COL_DET)):
        rgb[cls] = col
    p2 = os.path.join(OUT, 'ink_on_gray.png')
    Image.fromarray(rgb).save(p2)
    print(f'\n→ {p1}\n→ {p2}')

    # ---- 结论判据：① 边界线占比在合理区间，② 切出的板件数量在 12~120 之间
    # 低于 12 = 还在一张皮；高于 120 = 刻线被误判成边界，切得过碎
    frac_part = n_part / tot
    frac_det = n_det / tot
    ok_ratio = 0.15 <= frac_part <= 0.50 and frac_det >= 0.20
    ok_plate = 12 <= len(a3) <= 120
    verdict = 'PASS' if (ok_ratio and ok_plate) else 'WEAK'
    print(f'\n分层可用性：{verdict}')
    print(f'  边界线占比 {frac_part:.0%}（要求 15~50%）、'
          f'刻线占比 {frac_det:.0%}（要求 ≥20%）→ {"符合" if ok_ratio else "不符"}')
    print(f'  切出板件 {len(a3)} 块（要求 12~120）→ {"符合" if ok_plate else "不符"}')

    with open(os.path.join(OUT, 'stats.json'), 'w') as f:
        json.dump(dict(n_regions_all_ink=int(n), n_plates=int(len(a3)),
                       ink=int(ink.sum()), contour=n_cont,
                       part_boundary=n_part, surface_detail=n_det,
                       ink_width_px=round(w, 2), radii=list(radii),
                       plate_area_q=[int(v) for v in
                                     (np.percentile(a3, [10, 50, 90]).tolist()
                                      if len(a3) else [0, 0, 0])],
                       verdict=verdict),
                  f, ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
