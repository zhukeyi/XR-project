"""
film.py — 《钢脊·白鸦》伪 3D 概念片

尺寸基准严格取自《建模外包内容清单》与《方案评审》：
  机高 18.2m / 肩宽 9.8m / 胸舱离地 11.4m / 胸宽 6.4 × 高 5.0 × 深 4.2
  腰宽 3.6m / 肩关节至腕 6.8m / 光剑柄 1.4 × 0.22m / 头 1.6 × 2.2 × 1.9
造型语法：白主色 + 蓝红点缀、翼状推进器、腰部双光束军刀、胸舱、V 形天线
场景：压缩城市（街区 60–80m、楼高 30–80m）
"""
import math
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hud import HUD
from r3d import (Node, Tris, collect, Renderer, T, S, Rx, Ry, Rz, chain,
                 look_at, g_box, g_tube, g_wedge, g_plate, MAT, Mat)

M = MAT


def lerp(a, b, t):
    return a + (b - a) * t


def smooth(t):
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


def ease_out(t):
    t = min(1.0, max(0.0, t))
    return 1 - (1 - t) ** 3


def ease_in(t):
    t = min(1.0, max(0.0, t))
    return t ** 3


def seg(t, a, b):
    """区间归一化，越界夹紧。"""
    if b <= a:
        return 1.0 if t >= b else 0.0
    return min(1.0, max(0.0, (t - a) / (b - a)))


# ================================================================ 机体

def joint(parent, name, pos, rot=(0, 0, 0)):
    return Node(name, parent=parent, pos=pos, rot=rot)


def part(parent, name, prim, mat, pos, rot=(0, 0, 0)):
    return Node(name, prim=prim, mat=mat, parent=parent, pos=pos, rot=rot)


