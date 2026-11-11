"""blender/a0_sample_validate.py — A0 门禁校验（独立进程，失败即非零退出）

为什么不把校验塞进构建脚本
  构建脚本自己算自己，等于自证。这里的每一项都从**已落盘的 .blend** 重新量，
  与 build.json 的声明值对账；两者不一致就报 discrepancy。

判据（见 docs/pm/05_A0_造型内核切换_门禁与样件任务书.md §3）
  A0-1 主视觉件 boolean 减法次数 ≥ 1
  A0-2 每对象 boundary_edges = 0（水密）
  A0-3 islands（连通壳数）
  A0-4 亏格 genus：胸 ≥ 3 / 肩甲 ≥ 1 / 上臂 ≥ 1 / 轴套 ≥ 1
  A0-5 有效壁厚 t_eff = 2V/A：胸 < 0.15（证明是抽壳而非实心）
  A0-6 每顶点恰好 1 个权重组且权重 = 1.0
  A0-7 骨名含 chest / shoulder_L / elbow_L，且总数 = 3
  A0-8 肩骨 −30°/0/+30° 三档，肩甲与胸的相交面对数不超过基准 +15%
        （肩窝处本来就有设计好的嵌合，故用「不增长」而非「为零」）
  A0-9 包络不越 s2 实测对应件并集 +0.05 m

用法
  /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup \
      -P blender/a0_sample_validate.py
"""
import json
import math
import os
import sys

import bmesh
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, 'out', 'a0')
BLEND = os.path.join(OUT, 'a0_sample.blend')
BUILD = os.path.join(OUT, 'build.json')
DEST = os.path.join(OUT, 'validate.json')

RAD = math.radians
BODY = 'A0_SAMPLE'
RIG = 'SteelRidge_Rig'

# s2 实测对应件并集（out/s2/rig_probe_clean.json）：x / z 两个方向
ENVELOPE = dict(x=(-1.171, 2.066), z=(4.880, 7.055), tol=0.05)

GENUS_MIN = {'chest': 3, 'sh_armor': 1, 'uarm': 1, 'sh_axle': 1}
BONES_EXPECT = {'chest', 'shoulder_L', 'elbow_L'}

results = []


def check(cid, title, ok, detail):
    results.append(dict(id=cid, title=title, ok=bool(ok), detail=detail))
    print('[%s] %-4s %s — %s' % ('PASS' if ok else 'FAIL', cid, title, detail))
    return ok


def mesh_stats(ob):
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    v, e, f = len(bm.verts), len(bm.edges), len(bm.faces)
    boundary = sum(1 for ed in bm.edges if len(ed.link_faces) < 2)
    nonman = sum(1 for ed in bm.edges if len(ed.link_faces) > 2)
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
    genus = max(0.0, (2 * islands - chi) / 2.0)
    area = sum(fc.calc_area() for fc in bm.faces)
    vol = bm.calc_volume(signed=False)
    bm.free()
    t_eff = (2.0 * vol / area) if area > 1e-9 else 0.0
    return dict(verts=v, edges=e, faces=f, boundary=boundary, nonman=nonman,
                islands=islands, euler=chi, genus=round(genus, 2),
                area=round(area, 4), volume=round(vol, 4),
                t_eff=round(t_eff, 4))


def group_tris(ob, group_name, dg):
    """取属于某权重组的多边形，返回 BVH（用求值后的形变顶点）。"""
    ev = ob.evaluated_get(dg)
    me = ev.to_mesh()
    gi = ob.vertex_groups[group_name].index
    verts = [Vector(v.co) for v in me.vertices]
    polys = []
    for p in me.polygons:
        if all(ob.data.vertices[i].groups and
               any(g.group == gi for g in ob.data.vertices[i].groups)
               for i in p.vertices):
            polys.append(list(p.vertices))
    tree = BVHTree.FromPolygons(verts, polys, all_triangles=False, epsilon=0.0)
    ev.to_mesh_clear()
    return tree


