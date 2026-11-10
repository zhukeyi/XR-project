"""tools/unicorn_trunk.py — 把外部 Unicorn 参考模型剥成「只剩机体主干」

为什么要有这个文件
  §26 剥的是**我们自己**的模型。但「剥掉枝枝叶叶之后主干该长什么样」这个问题的
  答案不在我们模型里，而在 Unicorn 的模型里 —— 得先把**它**剥干净，才有一把尺子。

  `ref_assets/source/UNICORN_GUNDAM_OBJ.obj` 是 3ds Max 导出的生产模型，
  189,593 三角，按 `*_assy_G` 分好组。它的「外挂」很明确：

      back_pack_assy_G            背包本体 + 挂在背包上的军刀座 / 上下翻板 / 推进器
      shoulder_guns_assy_G        胸部两侧 60 mm 火神炮
      rear_waist_thruster_assy_G  后腰推进器
      leg_thruster_assy_G         小腿推进器
      leg_fins_assy_G             小腿鳍（可选，默认保留 —— 它是腿部造型语言的一部分）

它做四件事
  1. 按 `g` 行给每个面打**装配标签**（OBJ 的 g 是一行一组，后一行覆盖前一行）；
  2. 输出「原素材 / 主干」两套三角，**共用同一份归一化**（否则两张图不能比）；
  3. 出 4 视角对照图（正 / 3-4 / 侧 / 背），同一机位同一光照；
  4. 量每个装配的 bbox，给出**主干的比例尺**：
     头高/总高、肩宽/总高、腰宽/肩宽、腿长/总高、胸深/肩宽、W/H、D/W。

单位约定
  原始 OBJ 厘米、Y 上。统一归一化到「机高 = 10、脚底 y = 0、+z 朝观察者」，
  与 refview.py / relief_v2 的 world 尺度一致。**两张图共用 full 的归一化**，
  所以主干版会比原素材矮一点点——那正是被剥掉的部分，不是缩放错误。

用法
  python3 tools/unicorn_trunk.py            # 出对照图 + 比例表
  python3 tools/unicorn_trunk.py --fins      # 连 leg_fins 也剥掉（更激进的主干）
"""
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'tools'))

import refview as RV                                     # noqa: E402

SRC = os.path.join(HERE, 'ref_assets', 'source', 'UNICORN_GUNDAM_OBJ.obj')
OUT = os.path.join(HERE, 'out', 'ref')
FONT = '/System/Library/Fonts/Hiragino Sans GB.ttc'

# 剥掉的东西：每一条都要能说清「为什么它是外挂而不是主干」
REMOVE = {
    'back_pack_assy_G': '背包本体（含军刀座/上下翻板/推进器）—— 挂在后背，剥掉后躯干自洽',
    'shoulder_guns_assy_G': '胸部两侧 60 mm 火神炮 —— 独立武器，装在胸上',
    'rear_waist_thruster_assy_G': '后腰推进器 —— 向后凸出的独立推力单元',
    'leg_thruster_assy_G': '小腿推进器 —— 挂在腿后侧的独立件',
}
REMOVE_STRICT = {'leg_fins_assy_G': '小腿鳍 —— 腿部造型的一部分，默认保留；--fins 时一并剥'}


# ---------------------------------------------------------------- 读 OBJ（带装配标签）
def load_obj_grouped(path):
    """返回 (V, tris, gid_of_face, gid→tokens)。

    ★ OBJ 的 `g` 是**一行一组**：后一个 g 行**覆盖**前一个，不是追加。
      这个文件里每个几何块前面都是 `g default` 再 `g <真实路径>` 两行，
      所以取「最近一个不含 default 的 g 行」才是这块的真实装配路径。
    """
    V = []
    tris = []
    gf = []
    sets = []
    ids = {}
    cur = -1
    with open(path, 'r', errors='ignore') as f:
        for line in f:
            if line.startswith('v '):
                p = line.split()
                V.append((float(p[1]), float(p[2]), float(p[3])))
            elif line.startswith('g '):
                toks = frozenset(t for t in line.split()[1:] if t != 'default')
                if not toks:
                    continue                    # `g default` 是分隔符，不改变归属
                if toks not in ids:
                    ids[toks] = len(sets)
                    sets.append(toks)
                cur = ids[toks]
            elif line.startswith('f '):
                idx = []
                for tok in line.split()[1:]:
                    s = tok.split('/')[0]
                    if not s:
                        continue
                    i = int(s)
                    idx.append(i - 1 if i > 0 else len(V) + i)
                for k in range(1, len(idx) - 1):
                    tris.append((idx[0], idx[k], idx[k + 1]))
                    gf.append(cur)
    return np.array(V, np.float64), np.array(tris, np.int64), np.array(gf, np.int64), sets


