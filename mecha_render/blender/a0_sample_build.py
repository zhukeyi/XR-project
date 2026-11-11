"""blender/a0_sample_build.py — A0 样件：胸 + 单侧肩甲 + 肩关节 + 上臂上段

与 s2_graybox.py 的根本差别
  s2 只有「截面沿单轴放样」（221 次造型调用里 60% 是 L/LZ/LX），布尔、倒角、
  抽壳关键字出现次数全为 0 —— 所以内凹、通孔、变厚度、零件覆盖关系在原理上
  做不出来，只能贴片假装。
  本脚本走 bpy + CSG：每个主视觉件都经过**真减法**，验收用**亏格（真通孔数）**
  判定，贴片伪造不出来。规格见 docs/pm/05_A0_造型内核切换_门禁与样件任务书.md。

坐标
  Blender 内部 Z 上。s2 的 Y（高）→ Blender Z；s2 的 +Z（正面）→ Blender −Y。
  故几何里一律用 `d`（前深，正数朝正面），落顶点时 y = −d。

幂等
  开头清场 + 固定对象名，重复执行不会累积骨架、权重、材质或面。

用法
  /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup \
      -P blender/a0_sample_build.py
"""
import json
import math
import os
import sys

import bmesh
import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # mecha_render/
OUT = os.path.join(HERE, 'out', 'a0')
BLEND = os.path.join(OUT, 'a0_sample.blend')

RAD = math.radians

# ---------------------------------------------------------------- 尺寸（米）
# 全部取自 out/s2/rig_probe_clean.json 的实测包络，见任务书 §4/§5
CHEST_SECTIONS = [
    # (z, 半宽 w, 前深 zf, 后深 zb, 倒角 c, 壁厚 t)
    (4.88, 0.62, 0.55, -0.60, 0.08, 0.10),
    (5.20, 0.70, 0.62, -0.66, 0.08, 0.09),
    (5.60, 0.80, 0.68, -0.72, 0.09, 0.08),
    (6.10, 0.92, 0.72, -0.80, 0.09, 0.07),
    (6.55, 1.02, 0.70, -0.85, 0.10, 0.06),
    (6.83, 0.86, 0.55, -0.78, 0.08, 0.06),
]

UARM_SECTIONS = [
    # (z, 半宽 w, 前深 zf, 后深 zb, 倒角 c)
    (5.40, 0.235, 0.21, -0.22, 0.05),
    (5.62, 0.255, 0.24, -0.25, 0.06),
    (6.20, 0.280, 0.24, -0.26, 0.06),
    (6.54, 0.250, 0.22, -0.23, 0.05),
]

UARM_X = 1.67          # 上臂中心 X（实测 1.279–2.066，中心 1.6725）

BONES = [
    # (name, head, tail, parent)
    ('chest',      (0.00, 0.0, 5.16), (0.00, 0.0, 6.83), None),
    ('shoulder_L', (1.32, 0.0, 6.52), (1.67, 0.0, 5.40), 'chest'),
    ('elbow_L',    (1.67, 0.0, 5.40), (1.67, 0.0, 4.40), 'shoulder_L'),
]

# 件 → 骨
BIND = {
    'chest': 'chest', 'ch_beam': 'chest', 'ch_rib': 'chest', 'ch_ram': 'chest',
    'sh_top': 'shoulder_L', 'sh_outer': 'shoulder_L', 'sh_front': 'shoulder_L',
    'sh_axle': 'shoulder_L', 'sh_link': 'shoulder_L', 'sh_collar': 'shoulder_L',
    'uarm': 'shoulder_L',
}

MATS = {
    'armor_w': ((0.86, 0.87, 0.86), 0.15, 0.42),
    'armor_b': ((0.13, 0.26, 0.45), 0.30, 0.38),
    'frame':   ((0.20, 0.21, 0.22), 0.75, 0.45),
    'ink':     ((0.045, 0.048, 0.05), 0.85, 0.55),
    'accent':  ((0.55, 0.16, 0.09), 0.25, 0.40),
}