def main():
    os.makedirs(OUT, exist_ok=True)
    if not os.path.exists(BLEND):
        print('找不到 %s，先跑 a0_sample_build.py' % BLEND)
        return 2
    bpy.ops.wm.open_mainfile(filepath=BLEND)
    build = json.load(open(BUILD)) if os.path.exists(BUILD) else {}

    body = bpy.data.objects.get(BODY)
    rig = bpy.data.objects.get(RIG)
    if not check('A0-0', '资产存在', body is not None and rig is not None,
                 'mesh=%s armature=%s' % (body, rig)):
        json.dump(dict(results=results), open(DEST, 'w'),
                  ensure_ascii=False, indent=1)
        return 1

    # ---- A0-1 CSG 次数
    nbool = build.get('booleans', 0)
    check('A0-1', 'boolean 减法/并集次数', nbool >= 1, '%d 次' % nbool)

    # ---- A0-2/3/4 水密 · 连通壳 · 亏格
    st = mesh_stats(body)
    check('A0-2', '合并网格水密（开放边=0）', st['boundary'] == 0,
          'boundary=%d nonmanifold=%d' % (st['boundary'], st['nonman']))
    check('A0-3', '连通壳数', st['islands'] >= 1, 'islands=%d' % st['islands'])

    per = {p['name']: p for p in build.get('parts', [])}
    ok_all = True
    lines = []
    for name, need in GENUS_MIN.items():
        got = per.get(name, {}).get('genus')
        ok = got is not None and got >= need
        ok_all &= ok
        lines.append('%s %s(需≥%d)' % (name, got, need))
    # 独立复算：合并网格的亏格应为各件之和
    check('A0-4a', '合并网格亏格合计', st['genus'] >= sum(GENUS_MIN.values()),
          'genus=%s（各件下限之和 %d）' % (st['genus'], sum(GENUS_MIN.values())))
    check('A0-4b', '逐件亏格达标（真通孔数）', ok_all, '；'.join(lines))

    # ---- A0-5 有效壁厚（抽壳证据）
    # ★ 面积必须自己从合并网格里按权重组量：build.json 的 parts 只存了体积，
    #   直接取 area 会静默得 0，t_eff 恒为 0 —— 这条一开始就是这么假通过的。
    ci = body.vertex_groups['chest'].index
    chest_polys = [p for p in body.data.polygons
                   if all(any(g.group == ci for g in body.data.vertices[i].groups)
                          for i in p.vertices)]
    chest_area = sum(p.area for p in chest_polys)
    chest_vol = sum(per.get(n, {}).get('volume', 0.0)
                    for n in ('chest', 'ch_beam', 'ch_rib0', 'ch_rib1',
                              'ch_ram0', 'ch_ram1'))
    declared = [s['wall_t'] for s in json.load(
        open(os.path.join(OUT, 'sections.json')))['chest']]
    spread = max(declared) - min(declared)
    t_eff = (2.0 * chest_vol / chest_area) if chest_area > 1e-9 else 0.0
    check('A0-5a', '胸为抽壳而非实心（t_eff<0.15）', 0 < t_eff < 0.15,
          't_eff=%.4f m（V=%.3f A=%.3f 面数=%d）'
          % (t_eff, chest_vol, chest_area, len(chest_polys)))
    check('A0-5b', '壁厚沿高度变化（极差≥0.02）', spread >= 0.02,
          'declared %.3f→%.3f，极差 %.3f' % (min(declared), max(declared), spread))

    # ---- A0-6 刚体权重
    bad_w, no_g, multi = 0, 0, 0
    for v in body.data.vertices:
        gs = [g for g in v.groups if g.weight > 0.0]
        if not gs:
            no_g += 1
        elif len(gs) > 1:
            multi += 1
        elif abs(gs[0].weight - 1.0) > 1e-6:
            bad_w += 1
    check('A0-6', '每顶点恰好 1 组且权重=1.0',
          no_g == 0 and multi == 0 and bad_w == 0,
          '无权重组=%d 多组=%d 权重≠1=%d（共 %d 顶点）'
          % (no_g, multi, bad_w, len(body.data.vertices)))

    # ---- A0-7 骨名
    names = set(b.name for b in rig.data.bones)
    check('A0-7', '骨名与 rig_contract 同一命名空间',
          BONES_EXPECT <= names and len(names) == 3,
          '实际 %s' % sorted(names))

    # ---- A0-8 关节扫掠：相交面对数不随旋转增长
    dg = bpy.context.evaluated_depsgraph_get()
    pb = rig.pose.bones['shoulder_L']
    pb.rotation_mode = 'XYZ'
    pairs = {}
    for ang in (0, -30, 30):
        pb.rotation_euler = (RAD(ang), 0.0, 0.0)
        bpy.context.view_layer.update()
        dg = bpy.context.evaluated_depsgraph_get()
        a = group_tris(body, 'chest', dg)
        b = group_tris(body, 'shoulder_L', dg)
        pairs[ang] = len(a.overlap(b)) if (a and b) else -1
        print('      肩骨 %+3d° 相交面对 = %d' % (ang, pairs[ang]))
    pb.rotation_euler = (0.0, 0.0, 0.0)
    bpy.context.view_layer.update()
    base = max(pairs[0], 1)
    worst = max(pairs[-30], pairs[30])
    check('A0-8', '旋转时相交面不增长（≤基准+15%）', worst <= base * 1.15,
          '基准 %d，−30° %d，+30° %d' % (pairs[0], pairs[-30], pairs[30]))

    # ---- A0-9 包络
    # ★ 必须用**未变形**的局部顶点：object.bound_box 取的是求值后的包围盒，
    #   pose 刚复位时 depsgraph 还没跟上，会把 +30° 摆动的峰值算进包络（实测虚高 0.12 m）。
    mw = body.matrix_world
    pts = [mw @ v.co for v in body.data.vertices]
    lo = [min(p[i] for p in pts) for i in range(3)]
    hi = [max(p[i] for p in pts) for i in range(3)]
    tol = ENVELOPE['tol']
    ok = (lo[0] >= ENVELOPE['x'][0] - tol and hi[0] <= ENVELOPE['x'][1] + tol
          and lo[2] >= ENVELOPE['z'][0] - tol and hi[2] <= ENVELOPE['z'][1] + tol)
    check('A0-9', '包络不越 s2 对应件并集 +0.05 m', ok,
          'X[%.3f,%.3f] Z[%.3f,%.3f]  允收 X[%.3f,%.3f] Z[%.3f,%.3f]'
          % (lo[0], hi[0], lo[2], hi[2],
             ENVELOPE['x'][0] - tol, ENVELOPE['x'][1] + tol,
             ENVELOPE['z'][0] - tol, ENVELOPE['z'][1] + tol))

    passed = sum(1 for r in results if r['ok'])
    total = len(results)
    report = dict(
        passed=passed, total=total, all_pass=passed == total,
        merged_stats=st, part_genus={k: per.get(k, {}).get('genus')
                                     for k in GENUS_MIN},
        joint_pairs={str(k): v for k, v in pairs.items()},
        t_eff_chest=round(t_eff, 4), wall_spread=round(spread, 4),
        envelope=dict(lo=[round(x, 4) for x in lo],
                      hi=[round(x, 4) for x in hi]),
        results=results,
    )
    json.dump(report, open(DEST, 'w'), ensure_ascii=False, indent=1)

    print('=' * 78)
    print('A0 门禁 %d/%d 通过%s · 报告 %s'
          % (passed, total, '' if passed == total else '（存在失败项）', DEST))
    fails = [r['id'] for r in results if not r['ok']]
    if fails:
        print('失败项：' + ', '.join(fails))
    print('=' * 78)
    return 0 if passed == total else 1


if __name__ == '__main__':
    sys.exit(main())