def build_mecha(p):
    """p: 姿态参数字典。返回 root 节点。"""
    root = Node('root', pos=p.get('pos', (0, 0, 0)), rot=p.get('rot', (0, 0, 0)))

    idle = p.get('idle', 0.0)
    hips = joint(root, 'hips', (0, 9.9 + 0.02 * math.sin(idle), 0))

    # ---- 骨盆 / 腰核 (A6)
    part(hips, 'pelvis', g_box(3.2, 1.5, 2.6), M['frame'], (0, 0, 0))
    part(hips, 'waist_core', g_tube(1.15, 1.05, 1.5, 8), M['frame_d'], (0, 0.9, 0))
    for s in (-1, 1):
        part(hips, f'skirt_front{s}', g_wedge(1.35, 1.6, 0.5, 0.7),
             M['armor_w'], (s * 0.72, -0.2, 1.15), (-8, 0, s * 3))
        part(hips, f'skirt_side{s}', g_wedge(0.55, 1.9, 2.2, 0.75),
             M['armor_blue'], (s * 1.72, -0.15, 0.1), (0, 0, s * 7))
        part(hips, f'skirt_back{s}', g_wedge(1.5, 1.5, 0.45, 0.7),
             M['armor_w2'], (s * 0.75, -0.1, -1.15), (8, 0, 0))
    # 腰部双光束军刀挂架（造型语法必须保留）
    for s in (-1, 1):
        rack = joint(hips, f'rack{s}', (s * 1.95, 0.3, -0.2), (0, 0, s * 8))
        part(rack, f'hilt{s}', g_tube(0.115, 0.115, 1.4, 6), M['frame'], (0, 0, 0))
        part(rack, f'hilt_cap{s}', g_tube(0.09, 0.13, 0.22, 6), M['armor_red'],
             (0, 0.8, 0))

    # ---- 胸腔 (A2)：中心世界 y=12.8
    chest = joint(hips, 'chest', (0, 2.9, 0), (p.get('chest_pitch', 0), 0, 0))
    for s in (-1, 1):
        part(chest, f'chest{s}', g_wedge(2.95, 4.6, 4.0, 0.62),
             M['armor_w'], (s * 1.62, 0.35, -0.1), (0, 0, s * -2))
        # 蓝色上胸块
        part(chest, f'chest_blue{s}', g_box(2.2, 1.1, 0.42), M['armor_blue'],
             (s * 1.55, 2.0, 1.72), (-6, 0, 0))
        # 红色进气口斜条
        part(chest, f'chest_red{s}', g_box(1.5, 0.26, 0.3), M['armor_red'],
             (s * 1.5, 1.34, 1.86), (-8, 0, s * 12))
        # 散热格栅
        for i in range(3):
            part(chest, f'grill{s}{i}', g_box(1.6, 0.18, 0.24), M['frame_d'],
                 (s * 1.45, -1.35 + i * 0.34, 1.92))
    # 中央舱门（双开，铰链在左右外侧）
    hatch = p.get('hatch', 0.0)
    for s in (-1, 1):
        hg = joint(chest, f'hatch_hinge{s}', (s * 0.86, -0.1, 1.9))
        hg.rot = np.array([0, s * -95.0 * hatch, 0])
        # 门板绕铰链旋转：几何偏移到门板中心
        part(hg, f'hatch{s}', g_box(0.86, 2.5, 0.16), M['armor_w2'],
             (s * -0.43, 0, 0))
        part(hg, f'hatch_blue{s}', g_box(0.5, 1.6, 0.1), M['armor_blue'],
             (s * -0.43, 0.25, 0.11))
    # 舱内发光（舱门打开后可见）
    if hatch > 0.02:
        Mat_cock = Mat((1.0, 0.55, 0.18), emissive=0.85 * hatch)
        part(chest, 'cockpit_glow', g_box(1.62, 2.3, 0.1), Mat_cock,
             (0, -0.1, 1.72))
    # 颈环
    part(chest, 'neck_ring', g_tube(0.62, 0.55, 0.7, 8), M['frame_d'], (0, 3.1, 0))

    # ---- 背包 / 翼状推进器 (A7)
    bp = joint(chest, 'backpack', (0, 0.3, -2.35))
    part(bp, 'bp_core', g_box(2.6, 2.4, 1.3), M['frame'], (0, 0, 0))
    part(bp, 'bp_top', g_box(2.0, 0.5, 1.0), M['armor_w2'], (0, 1.35, 0.1))
    thrust = p.get('thrust', 0.0)
    for s in (-1, 1):
        # 两片翼板：斜后上展开
        for k, (ang, ln, wid) in enumerate([(28, 4.6, 1.5), (52, 3.6, 1.1)]):
            w = joint(bp, f'wing{s}{k}', (s * 1.1, 0.7, -0.5),
                      (0, s * -14, s * ang))
            part(w, f'wing_plate{s}{k}',
                 g_plate([(0, -wid / 2), (ln, -wid / 2 * 0.35),
                          (ln * 1.02, wid / 2 * 0.3), (0, wid / 2)],
                         0.22, axis='x'),
                 M['armor_blue'], (0, 0, 0))
            part(w, f'wing_tip{s}{k}', g_box(0.5, 0.14, wid * 0.5),
                 M['armor_red'], (ln * 0.92, 0, 0))
        # 主喷口
        noz = joint(bp, f'nozzle{s}', (s * 1.0, -0.9, -0.55), (18, 0, 0))
        part(noz, 'noz_body', g_tube(0.52, 0.66, 1.2, 8), M['frame_d'], (0, -0.3, 0))
        if thrust > 0.02:
            ln = 1.6 + 11.0 * thrust
            fl = 0.86 + 0.14 * math.sin(idle * 9.0 + s)
            part(noz, 'flame_out', g_tube(0.92, 0.03, ln * 1.18 * fl, 7),
                 Mat((0.36, 0.74, 1.0), emissive=1.0), (0, -0.9 - ln * 0.59, 0))
            part(noz, 'flame_mid', g_tube(0.70, 0.09, ln * 0.86 * fl, 7),
                 Mat((1.0, 0.70, 0.28), emissive=1.0), (0, -0.9 - ln * 0.43, 0))
            part(noz, 'flame_core', g_tube(0.46, 0.03, ln * 0.60 * fl, 7),
                 Mat((0.96, 0.99, 1.0), emissive=1.0), (0, -0.9 - ln * 0.30, 0))
            part(noz, 'noz_glow', g_tube(0.56, 0.50, 0.34, 8),
                 Mat((1.0, 0.85, 0.5), emissive=1.0), (0, -0.82, 0))

    # ---- 头部 (A1)：中心世界 y=17.1
    head = joint(chest, 'head', (0, 4.3, 0.05), (p.get('head_pitch', 0), 0, 0))
    part(head, 'head_shell', g_wedge(1.55, 2.1, 1.85, 0.82), M['armor_w'], (0, 0.1, 0))
    part(head, 'face_mask', g_box(1.16, 0.95, 0.3), M['frame_d'], (0, -0.12, 0.88))
    # 双眼传感器窗（发光）
    eye = p.get('eye', 0.0)
    eye_mat = Mat((0.42, 0.93, 1.0), emissive=0.35 + 0.65 * eye)
    for s in (-1, 1):
        part(head, f'sensor{s}', g_box(0.42, 0.2, 0.12), eye_mat,
             (s * 0.30, 0.0, 1.0), (0, 0, s * -8))
    # 中央 V 形天线
    part(head, 'vfin_c', g_plate([(0, 0), (0.95, 0.10), (0.92, 0.28), (0, 0.30)],
                                 0.09, axis='x'), M['armor_red'],
         (0.0, 0.95, 0.55), (0, 0, 0))
    # 左右耳侧天线（后掠）
    for s in (-1, 1):
        part(head, f'ant{s}', g_plate([(0, 0), (1.3, 0.62), (1.22, 0.80), (-0.05, 0.22)],
                                      0.08, axis='x'), M['armor_w2'],
             (s * 0.78, 0.45, -0.2), (0, s * 18, s * 14))
    part(head, 'head_vent', g_box(0.9, 0.5, 0.2), M['frame'], (0, 0.55, -0.92))

    # ---- 双臂 (A4/A5)
    hands = {}
    for s in (-1, 1):
        sh = joint(chest, f'shoulder{s}', (s * 3.55, 1.55, 0))
        # 肩球
        part(sh, 'sh_ball', g_tube(0.85, 0.85, 1.1, 8), M['frame'], (0, 0, 0),
             (0, 0, 90))
        # 肩甲（外扩，构成 9.8m 肩宽）
        part(sh, 'pauldron', g_wedge(1.75, 2.3, 3.1, 0.72), M['armor_w'],
             (s * 0.72, 0.35, 0), (0, 0, s * -9))
        part(sh, 'pauldron_top', g_box(1.5, 0.5, 2.5), M['armor_blue'],
             (s * 0.75, 1.35, 0), (0, 0, s * -9))
        part(sh, 'pauldron_red', g_box(1.62, 0.26, 0.4), M['armor_red'],
             (s * 0.74, 0.72, 1.5), (0, 0, s * -9))

        arm = joint(sh, f'upper{s}', (0, -0.3, 0),
                    (p.get(f'sh_pitch{s}', 6), 0, p.get(f'sh_roll{s}', s * 5)))
        part(arm, 'uarm_a', g_tube(0.60, 0.66, 2.9, 8), M['armor_w'], (0, -1.45, 0))
        part(arm, 'uarm_blue', g_box(0.62, 1.5, 0.3), M['armor_blue'],
             (0, -1.4, 0.58))
        el = joint(arm, f'elbow{s}', (0, -2.95, 0),
                   (p.get(f'el_pitch{s}', -8), 0, 0))
        part(el, 'elbow_ball', g_tube(0.58, 0.58, 0.85, 8), M['frame_d'], (0, 0, 0),
             (0, 0, 90))
        fa = joint(el, f'fore{s}', (0, 0, 0), (p.get(f'fa_pitch{s}', 0), 0, 0))
        part(fa, 'farm_a', g_tube(0.70, 0.58, 3.1, 8), M['armor_w'], (0, -1.6, 0))
        part(fa, 'farm_b', g_box(0.7, 1.9, 0.36), M['armor_w2'], (0, -1.7, 0.62))
        part(fa, 'farm_c', g_box(0.5, 1.1, 0.2), M['armor_blue'], (0, -1.9, 0.82))
        hand = joint(fa, f'hand{s}', (0, -3.25, 0), (p.get(f'hand_pitch{s}', 0), 0, 0))
        part(hand, 'palm', g_box(0.62, 0.85, 0.72), M['frame'], (0, -0.3, 0.05))
        part(hand, 'fingers', g_box(0.56, 0.5, 0.55), M['frame_d'], (0, -0.72, 0.18))
        hands[s] = hand

    # ---- 双腿
    for s in (-1, 1):
        hip = joint(hips, f'hip{s}', (s * 1.62, -0.35, 0),
                    (p.get(f'hip_pitch{s}', 0), 0, p.get(f'hip_roll{s}', 0)))
        part(hip, 'hip_ball', g_tube(0.78, 0.78, 1.2, 8), M['frame_d'], (0, 0, 0),
             (0, 0, 90))
        part(hip, 'thigh', g_tube(0.86, 0.78, 4.1, 8), M['armor_w'], (0, -2.2, 0))
        part(hip, 'thigh_blue', g_box(0.6, 2.4, 0.34), M['armor_blue'],
             (0, -2.3, 0.76))
        part(hip, 'thigh_out', g_wedge(0.5, 2.6, 1.4, 0.8), M['armor_w2'],
             (s * 0.82, -2.1, 0), (0, 0, s * -6))
        kn = joint(hip, f'knee{s}', (0, -4.25, 0),
                   (p.get(f'knee_pitch{s}', 0), 0, 0))
        part(kn, 'knee_cap', g_wedge(1.3, 1.1, 0.9, 0.6), M['armor_blue'],
             (0, 0.1, 0.72), (-12, 0, 0))
        part(kn, 'knee_ball', g_tube(0.72, 0.72, 1.0, 8), M['frame_d'], (0, 0, 0),
             (0, 0, 90))
        sh2 = joint(kn, f'shin{s}', (0, 0, 0), (p.get(f'shin_pitch{s}', 0), 0, 0))
        part(sh2, 'shin', g_tube(1.02, 0.80, 4.0, 8), M['armor_w'], (0, -2.1, 0))
        part(sh2, 'shin_front', g_wedge(1.1, 3.0, 0.55, 0.75), M['armor_w2'],
             (0, -2.0, 0.66), (0, 0, 0))
        part(sh2, 'shin_blue', g_box(0.5, 2.0, 0.28), M['armor_blue'],
             (0, -2.2, 0.94))
        part(sh2, 'calf', g_wedge(0.9, 2.2, 0.9, 0.7), M['frame'], (0, -1.6, -0.85))
        an = joint(sh2, f'ankle{s}', (0, -4.15, 0), (p.get(f'ankle{s}', 0), 0, 0))
        part(an, 'ankle_ball', g_tube(0.55, 0.55, 0.9, 8), M['frame_d'], (0, 0, 0),
             (0, 0, 90))
        part(an, 'foot', g_wedge(1.45, 0.85, 3.3, 0.85), M['armor_w'],
             (0, -0.62, 0.75))
        part(an, 'foot_toe', g_wedge(1.35, 0.62, 1.0, 0.7), M['armor_red'],
             (0, -0.72, 2.1))
        part(an, 'heel', g_box(1.2, 0.7, 0.8), M['frame'], (0, -0.7, -0.75))

    # ---- 武器：光束步枪（右）
    if p.get('rifle_on', False):
        r = build_rifle(hands[1])
        mz = p.get('muzzle', 0.0)
        if mz > 0.02:
            part(r, 'muzzle_flash', g_tube(0.62 * mz, 0.04, 1.8 * mz, 6),
                 Mat((1.0, 0.94, 0.72), emissive=1.0), (0, 7.4, 0))
            part(r, 'muzzle_star', g_box(0.9 * mz, 0.9 * mz, 0.9 * mz),
                 Mat((0.85, 0.97, 1.0), emissive=1.0), (0, 7.3, 0))
    # ---- 光剑（右手，A4）
    if p.get('saber_on', 0.0) > 0.0:
        sb = joint(hands[1], 'saber_hilt', (0, -0.55, 0.12), (92, 0, 0))
        part(sb, 'hilt', g_tube(0.115, 0.115, 1.5, 6), M['frame'], (0, 0.2, 0))
        part(sb, 'hilt_cap', g_tube(0.09, 0.14, 0.24, 6), M['armor_red'],
             (0, 0.92, 0))
        bl = p['saber_on']
        if bl > 0.02:
            cy = 1.0 + 5.4 * bl * 0.5
            part(sb, 'blade_out', g_tube(0.20, 0.02, 5.4 * bl, 6),
                 Mat((0.30, 0.80, 1.0), emissive=1.0), (0, cy, 0))
            part(sb, 'blade_core', g_tube(0.095, 0.012, 5.4 * bl, 6),
                 Mat((0.94, 1.0, 1.0), emissive=1.0), (0, cy, 0))

    return root


