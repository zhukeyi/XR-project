"""tools/export_obj_parts.py — 把 mecha_model 导出成「按分件分组」的 OBJ

为什么需要它
  现有的 tools/s2_graybox.py:write_obj 是三角形汤写法：每三角形 3 个独立顶点、
  单一 `o s2_upper`、无 usemtl / vt / vn。38 个零件在文件里塌成 1 个物体，
  进 Unity 后无法按 Pivot_* 定位任何关节。
  本脚本按节点树逐件输出 `o <节点名>` + `usemtl <材质名>` + `vn` + 占位 `vt`，
  使 OBJ 能带着层级语义进入 Blender / Unity。

输出
  out/pico/mecha_parts.obj   按分件分组的网格
  out/pico/mecha_parts.json  分件清单 + 关节世界坐标 + 包围盒

用法
  python3 tools/export_obj_parts.py
  python3 tools/export_obj_parts.py --hatch     # 舱门开到 95°，便于检查内构
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import mecha_model as M            # noqa: E402
import r3d                         # noqa: E402
from gfx import mesh as GM         # noqa: E402
from tools.export_gltf import unique_names, mat_name_table, resolve_mat   # 与 glTF 共用命名与材质名

OUT = os.path.join(ROOT, 'out', 'pico')


def world_pos(node):
    """节点世界坐标（取变换矩阵的平移列）。"""
    return node.world()[:3, 3]


def collect_parts(root):
    """逐节点收集三角形。返回 [(node, P(T,3,3), N(T,3,3)), ...]"""
    parts = []

    def rec(n):
        if n.prim is not None and not n.hide:
            m = GM.Mesh()
            GM.prim_to_tris(m, n.prim[0], n.prim[1], n.world(), n.mat, smooth=n.smooth)
            if len(m.P):
                parts.append((n, np.array(m.P), np.array(m.N)))
        for c in n.children:
            rec(c)

    rec(root)
    return parts


def write_obj(parts, path, names, mtab):
    lines = ['# 钢脊 HX-07 · 按分件导出（%d 件）' % len(parts),
             '# 单位 m，Y-up，正面 +Z，脚底 y=0（导出后需平移）',
             '# 注意：OBJ 无父子关系，本文件是平级分件；要层级请用 mecha_parts.glb']
    voff = 0
    for node, P, N in parts:
        lines.append('o %s' % names[id(node)])
        lines.append('usemtl %s' % resolve_mat(node.mat, mtab))
        V = P.reshape(-1, 3)
        Nn = N.reshape(-1, 3)
        for p in V:
            lines.append('v %.5f %.5f %.5f' % (p[0], p[1], p[2]))
        for n in Nn:
            lines.append('vn %.4f %.4f %.4f' % (n[0], n[1], n[2]))
        for i in range(0, len(V), 3):
            a, b, c = voff + i + 1, voff + i + 2, voff + i + 3
            lines.append('f %d//%d %d//%d %d//%d' % (a, a, b, b, c, c))
        voff += len(V)
    with open(path, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    return voff


def main():
    hatch = 1.0 if '--hatch' in sys.argv else 0.0
    root = M.build_mecha({'rifle_on': True, 'saber_on': 0.0, 'hatch': hatch})

    parts = collect_parts(root)
    os.makedirs(OUT, exist_ok=True)

    all_nodes = []

    def walk_all(n):
        all_nodes.append(n)
        for c in n.children:
            walk_all(c)

    walk_all(root)
    names = unique_names(all_nodes)

    mtab = mat_name_table()
    obj_path = os.path.join(OUT, 'mecha_parts.obj')
    nv = write_obj(parts, obj_path, names, mtab)

    allP = np.concatenate([P.reshape(-1, 3) for _, P, _ in parts])
    lo, hi = allP.min(0), allP.max(0)

    joints = {}
    for name in ('hips', 'chest', 'head', 'backpack', 'shoulder-1', 'shoulder1',
                 'elbow-1', 'elbow1', 'wrist', 'knee-1', 'knee1', 'ankle-1', 'ankle1',
                 'hatch_hinge-1', 'hatch_hinge1', 'cockpit_seat'):
        found = []

        def rec(n):
            if n.name == name:
                found.append(n)
            for c in n.children:
                rec(c)

        rec(root)
        if found:
            joints[name] = [round(float(x), 4) for x in world_pos(found[0])]

    info = {
        'parts': len(parts),
        'vertices': nv,
        'tris': nv // 3,
        'bbox': {'min': [round(float(x), 4) for x in lo],
                 'max': [round(float(x), 4) for x in hi],
                 'size': [round(float(x), 4) for x in (hi - lo)]},
        'materials': sorted({resolve_mat(n.mat, mtab) for n, _, _ in parts}),
        'joints_world': joints,
        'parts_detail': [{'name': names[id(n)], 'tris': len(P),
                          'mat': resolve_mat(n.mat, mtab),
                          'pos': [round(float(x), 4) for x in world_pos(n)]}
                         for n, P, _ in parts],
    }
    with open(os.path.join(OUT, 'mecha_parts.json'), 'w') as f:
        json.dump(info, f, ensure_ascii=False, indent=1)

    print('=' * 70)
    print('按分件导出 · %s' % obj_path)
    print('=' * 70)
    print('  分件数    %d' % info['parts'])
    print('  三角面    %d' % info['tris'])
    print('  顶点      %d（未共享，三角汤）' % info['vertices'])
    print('  材质      %d 个：%s' % (len(info['materials']), ', '.join(info['materials'])))
    print('  包围盒    W=%.3f  H=%.3f  D=%.3f' % tuple(info['bbox']['size']))
    print('  脚底 y    %.4f' % info['bbox']['min'][1])
    print()
    print('  关节世界坐标：')
    for k, v in joints.items():
        print('    %-14s %s' % (k, v))
    print()
    print('  文件大小  %.1f KB' % (os.path.getsize(obj_path) / 1024))


if __name__ == '__main__':
    main()
