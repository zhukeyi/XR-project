"""
mecha_model.py — 《钢脊·白鸦》HX-07 机体建模（程序化高密度装甲版）

设计目标：动画设定画式的完整机体，而非灰模骨架。
手段：
  1. 装甲分块——每块甲片独立成件，靠渲染器的暗色描边形成"分割线"；
  2. 涂装分区——白主色 / 蓝中段 / 红点缀 / 警示橙 / 深灰骨架，共 6 级明度；
  3. 贴花层——在装甲表面贴 0.04m 薄片，表达编号条、警示带、队徽；
  4. 内构外露——关节处露出深灰机械体，形成"装甲覆盖骨架"的层次。

尺寸基准（严格取自《建模外包内容清单》A1–A7）：
  机高 18.2 / 肩宽 9.8 / 胸舱离地 11.4 / 胸 6.4W×5.0H×4.2D / 腰宽 3.6
  头 1.6W×2.2H×1.9D / 肩关节至腕 6.8 / 光剑柄 1.4×0.22
"""
import math
import numpy as np

from r3d import (Node, T, S, Rx, Ry, Rz, chain,
                 g_box, g_tube, g_wedge, g_plate, Mat)

# ---------------------------------------------------------------- 涂装色板
# 动画感的关键是多级明度 + 明确的分区色，而非单一白
# ★ spec / rim 是「金属扎实感」的唯一渲染通道：v1 起这两个字段就存在，但调色板
#   从未赋值、shade() 也没接，全系 0.0 → 渲染出来只能是塑料。这里按材质分层给：
#   主装甲白最亮（高光强、边缘光中），蓝/红次之，深灰骨架弱高光（哑光机械漆）。
W1 = Mat((0.938, 0.948, 0.962), spec=1.00, rim=0.55)  # 主装甲白（最亮）
W2 = Mat((0.845, 0.862, 0.885), spec=0.90, rim=0.50)  # 次级白（大面积）
W3 = Mat((0.700, 0.722, 0.755), spec=0.70, rim=0.45)  # 阴影白 / 内衬
BL1 = Mat((0.095, 0.255, 0.560), spec=0.85, rim=0.60)  # 主蓝
BL2 = Mat((0.062, 0.176, 0.375), spec=0.70, rim=0.55)  # 深蓝（阴影侧）
RD1 = Mat((0.800, 0.170, 0.150), spec=0.80, rim=0.55)  # 红
OR1 = Mat((0.930, 0.590, 0.140), spec=0.85, rim=0.50)  # 警示橙
GR1 = Mat((0.235, 0.255, 0.290), spec=0.45, rim=0.35)  # 骨架深灰
GR2 = Mat((0.150, 0.165, 0.190), spec=0.35, rim=0.30)  # 骨架最深
GR3 = Mat((0.400, 0.425, 0.465), spec=0.75, rim=0.45)  # 机械中灰
VIS = Mat((0.400, 0.930, 1.000), emissive=0.85)     # 传感器青
SAK = Mat((0.320, 0.860, 1.000), emissive=1.000)    # 光束
FLA = Mat((1.000, 0.780, 0.380), emissive=1.000)
FLC = Mat((0.980, 0.995, 1.000), emissive=1.000)


def P(parent, name, w, h, d, mat, pos, rot=(0, 0, 0)):
    return Node(name, parent=parent, prim=g_box(w, h, d), mat=mat,
                pos=pos, rot=rot)


def PW(parent, name, w, h, d, mat, pos, rot=(0, 0, 0), taper=0.62):
    return Node(name, parent=parent, prim=g_wedge(w, h, d, taper), mat=mat,
                pos=pos, rot=rot)


def PT(parent, name, r0, r1, h, mat, pos, rot=(0, 0, 0), sides=8, phase=0.0):
    # smooth='tube'：侧面法线做平滑，M1 起消除棱面感（v1 管线不读该字段，无影响）
    return Node(name, parent=parent, prim=g_tube(r0, r1, h, sides, phase=phase),
                mat=mat, pos=pos, rot=rot, smooth='tube')


def PL(parent, name, pts, thick, axis, mat, pos, rot=(0, 0, 0)):
    return Node(name, parent=parent, prim=g_plate(pts, thick, axis), mat=mat,
                pos=pos, rot=rot)


def J(parent, name, pos, rot=(0, 0, 0)):
    return Node(name, parent=parent, pos=pos, rot=rot)


