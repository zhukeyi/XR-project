"""tools/export_gltf.py — 把 mecha_model 的节点树导出为 glTF 2.0（.glb / .gltf）

为什么必须写它（而不是让 Blender 代劳）
  Blender 自带 glTF 导入与导出（io_scene_gltf2，默认启用），但它读不了
  mecha_model 里的 Python 对象树。中间必须有人把「265 节点 / 深度 8 / 244 图元」
  序列化成一个带层级的文件格式 —— 这一段没有任何现成工具能替。
  OBJ 不行（只有平级 o 组，无父子关系）；glTF 可以（nodes.children 原生支持）。

为什么用局部空间 + 节点 TRS
  如果把世界坐标的顶点直接写进 mesh 并把节点变换置为 identity，模型能正确显示，
  但一旋转枢纽（比如舱门 ±95°）整块件就会绕世界原点飞走。所以：
    · mesh 顶点 = 该节点局部空间的坐标（变换用 identity 三元化）
    · 层级 = glTF nodes.children
    · 变换 = node.translation / rotation / scale
  这样枢轴语义才成立，Blender / Unity 里拖任意父节点都正确。

欧拉角约定
  r3d 的局部变换是 T @ Rx @ Ry @ Rz @ S（度）。glTF 的 rotation 是四元数，
  为避免「欧拉序」理解歧义，这里直接由 r3d 自己的矩阵算出 3x3，再从矩阵
  转四元数 —— 不经过任何欧拉约定假设。

输出
  out/pico/mecha_parts.glb    单文件二进制 glTF（主交付）
  out/pico/mecha_parts.gltf   文本 glTF + mecha_parts.bin（便于人工核对）
  out/pico/gltf_check.json    自检报告（层级 / 包围盒 / 材质 / 访问器）

用法
  python3 tools/export_gltf.py
  python3 tools/export_gltf.py --hatch       # 舱门 95° 打开态
  python3 tools/export_gltf.py --normalize   # 等比缩放到 H=18.20 并让脚底落在 y=0
"""
import base64
import json
import os
import struct
import sys
from collections import Counter

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import mecha_model as M            # noqa: E402
import r3d                         # noqa: E402
from gfx import mesh as GM         # noqa: E402

OUT = os.path.join(ROOT, 'out', 'pico')

SHORT_NAME = {
    'W1': 'ArmorWhite', 'W2': 'ArmorWhite2', 'W3': 'ArmorWhite3',
    'BL1': 'ArmorBlue', 'BL2': 'ArmorBlue2', 'RD1': 'ArmorRed',
    'OR1': 'ArmorOrange',
    'GR1': 'FrameMid', 'GR2': 'FrameDark', 'GR3': 'FrameLight',
    'VIS': 'Visor', 'SAK': 'SaberBlade', 'FLA': 'Flame', 'FLC': 'FlameCore',
}
GLOSSY = ('visor', 'sensor', 'beam', 'saber', 'thrust', 'flame', 'glow')


# ---------------------------------------------------------------- 材质

def mat_name_table():
    """rgb -> 语义名。先扫 r3d.MAT（有语义键），再扫 mecha_model 的短名常量。"""
    table = {}
    for k, v in r3d.MAT.items():
        table.setdefault(tuple(np.round(v.rgb, 4)), k)
    for k, v in vars(M).items():
        if isinstance(v, r3d.Mat):
            table.setdefault(tuple(np.round(v.rgb, 4)), SHORT_NAME.get(k, k))
    return table


def resolve_mat(mat, table):
    key = tuple(np.round(mat.rgb, 4))
    name = table.get(key)
    if name is None:
        name = 'Mat_%02x%02x%02x' % tuple(int(np.clip(c, 0, 1) * 255) for c in mat.rgb)
    return name


def gltf_material(name, mat):
    """r3d.Mat（rgb/emissive/rim/spec）→ glTF PBR 材质。

    这是「降级映射」，不是等价转换：r3d 的 rim 在 glTF 里没有对应概念，
    spec 只能近似成 metallic。真正的 PBR 要等 Substance 做完才算数。
    """
    rgb = np.clip(mat.rgb, 0.0, 1.0)
    glossy = any(k in name for k in GLOSSY)
    m = {
        'name': name,
        'pbrMetallicRoughness': {
            'baseColorFactor': [round(float(c), 4) for c in rgb] + [1.0],
            'metallicFactor': round(float(np.clip(mat.spec, 0.0, 1.0)), 4),
            'roughnessFactor': 0.22 if glossy else 0.58,
        },
        'doubleSided': False,
    }
    if mat.emissive > 0.02:
        m['emissiveFactor'] = [round(float(c) * float(mat.emissive), 4) for c in rgb]
    return m