LOG = []


def log(msg):
    LOG.append(msg)
    print('[a0] ' + msg)


# ---------------------------------------------------------------- 基础
def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.unit_settings.system = 'METRIC'
    sc.unit_settings.scale_length = 1.0
    sc.unit_settings.length_unit = 'METERS'
    log('清场完成 · 单位 米 · scale_length=1.0')


def mat(name):
    m = bpy.data.materials.get(name)
    if m is not None:
        return m
    col, metal, rough = MATS[name]
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    bsdf = m.node_tree.nodes.get('Principled BSDF')
    bsdf.inputs['Base Color'].default_value = (col[0], col[1], col[2], 1.0)
    bsdf.inputs['Metallic'].default_value = metal
    bsdf.inputs['Roughness'].default_value = rough
    return m


def new_obj(name, verts, faces, matname):
    """verts 用 (x, d, z)，这里统一翻成 Blender 的 (x, -d, z)。"""
    bv = [(v[0], -v[1], v[2]) for v in verts]
    me = bpy.data.meshes.new(name)
    me.from_pydata(bv, [], faces)
    me.validate(verbose=False)
    ob = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(ob)
    ob.data.materials.append(mat(matname))
    recalc(ob)
    return ob


def recalc(ob):
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(ob.data)
    bm.free()
    ob.data.update()


def ring(w, zf, zb, c):
    """8 点倒角矩形，参数空间 (x, d)。"""
    return [
        (w - c, zb), (w, zb + c), (w, zf - c), (w - c, zf),
        (-w + c, zf), (-w, zf - c), (-w, zb + c), (-w + c, zb),
    ]


def rect_ring(dc, zc, dh, zh, c):
    """(d, z) 平面上的 8 点倒角矩形，用于沿 X / Z 的扫掠。"""
    return [
        (dc - dh + c, zc - zh), (dc + dh - c, zc - zh),
        (dc + dh, zc - zh + c), (dc + dh, zc + zh - c),
        (dc + dh - c, zc + zh), (dc - dh + c, zc + zh),
        (dc - dh, zc + zh - c), (dc - dh, zc - zh + c),
    ]


def _stack(name, rings, matname):
    """rings: [[(x, d, z) × 8], ...] 逐环堆叠成闭合实体。"""
    verts, faces = [], []
    n = len(rings[0])
    for r in rings:
        for (x, d, z) in r:
            verts.append((x, d, z))
    for i in range(len(rings) - 1):
        b = i * n
        for k in range(n):
            faces.append((b + k, b + (k + 1) % n, b + n + (k + 1) % n, b + n + k))
    faces.append(tuple(range(n - 1, -1, -1)))
    top = (len(rings) - 1) * n
    faces.append(tuple(top + k for k in range(n)))
    return new_obj(name, verts, faces, matname)


def sweep_x(name, sections, matname):
    """沿 X 扫掠。sections: [(x, [(d, z) × 8])]。"""
    rings = [[(x, d, z) for (d, z) in pts] for (x, pts) in sections]
    return _stack(name, rings, matname)


def loft(name, sections, matname, cx=0.0, inset=0.0):
    """沿 Z 扫掠。sections: [(z, w, zf, zb, c[, ...])]，多余字段忽略。"""
    rings = []
    for sec in sections:
        z, w, zf, zb, c = sec[0], sec[1], sec[2], sec[3], sec[4]
        w2, zf2, zb2 = w - inset, zf - inset, zb + inset
        if w2 <= 0.01 or zf2 - zb2 <= 0.02:
            raise RuntimeError('%s: 内缩 %s 后截面退化' % (name, inset))
        rings.append([(x + cx, d, z)
                      for (x, d) in ring(w2, zf2, zb2, min(c, w2 * 0.45))])
    return _stack(name, rings, matname)


