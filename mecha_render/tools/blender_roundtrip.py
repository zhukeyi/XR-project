"""tools/blender_roundtrip.py — 在 Blender 内无头执行「glb 导入 → 核对 → FBX 导出」

用途
  验证 mecha_parts.glb 进入 Blender 后层级是否完整、枢轴空物体是否保留，
  并按 Unity 需要的约定导出 FBX 2020。这是「路线 A：当白盒用」的最后一步。

为什么必须走 Blender
  Unity 不原生读 glb（要装 glTFast / UnityGLTF），而 FBX 是 Unity 的原生格式。
  Blender 自带 glTF 导入器，能把 Y-up 转成自己的 Z-up，再按 Unity 约定导出。

调用（无头，无需图形界面）
  /tmp/Blender.app/Contents/MacOS/Blender -b -factory-startup \
      -P tools/blender_roundtrip.py -- <in.glb> <out.fbx> <report.json>

关键参数（三个都踩过坑，其中一条是被实测推翻的）
  apply_scale_options='FBX_SCALE_ALL'  否则进 Unity 再乘 0.01
  bake_space_transform=False           ★ 实测必须关。开着会让读取端二次施加轴向转换：
                                       本机对照实验，同一份模型回读后 Z 高 18.864、
                                       Y 深 21.318（应为 18.200 / 9.564），关掉后精确复原。
  object_types={'EMPTY','MESH'}        不选 EMPTY 的话枢轴空物体整批丢失

  设 FBX_BAKE=1 可复现「开着」的错误结果，用于对照。
"""
import json
import os
import sys

import bpy

argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
if len(argv) < 3:
    print('用法: blender -b -P tools/blender_roundtrip.py -- <in.glb> <out.fbx> <report.json>')
    sys.exit(2)
src, out_fbx, out_json = argv[0], argv[1], argv[2]

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)

objs = list(bpy.data.objects)
empties = [o for o in objs if o.type == 'EMPTY']
meshes = [o for o in objs if o.type == 'MESH']


def depth(o):
    d = 1
    p = o.parent
    while p is not None:
        d += 1
        p = p.parent
    return d


maxd = max((depth(o) for o in objs), default=0)
roots = [o for o in objs if o.parent is None]

# 世界包围盒：逐顶点算，不用 bound_box（局部 AABB 角点会高估）
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

mats = [m.name for m in bpy.data.materials]

report = {
    'blender_version': bpy.app.version_string,
    'source': os.path.basename(src),
    'objects_total': len(objs),
    'meshes': len(meshes),
    'empties': len(empties),
    'max_depth': maxd,
    'roots': [o.name for o in roots],
    'triangles': tris,
    'materials': mats,
    'bbox_blender_xyz': {'min': [round(x, 4) for x in lo],
                         'max': [round(x, 4) for x in hi],
                         'size': [round(hi[i] - lo[i], 4) for i in range(3)]},
    'height_m': round(hi[2] - lo[2], 4),
    'width_m': round(hi[0] - lo[0], 4),
    'depth_m': round(hi[1] - lo[1], 4),
    'pivots_found': sorted(o.name for o in empties
                           if any(o.name.startswith(p) for p in
                                  ('hips', 'chest', 'head', 'shoulder', 'elbow',
                                   'wrist', 'hatch', 'knee', 'ankle', 'hip',
                                   'backpack', 'skirt', 'rack'))),
}

BAKE = os.environ.get('FBX_BAKE', '0') != '0'

bpy.ops.export_scene.fbx(
    filepath=out_fbx,
    use_selection=False,
    object_types={'EMPTY', 'MESH'},
    apply_scale_options='FBX_SCALE_ALL',
    bake_space_transform=BAKE,
    axis_forward='-Z',
    axis_up='Y',
    mesh_smooth_type='FACE',
    use_mesh_modifiers=True,
    add_leaf_bones=False,
    path_mode='COPY',
    embed_textures=False,
)
report['bake_space_transform'] = BAKE
report['fbx_bytes'] = os.path.getsize(out_fbx) if os.path.exists(out_fbx) else 0

with open(out_json, 'w') as f:
    json.dump(report, f, ensure_ascii=False, indent=1)

print('=' * 66)
print('Blender %s · %s' % (report['blender_version'], report['source']))
print('=' * 66)
print('  对象      %d（网格 %d + 空物体 %d）' % (len(objs), len(meshes), len(empties)))
print('  最大深度  %d   根节点 %s' % (maxd, roots and roots[0].name))
print('  三角面    %d' % tris)
print('  材质      %d' % len(mats))
print('  Blender 空间 X=%.3f Y=%.3f Z=%.3f（Z 即高度）'
      % tuple(report['bbox_blender_xyz']['size']))
print('  换算      宽 %.3f × 高 %.3f × 深 %.3f m'
      % (report['width_m'], report['height_m'], report['depth_m']))
print('  枢轴空物体 %d 个' % len(report['pivots_found']))
print('  FBX       %.1f KB' % (report['fbx_bytes'] / 1024))