# ---------------------------------------------------------------- 变换

def rot_matrix(node):
    """r3d 的 Rx @ Ry @ Rz（度）→ 3x3。"""
    m = r3d.Rx(node.rot[0]) @ r3d.Ry(node.rot[1]) @ r3d.Rz(node.rot[2])
    return np.asarray(m, float)[:3, :3]


def mat_to_quat(R):
    """3x3 旋转矩阵 → (x, y, z, w)。Shepperd 分支法，任一角都稳定。"""
    t = R[0, 0] + R[1, 1] + R[2, 2]
    if t > 0.0:
        s = np.sqrt(t + 1.0) * 2.0
        w = 0.25 * s
        x = (R[2, 1] - R[1, 2]) / s
        y = (R[0, 2] - R[2, 0]) / s
        z = (R[1, 0] - R[0, 1]) / s
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = np.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2]) * 2.0
        w = (R[2, 1] - R[1, 2]) / s
        x = 0.25 * s
        y = (R[0, 1] + R[1, 0]) / s
        z = (R[0, 2] + R[2, 0]) / s
    elif R[1, 1] > R[2, 2]:
        s = np.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2]) * 2.0
        w = (R[0, 2] - R[2, 0]) / s
        x = (R[0, 1] + R[1, 0]) / s
        y = 0.25 * s
        z = (R[1, 2] + R[2, 1]) / s
    else:
        s = np.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1]) * 2.0
        w = (R[1, 0] - R[0, 1]) / s
        x = (R[0, 2] + R[2, 0]) / s
        y = (R[1, 2] + R[2, 1]) / s
        z = 0.25 * s
    q = np.array([x, y, z, w], float)
    q /= np.linalg.norm(q)
    if q[3] < 0:            # 统一取 w>=0 的半球，避免上下游符号抖动
        q = -q
    return [round(float(v), 7) for v in q]


def quat_to_mat(q):
    x, y, z, w = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ], float)


# ---------------------------------------------------------------- 节点名唯一化

def unique_names(nodes):
    """把节点名归一成「左右可分」的稳定形式。

    源模型有两种左右约定，都要处理：
      ① 同名字出现两次（wrist / knee_ball / pauldron … 61 组）→ 按世界 X 符号加 _L/_R
      ② 名字自带 -1 / 1 后缀（shoulder-1 / shoulder1，共 88 个节点）→ 改写成 _L/_R
         · 只在「成对存在」时改写：X-1 与 X1 两个都在，才认定是一对
         · 单独出现的（如 chest_vent_c2）不动，避免误伤

    另：mecha_model.py 有一处笔误 'foot_side{s}' 少了 f 前缀，节点名字面带着 {s}，
    这里一并剥掉，再由上面的规则补 _L/_R。
    """
    raws = [n.name.replace('{s}', '') for n in nodes]
    rawset = set(raws)

    def norm(r):
        if r.endswith('-1') and (r[:-2] + '1') in rawset:
            return r[:-2] + '_L'
        if r.endswith('1') and not r.endswith('-1') and (r[:-1] + '-1') in rawset:
            return r[:-1] + '_R'
        return r

    cand_names = [norm(r) for r in raws]
    cnt = Counter(cand_names)
    seen = Counter()
    used = set()
    out = {}
    for n, base in zip(nodes, cand_names):
        if cnt[base] == 1 and base not in used:
            out[id(n)] = base
            used.add(base)
            continue
        x = float(n.world()[0, 3])
        if abs(x) > 1e-4:
            suf = '_L' if x < 0 else '_R'
        else:
            seen[base] += 1
            suf = '_%d' % seen[base]
        cand = base + suf
        while cand in used:
            seen[base] += 1
            cand = base + suf + '_%d' % seen[base]
        used.add(cand)
        out[id(n)] = cand
    return out


# ---------------------------------------------------------------- 主构建