# ================================================================ 头部 A1
def _head(chest, p):
    eye = p.get('eye', 0.0)
    head = J(chest, 'head', (0, 4.30, 0.05), (p.get('head_pitch', 0), 0, 0))

    # 颈：机械管 + 护环
    PT(head, 'neck_tube', 0.46, 0.52, 0.55, GR2, (0, -1.35, 0), sides=8)
    PT(head, 'neck_ring_a', 0.58, 0.58, 0.16, GR3, (0, -1.20, 0), sides=10)
    PT(head, 'neck_ring_b', 0.54, 0.54, 0.12, GR1, (0, -1.02, 0), sides=10)

    # 头壳：后脑 + 头顶 + 前额，三段拼接（分割线来源）
    PW(head, 'skull_back', 1.34, 1.10, 0.95, W1, (0, 0.30, -0.45), taper=0.80)
    PW(head, 'skull_top', 1.50, 0.72, 1.60, W1, (0, 0.72, -0.05), taper=0.86)
    PW(head, 'brow', 1.56, 0.66, 0.72, W2, (0, 0.22, 0.62), taper=0.72)
    # 前额中央脊
    PW(head, 'brow_ridge', 0.30, 0.80, 0.55, W1, (0, 0.30, 0.86), taper=0.55)
    # 面罩：上（眼罩）/ 下（口部格栅）
    P(head, 'visor_frame', 1.22, 0.62, 0.30, GR2, (0, -0.06, 0.80))
    P(head, 'mask_lower', 1.02, 0.52, 0.26, GR1, (0, -0.48, 0.78))
    for i in range(3):
        P(head, f'mask_vent{i}', 0.86, 0.07, 0.10, GR2,
          (0, -0.38 - i * 0.13, 0.92))
    # 颚部白色侧甲
    for s in (-1, 1):
        PW(head, f'jaw{s}', 0.26, 0.72, 0.85, W2, (s * 0.62, -0.42, 0.42),
           rot=(0, s * -10, 0), taper=0.8)
    # 双眼传感器：外框 + 发光内芯（双层，动画里会先暗后亮）
    for s in (-1, 1):
        P(head, f'sens_frame{s}', 0.46, 0.26, 0.10, GR2, (s * 0.30, -0.02, 0.94))
        em = 0.18 + 0.82 * eye
        P(head, f'sens_core{s}', 0.36, 0.15, 0.06,
          Mat((0.42, 0.94, 1.0), emissive=em), (s * 0.30, -0.02, 1.00))
    # V 形天线：红芯 + 白边（左右各一）
    for s in (-1, 1):
        PL(head, f'vfin_w{s}', [(0, 0), (0.86, 0.10), (0.84, 0.34), (0, 0.36)],
           0.10, 'x', W1, (s * 0.03, 0.86, 0.42), rot=(0, 0, s * 0))
        PL(head, f'vfin_r{s}', [(0.02, 0.06), (0.80, 0.14), (0.78, 0.28), (0.02, 0.30)],
           0.14, 'x', RD1, (s * 0.03, 0.86, 0.42))
        # 耳侧后掠天线
        PL(head, f'ant{s}', [(0, 0), (1.24, 0.54), (1.16, 0.76), (-0.04, 0.26)],
           0.09, 'x', W2, (s * 0.74, 0.36, -0.18), rot=(0, s * 16, s * 12))
        PT(head, f'ant_base{s}', 0.16, 0.13, 0.20, GR3, (s * 0.76, 0.30, -0.16),
           rot=(0, 0, 90), sides=6)
    # 后脑散热鳍
    for i in range(4):
        P(head, f'fin{i}', 0.80, 0.30, 0.10, GR1, (0, 0.62 - i * 0.26, -0.94))
    # 侧面进气口（警示橙贴花）
    for s in (-1, 1):
        P(head, f'ear_vent{s}', 0.12, 0.34, 0.52, GR2, (s * 0.80, 0.02, -0.12))
        P(head, f'ear_decal{s}', 0.05, 0.10, 0.38, OR1, (s * 0.86, 0.02, -0.12))
    return head