def build_rifle(parent, hand_node, scale=1.0):
    """光束步枪：挂在右手节点下。"""
    g = joint(hand_node, 'rifle', (0, -0.5, 0.15), (88, 0, 0))
    part(g, 'r_body', g_box(0.75, 6.2, 0.85), M['frame'], (0, 1.6, 0))
    part(g, 'r_top', g_box(0.6, 4.4, 0.4), M['armor_blue'], (0, 2.0, 0.55))
    part(g, 'r_barrel', g_tube(0.22, 0.22, 2.6, 8), M['frame_d'], (0, 5.6, 0.05),
         (90, 0, 0))
    part(g, 'r_scope', g_box(0.35, 1.6, 0.35), M['frame_d'], (0, 3.2, 0.95))
    part(g, 'r_mag', g_box(0.5, 1.2, 0.6), M['frame_d'], (0, 1.0, -0.5))
    part(g, 'r_grip', g_box(0.42, 1.1, 0.5), M['frame'], (0, -0.2, -0.3), (14, 0, 0))
    return g


# ================================================================ 场景

def build_city(rng=None):
    """压缩城市废墟：楼高 30–80m，街区 60–80m。返回静态三角形集合。"""
    rng = rng or np.random.default_rng(7)
    t = Tris()

    def add_box(w, h, d, cx, cy, cz, rgb, emis=0.0):
        v, f = g_box(w, h, d)
        v = v + np.array([cx, cy, cz])
        piv = v.mean(axis=0)
        for face in f:
            pts = v[face]
            n = np.cross(pts[1] - pts[0], pts[2] - pts[0])
            ln = np.linalg.norm(n)
            if ln < 1e-9:
                continue
            n = n / ln
            if n @ (pts.mean(axis=0) - piv) < 0:
                n = -n
            t.add(pts, rgb, emis, n)

    # 地面条带（横向色带制造纵深）
    for i in range(16):
        z0 = 80 - i * 44
        z1 = z0 - 44
        c = 0.105 - i * 0.0032
        v = np.array([[-1200, 0, z0], [1200, 0, z0],
                      [1200, 0, z1], [-1200, 0, z1]], float)
        t.add(v, np.array([c * 1.04, c * 1.0, c * 1.12]), 0.0,
              np.array([0.0, 1.0, 0.0]))
    # 楼群
    for layer, (zc, n, hmin, hmax) in enumerate([
            (170, 18, 38, 78), (330, 20, 45, 95), (560, 24, 55, 115)]):
        for i in range(n):
            x = rng.uniform(-280, 280)
            z = zc + rng.uniform(-70, 70)
            if abs(x) < 40:
                continue
            w = rng.uniform(18, 46)
            d = rng.uniform(18, 46)
            h = rng.uniform(hmin, hmax)
            base = rng.choice([0.105, 0.125, 0.092])
            add_box(w, h, d, x, h / 2, z,
                    np.array([base, base * 0.96, base * 1.08]))
            if rng.random() < 0.22:
                add_box(1.8, 1.8, 1.8, x, h + 0.9, z,
                        np.array([1.0, 0.42, 0.16]), 1.0)
    # 近处废墟块
    for i in range(30):
        x = rng.uniform(-75, 75)
        z = rng.uniform(-20, 95)
        if abs(x) < 27:
            continue
        w = rng.uniform(4, 14)
        h = rng.uniform(2, 9)
        add_box(w, h, w * rng.uniform(0.7, 1.5), x, h / 2, z,
                np.array([0.145, 0.142, 0.155]))
    # 弹射滑轨（对齐"40m 滑轨 + 闸门"的甲板设定）
    add_box(1.2, 0.5, 120, -9.0, 0.25, -40, np.array([0.20, 0.21, 0.23]))
    add_box(1.2, 0.5, 120, 9.0, 0.25, -40, np.array([0.20, 0.21, 0.23]))
    for i in range(12):
        add_box(19.2, 0.12, 0.7, 0, 0.42, 8 - i * 10,
                np.array([0.26, 0.27, 0.29]))
    return t