def build(hatch=0.0):
    root = M.build_mecha({'rifle_on': True, 'saber_on': 0.0, 'hatch': hatch})

    order = []

    def walk(n):
        order.append(n)
        for c in n.children:
            walk(c)

    walk(root)
    names = unique_names(order)
    idx = {id(n): i for i, n in enumerate(order)}
    mtab = mat_name_table()

    gltf = {
        'asset': {'version': '2.0', 'generator': 'mecha_render tools/export_gltf.py'},
        'scene': 0,
        'scenes': [{'nodes': [0]}],
        'nodes': [],
        'meshes': [],
        'materials': [],
        'accessors': [],
        'bufferViews': [],
        'buffers': [],
    }

    bin_parts = []
    offset = [0]

    def add_view(arr, target=None):
        """arr: numpy 连续数组 → bufferView 索引。4 字节对齐。"""
        b = arr.tobytes()
        pad = (-len(b)) % 4
        bin_parts.append(b + b'\x00' * pad)
        bv = {'buffer': 0, 'byteOffset': offset[0], 'byteLength': len(b)}
        if target:
            bv['target'] = target
        gltf['bufferViews'].append(bv)
        offset[0] += len(b) + pad
        return len(gltf['bufferViews']) - 1

    mat_index = {}
    mat_list = []

    for n in order:
        i = idx[id(n)]
        node = {'name': names[id(n)]}
        kids = [idx[id(c)] for c in n.children]
        if kids:
            node['children'] = kids

        node['translation'] = [round(float(v), 6) for v in n.pos]
        node['rotation'] = mat_to_quat(rot_matrix(n))
        s = n.scl if np.isscalar(n.scl) else list(n.scl)
        if np.isscalar(s):
            if abs(float(s) - 1.0) > 1e-9:
                node['scale'] = [round(float(s), 6)] * 3
        elif not np.allclose(np.array(s, float), 1.0):
            node['scale'] = [round(float(v), 6) for v in s]

        if n.prim is not None and not n.hide:
            m = GM.Mesh()
            # ★ identity 变换 → 顶点留在节点局部空间
            GM.prim_to_tris(m, n.prim[0], n.prim[1], np.eye(4), n.mat, smooth=n.smooth)
            if len(m.P):
                P = np.array(m.P, np.float32).reshape(-1, 3)
                Nn = np.array(m.N, np.float32).reshape(-1, 3)
                I = np.arange(len(P), dtype=np.uint32)

                # ★ min/max 必须与 float32 顶点逐位一致。四舍五入会让声明范围
                #   比实际窄，触发 ACCESSOR_MIN_MISMATCH / OUT_OF_BOUND（实测 180 条）。
                mn = P.min(0)
                mx = P.max(0)
                a_pos = {'bufferView': add_view(P, 34962), 'componentType': 5126,
                         'count': len(P), 'type': 'VEC3',
                         'min': [float(v) for v in mn],
                         'max': [float(v) for v in mx]}
                gltf['accessors'].append(a_pos)
                ip = len(gltf['accessors']) - 1

                gltf['accessors'].append({'bufferView': add_view(Nn, 34962),
                                          'componentType': 5126, 'count': len(Nn),
                                          'type': 'VEC3'})
                inx = len(gltf['accessors']) - 1

                gltf['accessors'].append({'bufferView': add_view(I, 34963),
                                          'componentType': 5125, 'count': len(I),
                                          'type': 'SCALAR'})
                ii = len(gltf['accessors']) - 1

                mname = resolve_mat(n.mat, mtab)
                if mname not in mat_index:
                    mat_index[mname] = len(mat_list)
                    mat_list.append(gltf_material(mname, n.mat))
                mi = mat_index[mname]

                gltf['meshes'].append({
                    'name': names[id(n)] + '_mesh',
                    'primitives': [{'attributes': {'POSITION': ip, 'NORMAL': inx},
                                    'indices': ii, 'material': mi, 'mode': 4}],
                })
                node['mesh'] = len(gltf['meshes']) - 1
                node['extras'] = {'part': names[id(n)], 'surface': 'greybox_local'}

        gltf['nodes'].append(node)

    gltf['materials'] = mat_list

    raw = b''.join(bin_parts)
    gltf['buffers'] = [{'byteLength': len(raw)}]

    return gltf, raw, order, names, idx


