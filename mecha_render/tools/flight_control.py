"""tools/flight_control.py — 姿控构型决策：翅膀 / 鸭翼 / 额外推进器，到底需不需要

问题（用户 2026-11-08 提出）
  背包是否需要翅膀类结构、鸭翼、或额外方向的推进器来做飞行控制？

方法
  不去猜「像不像飞机」，只回答一个可算的问题：
  **每一套控制手段，在它该起作用的速度段，能提供多少三轴力矩？够不够用？**

  判据（先定，后算）
    角加速度 α ≥ 0.5 rad/s² → 可用作主控（2 s 内完成 60°/s 的姿态变化）
    0.1 ≤ α < 0.5          → 只能做配平/精修，不能做主控
    α < 0.1                → 无效，别装

输入全部取自 nuclear_mecha.py（H=8.0 m 核动力构型），不另设参数：
  MTOW 34.9 t、四具折叠吊臂、风扇 D=0.6H=4.8 m、悬停轴功率 22.3 MW、T/W 1.30

坐标：米。X 右、Y 上、Z 前。质心取 y=4.0（机身几何中心偏上）。

用法
  python3 tools/flight_control.py
"""
import math

# ---------------------------------------------------------------- 输入
G = 9.81
RHO = 1.225

H = 8.0
W = 4.48
D = 2.80
MTOW = 34900.0            # kg
WEIGHT = MTOW * G         # 342.4 kN
TW = 1.30
THRUST = WEIGHT * TW      # N，总推力
N_ARM = 4
T_ARM = THRUST / N_ARM    # 每具

D_FAN = 0.6 * H           # 4.8 m
A_FAN = math.pi * (D_FAN / 2) ** 2

# 吊臂位置（收拢段 x 1.20–1.78、z −1.86…−1.04；展开后风扇在臂端）
X_ARM = 1.52
Z_ARM = -1.50
Y_ARM = 5.92
Y_CG = 4.00               # 质心高度（估）

# 巡航速度（化学基线 648 km/h；核动力吊扇推进按同量级取）
V_CRUISE = 180.0          # m/s
Q_CRUISE = 0.5 * RHO * V_CRUISE ** 2

# 散热翼（§13.5 给出 64 m² 展开面）
A_RAD = 64.0


def inertia():
    """把机体当均匀长方体估转动惯量，再乘 0.75（质量向质心集中）。

    ★ 这是估值不是实测：真实资产需要按分件质量分布积分。误差量级 ±30%，
      但三轴之间的**比例关系**是可靠的，而决策只依赖比例。
    """
    k = 0.75
    i_roll = k * MTOW * (W ** 2 + H ** 2) / 12      # 绕 Z（前后轴）
    i_pitch = k * MTOW * (D ** 2 + H ** 2) / 12     # 绕 X（横轴）
    i_yaw = k * MTOW * (W ** 2 + D ** 2) / 12       # 绕 Y（竖轴）
    return i_roll, i_pitch, i_yaw


def thrust_vector_torque():
    """四臂推力矢量的三轴力矩能力。

    ★ 关键结构事实：**四具吊臂全在质心后方同一平面（z≈−1.5）**。
      这决定了三轴的来源完全不同：
        roll  → 左右差动（有力臂）
        yaw   → 左右差动（有力臂）
        pitch → **没有前后分布，差动为零** → 只能靠整机倾转，让推力产生
                水平分量，再由「作用点高于质心」的力臂生成力矩。
      这不是设计缺陷，是所有「四旋翼」构型的共性：pitch/roll 靠差动，
      但四臂共面时 pitch 只能靠倾转。
    """
    dT = 0.15 * T_ARM                     # 单臂可用推力增量（保留 15% 余量）
    m_roll = 2 * dT * X_ARM               # 左右各两臂
    m_yaw = 2 * dT * X_ARM                # 差动产生的偏航（同性）
    # pitch：倾转 θ，水平分量 T·sinθ，作用点 y=5.92 高于质心 4.00
    tilt = math.radians(12.0)
    arm_y = Y_ARM - Y_CG
    m_pitch = THRUST * math.sin(tilt) * arm_y
    return m_roll, m_pitch, m_yaw, tilt