def box(name, x0, x1, d0, d1, z0, z1, matname='ink'):
    v = [(x0, d0, z0), (x1, d0, z0), (x1, d1, z0), (x0, d1, z0),
         (x0, d0, z1), (x1, d0, z1), (x1, d1, z1), (x0, d1, z1)]
    f = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
         (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    return new_obj(name, v, f, matname)


def cyl_x(name, x0, x1, d, z, r, matname='frame', n=28):
    """沿 X 的圆柱（轴套 / 液压筒）。"""
    verts, faces = [], []
    for x in (x0, x1):
        for k in range(n):
            a = 2.0 * math.pi * k / n
            verts.append((x, d + r * math.cos(a), z + r * math.sin(a)))
    for k in range(n):
        faces.append((k, (k + 1) % n, n + (k + 1) % n, n + k))
    faces.append(tuple(range(n - 1, -1, -1)))
    faces.append(tuple(n + k for k in range(n)))
    return new_obj(name, verts, faces, matname)


def apply_mod(ob, mod):
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.modifier_apply(modifier=mod.name)


def boolean(target, cutter, op='DIFFERENCE'):
    m = target.modifiers.new('bool', 'BOOLEAN')
    m.operation = op
    m.solver = 'EXACT'
    m.object = cutter
    apply_mod(target, m)
    bpy.data.objects.remove(cutter, do_unlink=True)
    log('CSG %-10s %s' % (op, target.name))


def bevel(ob, width=0.008, segments=2, angle=30.0):
    """★ 属性名在 5.x 改过：clamp_overlap → use_clamp_overlap。写死会抛异常，
    而异常被吞掉的表现是「倒角全部静默跳过」，模型看着像没做收光。"""
    try:
        m = ob.modifiers.new('bev', 'BEVEL')
        m.width = width
        m.segments = segments
        m.limit_method = 'ANGLE'
        m.angle_limit = RAD(angle)
        for attr in ('use_clamp_overlap', 'clamp_overlap'):
            if hasattr(m, attr):
                setattr(m, attr, True)
                break
        apply_mod(ob, m)
        log('倒角 %-10s w=%.3f seg=%d' % (ob.name, width, segments))
    except Exception as e:                                   # noqa: BLE001
        log('倒角失败 %s：%s' % (ob.name, e))


# ---------------------------------------------------------------- 统计
def stats(ob):
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bm.verts.ensure_lookup_table()
    v, e, f = len(bm.verts), len(bm.edges), len(bm.faces)
    boundary = sum(1 for ed in bm.edges if len(ed.link_faces) < 2)
    nonman = sum(1 for ed in bm.edges if len(ed.link_faces) > 2)
    # 连通壳：按面邻接做并查集
    seen, islands = set(), 0
    for face in bm.faces:
        if face.index in seen:
            continue
        islands += 1
        stack = [face]
        seen.add(face.index)
        while stack:
            cur = stack.pop()
            for ed in cur.edges:
                for nf in ed.link_faces:
                    if nf.index not in seen:
                        seen.add(nf.index)
                        stack.append(nf)
    chi = v - e + f
    # 单壳时 genus = (2 - chi)/2；多壳按 islands 修正
    genus = max(0.0, (2 * islands - chi) / 2.0)
    vol = bm.calc_volume(signed=False)
    bm.free()
    bb = [ob.matrix_world @ Vector(c) for c in ob.bound_box]
    lo = [min(p[i] for p in bb) for i in range(3)]
    hi = [max(p[i] for p in bb) for i in range(3)]
    return dict(
        name=ob.name, verts=v, edges=e, faces=f,
        boundary_edges=boundary, nonmanifold_edges=nonman,
        islands=islands, euler=chi, genus=round(genus, 2),
        volume=round(vol, 4),
        bbox=[[round(x, 4) for x in lo], [round(x, 4) for x in hi]],
        tris=sum(len(p.vertices) - 2 for p in ob.data.polygons),
    )


# ---------------------------------------------------------------- 造件
def build_chest():
    outer = loft('chest_outer', CHEST_SECTIONS, 'armor_w')
    # 内层逐段独立内缩 ⇒ 壁厚沿高度变化（4.88 处 0.10 m，6.83 处 0.06 m）。
    # ★ 首末段的 z 也必须内缩，否则内外层共面，做差会留下零厚度的顶/底盖，
    #   布尔结果非流形。这是抽壳唯一的坑。
    last = len(CHEST_SECTIONS) - 1
    ins = []
    for i, (z, w, zf, zb, c, t) in enumerate(CHEST_SECTIONS):
        zz = z + t if i == 0 else (z - t if i == last else z)
        ins.append((zz, w - t, zf - t, zb + t, c))
    inner = loft('chest_inner', ins, 'ink')
    boolean(outer, inner, 'DIFFERENCE')
    outer.name = 'chest'

    # 座舱凹腔：真凹（打通前壁到内腔，露出内壁与主梁）
    boolean(outer, box('cut_cockpit', -0.42, 0.42, 0.25, 0.95, 5.95, 6.70))

    # 前壁通孔 ×3：贯穿壁厚 ⇒ 每个孔贡献 1 个亏格
    for i, (x0, x1) in enumerate([(-0.58, -0.22), (-0.10, 0.26), (0.34, 0.62)]):
        boolean(outer, box('cut_vent%d' % i, x0, x1, 0.30, 0.95, 5.34, 5.76))

    # 肩窝：外侧上角减出圆柱窝，让轴套坐进去
    boolean(outer, cyl_x('cut_socket', 0.95, 1.20, 0.0, 6.52, 0.20, 'ink'))

    # 刻线：真凹槽，深度 0.05 < 该高度壁厚 0.08~0.09 ⇒ 不破坏水密
    boolean(outer, box('cut_line_h', -0.55, 0.55, 0.52, 0.72, 5.02, 5.055))
    boolean(outer, box('cut_line_v', -0.022, 0.022, 0.52, 0.72, 4.94, 5.30))

    bevel(outer, 0.009, 2)
    return outer


def build_chest_internals():
    """腔内机构：主梁 + 肋 ×2 + 液压筒 ×2。座舱凹腔打开后能看见。"""
    parts = []
    parts.append(box('ch_beam', -0.10, 0.10, -0.30, 0.20, 5.90, 6.75, 'frame'))
    for i, x in enumerate((-0.30, 0.30)):
        parts.append(box('ch_rib%d' % i, x - 0.045, x + 0.045,
                         -0.28, 0.16, 5.98, 6.62, 'frame'))
    for i, (d, z) in enumerate(((0.10, 6.30), (0.10, 5.80))):
        parts.append(cyl_x('ch_ram%d' % i, -0.24, 0.24, d, z, 0.055, 'accent'))
    return parts


def build_shoulder():
    """披膊式肩甲：沿 X 扫掠的 8 边形截面，外端下压形成外下角覆盖。

    ★ 第一版用三个正交盒子并集，渲出来读作「三个白盒子叠在一起」——这恰好是
      代码型建模最容易掉的坑：并集不等于造型。改成沿 X 扫掠之后，轮廓是
      「内端贴肩、外端外扩并下压」的一条连续曲面，才是甲片。
    """
    secs = [
        # (x, [(d, z)])  ← rect_ring(中心前深, 中心高, 半深, 半高, 倒角)
        (0.80, rect_ring(0.02, 6.56, 0.30, 0.30, 0.05)),
        (1.10, rect_ring(0.02, 6.60, 0.40, 0.45, 0.07)),
        (1.50, rect_ring(0.04, 6.52, 0.46, 0.53, 0.08)),
        (1.86, rect_ring(0.02, 6.34, 0.38, 0.42, 0.07)),
    ]
    sh = sweep_x('sh_armor', secs, 'armor_w')

    # 铰链通道：沿 X 贯穿甲片中段 ⇒ 真通孔（亏格 +1），轴套从外侧可见
    boolean(sh, box('cut_hinge', 0.72, 1.92, -0.30, 0.30, 6.40, 6.72))

    # 下缘通风槽 ×2：自底面开口 ⇒ 凹口而非通孔，制造遮蔽层次
    for i, (x0, x1) in enumerate(((1.02, 1.28), (1.46, 1.78))):
        boolean(sh, box('cut_louver%d' % i, x0, x1, -0.44, 0.40, 5.94, 6.18))

    # 前缘凹口：让前缘向肩转轴收束，不再是直切边
    boolean(sh, box('cut_front_notch', 0.86, 1.14, 0.30, 0.55, 6.02, 6.30))

    bevel(sh, 0.010, 2, 28)

    # 二级台阶：外主面上贴一片凸出 0.03 的甲板（P3：分缝落在结构边界）
    step = box('sh_step', 1.862, 1.892, -0.26, 0.28, 6.12, 6.74, 'armor_b')
    bevel(step, 0.005, 2, 25)
    return [sh, step]


def build_joint():
    """轴套（真通孔）+ 连杆 + 止口环。轴穿过铰链槽，外侧可见。"""
    axle = cyl_x('sh_axle', 1.24, 1.58, 0.0, 6.52, 0.17, 'frame')
    boolean(axle, cyl_x('cut_bore', 1.18, 1.64, 0.0, 6.52, 0.085, 'ink'))
    bevel(axle, 0.005, 2)

    link = box('sh_link', 1.10, 1.34, -0.14, 0.14, 5.92, 6.50, 'frame')
    collar = cyl_x('sh_collar', 1.56, 1.62, 0.0, 6.52, 0.20, 'accent',
                   n=20)
    boolean(collar, cyl_x('cut_collar', 1.54, 1.64, 0.0, 6.52, 0.11, 'ink'))
    return [axle, link, collar]


def build_uarm():
    """空心锥筒：外放样 − 内放样（壁厚 0.08），再减液压筒安装通孔；
    顶部并一段 φ0.17 插口，穿进肩甲铰链通道 —— 否则臂是「浮」在甲片下面的。"""
    out = loft('uarm', UARM_SECTIONS, 'armor_w', cx=UARM_X)
    ins = []
    for (z, w, zf, zb, c) in UARM_SECTIONS:
        t = 0.08
        ins.append((z, w - t, zf - t, zb + t, c))
    boolean(out, loft('uarm_inner', ins, 'ink', cx=UARM_X))
    # 通孔必须贯穿外壁：槽深 -0.30~0.30 越过 ±0.24 的外表面，否则是盲槽（亏格 0）
    boolean(out, box('cut_ram_slot', 1.44, 1.90, -0.30, 0.30, 5.90, 6.20))

    stub = loft('uarm_stub', [
        (6.48, 0.200, 0.190, -0.190, 0.04),
        (6.60, 0.180, 0.175, -0.175, 0.035),
        (6.72, 0.165, 0.160, -0.160, 0.03),
    ], 'frame', cx=UARM_X)
    boolean(out, stub, 'UNION')

    bevel(out, 0.008, 2)
    return out


# ---------------------------------------------------------------- 骨架
def build_rig(meshes):
    arm_data = bpy.data.armatures.new('SteelRidge_Rig')
    arm = bpy.data.objects.new('SteelRidge_Rig', arm_data)
    bpy.context.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode='EDIT')
    made = {}
    for (name, head, tail, parent) in BONES:
        b = arm_data.edit_bones.new(name)
        b.head = Vector(head)
        b.tail = Vector(tail)
        b.roll = 0.0
        made[name] = b
    for (name, _h, _t, parent) in BONES:
        if parent:
            made[name].parent = made[parent]
    bpy.ops.object.mode_set(mode='OBJECT')
    log('骨架 3 骨：' + ', '.join(b[0] for b in BONES))

    for ob, bone in meshes:
        vg = ob.vertex_groups.new(name=bone)
        vg.add([v.index for v in ob.data.vertices], 1.0, 'REPLACE')
    return arm


