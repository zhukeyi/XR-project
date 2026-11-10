"""tools/prop_audit.py — 从几何顶点直接量「体型」，不依赖看图

为什么不量图：图要经过相机、裁切、抗锯齿，量出来的肩宽受透视影响（正视渲出
630 px / 机高 1077 px = 0.585，而模型实际肩宽 9.8 / 机高 18.2 = 0.538）。
几何量是定义域，图是值域 —— 判断体型该量定义域。

输出每项都与参考带对比：
  · 头身比 8.2~8.8       （SEED 画法规格）
  · 肩宽/机高 0.30~0.33  （RX-78 实测区间；0.54 是「过宽」，0.25 是「偏瘦」）
  · 头宽/肩宽 0.22~0.28  （重型机体头要小；>0.32 显得头大、稚气）
  · 双腿合计/肩宽 0.50~0.60（<0.40 是「一看就不厉害」的主因）
  · 脚长/机高 0.11~0.13  （脚小站不住）

用法：python3 tools/prop_audit.py [--rot 0, --json]
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mecha_model as MM

HEAD_CORE = ('skull_back', 'skull_top', 'brow', 'brow_ridge', 'visor_frame',
             'mask_lower', 'jaw', 'ear_vent')
CHEST = ('chest_up', 'chest_low', 'chest_side', 'chest_blue')
FOOT = ('foot_main', 'foot_toe', 'heel')


def world_boxes(node, M=None, out=None):
    """遍历节点树，按「节点名 → 世界空间包围盒」收集（同名合并）。"""
    if out is None:
        out = {}
    M = node.local() if M is None else M @ node.local()
    if getattr(node, 'hide', False):
        return out
    if node.prim is not None:
        v = np.asarray(node.prim[0], float)          # (nv,3)
        w = v @ M[:3, :3].T + M[:3, 3]
        k = node.name
        lo, hi = w.min(0), w.max(0)
        if k in out:
            out[k] = (np.minimum(out[k][0], lo), np.maximum(out[k][1], hi))
        else:
            out[k] = (lo, hi)
    for c in node.children:
        world_boxes(c, M, out)
    return out


def span(boxes, names=None, axis=None):
    """给定名字集合（前缀匹配）返回并集包围盒。axis None→(lo,hi) 全轴。"""
    sel = [b for k, b in boxes.items()
           if names is None or any(k.startswith(n) for n in names)]
    if not sel:
        return None
    lo = np.min([b[0] for b in sel], axis=0)
    hi = np.max([b[1] for b in sel], axis=0)
    return (lo, hi) if axis is None else (lo[axis], hi[axis])


def audit(p=None):
    root = MM.build_mecha(p or {})
    bx = world_boxes(root)
    lo, hi = span(bx)
    H = hi[1] - lo[1]
    head = span(bx, HEAD_CORE)
    hh = head[1][1] - head[0][1]
    hw = head[1][0] - head[0][0]
    sh = max(abs(v) for b in bx.values() for v in (b[0][0], b[1][0])) * 2
    ch = span(bx, CHEST)
    legs = span(bx, ('hip-', 'hip'))
    legw = legs[1][0] - legs[0][0]
    ft = span(bx, FOOT)
    fl = ft[1][2] - ft[0][2]
    fw = ft[1][0] - ft[0][0]
    # 腿长：髋关节高度（hips 节点 y=9.90 - 0.55 髋球半径 近似）→ 用 hip 子树顶面
    hipp = span(bx, ('hip-', 'hip'))
    leg_h = hipp[1][1] - lo[1]
    return dict(
        H=H, head_h=hh, head_w=hw, shoulder=sh,
        chest_w=ch[1][0] - ch[0][0], chest_d=ch[1][2] - ch[0][2],
        leg_w=legw, leg_h=leg_h, foot_l=fl, foot_w=fw,
        r_head=H / hh, r_sh=sh / H, r_hw_sh=hw / sh, r_leg_sh=legw / sh,
        r_leg_h=leg_h / H, r_foot=fl / H,
    )


# 参考带的给定方式说明：肩宽/脚长这两项「英雄型」和「重装型」差得很多，
# 拿 RX-78 的 0.31 去卡一台重装机是错的口径，所以带取到重装型上界。
BANDS = [
    ('头身比',       'r_head',   8.2, 8.8, 'SEED 画法规格'),
    ('肩宽/机高',    'r_sh',     0.30, 0.38, 'RX-78 0.31 / 重装型 0.34~0.38'),
    ('头宽/肩宽',    'r_hw_sh',  0.22, 0.30, '重型头要小，>0.32 显稚气'),
    ('双腿合计/肩宽', 'r_leg_sh', 0.50, 0.65, '<0.40 就是「一看就不厉害」'),
    ('腿长/机高',    'r_leg_h',  0.48, 0.54, '腿短显笨'),
    ('脚长/机高',    'r_foot',   0.11, 0.16, '脚小站不住 / >0.17 是小丑鞋'),
]


def show(a):
    print(f'机高 {a["H"]:.2f}  头高 {a["head_h"]:.2f}  头宽 {a["head_w"]:.2f}'
          f'  肩宽 {a["shoulder"]:.2f}  胸宽 {a["chest_w"]:.2f} 胸深 {a["chest_d"]:.2f}')
    print(f'双腿合计 {a["leg_w"]:.2f}  腿长 {a["leg_h"]:.2f}'
          f'  脚长 {a["foot_l"]:.2f}  脚宽 {a["foot_w"]:.2f}')
    print('-' * 78)
    print(f'{"指标":<14}{"实测":>9}{"目标":>16}{"差":>10}  判定')
    for label, k, lo, hi, note in BANDS:
        v = a[k]
        if v < lo:
            d = (v - lo) / lo * 100; verdict = f'↓ 偏小 {d:+.0f}%'
        elif v > hi:
            d = (v - hi) / hi * 100; verdict = f'↑ 偏大 {d:+.0f}%'
        else:
            verdict = '✓'
        print(f'{label:<14}{v:>9.3f}{f"{lo:.2f}~{hi:.2f}":>16}{verdict:>12}  {note}')


if __name__ == '__main__':
    a = audit()
    if '--json' in sys.argv:
        print(json.dumps(a, indent=2, ensure_ascii=False))
    else:
        show(a)