# ================================================================ 胸部 A2
def _chest(hips, p):
    chest = J(hips, 'chest', (0, 2.90, 0), (p.get('chest_pitch', 0), 0, 0))

    # 胸腔核心（骨架，外露于装甲缝隙）
    PW(chest, 'core', 4.40, 3.60, 3.10, GR2, (0, 0.10, -0.10), taper=0.82)
    # 上胸甲：左右各分两层（上白下蓝），这是动画机体的经典分区
    for s in (-1, 1):
        PW(chest, f'chest_up{s}', 2.90, 1.85, 3.95, W1, (s * 1.60, 1.35, -0.05),
           rot=(0, 0, s * -2), taper=0.68)
        PW(chest, f'chest_low{s}', 2.86, 1.60, 3.70, W2, (s * 1.58, -0.35, 0.02),
           rot=(0, 0, s * -2), taper=0.72)
        # 蓝色中段带
        P(chest, f'chest_blue{s}', 2.46, 0.74, 0.36, BL1, (s * 1.56, 0.50, 1.86))
        # 红色进气斜条（加厚加大，确保 30m 距离下仍可辨识）
        P(chest, f'chest_red{s}', 2.26, 0.84, 0.44, RD1, (s * 1.52, 1.34, 2.02),
          rot=(0, 0, s * 14))
        # 散热格栅（4 条）
        for i in range(4):
            P(chest, f'grill{s}{i}', 1.55, 0.14, 0.16, GR2,
              (s * 1.45, -1.05 - i * 0.26 + 0.52, 1.86))
        # 圆形排气口
        PT(chest, f'exh{s}', 0.30, 0.30, 0.20, GR1, (s * 0.98, -0.92, 1.80),
           rot=(90, 0, 0), sides=10)
        PT(chest, f'exh_in{s}', 0.20, 0.20, 0.10, GR2, (s * 0.98, -0.92, 1.88),
           rot=(90, 0, 0), sides=10)
        # 胸侧装甲（外扩包边）
        PW(chest, f'chest_side{s}', 0.55, 3.10, 3.20, W2, (s * 3.05, 0.35, -0.1),
           rot=(0, 0, s * -14), taper=0.78)
        # 肩接口
        PT(chest, f'sh_socket{s}', 0.80, 0.80, 0.60, GR1, (s * 3.30, 1.55, 0),
           rot=(0, 0, 90), sides=10)
        # 贴花：队徽编号条
        P(chest, f'decal{s}', 0.62, 0.16, 0.06, BL2, (s * 1.52, 1.92, 1.80),
          rot=(0, 0, s * 8))

    # 中央舱门（双开）+ 门框
    hatch = p.get('hatch', 0.0)
    # 胸部中央黄色进气 V 口（动画机体的经典识别点）
    P(chest, 'chest_vent_c', 0.76, 0.40, 0.28, OR1, (0, 1.98, 1.84))
    P(chest, 'chest_vent_c2', 1.26, 0.20, 0.22, OR1, (0, 1.72, 1.80))
    P(chest, 'hatch_frame', 2.02, 2.86, 0.30, GR2, (0, -0.10, 1.76))
    for s in (-1, 1):
        hg = J(chest, f'hatch_hinge{s}', (s * 0.92, -0.10, 1.90))
        hg.rot = np.array([0, s * -95.0 * hatch, 0])
        P(hg, f'hatch{s}', 0.86, 2.62, 0.18, W1, (s * -0.43, 0, 0))
        P(hg, f'hatch_blue{s}', 0.52, 1.70, 0.10, BL1, (s * -0.43, 0.28, 0.11))
        P(hg, f'hatch_num{s}', 0.30, 0.22, 0.06, RD1, (s * -0.43, -0.86, 0.11))
        # 门内侧结构
        P(hg, f'hatch_in{s}', 0.74, 2.30, 0.10, GR3, (s * -0.43, 0, -0.12))
    if hatch > 0.02:
        P(chest, 'cockpit_glow', 1.72, 2.40, 0.10,
          Mat((1.0, 0.48, 0.14), emissive=0.55 + 0.40 * hatch),
          (0, -0.10, 1.70))
        P(chest, 'cockpit_seat', 0.70, 1.30, 0.30, GR2, (0, -0.20, 1.58))
    # 颈部护甲
    PW(chest, 'collar', 1.90, 0.70, 1.40, W2, (0, 2.85, -0.10), taper=0.72)
    return chest