def bind_single_mesh(meshes, arm):
    """全部件合并成一个对象 ⇒ Unity 侧 1 个 SkinnedMeshRenderer + 多材质 submesh。"""
    for ob in bpy.context.selected_objects:
        ob.select_set(False)
    for ob, _b in meshes:
        ob.select_set(True)
    body = meshes[0][0]
    bpy.context.view_layer.objects.active = body
    bpy.ops.object.join()
    body.name = 'A0_SAMPLE'
    m = body.modifiers.new('Armature', 'ARMATURE')
    m.object = arm
    body.parent = arm
    body.matrix_parent_inverse = arm.matrix_world.inverted()
    log('合并为单网格 %s · 材质槽 %d · 顶点组 %s' % (
        body.name, len(body.data.materials),
        [g.name for g in body.vertex_groups]))
    return body


# ---------------------------------------------------------------- 出图
def setup_render():
    sc = bpy.context.scene
    for eng in ('BLENDER_EEVEE_NEXT', 'BLENDER_EEVEE', 'BLENDER_WORKBENCH'):
        try:
            sc.render.engine = eng
            break
        except TypeError:
            continue
    sc.render.resolution_x = 1100
    sc.render.resolution_y = 1400
    sc.render.resolution_percentage = 100
    sc.render.film_transparent = False
    sc.view_settings.view_transform = 'Standard'

    world = bpy.data.worlds.new('W')
    sc.world = world
    world.use_nodes = True
    world.node_tree.nodes['Background'].inputs[0].default_value = (0.05, 0.055, 0.06, 1)
    world.node_tree.nodes['Background'].inputs[1].default_value = 1.0

    for nm, loc, rot, energy in (
        ('key', (5.0, -7.0, 9.0), (RAD(52), 0, RAD(36)), 6.0),
        ('fill', (-7.0, -5.0, 5.0), (RAD(72), 0, RAD(-40)), 2.2),
        ('rim', (-3.0, 8.0, 7.0), (RAD(115), 0, RAD(200)), 3.5),
    ):
        lamp = bpy.data.lights.new(nm, 'SUN')
        lamp.energy = energy
        lamp.angle = RAD(12)
        lo = bpy.data.objects.new(nm, lamp)
        lo.location = loc
        lo.rotation_euler = rot
        bpy.context.collection.objects.link(lo)

    cam_data = bpy.data.cameras.new('cam')
    cam_data.type = 'ORTHO'
    cam_data.ortho_scale = 3.5
    cam = bpy.data.objects.new('cam', cam_data)
    bpy.context.collection.objects.link(cam)
    sc.camera = cam
    log('渲染引擎 %s' % sc.render.engine)
    return cam