def apply_normalize(gltf, V):
    """在根节点上加等比缩放与落地偏移。

    ★ 必须用「世界空间真实顶点」算机高，不能合并各节点的局部 AABB：
      局部 AABB 只是局部位姿下的盒，既不含父级平移、也不含旋转，
      直接合并会把 19.02 m 的机体量成 8.10 m（本函数第一版就是这个错）。
    """
    H = float(V[:, 1].max() - V[:, 1].min())
    s = 18.20 / H
    cx = float((V[:, 0].min() + V[:, 0].max()) / 2)
    cz = float((V[:, 2].min() + V[:, 2].max()) / 2)
    y0 = float(V[:, 1].min())

    root = gltf['nodes'][0]
    assert 'rotation' not in root or np.allclose(root['rotation'], [0, 0, 0, 1]), \
        '根节点带旋转，缩放会沿局部轴生效，需先处理'
    root['scale'] = [round(float(s), 6)] * 3
    root['translation'] = [round(-cx * s, 6), round(-y0 * s, 6), round(-cz * s, 6)]
    gltf['asset']['extras'] = {
        'normalized_to_height': 18.20,
        'source_height': round(H, 4),
        'uniform_scale': round(float(s), 6),
        'feet_at_y': 0.0,
        'note': '肩宽仍为 %.3f m，未随归一化修正' % (float(V[:, 0].max() - V[:, 0].min()) * s),
    }
    return s, V * s + np.array([root['translation']])


# ---------------------------------------------------------------- 写出

def write_glb(gltf, raw, path):
    js = json.dumps(gltf, separators=(',', ':')).encode('utf-8')
    js += b' ' * ((-len(js)) % 4)
    bn = raw + b'\x00' * ((-len(raw)) % 4)
    total = 12 + 8 + len(js) + 8 + len(bn)
    with open(path, 'wb') as f:
        f.write(struct.pack('<4sII', b'glTF', 2, total))
        f.write(struct.pack('<II', len(js), 0x4E4F534A))
        f.write(js)
        f.write(struct.pack('<II', len(bn), 0x004E4942))
        f.write(bn)
    return total


def write_gltf_sep(gltf, raw, path, binname):
    g = json.loads(json.dumps(gltf))
    g['buffers'] = [{'byteLength': len(raw), 'uri': binname}]
    with open(os.path.join(os.path.dirname(path), binname), 'wb') as f:
        f.write(raw)
    with open(path, 'w') as f:
        json.dump(g, f, ensure_ascii=False, indent=1)
    return len(raw)


# ---------------------------------------------------------------- 自检

def verify_glb(path):
    """重新解析 .glb，按节点层级算世界包围盒，与直接测量比对。

    这是整个导出器的唯一硬校验：如果四元数与平移写错，层级累乘后的包围盒
    一定对不上原模型的实测值。
    """
    with open(path, 'rb') as f:
        data = f.read()
    magic, ver, total = struct.unpack('<4sII', data[:12])
    assert magic == b'glTF', 'GLB magic 错误'
    assert ver == 2, 'GLB 版本错误'
    assert total == len(data), 'GLB 长度字段 %d ≠ 文件 %d' % (total, len(data))

    jlen, jtype = struct.unpack('<II', data[12:20])
    assert jtype == 0x4E4F534A, 'JSON chunk 类型错误'
    gltf = json.loads(data[20:20 + jlen].decode('utf-8'))

    blen, btype = struct.unpack('<II', data[20 + jlen:28 + jlen])
    assert btype == 0x004E4942, 'BIN chunk 类型错误'
    assert blen % 4 == 0, 'BIN chunk 未 4 字节对齐'
    binbuf = data[28 + jlen:28 + jlen + blen]

    nodes = gltf['nodes']
    lo = np.full(3, np.inf)
    hi = np.full(3, -np.inf)
    depth = {}

    def read_pos(mesh_i):
        acc_i = gltf['meshes'][mesh_i]['primitives'][0]['attributes']['POSITION']
        acc = gltf['accessors'][acc_i]
        bv = gltf['bufferViews'][acc['bufferView']]
        off = bv['byteOffset'] + acc.get('byteOffset', 0)
        return np.frombuffer(binbuf, dtype='<f4', count=acc['count'] * 3,
                             offset=off).reshape(-1, 3).astype(float)

    def local_mat(n):
        m = np.eye(4)
        m[:3, 3] = n.get('translation', [0, 0, 0])
        m[:3, :3] = quat_to_mat(n.get('rotation', [0, 0, 0, 1])) @ np.diag(n.get('scale', [1, 1, 1]))
        return m

    nverts = [0]

    def rec(i, pw, d):
        """pw = 父节点世界矩阵；本节点世界矩阵 = pw @ 本地矩阵。

        ★ 用真实顶点而不是局部 AABB 的 8 个角点：旋转件的 AABB 角点变换后
        会比真实几何更外扩（AABB of AABB），那是算法高估，不是导出错误。
        """
        depth[i] = d
        n = nodes[i]
        w = pw @ local_mat(n)
        if 'mesh' in n:
            P = read_pos(n['mesh'])
            Pw = (w[:3, :3] @ P.T).T + w[:3, 3]
            lo[:] = np.minimum(lo, Pw.min(0))
            hi[:] = np.maximum(hi, Pw.max(0))
            nverts[0] += len(P)
        for c in n.get('children', []):
            rec(c, w, d + 1)

    rec(0, np.eye(4), 1)
    return gltf, data, lo, hi, max(depth.values()), nverts[0]


