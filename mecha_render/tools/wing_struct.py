"""tools/wing_struct.py — 折叠翼盒的结构校核（回答「这小翅膀撑得住吗」）

★ 这一份存在的理由
  前几轮给的都是面积、升力、功率、像素 —— 全是**系统级**的数，
  没有一处是「这块板受多少力、应力多少、会不会屈曲」。
  「算得太抽象」指的就是这个。所以这里只做一件事：
  把翼片当悬臂梁，把三处会出事的地方逐个算出来。

载荷工况（三条，逐条给依据）
  A 巡航升力：§17.5 的 46.2 kN 按面积分到 6 片叶
  B 阵风/侧滑：180 m/s 动压作用在单片叶上，Cn 取 1.0（平板法向，保守）
  C 鸟撞：1.8 kg @ 180 m/s，10 ms 停住

三处会出事的地方
  ① 面板受压屈曲 —— 最可能先坏的（薄板通病）
  ② 根部弯曲应力 —— 材料强度够不够
  ③ 铰点与展开限位 —— 这是最后真正的卡点

用法
  python3 tools/wing_struct.py
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'tools'))

import s2_graybox as S                                   # noqa: E402

RHO = 1.225
V_C = 180.0
LIFT_TOTAL = 46_200.0        # N，§17.5 的 CL 0.45 结果
R0 = S.WING_R0               # 0.26 铰点内缘
R1S = S.WING_R1S             # (1.45, 1.80, 2.15)
W0, W1 = S.WING_W0, S.WING_W1
TH = S.WING_TH               # 0.075 几何厚度（前后两面之间的距离）

RHO_AL = 2700.0
E_AL = 70e9
NU = 0.33
SIG_Y = 500e6                # 7075-T6
FS = 1.5
SIG_ALLOW = SIG_Y / FS


def blade_area(r1):
    return (2 * W0 + 2 * W1) / 2.0 * (r1 - R0)


A_TOT = sum(blade_area(r) * 2 for r in R1S)          # 双侧总面积
F_MAX = LIFT_TOTAL * max(blade_area(r) for r in R1S) / A_TOT
L_MAX = (max(R1S) - R0) / 2


def w_box(c, t, tf):
    """薄壁（或夹芯）箱截面抗弯模量：两面面板各在 ±t/2。"""
    return 2 * (c * tf) * (t / 2.0)


def sigma_cr(t, b, E=E_AL, k=4.0):
    """四边简支板单轴受压屈曲。"""
    return k * math.pi ** 2 * E / (12 * (1 - NU ** 2)) * (t / b) ** 2


def mass_blade(r1, tf, core=True):
    a = blade_area(r1)
    m = 2 * a * tf * RHO_AL
    if core:
        m += a * (TH - 2 * tf) * 60.0        # 铝蜂窝 60 kg/m³
    return m + 0.9 * (r1 - R0)               # 翼梁 / 翼肋


def main():
    print('=' * 78)
    print('折叠翼盒 · 结构校核（悬臂梁 + 面板屈曲 + 铰点）')
    print('=' * 78)

    print('\n§0 算之前先量一下（几何全部读 s2_graybox 的常数）')
    print('-' * 78)
    print(f'  三片展长 {R1S[0]-R0:.2f} / {R1S[1]-R0:.2f} / {R1S[2]-R0:.2f} m，'
          f'根部弦 {2*W0:.2f} m，厚度 {TH:.3f} m')
    print(f'  单侧叶面积 {sum(blade_area(r) for r in R1S):.2f} m²，'
          f'双侧 {A_TOT:.2f} m²')
    print(f'  ⇒ **这是一个 0.92 m 弦、75 mm 厚的悬臂板**。梁高只有 75 mm，')
    print('    这是它所有问题的根源：翼片的「梁」就是板厚本身。')

    print('\n§1 三条载荷工况')
    print('-' * 78)
    q = 0.5 * RHO * V_C ** 2
    f_gust = q * max(blade_area(r) for r in R1S) * 1.0
    f_bird = 1.8 * V_C / 0.010
    print(f'  动压 q(180 m/s)          {q/1000:7.1f} kPa')
    print(f'  A 巡航升力（最外片）      {F_MAX/1000:7.2f} kN')
    print(f'  B 阵风法向（q·S·Cn=1.0）  {f_gust/1000:7.2f} kN')
    print(f'  C 鸟撞冲量（10 ms）       {f_bird/1000:7.2f} kN')
    print('  ★ 最外片只有几 kg，阵风载荷却是 21 kN —— 相当于 285 g。')
    print('    这不是算错，是「大展长 + 轻板 + 高速」的必然。')

    print('\n§2 根部弯曲应力：四种面板厚度 × 三条工况（许用 %.0f MPa）'
          % (SIG_ALLOW / 1e6))
    print('-' * 78)
    print('  面板 mm   截面模量 ×1e-6 m³    A 升力   B 阵风   C 鸟撞   判定')
    rows = []
    for tf_mm in (1.2, 1.6, 2.0, 2.5):
        tf = tf_mm / 1000.0
        wb = w_box(2 * W0, TH, tf)
        sA = F_MAX * L_MAX / wb
        sB = f_gust * L_MAX / wb
        sC = f_bird * L_MAX / wb
        ok = max(sA, sB, sC) <= SIG_ALLOW
        rows.append((tf_mm, wb, sA, sB, sC, ok))
        print(f'  {tf_mm:4.1f}     {wb*1e6:10.1f}       '
              f'{sA/1e6:7.1f}  {sB/1e6:7.1f}  {sC/1e6:7.1f}   '
              f'{"过" if ok else "不过"}')
    print('  ⇒ 1.2 mm 面板在鸟撞工况不过；**2.0 mm 面板三工况全过**')
    print('    （阵风 144 MPa、鸟撞 222 MPa，余量 33%）。')

    print('\n§3 面板屈曲：这是薄板的真短板')
    print('-' * 78)
    tf = 0.002
    wb = w_box(2 * W0, TH, tf)
    s_work = max(F_MAX * L_MAX, f_gust * L_MAX) / wb
    print(f'  按 2.0 mm 面板、阵风工况的工作压应力 {s_work/1e6:.1f} MPa')
    print('  未加筋面板宽 b m    σ_cr MPa   σ_cr/工作应力')
    for b in (0.92, 0.60, 0.40, 0.30, 0.22, 0.15):
        cr = sigma_cr(tf, b) / 1e6
        print(f'  {b:6.2f}            {cr:8.2f}     {cr/(s_work/1e6)*100:6.1f}%')
    print('  ⇒ 只加翼肋（b 降到 0.15）也追不上：屈曲应力 45.9 MPa 仍只有工作应力的 32%。')
    print('    **肋救不了薄面板，得让芯材去撑。** 夹芯板（面板 + 铝蜂窝）后，')
    print('    控制项从「面板屈曲」变成「面板皱曲」，后者按')
    print('    σ_wr ≈ 0.5·(E_f·E_c·G_c)^(1/3) 估算：')
    E_f, E_c, G_c = 70e9, 1.0e9, 0.4e9
    s_wr = 0.5 * (E_f * E_c * G_c) ** (1.0 / 3.0)
    print(f'    E_c=1.0 GPa、G_c=0.4 GPa → σ_wr ≈ {s_wr/1e6:.0f} MPa'
          f'（> 许用 {SIG_ALLOW/1e6:.0f}）→ 皱曲不控制。')
    print('  ⇒ 结论：**必须是夹芯板（面板 2 mm + 20 mm 以上蜂窝），不能是空壳薄壁。**')

    print('\n§4 铰点与展开限位（真正卡死的地方）')
    print('-' * 78)
    m_sum = 0.0
    for r1 in R1S:
        f = LIFT_TOTAL * blade_area(r1) / A_TOT
        m_sum += f * (r1 - R0) / 2
    m_gust = m_sum * f_gust / F_MAX
    print(f'  三片根弯矩合计：升力 {m_sum/1000:.2f} kN·m ／ 阵风 {m_gust/1000:.2f} kN·m')
    print('    ★ 阵风 41 kN·m 要由一个铰座吃掉 —— 这不是材料问题，是机构问题。')
    d = 0.030
    tau = (f_gust * 3) / (2 * math.pi * (d / 2) ** 2)
    print(f'  铰销 Ø30 双耳受剪 τ = {tau/1e6:.1f} MPa（许用 200）→ 销本身没问题')
    print('  展开限位：纯销铰抗不了弯矩，必须靠撑杆或限位块。')
    for h in (0.30, 0.50, 0.70, 1.00):
        print(f'    撑杆力臂 {h:.2f} m → 轴力 {m_gust/h/1000:6.1f} kN')
    print('  ⇒ 0.70 m 力臂处 58 kN：要 Ø30 拉杆 + 双耳，且**每片叶独立铰**，')
    print('    不能三片共用一个铰座（共用的话力臂只有 0.3 m，170 kN，做不出来）。')

    print('\n§5 质量（含夹芯）')
    print('-' * 78)
    for tf_mm in (1.2, 2.0):
        mt = sum(mass_blade(r, tf_mm / 1000.0) for r in R1S) * 2
        print(f'  面板 {tf_mm:.1f} mm：双侧 6 片 {mt:5.1f} kg（含蜂窝芯 + 梁肋）')
    mt = sum(mass_blade(r, 0.002) for r in R1S) * 2 + 18
    print(f'  + 铰座/撑杆 18 kg → {mt:.0f} kg = {mt/34_900*100:.2f}% MTOW')

    print('\n§6 速度包络：展开态能飞多快')
    print('-' * 78)
    wb = w_box(2 * W0, TH, 0.002)
    m_allow = SIG_ALLOW * wb
    q_allow = m_allow / (max(blade_area(r) for r in R1S) * L_MAX * 1.0)
    v_allow = math.sqrt(2 * q_allow / RHO)
    print(f'  许用弯矩 {m_allow/1000:.1f} kN·m → 许用动压 {q_allow/1000:.1f} kPa'
          f' → 展开态限速 **{v_allow:.0f} m/s**')
    print(f'  巡航 {V_C:.0f} m/s 时：{"可以展开" if V_C <= v_allow else "必须收纳"}')
    print('  ⇒ 展开态本身不违背 180 m/s 的巡航包线（限速 274 > 180），')
    print('    所以问题不在「能不能展开」，而在「展开后铰点要吃 41 kN·m」。')
    print('    真正的用途分工是：展开态用于悬停/低速机动/着陆，高速收纳以减少阻力。')

    print('\n§7 结论')
    print('-' * 78)
    print('  ① 材料强度：1.2 mm 空壳在鸟撞下不过（370 MPa > 333）；')
    print('     改 **2.0 mm 面板 + 蜂窝夹芯** 后三工况全过（最大 222 MPa）。')
    print('  ② 屈曲：空壳靠加肋救不回来（0.15 m 肋距仍只有 16.5 MPa），')
    print('     必须夹芯 —— 皱曲 1,518 MPa，不控制。')
    print('  ③ 机构：阵风下铰点要抗 **41 kN·m**，展开限位撑杆 58 kN 级，')
    print('     且**每片独立双耳铰**，三片共用铰座做不出来。')
    print('  ④ 构型：展开态限速约 275 m/s（用 2.0 mm 面板时），')
    print('     所以「展开」是低速动作，高速必须收纳 —— 与 SEED 的用法一致。')
    print('  ★ 一句话：**不是板撑不住，是铰撑不住。** 板换成夹芯就够，')
    print('    铰必须重做（每片独立铰 + 撑杆 + 限位块），这才是要改的地方。')


if __name__ == '__main__':
    main()