def shoot(cam, name, azim_deg, elev_deg, scale, target=(1.0, 0.0, 6.0)):
    d = 14.0
    a, e = RAD(azim_deg), RAD(elev_deg)
    cam.location = (
        target[0] + d * math.sin(a) * math.cos(e),
        target[1] - d * math.cos(a) * math.cos(e),
        target[2] + d * math.sin(e),
    )
    cam.rotation_euler = (RAD(90) - e, 0.0, a)
    cam.data.ortho_scale = scale
    bpy.context.scene.render.filepath = os.path.join(OUT, 'view_%s.png' % name)
    bpy.ops.render.render(write_still=True)
    log('出图 view_%s.png' % name)


# ---------------------------------------------------------------- main
def main():
    os.makedirs(OUT, exist_ok=True)
    reset()

    parts = []
    chest = build_chest()
    parts.append((chest, 'chest'))
    for ob in build_chest_internals():
        parts.append((ob, 'chest'))
    sh = build_shoulder()
    for ob in sh:
        parts.append((ob, 'shoulder_L'))
    for ob in build_joint():
        parts.append((ob, 'shoulder_L'))
    ua = build_uarm()
    parts.append((ua, 'shoulder_L'))

    # 逐件统计（合并前量，合并后亏格会被加总而失去意义）
    per_part = [stats(ob) for ob, _b in parts]
    for s in per_part:
        log('统计 %-10s verts=%5d tris=%5d genus=%4.1f islands=%d bnd=%d vol=%.3f' % (
            s['name'], s['verts'], s['tris'], s['genus'], s['islands'],
            s['boundary_edges'], s['volume']))

    arm = build_rig(parts)
    body = bind_single_mesh(parts, arm)
    total = stats(body)

    sections = dict(
        chest=[dict(z=z, half_w=w, front_d=zf, back_d=zb, chamfer=c, wall_t=t)
               for (z, w, zf, zb, c, t) in CHEST_SECTIONS],
        uarm=[dict(z=z, half_w=w, front_d=zf, back_d=zb, chamfer=c)
              for (z, w, zf, zb, c) in UARM_SECTIONS],
        uarm_cx=UARM_X,
        bones=[dict(name=n, head=list(h), tail=list(t), parent=p)
               for (n, h, t, p) in BONES],
        note='Blender Z 上；d 为前深，落顶点时 y=-d。s2 的 Y→Blender Z。',
    )
    with open(os.path.join(OUT, 'sections.json'), 'w') as f:
        json.dump(sections, f, ensure_ascii=False, indent=1)

    cam = setup_render()
    # ★ 侧视从 −X 拍：从 +X 拍时整条上臂正好挡在胸与肩甲前面，等于什么都没看见。
    shoot(cam, 'front', 0, 0, 3.9, (0.50, 0, 6.05))
    shoot(cam, 'side', -90, 0, 3.9, (0.50, 0, 6.05))
    shoot(cam, '35', 35, 12, 4.0, (0.50, 0, 6.05))

    bpy.ops.wm.save_as_mainfile(filepath=BLEND)
    log('保存 %s' % BLEND)

    glb = os.path.join(OUT, 'a0_sample.glb')
    bpy.ops.export_scene.gltf(filepath=glb, export_format='GLB',
                              use_selection=False, export_apply=False,
                              export_yup=True)
    log('导出 %s (%.1f KB)' % (glb, os.path.getsize(glb) / 1024.0))

    fbx = os.path.join(OUT, 'a0_sample.fbx')
    bpy.ops.export_scene.fbx(
        filepath=fbx, use_selection=False,
        object_types={'ARMATURE', 'MESH'},
        apply_scale_options='FBX_SCALE_ALL',
        bake_space_transform=False,
        add_leaf_bones=False, use_mesh_modifiers=False,
        mesh_smooth_type='FACE', global_scale=1.0)
    log('导出 %s (%.1f KB)' % (fbx, os.path.getsize(fbx) / 1024.0))

    report = dict(
        parts=per_part, merged=total,
        booleans=sum(1 for line in LOG if line.startswith('CSG')),
        materials=[m.name for m in body.data.materials],
        vertex_groups=[g.name for g in body.vertex_groups],
        bones=[b[0] for b in BONES],
        log=LOG,
    )
    with open(os.path.join(OUT, 'build.json'), 'w') as f:
        json.dump(report, f, ensure_ascii=False, indent=1)

    print('=' * 78)
    print('A0 样件构建完成 · CSG %d 次 · 合并后 %d tris / %d verts' % (
        report['booleans'], total['tris'], total['verts']))
    print('  bbox  X[%.3f, %.3f]  Y[%.3f, %.3f]  Z[%.3f, %.3f]' % (
        total['bbox'][0][0], total['bbox'][1][0], total['bbox'][0][1],
        total['bbox'][1][1], total['bbox'][0][2], total['bbox'][1][2]))
    print('=' * 78)
    return 0


if __name__ == '__main__':
    sys.exit(main())