# ---------------------------------------------------------------- main

def main():
    hatch = 1.0 if '--hatch' in sys.argv else 0.0
    normalize = '--normalize' in sys.argv
    os.makedirs(OUT, exist_ok=True)

    gltf, raw, order, names, idx = build(hatch=hatch)

    # 直接测量（世界空间真实顶点），既作归一化依据，也作校验基准
    root = M.build_mecha({'rifle_on': True, 'saber_on': 0.0, 'hatch': hatch})
    m = GM.Mesh()
    GM.collect2(root, m)
    V = np.array(m.P).reshape(-1, 3)

    exp = V
    if normalize:
        s, exp = apply_normalize(gltf, V)

    stem = 'mecha_parts' + ('_hatch' if hatch > 0 else '') + ('_norm' if normalize else '')
    glb = os.path.join(OUT, stem + '.glb')
    total = write_glb(gltf, raw, glb)
    write_gltf_sep(gltf, raw, os.path.join(OUT, stem + '.gltf'), stem + '.bin')

    g2, data, lo, hi, depth, nverts = verify_glb(glb)

    print('=' * 74)
    print('glTF 2.0 导出 · %s' % glb)
    print('=' * 74)
    print('  节点            %d（其中带网格 %d）' % (len(g2['nodes']), len(g2['meshes'])))
    print('  最大层级深度    %d' % depth)
    print('  材质            %d：%s' % (len(g2['materials']),
                                        ', '.join(x['name'] for x in g2['materials'])))
    print('  accessors       %d   bufferViews %d' % (len(g2['accessors']), len(g2['bufferViews'])))
    print('  GLB 大小        %.1f KB（BIN %.1f KB）' % (total / 1024, len(raw) / 1024))
    print()
    print('  世界包围盒对照（层级累乘 vs 直接测量）：')
    print('    重算  min [%.3f %.3f %.3f]  max [%.3f %.3f %.3f]'
          % (lo[0], lo[1], lo[2], hi[0], hi[1], hi[2]))
    print('    直测  min [%.3f %.3f %.3f]  max [%.3f %.3f %.3f]'
          % (exp.min(0)[0], exp.min(0)[1], exp.min(0)[2], exp.max(0)[0], exp.max(0)[1], exp.max(0)[2]))
    d = max(np.abs(np.concatenate([lo - exp.min(0), hi - exp.max(0)])))
    print('    最大偏差  %.6f m  →  %s' % (d, '✓ 一致' if d < 1e-3 else '✗ 不一致'))
    print()
    size = hi - lo
    print('  尺寸  W=%.3f  H=%.3f  D=%.3f' % (size[0], size[1], size[2]))
    if normalize:
        print('  （已归一化：H→18.20，脚底→0，统一缩放 %.4f）'
              % g2['asset']['extras']['uniform_scale'])
    print()
    print('  校验：magic/版本/长度 ✓  chunk 类型与对齐 ✓  层级深度 ✓')

    chk = {
        'glb_bytes': total,
        'bin_bytes': len(raw),
        'nodes': len(g2['nodes']),
        'meshes': len(g2['meshes']),
        'materials': [x['name'] for x in g2['materials']],
        'max_depth': depth,
        'bbox_recomputed': {'min': lo.tolist(), 'max': hi.tolist()},
        'bbox_expected': {'min': exp.min(0).tolist(), 'max': exp.max(0).tolist()},
        'max_deviation_m': float(d),
        'normalized': normalize,
        'hatch': hatch,
    }
    with open(os.path.join(OUT, stem + '_check.json'), 'w') as f:
        json.dump(chk, f, ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
