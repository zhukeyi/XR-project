"""tools/rig_probe.py — 绑定前实测探针：把 s2 节点树里每个节点的**真实世界包围盒**量出来

为什么需要它
  任何「骨骼锚点」数字都必须来自最终几何，不能来自 DIM 设计值，也不能拿设计值乘
  一个比例系数凑。本文件只做一件事：走一遍节点树，把每个节点的子树包围盒
  （世界系、米、Y 上）算出来，落到 JSON，供 rig_contract 对账。

用法
  python3 tools/rig_probe.py --clean        # 主干构型（默认）
  python3 tools/rig_probe.py --full         # 含动力舱/浮游炮/折叠翼
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'tools'))

import s2_graybox as S2                                   # noqa: E402


def _verts(prim, M):
    """prim 是 (v, faces) 二元组 —— 与 gfx.mesh.collect2 的取法一致。"""
    if prim is None:
        return None
    v, _faces = prim[0], prim[1]
    P = np.array(v, np.float64).reshape(-1, 3)
    if len(P) == 0:
        return None
    Ph = np.hstack([P, np.ones((len(P), 1))])
    return (M @ Ph.T).T[:, :3]


def walk(node, M, out, depth=0):
    """返回 (该子树顶点数, 该子树世界 bbox 或 None)"""
    if getattr(node, 'hide', False):
        return 0, None
    M = M @ node.local()
    acc = [None]
    nv = 0

    v = _verts(node.prim, M)
    if v is not None:
        nv += len(v)
        acc[0] = (v.min(0), v.max(0))

    for c in node.children:
        cn, cb = walk(c, M, out, depth + 1)
        nv += cn
        if cb is not None:
            if acc[0] is None:
                acc[0] = cb
            else:
                acc[0] = (np.minimum(acc[0][0], cb[0]),
                          np.maximum(acc[0][1], cb[1]))

    if acc[0] is not None:
        lo, hi = acc[0]
        out.append(dict(
            path=node.name,
            depth=depth,
            prims=1 if node.prim is not None else 0,
            verts=nv,
            lo=[round(float(x), 4) for x in lo],
            hi=[round(float(x), 4) for x in hi],
            size=[round(float(hi[i] - lo[i]), 4) for i in range(3)],
            center=[round(float(0.5 * (lo[i] + hi[i])), 4) for i in range(3)],
        ))
    return nv, acc[0]


def main():
    if '--full' in sys.argv:
        S2.CLEAN = False
    root, mesh = S2.build()
    out = []
    nv, bb = walk(root, np.eye(4), out)
    meta = S2.meta_for(mesh)
    report = dict(
        config='full' if '--full' in sys.argv else 'clean',
        total_verts=nv,
        total_tris=len(mesh),
        parts=S2.count_parts(root),
        bbox=[round(x, 4) for x in meta['bbox']],
        nodes=out,
    )
    dst = os.path.join(HERE, 'out', 's2', 'rig_probe_%s.json' % report['config'])
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, 'w') as f:
        json.dump(report, f, ensure_ascii=False, indent=1)

    print('=' * 76)
    print('rig_probe · %s · parts=%d tris=%d verts=%d' % (
        report['config'], report['parts'], report['total_tris'], nv))
    print('整机 bbox  X[%.3f,%.3f]  Y[%.3f,%.3f]  Z[%.3f,%.3f]' % (
        meta['bbox'][0], meta['bbox'][1], meta['bbox'][2],
        meta['bbox'][3], meta['bbox'][4], meta['bbox'][5]))
    print('-' * 76)
    print('%-22s %6s %7s  %-26s %-26s' % ('node', 'depth', 'verts', 'Y 范围', 'X 范围'))
    for n in out:
        if n['depth'] > 3:
            continue
        print('%-22s %6d %7d  [%7.3f,%7.3f] %14s  [%7.3f,%7.3f]' % (
            ('  ' * n['depth']) + (n['path'] or '(anon)'), n['depth'], n['verts'],
            n['lo'][1], n['hi'][1], '', n['lo'][0], n['hi'][0]))
    print('-' * 76)
    print('写入 %s' % dst)
    return 0


if __name__ == '__main__':
    sys.exit(main())