def face_in(gf, sets, token):
    out = np.zeros(len(gf), bool)
    for i, toks in enumerate(sets):
        if token in toks:
            out |= (gf == i)
    return out


def assembly_bbox(V, tris, gf, sets, token):
    m = face_in(gf, sets, token)
    if not m.any():
        return None
    v = np.unique(tris[m].ravel())
    return V[v].min(0), V[v].max(0), int(m.sum())


# ---------------------------------------------------------------- 出图
def panel_grid(panels, labels, out, title, sub):
    gap, hdr, lb = 8, 96, 26
    h, w = panels[0][0].shape[:2]
    W = gap + (w + gap) * len(panels[0])
    H = hdr + sum((lb + h + gap) for _ in panels)
    cv = Image.new('RGB', (W, H), (255, 255, 255))
    d = ImageDraw.Draw(cv)
    d.text((gap + 4, 12), title, font=ImageFont.truetype(FONT, 26), fill=(24, 24, 24))
    yy = 46
    for line in sub.split('\n'):
        d.text((gap + 4, yy), line, font=ImageFont.truetype(FONT, 16), fill=(104, 104, 104))
        yy += 22
    y = hdr
    for row, lab in zip(panels, labels):
        d.text((gap + 4, y + 2), lab, font=ImageFont.truetype(FONT, 20), fill=(20, 20, 20))
        for k, p in enumerate(row):
            cv.paste(Image.fromarray(p), (gap + k * (w + gap), y + lb))
        y += lb + h + gap
    cv.save(out)
    return out, cv.size


