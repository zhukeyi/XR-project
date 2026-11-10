"""tools/export_viewer_bin.py — 把机体导出成 Android 查看器用的紧凑二进制

为什么不用 glTF/OBJ 直接读
  Java 侧解析 GLB 要写 accessor/bufferView 解码，解析 OBJ 要处理 31 MB 文本 +
  MTL + 贴图，都不划算。查看器只需要「顶点 + 法线 + 索引 + 每件颜色」，
  所以导成一个定长头 + 两个连续数组，Java 侧 30 行就能读。

格式（小端）
  magic        4s   'SPV1'
  partCount    u32
  vertexCount  u32
  indexCount   u32
  center       3f   包围盒中心（米）
  size         3f   包围盒尺寸（米）
  --- partCount × 60 字节 ---
  name         32s  分件名（UTF-8，截断到 31 字节）
  rgb          3f   平色（0-1）
  voff         u32  顶点起始（顶点为单位）
  vcnt         u32
  ioff         u32  索引起始
  icnt         u32
  --- 顶点区 ---
  vertexCount × 6f  x,y,z,nx,ny,nz
  --- 索引区 ---
  indexCount × u32  三角形列表（全局顶点索引）

输出
  android-viewer/assets/hx07.bin
  android-viewer/assets/hx07.meta.json   供报告与校验用

用法
  python3 tools/export_viewer_bin.py
"""
import json
import os
import struct
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import mecha_model as M            # noqa: E402
import r3d                         # noqa: E402
from gfx import mesh as GM         # noqa: E402

OUTDIR = os.path.join(ROOT, 'android-viewer', 'assets')
MAGIC = b'SPV1'


def collect(hatch=1.0):
    """按节点收集（世界坐标），每件保留自己的平色。"""
    root = M.build_mecha({'rifle_on': True, 'saber_on': 0.0, 'hatch': hatch})
    parts = []

    def rec(n):
        if n.prim is not None and not n.hide:
            m = GM.Mesh()
            GM.prim_to_tris(m, n.prim[0], n.prim[1], n.world(), n.mat, smooth=n.smooth)
            if len(m.P):
                P = np.array(m.P, np.float32).reshape(-1, 3)
                Nn = np.array(m.N, np.float32).reshape(-1, 3)
                parts.append((n.name, np.array(n.mat.rgb, np.float32), P, Nn))
        for c in n.children:
            rec(c)

    rec(root)
    return parts


def main():
    parts = collect()
    os.makedirs(OUTDIR, exist_ok=True)

    verts = np.concatenate([np.hstack([P, Nn]) for _, _, P, Nn in parts], 0).astype('<f4')
    idx = []
    off = 0
    for _, _, P, _ in parts:
        n = len(P)
        idx.append(np.arange(off, off + n, dtype='<u4'))
        off += n
    idx = np.concatenate(idx, 0)

    allP = verts[:, :3]
    center = (allP.min(0) + allP.max(0)) / 2
    size = allP.max(0) - allP.min(0)

    buf = bytearray()
    buf += MAGIC
    buf += struct.pack('<III', len(parts), len(verts), len(idx))
    buf += struct.pack('<3f', *center)
    buf += struct.pack('<3f', *size)

    voff = 0
    ioff = 0
    meta_parts = []
    for name, rgb, P, _ in parts:
        nb = name.encode('utf-8')[:31]
        buf += nb + b'\x00' * (32 - len(nb))
        buf += struct.pack('<3f', *rgb)
        buf += struct.pack('<IIII', voff, len(P), ioff, len(P))
        meta_parts.append({'name': name, 'rgb': [round(float(c), 3) for c in rgb],
                           'verts': int(len(P))})
        voff += len(P)
        ioff += len(P)

    buf += verts.tobytes()
    buf += idx.tobytes()

    path = os.path.join(OUTDIR, 'hx07.bin')
    with open(path, 'wb') as f:
        f.write(buf)

    meta = {
        'parts': len(parts),
        'vertices': int(len(verts)),
        'triangles': int(len(idx) // 3),
        'bbox_center_m': [round(float(x), 4) for x in center],
        'bbox_size_m': [round(float(x), 4) for x in size],
        'bytes': len(buf),
        'part_list': meta_parts,
    }
    with open(os.path.join(OUTDIR, 'hx07.meta.json'), 'w') as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)

    print('=' * 62)
    print('查看器网格导出 · %s' % path)
    print('=' * 62)
    print('  分件   %d' % meta['parts'])
    print('  顶点   %d' % meta['vertices'])
    print('  三角   %d' % meta['triangles'])
    print('  包围盒 %.2f × %.2f × %.2f m' % tuple(meta['bbox_size_m']))
    print('  文件   %.1f KB' % (len(buf) / 1024))
    print('  头信息 4 + 12 + 24 + %d×60 = %d 字节，总长 %d'
          % (len(parts), 4 + 12 + 24 + len(parts) * 60, len(buf)))


if __name__ == '__main__':
    main()