# ================================================================ 敌机

def build_enemy(p):
    """敌方无人战斗机甲（简化低模）：深灰装甲 + 单眼红色传感器。"""
    root = Node('enemy', pos=p.get('pos', (0, 0, -70)),
                rot=p.get('rot', (0, 0, 0)))
    dead = p.get('dead', 0.0)
    body = joint(root, 'e_body', (0, 7.4, 0), (p.get('lean', 0), 0, 0))
    part(body, 'e_core', g_wedge(3.0, 3.4, 2.6, 0.55), M['frame'], (0, 0, 0))
    part(body, 'e_shoulder', g_box(5.6, 1.1, 2.2), M['frame_d'], (0, 1.6, -0.2))
    for s in (-1, 1):
        part(body, f'e_pod{s}', g_wedge(1.6, 1.8, 2.4, 0.6), M['armor_blu2'],
             (s * 2.9, 1.2, 0))
        # 手臂（简化锥台）
        arm = joint(body, f'e_arm{s}', (s * 3.4, 0.9, 0), (12, 0, s * 6))
        part(arm, 'a1', g_tube(0.42, 0.36, 3.4, 6), M['frame'], (0, -1.7, 0))
        part(arm, 'a2', g_tube(0.34, 0.26, 3.0, 6), M['frame_d'], (0, -4.8, 0))
    head = joint(body, 'e_head', (0, 2.4, 0.2))
    part(head, 'e_head_a', g_wedge(1.1, 1.3, 1.5, 0.7), M['frame'], (0, 0.2, 0))
    eye = Mat((1.0, 0.26, 0.18), emissive=0.45 + 0.55 * (1 - dead))
    part(head, 'e_eye', g_box(0.7, 0.16, 0.1), eye, (0, 0.1, 0.78))
    part(head, 'e_horn', g_plate([(0, 0), (0.7, 0.5), (0.62, 0.66), (0, 0.2)],
                                 0.06, axis='x'), M['armor_red'], (0, 0.6, 0.1))
    for s in (-1, 1):
        leg = joint(root, f'e_leg{s}', (s * 1.5, 7.2, 0), (p.get('leg', 0), 0, 0))
        part(leg, 'l1', g_tube(0.55, 0.45, 4.0, 6), M['frame_d'], (0, -2.0, 0))
        part(leg, 'l2', g_tube(0.5, 0.34, 3.4, 6), M['frame'], (0, -5.6, 0))
        part(leg, 'l3', g_wedge(1.1, 0.6, 2.4, 0.8), M['frame_d'], (0, -7.3, 0.5))
    # 推进器
    part(body, 'e_pack', g_box(1.6, 1.4, 1.0), M['frame_d'], (0, 0.2, -1.6))
    return root