# ================================================================ 背包 A7
def _backpack(chest, p):
    bp = J(chest, 'backpack', (0, 0.30, -2.30))
    P(bp, 'bp_core', 2.70, 2.50, 1.40, GR1, (0, 0, 0))
    P(bp, 'bp_top', 2.10, 0.44, 1.10, W2, (0, 1.42, 0.10))
    P(bp, 'bp_panel', 2.20, 0.30, 0.08, GR3, (0, 0.60, 0.74))
    P(bp, 'bp_decal', 0.90, 0.12, 0.05, OR1, (0, 0.20, 0.74))
    for s in (-1, 1):
        # 输能管线
        PT(bp, f'pipe{s}', 0.13, 0.13, 1.90, GR2, (s * 0.55, -1.30, 0.42),
           rot=(0, 0, s * 8), sides=6)
        # 两段翼板（外段更长，形成剪影）
        for k, (ang, ln, wid, th, mat) in enumerate([
                (26, 4.90, 1.60, 0.26, BL1), (48, 3.80, 1.15, 0.20, BL2)]):
            w = J(bp, f'wing{s}{k}', (s * 1.15, 0.75, -0.45), (0, s * -13, s * ang))
            PL(w, f'wing_plate{s}{k}',
               [(0, -wid / 2), (ln, -wid / 2 * 0.32),
                (ln * 1.02, wid / 2 * 0.26), (0, wid / 2)], th, 'x', mat, (0, 0, 0))
            P(w, f'wing_edge{s}{k}', 0.46, 0.12, wid * 0.52, RD1,
              (ln * 0.90, 0, 0))
            P(w, f'wing_rib{s}{k}', ln * 0.30, 0.10, 0.22, GR3, (ln * 0.34, 0, 0))
        # 主喷口：三段收口
        noz = J(bp, f'nozzle{s}', (s * 1.02, -1.05, -0.55), (16, 0, 0))
        PT(noz, 'noz_a', 0.56, 0.70, 0.60, GR1, (0, 0.10, 0), sides=9)
        PT(noz, 'noz_b', 0.62, 0.46, 0.50, GR2, (0, -0.42, 0), sides=9)
        PT(noz, 'noz_c', 0.46, 0.42, 0.26, GR3, (0, -0.78, 0), sides=9)
        # 姿控喷口（小）
        for k, (px, py) in enumerate([(0.30, 1.30), (-0.30, 1.30)]):
            PT(bp, f'rcs{s}{k}', 0.12, 0.16, 0.26, GR2,
               (s * 1.30, py, -0.30 + 0.4 * (k % 2)), rot=(90, 0, 0), sides=6)

    # 主推进焰
    thrust = p.get('thrust', 0.0)
    if thrust > 0.02:
        fl = 0.88 + 0.12 * math.sin(p.get('idle', 0) * 9.0)
        for s in (-1, 1):
            noz = J(bp, f'fl{s}', (s * 1.02, -1.05, -0.55), (16, 0, 0))
            ln = (1.5 + 11.5 * thrust) * fl
            PT(noz, 'f_out', 1.00, 0.03, ln * 1.20, Mat((0.34, 0.72, 1.0), emissive=1.0),
               (0, -0.95 - ln * 0.60, 0), sides=7)
            PT(noz, 'f_mid', 0.74, 0.07, ln * 0.86, FLA, (0, -0.95 - ln * 0.43, 0), sides=7)
            PT(noz, 'f_core', 0.48, 0.02, ln * 0.58, FLC, (0, -0.95 - ln * 0.29, 0), sides=7)
            PT(noz, 'f_glow', 0.60, 0.54, 0.36, Mat((1.0, 0.90, 0.62), emissive=1.0),
               (0, -0.88, 0), sides=9)
    return bp


# ================================================================ 手臂 A4/A5
def _arm(chest, p, s):
    hands = {}
    sh = J(chest, f'shoulder{s}', (s * 3.55, 1.55, 0))
    # 肩球 + 护罩
    PT(sh, 'ball', 0.88, 0.88, 1.15, GR1, (0, 0, 0), rot=(0, 0, 90), sides=10)
    PT(sh, 'ball_in', 0.60, 0.60, 1.20, GR2, (0, 0, 0), rot=(0, 0, 90), sides=10)
    # 肩甲：主甲 + 顶盖 + 前缘 + 侧裙 + 编号贴花（四件套）
    PW(sh, 'pauldron', 1.80, 2.40, 3.15, W1, (s * 0.74, 0.30, 0),
       rot=(0, 0, s * -9), taper=0.70)
    P(sh, 'pauldron_top', 1.52, 0.46, 2.55, BL1, (s * 0.76, 1.38, 0),
      rot=(0, 0, s * -9))
    P(sh, 'pauldron_edge', 2.02, 0.66, 0.92, RD1, (s * 0.75, 0.66, 1.56),
      rot=(0, 0, s * -9))
    # 肩甲顶面红翼条（从正面/斜上视角可见）
    P(sh, 'pauldron_redtop', 1.34, 0.26, 2.32, RD1, (s * 0.76, 1.50, 0),
      rot=(0, 0, s * -9))
    PW(sh, 'pauldron_skirt', 0.34, 1.90, 2.40, W2, (s * 1.60, -0.20, 0),
       rot=(0, 0, s * -12), taper=0.82)
    P(sh, 'pauldron_decal', 0.44, 0.16, 0.42, OR1, (s * 0.72, -0.55, 1.42))

    arm = J(sh, f'upper{s}', (0, -0.30, 0),
            (p.get(f'sh_pitch{s}', 6), 0, p.get(f'sh_roll{s}', s * 5)))
    PT(arm, 'uarm_core', 0.44, 0.48, 3.00, GR2, (0, -1.50, 0), sides=8)
    PW(arm, 'uarm_a', 1.06, 2.60, 1.10, W1, (0, -1.45, 0.06), taper=0.82)
    PW(arm, 'uarm_b', 0.90, 1.70, 0.95, W2, (0, -2.30, -0.05), taper=0.86)
    P(arm, 'uarm_blue', 0.90, 2.05, 0.26, BL1, (0, -1.45, 0.60))
    PT(arm, 'uarm_piston', 0.10, 0.10, 1.10, GR3, (s * 0.45, -1.60, -0.45),
       sides=5)

    el = J(arm, f'elbow{s}', (0, -2.95, 0), (p.get(f'el_pitch{s}', -8), 0, 0))
    PT(el, 'el_ball', 0.60, 0.60, 0.90, GR2, (0, 0, 0), rot=(0, 0, 90), sides=10)
    PW(el, 'el_guard', 0.90, 0.70, 1.00, W2, (0, 0.10, -0.34), taper=0.7)

    fa = J(el, f'fore{s}', (0, 0, 0), (p.get(f'fa_pitch{s}', 0), 0, 0))
    PT(fa, 'farm_core', 0.52, 0.44, 3.10, GR2, (0, -1.60, 0), sides=8)
    PW(fa, 'farm_a', 1.28, 2.60, 1.24, W1, (0, -1.55, 0.05), taper=0.80)
    PW(fa, 'farm_b', 1.10, 1.40, 1.06, W2, (0, -2.55, 0), taper=0.86)
    P(fa, 'farm_blue', 1.02, 2.25, 0.28, BL1, (0, -1.72, 0.68))
    P(fa, 'farm_decal', 0.34, 0.18, 0.06, RD1, (0, -2.45, 0.60))
    PT(fa, 'wrist', 0.50, 0.50, 0.26, GR3, (0, -3.05, 0), sides=9)

    hand = J(fa, f'hand{s}', (0, -3.28, 0), (p.get(f'hand_pitch{s}', 0), 0, 0))
    P(hand, 'palm', 0.66, 0.80, 0.78, GR1, (0, -0.34, 0.04))
    P(hand, 'knuckle', 0.60, 0.26, 0.62, GR2, (0, -0.66, 0.10))
    for i in range(3):
        P(hand, f'finger{i}', 0.16, 0.34, 0.34, GR2,
          (-0.20 + i * 0.20, -0.88, 0.16))
    P(hand, 'thumb', 0.22, 0.34, 0.26, GR2, (s * 0.30, -0.50, 0.28), rot=(0, 0, s * -18))
    hands[s] = hand
    return hands[s]


