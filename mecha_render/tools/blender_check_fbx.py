"""tools/blender_check_fbx.py — 把导出的 FBX 重新导入 Blender，闭合验证

为什么要多这一步
  导出成功不等于文件正确。用一个新场景把它读回来，确认对象数、层级深度、
  空物体、尺寸都对，才算闭环。Blender 的 FBX 导入器是参考实现。

用法
  blender -b --factory-startup -P tools/blender_check_fbx.py -- <file.fbx> <report.json>
"""
import json
import os
import sys

import bpy

argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
src, out_json = argv[0], argv[1]

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=src)

objs = list(bpy.data.objects)
meshes = [o for o in objs if o.type == 'MESH']
empties = [o for o in objs if o.type == 'EMPTY']


def depth(o):
    d, p = 1, o.parent
    while p is not None:
        d += 1
        p = p.parent
    return d


lo = [float('inf')] * 3
hi = [float('-inf')] * 3
tris = 0
for o in meshes:
    mw = o.matrix_world
    me = o.data
    me.calc_loop_triangles()
    tris += len(me.loop_triangles)
    for v in me.vertices:
        p = mw @ v.co
        for i in range(3):
            lo[i] = min(lo[i], p[i])
            hi[i] = max(hi[i], p[i])

rep = {
    'source': os.path.basename(src),
    'objects_total': len(objs),
    'meshes': len(meshes),
    'empties': len(empties),
    'max_depth': max((depth(o) for o in objs), default=0),
    'roots': [o.name for o in objs if o.parent is None],
    'triangles': tris,
    'materials': len(bpy.data.materials),
    'size_blender_xyz': [round(hi[i] - lo[i], 4) for i in range(3)],
    'height_m': round(hi[2] - lo[2], 4),
    'pivots': sorted(o.name for o in empties if any(
        o.name.startswith(p) for p in ('hips', 'chest', 'head', 'shoulder', 'elbow',
                                       'wrist', 'hatch', 'knee', 'ankle', 'hip',
                                       'backpack', 'skirt', 'rack'))),
}
with open(out_json, 'w') as f:
    json.dump(rep, f, ensure_ascii=False, indent=1)

print('=' * 66)
print('FBX 回读验证 · %s' % rep['source'])
print('=' * 66)
print('  对象 %d（网格 %d + 空物体 %d）  最大深度 %d'
      % (len(objs), len(meshes), len(empties), rep['max_depth']))
print('  三角 %d  材质 %d  根节点 %s' % (tris, len(bpy.data.materials), rep['roots']))
print('  尺寸 X=%.3f Y=%.3f Z=%.3f（Z 即高度）' % tuple(rep['size_blender_xyz']))
print('  枢轴空物体 %d 个' % len(rep['pivots']))