# ================================================================ 时间轴

FPS = 24
DUR = 12.0
NF = int(FPS * DUR)


def camera(t):
    """返回 (eye, target, fov, roll)。"""
    # S1 0–3.2  仰视登场，缓慢推轨
    if t < 3.2:
        u = smooth(seg(t, 0.15, 3.2))
        eye = (lerp(3.0, 0.7, u), lerp(1.45, 2.1, u), lerp(34.0, 26.5, u))
        tgt = (0.0, lerp(10.0, 10.9, u), 0.0)
        return eye, tgt, lerp(42, 40, u), lerp(-1.4, 0.0, u)
    # S2 3.2–5.2  胸舱特写：升到胸舱高度正对
    if t < 5.2:
        u = smooth(seg(t, 3.2, 5.2))
        eye = (lerp(0.7, 0.25, u), lerp(2.1, 9.6, u), lerp(26.5, 16.5, u))
        tgt = (0.0, lerp(10.9, 12.5, u), 0.0)
        return eye, tgt, lerp(40, 36, u), 0.0
    # S3 5.2–7.0  弹射：贴地侧向甩镜
    if t < 7.0:
        u = smooth(seg(t, 5.2, 7.0))
        e = ease_in(u) * 0.55 + u * 0.45
        eye = (lerp(0.25, -17.0, e), lerp(9.6, 5.4, u), lerp(16.5, 30.0, u))
        tgt = (0.0, lerp(12.5, 9.8, u), lerp(0.0, -10.0, u))
        return eye, tgt, lerp(36, 44, u), lerp(0, -9, u)
    # S4 7.0–9.4  交战：侧前方，机体举枪，敌机在纵深
    if t < 9.4:
        u = smooth(seg(t, 7.0, 9.4))
        eye = (lerp(-25.0, -21.0, u), lerp(8.6, 9.2, u), lerp(15.0, 11.0, u))
        tgt = (-1.0, 11.4, lerp(-4.0, 2.0, u))
        return eye, tgt, 39, lerp(-3.5, 1.0, u)
    # S5 9.4–12.0  拔刀近战 + 收尾
    u = smooth(seg(t, 9.4, 12.0))
    eye = (lerp(-13.5, -10.5, u), lerp(12.6, 13.4, u), lerp(14.0, 11.6, u))
    tgt = (0.0, 13.0, lerp(-1.0, 0.6, u))
    return eye, tgt, lerp(35, 31, u), lerp(3.0, -1.5, u)