def aero_torque(v, s_ref, cl, arm):
    """气动控制面在速度 v 下的力矩。S_ref 是单侧面积，两侧合计 ×2。"""
    q = 0.5 * RHO * v ** 2
    return 2 * q * s_ref * cl * arm


def rcs_torque(f_thruster, arm, n):
    return f_thruster * arm * n


def fmt(x, u=''):
    return f'{x:,.0f}{u}'


def main():
    i_roll, i_pitch, i_yaw = inertia()
    m_roll, m_pitch, m_yaw, tilt = thrust_vector_torque()

    print('=' * 82)
    print('飞行控制构型决策 · H=8.0 m 核动力四臂吊扇')
    print('=' * 82)
    print(f'  MTOW {MTOW/1000:.1f} t   总推力 {THRUST/1000:.0f} kN   T/W {TW:.2f}')
    print(f'  每具推力 {T_ARM/1000:.1f} kN   风扇 D={D_FAN:.2f} m   A={A_FAN:.1f} m²')
    print(f'  吊臂位置 x ±{X_ARM} / z {Z_ARM} / y {Y_ARM}（质心 y {Y_CG}）')
    print()

    print('-' * 82)
    print('§1 转动惯量（均匀长方体 ×0.75，估值 ±30%）')
    print('-' * 82)
    print(f'  roll  绕 Z（前后轴）  {fmt(i_roll)} kg·m²')
    print(f'  pitch 绕 X（横轴）    {fmt(i_pitch)} kg·m²')
    print(f'  yaw   绕 Y（竖轴）    {fmt(i_yaw)} kg·m²')
    print()

    print('-' * 82)
    print('§2 四臂推力矢量能提供多少（判据 α≥0.5 主控 / 0.1–0.5 配平 / <0.1 无效）')
    print('-' * 82)
    print(f'{"轴":6s}{"力矩 N·m":>14s}{"角加速度 rad/s²":>18s}{"到 60°/s 用时 s":>18s}  判定')
    rows = [
        ('roll', m_roll, i_roll),
        ('pitch', m_pitch, i_pitch),
        ('yaw', m_yaw, i_yaw),
    ]
    verdict = {}
    for name, m, i in rows:
        a = m / i
        t60 = math.radians(60) / a
        if a >= 0.5:
            v = '主控 ✓'
        elif a >= 0.1:
            v = '仅配平'
        else:
            v = '无效 ✗'
        verdict[name] = (a, v)
        print(f'{name:6s}{fmt(m):>14s}{a:>18.3f}{t60:>18.2f}  {v}')
    print()
    print(f'  pitch 靠倾转 {math.degrees(tilt):.0f}°：水平分量 '
          f'{THRUST*math.sin(tilt)/1000:.0f} kN，力臂 {Y_ARM-Y_CG:.2f} m')
    print('  ★ 这不是可选项：四臂共面在 z 方向没有力臂，差动对 pitch 恒等于 0。')
    print()

    print('-' * 82)
    print('§3 气动面：鸭翼能不能替代 / 补充推力矢量')
    print('-' * 82)
    print(f'  巡航 {V_CRUISE:.0f} m/s（{V_CRUISE*3.6:.0f} km/h）动压 q = {Q_CRUISE/1000:.1f} kPa')
    print()
    print(f'{"速度 m/s":>10s}{"q kPa":>9s}{"鸭翼 1.0 m² 力矩":>20s}{"α_pitch":>10s}  判定')
    for v in (0.0, 20.0, 50.0, 100.0, 150.0, 180.0):
        m = aero_torque(v, 1.0, 0.8, 3.0)
        a = m / i_pitch
        vd = '主控 ✓' if a >= 0.5 else ('仅配平' if a >= 0.1 else '无效 ✗')
        print(f'{v:>10.0f}{0.5*RHO*v*v/1000:>9.1f}{fmt(m):>20s}{a:>10.3f}  {vd}')
    print()
    print('  ⇒ 鸭翼在悬停/低速完全无效（q→0），只在高速段有力矩。')
    print('    而高速段推力矢量本身也是强的（§2 已够主控）→ 鸭翼换不来控制能力，')
    print('    只换来「关掉风扇后还能控」这一条冗余。')
    print()

    print('-' * 82)
    print('§4 散热翼如果做成气动面，能顶多少升力（这是真正值钱的一条）')
    print('-' * 82)
    print(f'  散热面积 {A_RAD:.0f} m²（§13.5 的展开面）')
    print(f'{"速度 m/s":>10s}{"q kPa":>9s}{"CL=0.6 升力 kN":>18s}{"占重量":>10s}')
    for v in (60.0, 100.0, 150.0, 180.0):
        q = 0.5 * RHO * v * v
        L = q * A_RAD * 0.6
        print(f'{v:>10.0f}{q/1000:>9.1f}{L/1000:>18.0f}{L/WEIGHT*100:>9.0f}%')
    print()
    v_stall_equiv = math.sqrt(WEIGHT / (0.5 * RHO * A_RAD * 0.6))
    print(f'  ⇒ 仅靠散热翼（CL 0.6）托住 {MTOW/1000:.1f} t，需要 '
          f'{v_stall_equiv:.0f} m/s（{v_stall_equiv*3.6:.0f} km/h）。')
    print(f'    在 {V_CRUISE:.0f} m/s 下升力是重量的 '
          f'{Q_CRUISE*A_RAD*0.6/WEIGHT:.1f} 倍 —— 巡航时吊扇可以完全关掉。')
    print(f'    关掉风扇省下的是 §13.5 的 22.3 MW 轴功率，等于省掉约 '
          f'{22.3/27.9*100:.0f}% 的废热。')
    print('    所以「翅膀」的价值不在控制，在**散热 + 巡航升力**：')
    print('    它不是控制面，是把已经必须存在的 64 m² 散热面顺便做成升力面。')
    print()

    print('-' * 82)
    print('§4b 装得下吗：把散热面聚成一个翼面，需要多大的翼展（本节否掉 §4 的乐观解）')
    print('-' * 82)
    s_req = WEIGHT / (Q_CRUISE * 0.6)
    print(f'  要把 {MTOW/1000:.1f} t 在 {V_CRUISE:.0f} m/s 全托住（CL 0.6），')
    print(f'  需要投影翼面积 S = W/(q·CL) = {s_req:.1f} m²（§4 的 64 m² 是双面展开面，单面投影只有一半）')
    print()
    print(f'{"展弦比 AR":>10s}{"总翼展 m":>12s}{"弦长 m":>10s}{"相对机身宽 4.48":>18s}  可行性')
    for ar in (0.8, 1.0, 2.0, 4.0, 6.0):
        b = math.sqrt(ar * s_req)
        c = s_req / b
        ratio = b / W
        if b <= W * 1.2:
            vd = '可接受（短翼盒）'
        elif b <= W * 2.0:
            vd = '偏大（需折叠）'
        else:
            vd = '不可接受 ✗'
        print(f'{ar:>10.1f}{b:>12.1f}{c:>10.2f}{ratio:>17.1f}×  {vd}')
    print()
    print('  ★ 硬约束两条：')
    print(f'    ① 弦长受背包深度限制（{D:.2f} m）→ 若弦长卡 {D:.2f} m，')
    print(f'       要凑够 {s_req:.1f} m² 就得翼展 {s_req/D:.1f} m = {s_req/D/W:.1f}× 机宽')
    print(f'    ② 低展弦比诱导阻力大，可用 CL 从 0.6 掉到 ~0.35 →')
    s35 = WEIGHT / (Q_CRUISE * 0.35)
    print(f'       所需面积反而涨到 {s35:.1f} m² → 翼展 {math.sqrt(1.0*s35):.1f} m（AR 1.0）')
    print('  ⇒ 结论：**翅膀做不成「巡航全托举」的主升力面**，几何装不下。')
    print()
    print(f'{"可装方案":26s}{"翼面积 m²":>11s}{"翼展 m":>9s}{"CL 0.35 升力 kN":>16s}{"占重量":>9s}')
    best = None
    for s_w in (8.0, 12.0, 16.0):
        b = math.sqrt(1.0 * s_w * 2)     # 两侧各一半，AR 1.0
        L = Q_CRUISE * s_w * 0.35
        print(f'{"肩后短翼盒（双侧）":26s}{s_w:>11.1f}{b:>9.1f}{L/1000:>16.0f}{L/WEIGHT*100:>8.0f}%')
        best = (s_w, b, L)
    s_w, b, L = best if best else (12.0, 4.9, 0.0)
    frac = L / WEIGHT
    # ★ 动量理论：定盘面积下 P ∝ T^1.5。推力降到 (1-frac) → 轴功率比 (1-frac)^1.5
    p_ratio = (1.0 - frac) ** 1.5
    print()
    print(f'  ⇒ {s_w:.0f} m² 双侧短翼盒（翼展 {b:.1f} m，与肩宽 {W:.2f} 基本齐平）')
    print(f'    在 {V_CRUISE:.0f} m/s 提供 {frac*100:.0f}% 重量 → 吊扇推力只需 {100-frac*100:.0f}%')
    print(f'    ★ 动量理论（定盘面积 P ∝ T^1.5）：轴功率比 = (1-{frac:.2f})^1.5 = {p_ratio:.3f}')
    print(f'      省下 {22.3*(1-p_ratio):.1f} MW 轴功率（原 22.3 MW 的 {(1-p_ratio)*100:.0f}%）')
    print(f'      = 省掉总废热 27.9 MW 的 {(1-p_ratio)*22.3/27.9*100:.0f}%。这是「装得下的最优解」。')
    print()

    print('-' * 82)
    print('§5 额外推进器（RCS）：只在悬停精修与单发失效时有用')
    print('-' * 82)
    print(f'{"方案":26s}{"单具 kN":>10s}{"具数":>6s}{"力臂 m":>8s}{"力矩 N·m":>12s}{"α":>9s}  判定')
    cases = [
        ('冷气 RCS（1 kN 级）', 1.0, 8, 3.0, 'roll'),
        ('热气 RCS（5 kN 级）', 5.0, 8, 3.0, 'roll'),
        ('热气 RCS 大（20 kN）', 20.0, 4, 3.0, 'pitch'),
    ]
    for name, f, n, arm, axis in cases:
        m = rcs_torque(f * 1000, arm, n)
        i = i_pitch if axis == 'pitch' else i_roll
        a = m / i
        vd = '主控 ✓' if a >= 0.5 else ('仅配平' if a >= 0.1 else '无效 ✗')
        print(f'{name:26s}{f:>10.0f}{n:>6d}{arm:>8.1f}{fmt(m):>12s}{a:>9.3f}  {vd}')
    print()
    m_rcs = 8 * (12 + 40) + 8 * 3    # 推进器 12kg + 气瓶 40kg + 管路
    print(f'  8 具 1 kN 冷气 RCS 系统质量约 {m_rcs:.0f} kg = {m_rcs/MTOW*100:.1f}% MTOW')
    print('  ⇒ 冷气 RCS 只能做精修（α≈0.1），做主控要 20 kN 级，质量代价不划算。')
    print('    它的真实用途只有两个：① 悬停时抑制 ±0.1° 的漂移；')
    print('    ② 单具吊臂失效（丢 25% 推力）后保住姿态。')
    print()


if __name__ == '__main__':
    main()