# ================================================================ 腰部 A6
def _waist(hips, p):
    P(hips, 'pelvis', 3.20, 1.50, 2.60, GR1, (0, 0, 0))
    P(hips, 'pelvis_panel', 2.40, 0.90, 0.16, GR3, (0, -0.10, 1.32))
    PT(hips, 'waist_tube', 1.10, 1.00, 1.50, GR2, (0, 0.90, 0), sides=10)
    PT(hips, 'waist_ring', 1.30, 1.30, 0.22, GR3, (0, 0.30, 0), sides=10)
    # 前裙甲：中 + 左右（三片，动画机体标准分层）
    PW(hips, 'skirt_front_c', 1.30, 1.70, 0.42, W1, (0, -0.30, 1.22),
       rot=(-6, 0, 0), taper=0.72)
    P(hips, 'skirt_blue', 0.88, 1.08, 0.16, BL1, (0, -0.48, 1.50))
    P(hips, 'skirt_red_band', 1.04, 0.32, 0.12, RD1, (0, 0.26, 1.52))
    for s in (-1, 1):
        PW(hips, f'skirt_front{s}', 0.92, 1.55, 0.40, W2, (s * 1.10, -0.28, 1.10),
           rot=(-6, 0, s * 4), taper=0.74)
        # 侧裙甲：两片叠
        PW(hips, f'skirt_side{s}a', 0.42, 1.90, 2.10, BL1, (s * 1.76, -0.10, 0.10),
           rot=(0, 0, s * 7), taper=0.80)
        PW(hips, f'skirt_side{s}b', 0.20, 1.30, 1.50, BL2, (s * 1.96, -0.30, 0.05),
           rot=(0, 0, s * 10), taper=0.86)
        # 后裙甲
        PW(hips, f'skirt_back{s}', 1.45, 1.40, 0.40, W2, (s * 0.74, -0.12, -1.18),
           rot=(7, 0, 0), taper=0.76)
    # 腰部双刀挂架（造型语法必须保留）：斜挂，柄朝上后
    for s in (-1, 1):
        rack = J(hips, f'rack{s}', (s * 2.00, 0.15, -0.30), (0, 0, s * 9))
        P(rack, 'rack_base', 0.34, 0.80, 0.50, GR1, (0, 0, 0))
        if p.get('saber_on', 0) < 0.2 or s < 0:
            PT(rack, 'hilt', 0.115, 0.115, 1.40, GR2, (0, 0.10, 0), sides=7)
            PT(rack, 'hilt_guard', 0.16, 0.16, 0.14, GR3, (0, 0.78, 0), sides=7)
            PT(rack, 'hilt_cap', 0.10, 0.14, 0.24, RD1, (0, 0.92, 0), sides=7)


