"""tools/wing_box.py — 折叠翼盒（SEED 自由/正义口径）的定量账

回答三个问题，每个都给可复算的数：
  ① 装得下吗：收纳态是否还在原包络内、展开态翼展多大
  ② 值不值  ：散热面挪出多少、巡航升力多少、省多少轴功率
  ③ 控不控得住：翼尖游标能不能替代或补充四臂差动

★ 翼片几何全部从 s2_graybox.py 的常数读，不在这里另设一套 ——
  两份参数一旦分叉，文档里的数就和模型对不上了。

用法
  python3 tools/wing_box.py
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'tools'))

import s2_graybox as S                                   # noqa: E402

RHO = 1.225
G = 9.81
H = 8.0
W_BODY = 2 * 2.240          # 肩甲外缘 ±2.240
MTOW = 34900.0
WEIGHT = MTOW * G
T_W = 1.30
THRUST = WEIGHT * T_W
P_HOVER = 22.3e6            # §13.5 悬停轴功率
Q_TOTAL = 27.9e6            # 总废热
A_RAD_TOTAL = 64.0          # §13.5 散热面
V_C = 180.0

I_ROLL = 183_379.0          # flight_control.py §1


def blade_area(r1):
    """单叶片投影面积：梯形，半弦 W0→W1。"""
    chord = (2 * S.WING_W0 + 2 * S.WING_W1) / 2.0
    return chord * (r1 - S.WING_R0)


def tip(ang, swp, r1):
    """叶尖坐标（相对铰点，右手侧）。Rz 先、Ry 后，与 Node.local 一致。"""
    a, b = math.radians(ang), math.radians(swp)
    x = r1 * math.cos(a) * math.cos(b)
    z = -r1 * math.cos(a) * math.sin(b)
    y = r1 * math.sin(a)
    return x, y, z


def main():
    print('=' * 80)
    print('折叠翼盒 · 定量账（参数直读 s2_graybox.py）')
    print('=' * 80)
    print(f'  铰点 x ±{S.WING_HX:.2f} / y {S.WING_HY:.2f}')
    print(f'  叶片 {len(S.WING_R1S)} 片，长度 {S.WING_R1S} m，'
          f'半弦 {S.WING_W0}→{S.WING_W1}，厚 {S.WING_TH}')
    print()

    print('-' * 80)
    print('§1 装得下吗')
    print('-' * 80)
    a_side = sum(blade_area(r) for r in S.WING_R1S)
    a_both = 2 * a_side
    print(f'  叶面积      单侧 {a_side:.2f} m²   双侧 {a_both:.2f} m²')
    print(f'  翼盒质量    ~{a_both * 11.0:.0f} kg（11 kg/m²：钛蜂窝 + 铰 + 作动筒），'
          f'占 MTOW {a_both * 11.0 / MTOW * 100:.1f}%')
    print()
    # ★ 包络一律**量模型**，不手算。手算漏掉「翼根弦宽在 x 方向的投影」，
    #   会把收纳态翼展算成 4.43，实测是 4.715 —— 差的就是那 0.46 m 半弦。
    import numpy as np
    from gfx.mesh import Mesh, collect2
    rows = []
    for name, dep in (('收纳', 0.0), ('展开', 1.0)):
        S.WING_DEPLOY = dep
        root, _ = S.build()
        me = Mesh()
        collect2(root, me)
        P = np.array(me.P).reshape(-1, 3)
        mb = Mesh()
        for c in root.children:
            if c.name != 'wings':
                collect2(c, mb)
        Q = np.array(mb.P).reshape(-1, 3)
        rows.append((name,
                     P[:, 0].max() - P[:, 0].min(),
                     P[:, 1].max() - P[:, 1].min(),
                     P[:, 2].max() - P[:, 2].min(),
                     P[:, 0].max() - Q[:, 0].max()))
    hdr = '构型      全机包络 W x H x D (m)   每侧超出本体 (m)'
    print(hdr)
    for name, w, h, d, dx in rows:
        print(f'{name}    {w:7.3f} x {h:6.3f} x {d:6.3f}        {dx:6.2f}')
    print()
    print(f'  ⇒ 展开态翼展 {rows[1][1]:.2f} m = {rows[1][1] / W_BODY:.2f}× 本体宽 {W_BODY:.2f}')
    print(f'     收纳态每侧只超出本体 {rows[0][4]:.2f} m —— 这是翼根弦宽，折叠的几何代价。')
    print('     本体包络 4.480 × 7.920 × 2.800 一点没动：翼盒是铰接附件，')
    print('     不参与 W/H 0.561 这条线稿口径。拿含翼包络去比 0.561 只会得到假结论。')
    print()

    print('-' * 80)
    print('§2 值不值（散热 + 巡航升力）')
    print('-' * 80)
    rad = 2 * a_both
    print(f'  散热面外置  {a_both:.2f} m² 投影 × 两面 = {rad:.2f} m²，'
          f'占 64 m² 的 {rad / A_RAD_TOTAL * 100:.0f}%')
    print(f'  被遮挡最严重的位置恰好是机身背部 —— 挪出去的每一 m² 都比在蒙皮上值钱。')
    print()
    q = 0.5 * RHO * V_C ** 2
    for cl in (0.35, 0.45, 0.55):
        L = q * a_both * cl
        frac = L / WEIGHT
        pr = (1 - frac) ** 1.5
        print(f'  CL {cl:.2f}：{V_C:.0f} m/s 升力 {L/1000:5.1f} kN = 重量 {frac*100:4.1f}%'
              f'  → 吊扇推力 {100-frac*100:4.1f}%，轴功率比 {pr:.3f}，'
              f'省 {P_HOVER*(1-pr)/1e6:4.1f} MW')
    print()
    print(f'  ★ 隔离流（三片叠展）比单一大翼面 CL 高：缝翼效应，取 0.45 而不是 0.35。')
    print(f'    这是「三片」相对「一整块」唯一在气动上的好处，也是选扇形的第二个理由。')
    print()

    print('-' * 80)
    print('§3 控不控得住（翼尖游标 vs 四臂差动）')
    print('-' * 80)
    r_tip = rows[1][1] / 2.0
    print(f'  翼尖力臂 {r_tip:.2f} m（四臂是 {1.52:.2f} m，{r_tip/1.52:.2f}×）')
    print(f'{"方案":22s}{"单具 kN":>9s}{"具数":>6s}{"力矩 N·m":>12s}{"α_roll":>9s}  判定')
    for name, f, n in (('冷气 1 kN ×4（翼尖）', 1.0, 4),
                       ('冷气 1 kN ×8（四臂+翼尖）', 1.0, 8),
                       ('热气 5 kN ×4（翼尖）', 5.0, 4)):
        M = f * 1000 * r_tip * n
        a = M / I_ROLL
        vd = '主控 ✓' if a >= 0.5 else ('仅配平' if a >= 0.1 else '无效 ✗')
        print(f'{name:22s}{f:>9.0f}{n:>6d}{M:>12,.0f}{a:>9.3f}  {vd}')
    print(f'  四臂差动单轴 50,739 N·m → α 0.277（flight_control.py §2）')
    print()
    print('  ⇒ **翼尖游标补不上 roll**。1 kN 级 4 具只有 '
          f'{(1000*r_tip*4)/I_ROLL:.3f}，'
          '比四臂差动还弱；')
    print('    要主控得 5 kN 级，那是 20 kN 总推力的热气系统，质量 3–5% MTOW。')
    print('    所以翼尖游标的定位仍然是 §16.6 那两条：悬停抑漂 + 单臂失效备份，')
    print('    **不是**新增一条主控通道。翅膀在控制上的价值是 AMBAC 效应面')
    print('    （真空/稀薄大气里靠反作用质量转动），那要在轨/高空才成立，')
    print('    大气层内它就是个散热+升力件。')
    print()


if __name__ == '__main__':
    main()