def pose(t):
    """姿态与时间轴。角度约定：sh_pitch 为负 = 手臂向前抬。"""
    p = {'idle': t * 2.2}

    launch = smooth(seg(t, 5.3, 6.1)) * (1 - smooth(seg(t, 6.9, 7.7)) * 0.62)
    shoot_up = smooth(seg(t, 6.85, 7.75))
    recoil = smooth(seg(t, 7.95, 8.06)) * (1 - smooth(seg(t, 8.06, 8.75)))
    draw_dn = smooth(seg(t, 9.45, 9.95)) * (1 - smooth(seg(t, 10.05, 10.55)))
    raise_ = smooth(seg(t, 10.4, 10.95))
    slash = smooth(seg(t, 10.95, 11.55))

    # 躯干
    p['chest_pitch'] = -9 * launch + 5 * shoot_up + 7 * slash
    p['rot'] = (6 * launch + 2 * shoot_up, 0, -3 * slash)
    p['pos'] = (0, -1.5 * launch - 0.5 * slash, -2.0 * launch)

    # 推进器
    p['thrust'] = (smooth(seg(t, 4.55, 5.35))
                   * (1 - smooth(seg(t, 7.3, 8.3)) * 0.86))
    p['eye'] = smooth(seg(t, 3.3, 4.1))
    p['hatch'] = smooth(seg(t, 3.4, 4.5)) * (1 - smooth(seg(t, 4.95, 5.45)))

    # 腿
    crouch = launch * 10 + slash * 12 + shoot_up * 4
    p['hip_pitch-1'] = 3 + crouch * 0.8
    p['hip_pitch1'] = 3 + crouch * 0.8 - slash * 14
    p['knee_pitch-1'] = -6 - crouch * 1.1
    p['knee_pitch1'] = -6 - crouch * 1.1 + slash * 10
    p['ankle-1'] = 4 + crouch * 0.5
    p['ankle1'] = 4 + crouch * 0.5 - slash * 6

    # 右臂：站立 -> 举枪 -> 下垂 -> 高举 -> 劈下
    sh1 = 6.0
    sh1 = lerp(sh1, -74.0, shoot_up)
    sh1 += 15.0 * recoil
    sh1 = lerp(sh1, 16.0, draw_dn)
    sh1 = lerp(sh1, -106.0, raise_)
    sh1 = lerp(sh1, -20.0, slash)
    p['sh_pitch1'] = sh1 + 5 * launch
    p['sh_roll1'] = -6 - 10 * slash

    el1 = -10.0
    el1 = lerp(el1, -22.0, shoot_up) - 18 * recoil
    el1 = lerp(el1, -14.0, draw_dn) - 26 * raise_
    el1 = lerp(el1, -8.0, slash)
    p['el_pitch1'] = el1
    p['hand_pitch1'] = 12 * shoot_up + 10 * raise_

    # 左臂：支撑 / 平衡
    p['sh_pitch-1'] = 6 - 46 * shoot_up + 24 * slash + 5 * launch
    p['el_pitch-1'] = -10 - 30 * shoot_up - 16 * slash
    p['sh_roll-1'] = -6 - 8 * shoot_up

    p['head_pitch'] = -2 + 3 * launch (0) if False else -2 + 3 * launch - 4 * shoot_up
    # 武器状态
    p['rifle_on'] = t > 6.7
    p['muzzle'] = smooth(seg(t, 7.96, 8.02)) * (1 - smooth(seg(t, 8.02, 8.22)))
    p['saber_on'] = smooth(seg(t, 10.05, 10.75)) * (1 - smooth(seg(t, 11.75, 12.0)) * 0.15)
    return p