# ================================================================ 腿部
def _leg(hips, p, s):
    hip = J(hips, f'hip{s}', (s * 1.62, -0.35, 0),
            (p.get(f'hip_pitch{s}', 0), 0, p.get(f'hip_roll{s}', 0)))
    PT(hip, 'hip_ball', 0.80, 0.80, 1.25, GR2, (0, 0, 0), rot=(0, 0, 90), sides=10)
    PT(hip, 'thigh_core', 0.62, 0.60, 4.20, GR2, (0, -2.20, 0), sides=8)
    # 大腿：主甲 + 外侧甲 + 前蓝条 + 内侧护
    PW(hip, 'thigh_a', 1.34, 3.30, 1.50, W1, (0, -2.15, 0.02), taper=0.82)
    PW(hip, 'thigh_b', 0.50, 2.70, 1.30, W2, (s * 0.82, -2.05, 0),
       rot=(0, 0, s * -7), taper=0.86)
    P(hip, 'thigh_blue', 0.56, 2.20, 0.30, BL1, (0, -2.20, 0.82))
    P(hip, 'thigh_decal', 0.30, 0.18, 0.06, OR1, (0, -0.90, 0.74))
    PT(hip, 'thigh_piston', 0.11, 0.11, 2.40, GR3, (s * -0.42, -2.30, -0.55), sides=5)

    kn = J(hip, f'knee{s}', (0, -4.25, 0), (p.get(f'knee_pitch{s}', 0), 0, 0))
    PT(kn, 'knee_ball', 0.74, 0.74, 1.05, GR2, (0, 0, 0), rot=(0, 0, 90), sides=10)
    # 膝甲：蓝主 + 白边（双层，最显眼的识别点）
    PW(kn, 'knee_cap', 1.36, 1.15, 0.78, BL1, (0, 0.12, 0.66), rot=(-10, 0, 0),
       taper=0.60)
    PW(kn, 'knee_cap_w', 1.10, 0.44, 0.60, W1, (0, 0.52, 0.60), rot=(-10, 0, 0),
       taper=0.66)
    P(kn, 'knee_vent', 0.60, 0.16, 0.14, GR2, (0, -0.16, 0.96))

    sh2 = J(kn, f'shin{s}', (0, 0, 0), (p.get(f'shin_pitch{s}', 0), 0, 0))
    PT(sh2, 'shin_core', 0.66, 0.56, 4.10, GR2, (0, -2.15, 0), sides=8)
    # 小腿：主甲 + 前面板 + 后推进器 + 蓝条
    PW(sh2, 'shin_a', 1.62, 3.60, 1.90, W1, (0, -2.10, -0.05), taper=0.86)
    PW(sh2, 'shin_front', 1.30, 3.10, 0.70, W2, (0, -2.05, 0.72), taper=0.88)
    P(sh2, 'shin_blue', 1.12, 2.60, 0.34, BL1, (0, -2.10, 1.12))
    P(sh2, 'shin_red', 0.94, 1.44, 0.36, RD1, (0, -3.20, 1.16))
    P(sh2, 'shin_decal', 0.40, 0.20, 0.06, RD1, (0, -0.72, 1.04))
    # 后侧小腿推进器
    PW(sh2, 'calf_thr', 1.20, 2.30, 0.90, GR1, (0, -1.70, -0.98), taper=0.8)
    PT(sh2, 'calf_noz', 0.34, 0.42, 0.30, GR2, (0, -2.90, -1.10), sides=7)
    if p.get('thrust', 0) > 0.3:
        PT(sh2, 'calf_flame', 0.30, 0.02, 1.6 * p['thrust'], FLC,
           (0, -3.75 - 0.7 * p['thrust'], -1.10), sides=6)
    # 小腿外侧护板
    PW(sh2, 'shin_out', 0.36, 2.60, 1.40, W2, (s * 0.92, -2.10, 0),
       rot=(0, 0, s * -5), taper=0.88)
    PT(sh2, 'shin_piston', 0.10, 0.10, 2.00, GR3, (s * -0.50, -2.20, -0.40), sides=5)

    an = J(sh2, f'ankle{s}', (0, -4.15, 0), (p.get(f'ankle{s}', 0), 0, 0))
    PT(an, 'ankle_ball', 0.58, 0.58, 0.95, GR2, (0, 0, 0), rot=(0, 0, 90), sides=9)
    PW(an, 'foot_main', 1.50, 0.80, 1.90, W1, (0, -0.58, 0.60), taper=0.88)
    PW(an, 'foot_toe', 1.42, 0.60, 0.95, RD1, (0, -0.66, 1.90), taper=0.72)
    PW(an, 'foot_side{s}', 0.26, 0.62, 2.00, W2, (s * 0.78, -0.56, 0.55), taper=0.9)
    P(an, 'heel', 1.24, 0.74, 0.80, GR1, (0, -0.62, -0.72))
    PT(an, 'ankle_ring', 0.42, 0.42, 0.20, GR3, (0, -0.24, 0), sides=8)