def main():
    strict = '--fins' in sys.argv
    rem = dict(REMOVE)
    if strict:
        rem.update(REMOVE_STRICT)

    print('读入 %s' % os.path.basename(SRC))
    V, tris, gf, sets = load_obj_grouped(SRC)
    print('  %d 顶点 / %d 三角 / %d 个装配标签' % (len(V), len(tris), len(sets)))

    # ★ 归一化只用 full 的 bbox，两块共用 —— 这样两张图的缩放与站位完全一致
    Vn, meta = RV.normalize(V)
    print('  原始高 %.1f cm → 归一到 %.0f；宽 %.3f 深 %.3f（H=10 世界单位）'
          % (meta['raw_height'], RV.H_WORLD, meta['width'], meta['depth']))

    keep = np.ones(len(tris), bool)
    removed = []
    for tok, why in rem.items():
        m = face_in(gf, sets, tok)
        if m.any():
            keep &= ~m
            removed.append((tok, int(m.sum()), why))
    print('\n剥掉的装配：')
    for tok, n, why in removed:
        print('  - %-30s %6d 三角   %s' % (tok, n, why))
    print('  剩余 %d / %d 三角（%.1f%%）'
          % (keep.sum(), len(tris), 100.0 * keep.sum() / len(tris)))

    # 两套 mesh，共用 Vn
    full = RV._to_mesh(Vn, tris)
    trk = RV._to_mesh(Vn, tris[keep])

    views = [('front', 0.0), ('q35', 35.0), ('side', 90.0), ('back', 180.0)]
    rows, labels = [], []
    for name, mesh in (('原素材', full), ('主干', trk)):
        row = []
        for vn, yaw in views:
            img, _ = RV.render_view(mesh, yaw)
            row.append(img)
        rows.append(row)
        labels.append('%s %s' % ('A' if name == '原素材' else 'B', name))
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, 'unicorn_trunk.png')
    p, size = panel_grid(
        rows, labels, p,
        'Unicorn 参考模型：剥掉外挂只留主干',
        '同一机位 / 同一光照 / 同一归一化 —— 两行共用 full 的缩放，剥掉的体量如实体现，\n'
        '不重新放大。A 原素材（含背包 / 肩炮 / 后腰·小腿推进器）   B 主干（剥掉 4 组装配）')
    print('\n→ %s  %d × %d' % (p, size[0], size[1]))

    # ------------------------------------------------------------ 比例尺
    asm = {}
    for tok in ('head_assy_G', 'V_fins_G', 'body_assy_G', 'waist_assy_G',
                'shoulder_armor_assy_G', 'r_arm_assy_G', 'r_leg_assy_G',
                'back_pack_assy_G', 'feet_assy_G'):
        b = assembly_bbox(Vn, tris, gf, sets, tok)
        if b:
            lo, hi, n = b
            asm[tok] = dict(
                x=[round(float(lo[0]), 3), round(float(hi[0]), 3)],
                y=[round(float(lo[1]), 3), round(float(hi[1]), 3)],
                z=[round(float(lo[2]), 3), round(float(hi[2]), 3)],
                w=round(float(hi[0] - lo[0]), 3),
                h=round(float(hi[1] - lo[1]), 3),
                d=round(float(hi[2] - lo[2]), 3),
                tris=n)

    def bb(mask):
        if not mask.any():
            return None
        v = np.unique(tris[mask].ravel())
        return Vn[v].min(0), Vn[v].max(0)

    trk_mask = keep
    full_mask = np.ones(len(tris), bool)
    fl, fh = bb(full_mask)
    tl, th = bb(trk_mask)
    FW, FD = float(fh[0] - fl[0]), float(fh[2] - fl[2])
    TW, TD = float(th[0] - tl[0]), float(th[2] - tl[2])

    sh = asm.get('shoulder_armor_assy_G')
    hd = asm.get('head_assy_G')
    wst = asm.get('waist_assy_G')
    leg = asm.get('r_leg_assy_G')
    ch = asm.get('body_assy_G')

    rows_t = []
    rows_t.append(('原素材 W×D（含背包）', '%.3f × %.3f' % (FW, FD),
                   'W/H %.3f   D/W %.3f' % (FW / 10.0, FD / FW)))
    rows_t.append(('主干 W×D（剥掉外挂）', '%.3f × %.3f' % (TW, TD),
                   'W/H %.3f   D/W %.3f' % (TW / 10.0, TD / TW)))
    if hd:
        rows_t.append(('头（含 V 鳍）宽 × 高', '%.3f × %.3f' % (hd['w'], hd['h']),
                       '头高/总高 %.3f' % (hd['h'] / 10.0)))
    if sh:
        rows_t.append(('肩甲 宽 × 高 × 深', '%.3f × %.3f × %.3f' % (sh['w'], sh['h'], sh['d']),
                       '肩宽/总高 %.3f' % (sh['w'] / 10.0)))
    if hd and sh:
        rows_t.append(('头(含 V 鳍)宽 / 肩宽', '%.3f' % (hd['w'] / sh['w']),
                       '← 我们含鳍 1.480 / 4.480 = 0.330'))
    if ch:
        rows_t.append(('胸 宽 × 深', '%.3f × %.3f' % (ch['w'], ch['d']),
                       '胸深/肩宽 %.3f' % (ch['d'] / sh['w']) if sh else ''))
    if wst and sh:
        rows_t.append(('腰最窄 / 肩宽', '%.3f' % (wst['w'] / sh['w']),
                       '腰 宽 × 高 %.3f × %.3f' % (wst['w'], wst['h'])))
    if leg:
        rows_t.append(('腿 宽 × 高', '%.3f × %.3f' % (leg['w'], leg['h']),
                       '腿长/总高 %.3f' % (leg['h'] / 10.0)))
        rows_t.append(('髋线 y（腿顶）', '%.3f' % leg['y'][1],
                       '占全高 %.1f%%' % (100.0 * leg['y'][1] / 10.0)))

    print('\n' + '=' * 78)
    print('Unicorn 主干比例尺（H = 10 归一化，同一份归一化）')
    print('=' * 78)
    for a, b, c in rows_t:
        print('  %-22s %-22s %s' % (a, b, c))

    # 纵深归属：主干的前/后极值各由谁给出（这条决定侧视像不像「冰箱」）
    print('\n  主干纵深的归属（z 越大越靠前）：')
    own = []
    for tok in ('feet_assy_G', 'body_assy_G', 'waist_assy_G',
                'L_rear_skirt_assy_G', 'R_rear_skirt_assy_G', 'r_leg_assy_G'):
        m = face_in(gf, sets, tok) & keep
        if not m.any():
            continue
        v = np.unique(tris[m].ravel())
        q = Vn[v]
        own.append((tok, float(q[:, 2].min()), float(q[:, 2].max())))
        print('    %-24s z[%6.3f, %6.3f]' % (tok, own[-1][1], own[-1][2]))
    zf = max(o[2] for o in own)
    zb = min(o[1] for o in own)
    print('    → 前极值 %.3f 来自 %s；后极值 %.3f 来自 %s'
          % (zf, max(own, key=lambda o: o[2])[0], zb,
             min(own, key=lambda o: o[1])[0]))

    d = os.path.join(OUT, 'unicorn_trunk.json')
    with open(d, 'w') as f:
        json.dump(dict(meta=meta, assemblies=asm, removed=[r[0] for r in removed],
                       ratios=rows_t), f, ensure_ascii=False, indent=2)
    print('\n→ %s' % d)


if __name__ == '__main__':
    main()