# ================================================================ 渲染主程序

def mech_bbox(tris, cam_m, fov, W=1280, H=720):
    f = 1.0 / math.tan(fov * math.pi / 360.0)
    pts = np.concatenate([(cam_m @ np.hstack([p, np.ones((len(p), 1))]).T).T[:, :3]
                          for p in tris.pts])
    vis = pts[pts[:, 2] < -0.6]
    if len(vis) == 0:
        return None
    z = -vis[:, 2]
    sx = (vis[:, 0] / z) * f * (H / 2) + W / 2
    sy = H / 2 - (vis[:, 1] / z) * f * (H / 2)
    return (sx.min(), sy.min(), sx.max(), sy.max())


SUBS = [
    (0.0, 3.2, '序章 · 仰视 ／ 18.2m，一次出击的高度'),
    (3.2, 5.2, '启动 ／ 胸舱开启，双发点火'),
    (5.2, 7.0, '弹射出击 ／ 40m 滑轨，离舰'),
    (7.0, 9.4, '交战 ／ 光束步枪，破盾'),
    (9.4, 12.0, '近战 ／ 腰部双刀，光束军刀展开'),
]


def hud_state(t, bbox):
    s = {'bbox': bbox, 'threshold': 0}
    s['alpha'] = min(1.0, seg(t, 0.15, 0.9))
    s['boot'] = seg(t, 0.0, 0.55)
    s['scanline'] = 1.0 - seg(t, 0.3, 2.4)
    s['lock'] = smooth(seg(t, 1.0, 1.9)) * (1 - smooth(seg(t, 5.2, 5.6)))
    s['header'] = 'SECTOR 07 // CATAPULT DECK'
    mm, ss = divmod(int(t), 60)
    s['clock'] = f'00:{mm:02d}:{ss:02d}'
    s['armor'] = 1.0 - 0.12 * smooth(seg(t, 8.6, 9.2))
    s['thrust_gauge'] = 0.78 - 0.55 * smooth(seg(t, 4.6, 5.6)) \
        + 0.5 * smooth(seg(t, 7.6, 8.4))
    s['scale_label'] = '18.2 m'
    s['lock_label'] = 'HX-07  LOCK'
    s['lock_dist'] = f'{26.5 - 8.0 * seg(t, 0, 3.2):4.1f} m'
    s['model'] = 'HX-07  //  白鸦'
    for a, b, txt in SUBS:
        if a <= t < b:
            s['subtitle'] = txt
    s['flash'] = 0.0
    return s