# ================================================================ 主装配
def build_mecha(p):
    root = Node('root', pos=p.get('pos', (0, 0, 0)), rot=p.get('rot', (0, 0, 0)))
    idle = p.get('idle', 0.0)
    hips = J(root, 'hips', (0, 9.90 + 0.018 * math.sin(idle), 0))
    _waist(hips, p)
    chest = _chest(hips, p)
    _backpack(chest, p)
    _head(chest, p)
    hands = {}
    for s in (-1, 1):
        hands[s] = _arm(chest, p, s)
        _leg(hips, p, s)

    # ---- 光束步枪（右手）
    if p.get('rifle_on', False):
        _rifle(hands[1], p)
    # ---- 光剑（右手）
    if p.get('saber_on', 0.0) > 0.02:
        _saber(hands[1], p)
    _apply_props(root, p)
    return root


# ================================================================ 体型标定
# 为什么是「缩放」而不是「改数」：
#   建模时各部件是分开写死的，肩宽由 4 个数共同决定（肩接口 x / 肩球 x /
#   肩甲偏移 / 肩甲宽），腿宽由 3 个（髋 x / 髋球半径 / 大腿宽）。逐个数改
#   既容易漏、也无法回到「上一版体型」。在关节节点上做定向缩放，等于把
#   「体型」抽成一个可覆盖的参数表，几何仍然只有一份。
#
# 标定依据（tools/prop_audit.py 量的，不是拍脑袋）：
#   原始机体：肩宽/机高 0.585（RX-78 是 0.30~0.33，重装型 0.34~0.38）
#             双腿合计/肩宽 0.412（<0.40 就是「一看就不厉害」）
#             头身比 1:10.3（规格 8.2~8.8）
#   收窄上身与双腿、把省下来的量重新分配给腿，两个比例才可能同时落进区间 ——
#   只加粗腿而不收肩，腿/肩 会冲到 0.7 以上，变成「象腿细肩」。
PROP_DEFAULT = dict(
    sx_chest=0.62,     # 上身 X 收窄：胸宽 7.15→4.43（0.234 机高，草图 0.22）
    sz_chest=0.88,     # 胸腔进深略收：4.06→3.57，避免「方桶胸」
    sx_leg=0.80,       # 双腿 X 收窄：4.49→3.59（≈0.55 肩宽）
    sz_foot=0.80,      # 脚长：3.50→2.80（0.148 机高，站得住且不夸张）
    sy_head=1.21,      # 头高：1.81→2.19（头身比 10.3→8.6）
    sx_head=1.613,     # 抵消 sx_chest，头宽保持 1.72（0.264 肩宽）
    sx_arm=1.613,      # 抵消 sx_chest，保住手臂厚度（否则臂被压成竹竿）
)


def _apply_props(root, p):
    q = dict(PROP_DEFAULT)
    q.update({k: v for k, v in p.items() if k.startswith('sx_') or k.startswith('sy_')
              or k.startswith('sz_')})
    for n in _walk(root):
        if n.name == 'chest':
            n.scl = (q['sx_chest'], 1.0, q['sz_chest'])
        elif n.name == 'head':
            n.scl = (q['sx_head'], q['sy_head'], 1.0)
        elif n.name.startswith('upper'):
            n.scl = (q['sx_arm'], 1.0, 1.0)
        elif n.name in ('hip-1', 'hip1'):     # ★ 必须精确匹配：'hip' 前缀会误中 hips 根节点，
            n.scl = (q['sx_leg'], 1.0, 1.0)   #    等于给全身再压一次，肩宽会掉到 0.284
        elif n.name.startswith('ankle'):
            n.scl = (1.0, 1.0, q['sz_foot'])
    return root


def _walk(n):
    yield n
    for c in n.children:
        yield from _walk(c)


def _rifle(hand, p):
    g = J(hand, 'rifle', (0, -0.55, 0.16), (88, 0, 0))
    P(g, 'body', 0.80, 6.20, 0.90, GR1, (0, 1.60, 0))
    P(g, 'body_top', 0.62, 4.40, 0.42, BL1, (0, 2.00, 0.58))
    P(g, 'body_side', 0.20, 3.20, 0.60, GR3, (0.46, 1.70, 0))
    PT(g, 'barrel', 0.24, 0.24, 2.70, GR2, (0, 5.60, 0.05), rot=(90, 0, 0), sides=8)
    PT(g, 'barrel_tip', 0.30, 0.26, 0.40, GR3, (0, 7.00, 0.05), rot=(90, 0, 0), sides=8)
    P(g, 'scope', 0.38, 1.70, 0.36, GR2, (0, 3.20, 0.98))
    P(g, 'scope_gl', 0.20, 0.30, 0.10, SAK, (0, 3.90, 1.00))
    P(g, 'mag', 0.52, 1.30, 0.64, GR2, (0, 1.00, -0.52))
    P(g, 'grip', 0.44, 1.15, 0.52, GR1, (0, -0.25, -0.30), rot=(14, 0, 0))
    P(g, 'stock', 0.52, 1.10, 0.44, GR1, (0, -1.60, 0.10))
    mz = p.get('muzzle', 0.0)
    if mz > 0.02:
        PT(g, 'flash', 0.70 * mz, 0.05, 2.00 * mz, FLC, (0, 8.10, 0),
           rot=(90, 0, 0), sides=7)
        P(g, 'star', 1.10 * mz, 1.10 * mz, 1.10 * mz, SAK, (0, 7.95, 0))