def render_frame(rd, city, t, with_hud=True):
    tris = Tris()
    tris.merge(city)
    root = build_mecha(pose(t))
    mech = Tris()
    collect(root, mech)
    tris.merge(mech)
    eye, tgt, fov, roll = camera(t)
    rd.fov = fov
    rd.f = 1.0 / math.tan(fov * math.pi / 360.0)
    cm = look_at(eye, tgt, roll=roll)
    base = rd.sky(top=(0.032, 0.042, 0.072), bot=(0.175, 0.205, 0.255),
                  horizon_y=0.55, sun=(0.78, 0.46, 0.34), sun_k=0.30)
    img = rd.render(tris, cm, base=base, fog_col=(0.135, 0.160, 0.200),
                    fog_a=0.0016, fog_b=0.000008)
    if with_hud:
        bb = mech_bbox(mech, cm, fov, rd.W, rd.H)
        img = HUD(rd.W, rd.H).draw(img, t, hud_state(t, bb))
    return img


def probe(t, W=1280, H=720):
    """诊断：输出机体在屏幕上的精确包围盒与占比，用于构图校准。"""
    root = build_mecha(pose(t))
    tris = Tris()
    collect(root, tris)
    eye, tgt, fov, roll = camera(t)
    cm = look_at(eye, tgt, roll=roll)
    f = 1.0 / math.tan(fov * math.pi / 360.0)
    pts = np.concatenate([(cm @ np.hstack([p, np.ones((len(p), 1))]).T).T[:, :3]
                          for p in tris.pts])
    vis = pts[pts[:, 2] < -0.6]
    z = -vis[:, 2]
    sx = (vis[:, 0] / z) * f * (H / 2) + W / 2
    sy = H / 2 - (vis[:, 1] / z) * f * (H / 2)
    x0, x1, y0, y1 = sx.min(), sx.max(), sy.min(), sy.max()
    print(f't={t:5.2f} eye=({eye[0]:6.1f},{eye[1]:5.1f},{eye[2]:6.1f}) '
          f'fov={fov:4.1f} | mech px x[{x0:7.0f},{x1:7.0f}] '
          f'y[{y0:7.0f},{y1:7.0f}] | '
          f'w={100*(x1-x0)/W:5.1f}% h={100*(y1-y0)/H:5.1f}%')
    return x0, x1, y0, y1


if __name__ == '__main__':
    import time
    rd = Renderer(1280, 720, ss=2, fov=40)
    city = build_city()
    print('city tris', len(city))
    t0 = time.time()
    tt = float(sys.argv[1]) if len(sys.argv) > 1 else 1.6
    probe(tt)
    img = render_frame(rd, city, tt)
    dt = time.time() - t0
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'out', 'test.png')
    img.save(out)
    print(f'rendered in {dt:.2f}s -> {out}')