def _saber(hand, p):
    sb = J(hand, 'saber', (0, -0.55, 0.14), (92, 0, 0))
    PT(sb, 'hilt', 0.115, 0.115, 1.50, GR2, (0, 0.20, 0), sides=7)
    PT(sb, 'hilt_g', 0.16, 0.16, 0.16, GR3, (0, 0.86, 0), sides=7)
    PT(sb, 'hilt_cap', 0.10, 0.15, 0.26, RD1, (0, 1.00, 0), sides=7)
    bl = p['saber_on']
    cy = 1.05 + 2.75 * bl
    PT(sb, 'blade_out', 0.24, 0.02, 5.50 * bl, SAK, (0, cy, 0), sides=6)
    PT(sb, 'blade_core', 0.105, 0.010, 5.50 * bl, FLC, (0, cy, 0), sides=6)


# ================================================================ 敌机
def build_enemy(p):
    root = Node('enemy', pos=p.get('pos', (0, 0, -74)), rot=p.get('rot', (0, 0, 0)))
    dead = p.get('dead', 0.0)
    body = J(root, 'e_body', (0, 7.6, 0), (p.get('lean', 0), 0, 0))
    PW(body, 'core', 3.10, 3.50, 2.70, GR1, (0, 0, 0), taper=0.58)
    P(body, 'core_edge', 3.30, 1.20, 2.30, GR2, (0, 1.55, -0.20))
    for s in (-1, 1):
        PW(body, f'pod{s}', 1.70, 1.90, 2.50, BL2, (s * 2.90, 1.15, 0), taper=0.62)
        P(body, f'pod_red{s}', 1.20, 0.22, 0.30, RD1, (s * 2.85, 1.85, 0.9))
        arm = J(body, f'arm{s}', (s * 3.40, 0.85, 0), (12, 0, s * 6))
        PT(arm, 'a1', 0.44, 0.38, 3.40, GR1, (0, -1.70, 0), sides=7)
        PT(arm, 'a2', 0.36, 0.24, 3.00, GR2, (0, -4.80, 0), sides=7)
        PT(arm, 'a3', 0.22, 0.16, 0.70, GR3, (0, -6.50, 0), sides=6)
        PL(arm, 'blade', [(0, 0), (1.10, 0.10), (1.05, 0.26), (0, 0.28)],
           0.10, 'x', GR3, (s * 0.10, -6.90, 0), rot=(0, 0, s * 90))
    head = J(body, 'e_head', (0, 2.35, 0.20))
    PW(head, 'h_a', 1.15, 1.35, 1.55, GR1, (0, 0.20, 0), taper=0.66)
    eye_m = Mat((1.0, 0.22, 0.14), emissive=0.35 + 0.60 * (1 - dead))
    P(head, 'eye', 0.72, 0.17, 0.12, eye_m, (0, 0.10, 0.80))
    P(head, 'eye_bar', 1.00, 0.34, 0.10, GR2, (0, 0.10, 0.74))
    PL(head, 'horn', [(0, 0), (0.74, 0.52), (0.64, 0.70), (0, 0.22)],
       0.07, 'x', RD1, (0, 0.62, 0.10))
    for s in (-1, 1):
        leg = J(root, f'e_leg{s}', (s * 1.55, 7.30, 0), (p.get('leg', 0), 0, 0))
        PT(leg, 'l1', 0.56, 0.46, 4.00, GR2, (0, -2.00, 0), sides=7)
        PT(leg, 'l2', 0.50, 0.32, 3.40, GR1, (0, -5.60, 0), sides=7)
        PW(leg, 'l3', 1.20, 0.66, 2.60, GR2, (0, -7.35, 0.55), taper=0.82)
    P(body, 'pack', 1.70, 1.50, 1.10, GR2, (0, 0.20, -1.70))
    for s in (-1, 1):
        PT(body, f'e_noz{s}', 0.30, 0.38, 0.70, GR3, (s * 0.55, -0.55, -1.90),
           rot=(20, 0, 0), sides=7)
    return root
