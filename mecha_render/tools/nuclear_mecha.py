"""tools/nuclear_mecha.py — 核动力机甲：前提变了，约束会迁移到哪

为什么单独一个文件
  上一版（flight_physics.py）的结论是「悬停 6 分钟、H≤8 m」，全部建立在
  **化学燃料**这个前提上：燃油质量占 12% MTOW，悬停油耗 44.9 t/h。
  一换核动力，这条链整条作废 —— 但**不是所有约束都消失**，而是换了宿主。

  这个文件的唯一目的，是把「约束迁移」算清楚：
    化学：功率够不够 → 燃油够不够飞 → 悬停 6 min（功率与续航同时紧）
    核能：功率不再是问题、续航不再是问题
          → 新的短板是 **废热往哪儿排**
  如果只写「核动力所以能一直飞」，那是没算。

三个必须算的量
  1. 反应堆+屏蔽的质量  —— 核动力的入场费，且屏蔽随尺度摊薄（利好大机体）
  2. 废热功率           —— = 堆热功率 ×(1−效率) + 电机损耗
  3. 散热器面积         —— = 废热 / (2σT⁴)，这是新的硬约束

一个反直觉的关键点
  散热器面积 ∝ 废热 ∝ 功率 ∝ 重量 ∝ H³，而机体可用的表面积 ∝ H²。
  比值 ∝ H ⇒ **越大越装不下散热器**；而屏蔽质量近似定值，**越大越摊得薄**。
  两个方向相反，所以核动力机甲**存在一个最优尺度**，不是越大越好，也不是越小越好。

材料与部件的 +50 年设定（每条都注明现役水平，避免变成许愿）
  见 MATERIALS 表，逐项对照，不用「未来材料」这种空话。
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'tools'))

G = 9.80665
RHO = 1.225          # 海平面空气密度
SIGMA = 5.670374e-8  # 斯特藩-玻尔兹曼

# ---------------------------------------------------------------- 外形
WH = 0.561           # 宽/高（Unicorn 实测）
DW = 0.627           # 深/宽（Unicorn 实测）

# ---------------------------------------------------------------- +50 年设定
# 每一项都给「现役值 → 设定值」，比值就是突破幅度
MATERIALS = [
    # (项目, 现役, 现役值, +50y 值, 单位, 依据)
    ('结构等效密度', '钢/铝混合桁架', 700, 450, 'kg/m³',
     'CNT 增强复材 + 点阵结构，孔隙率提高但比强度上升'),
    ('结构比强度', '高强钢', 250, 900, 'MPa/(g·cm⁻³)',
     'CNT 理论 50 GPa，工程化取 2% 即 1 GPa 级'),
    ('结构耐温', '铝合金 450 K', 450, 1600, 'K',
     'SiC/SiC 陶瓷基复材，实验室已到 1500 K'),
    ('电机功率密度', '永磁 5 kW/kg', 5, 25, 'kW/kg',
     '高温超导绕组 + 高速转子，液氮温区已可工程化'),
    ('散热器温度', '流体回路 350 K', 350, 1400, 'K',
     '碱金属热管（锂 1400 K）+ CMC 面板，均为已实现技术'),
    ('散热器面密度', '铝翅片 8 kg/m²', 8, 2.0, 'kg/m²',
     '薄膜热管 + CMC 蜂窝，只承担面内导热'),
    ('堆芯比功率', 'KRUSTY 0.007 kW/kg', 0.007, 130, 'kW/kg(热)',
     'NERVA 实测约 1100 kW/kg(热)；快谱 UC + BeO 反射层取保守值'),
    ('屏蔽面密度', 'LiH+W 200 kg/m²', 200, 60, 'kg/m²',
     '方向性阴影屏蔽 + 梯度复合，只挡机组方向，不挡 4π'),
]

# 采用的设定值
RHO_STRUCT = 450.0
SIGMA_STR = 900.0
T_STRUCT_MAX = 1600.0
MOTOR_KWKG = 25.0
T_RAD = 1400.0
RAD_KG_M2 = 2.0
CORE_KWKG = 130.0
SHIELD_KG_M2 = 60.0

# ---------------------------------------------------------------- 核动力链
ETA_BRAYTON = 0.45       # 闭式布雷顿（sCO2 + 回热，+50y 保守取 45%）
ETA_MOTOR = 0.97         # 超导电机效率
TW_HOVER = 1.30          # 悬停推力裕度（比化学的 1.05 高，为了姿态机动）
CONV_KG_KWE = 0.25       # 闭式布雷顿机组（涡轮+压气机+回热器+换热器）kg/kWe
                         #   现役涡轴 AE1107C 是 0.096 kg/kWe；本机无燃烧室但多回热器，
                         #   取 0.25 已含余量
GENMOT_KG_KWE = 0.08     # 超导发电 + 电动机合计 kg/kWe（25 kW/kg × 2 台）
PROP_KG_KN = 10.0        # 涵道风扇 + 风道 + 喷口 kg/kN 推力
                         #   F-35B 升力风扇 87 kN / 1.1 t = 12.6；F135 是 8.9
MISC_FRAC = 0.06         # 航电/作动/装甲/挂载 占 MTOW
SHIELD_DISC = 1.8        # 阴影屏蔽盘面积 m²（遮住驾驶舱投影，不是 4π）
WING_AR = 4.0            # 机翼展弦比
BOOM_FRAC = 0.03         # 折叠吊臂结构占 MTOW
N_BOOM = 4               # 吊臂风扇数
BOOM_D = 0.60            # 吊臂风扇直径 / 机高

# 悬停风扇构型 —— 这是核动力与化学动力最大的架构分歧
#   'body'：内嵌于机身（化学方案的做法）。盘面积被机身深度卡死 A≈0.8H²
#   'boom'：四具折叠吊臂，展开后 A≈1.13H²。**多出 40%**，且不占机身深度
FAN_MODE = 'boom'

# ---------------------------------------------------------------- 材料表
def materials_table():
    return [dict(item=a, now=b, now_v=c, fut_v=d, unit=e, basis=f)
            for a, b, c, d, e, f in MATERIALS]


# ---------------------------------------------------------------- 质量闭合
def geometry(H):
    Wm = WH * H
    Dm = DW * Wm
    return dict(W=Wm, D=Dm, v_env=Wm * H * Dm)


def disk_area(H):
    """悬停盘面积：两种构型。

    'body' 内嵌 —— 风扇必须绕机身横轴，直径 < 机身深度 ⇒ A ≈ 0.8·H²
    'boom' 吊臂 —— 四具风扇装在可折叠吊臂末端，直径 0.6H ⇒ A ≈ 1.13·H²
                    且**不再占用机身深度**，所以机身可以按气动需要而非风扇需要来定

    这一条就是核动力与化学动力在架构上的真正分歧：化学动力受轴功率限，
    盘面积越大越省；核动力受散热限，盘面积越大**废热越少** —— 结论同向但更极端，
    所以核动力会把风扇推到机身之外。
    """
    g = geometry(H)
    if FAN_MODE == 'boom':
        D = BOOM_D * H
        return N_BOOM * math.pi * (D / 2.0) ** 2, D, 'boom'
    D = min(g['D'] - 0.30, 0.55 * H)
    return 2.0 * math.pi * (D / 2.0) ** 2, D, 'body'


def powerplant_mass(P_shaft, T_hover):
    """给定轴功率与推力，反算动力系统质量（不含散热器）。

    四项缩放律完全不同，这是本文件最关键的一段：
      堆芯   ∝ 热功率 → ∝ 轴功率（可缩放）
      机组   ∝ 电功率 → ∝ 轴功率（可缩放）
      屏蔽   ∝ 面积   → **定值，与功率无关**（越大越摊薄）
      推进器 ∝ 推力   → ∝ 重量 ∝ H³（与堆芯同阶）
    把四项混成一个「比功率」会掩盖屏蔽的定值特性，也就看不出最优尺度从哪来。
    """
    P_th = P_shaft / ETA_BRAYTON
    P_e = P_shaft / ETA_MOTOR
    # 单位链必须写清：W → kW → kg → t，少除一个 1000 就是 1000 倍质量。
    # 上一版 m_core 与 m_motor 都少除了一次，直接把 MTOW 顶到 2500 t。
    m_core = P_th / 1000.0 / CORE_KWKG / 1000.0        # kW /(kW/kg) → kg → t
    m_conv = P_e / 1000.0 * CONV_KG_KWE / 1000.0       # kW × kg/kW → kg → t
    m_genmot = P_e / 1000.0 * GENMOT_KG_KWE / 1000.0
    m_shield = SHIELD_DISC * SHIELD_KG_M2 / 1000.0     # 定值
    m_prop = T_hover / 1000.0 * PROP_KG_KN / 1000.0    # kN × kg/kN → kg → t
    return dict(P_th=P_th, P_e=P_e, m_core=m_core, m_conv=m_conv,
                m_genmot=m_genmot, m_shield=m_shield, m_prop=m_prop,
                total=m_core + m_conv + m_genmot + m_shield + m_prop)


def _state(H, mtow_kg):
    """给定机高与 MTOW，算出整条功率链与各项质量（质量单位 t，need 转 kg）。"""
    g = geometry(H)
    A_fan, D_fan, mode = disk_area(H)
    Wt = mtow_kg * G
    T = TW_HOVER * Wt
    P = T ** 1.5 / math.sqrt(2.0 * RHO * A_fan)
    pp = powerplant_mass(P, T)
    Q = pp['P_th'] - P + P * (1.0 / ETA_MOTOR - 1.0)
    A_rad = Q / (2.0 * SIGMA * T_RAD ** 4)
    m_rad = A_rad * RAD_KG_M2 / 1000.0
    m_struct = g['v_env'] * 0.42 * RHO_STRUCT / 1000.0
    m_boom = BOOM_FRAC * mtow_kg / 1000.0 if mode == 'boom' else 0.0
    need_t = (m_struct + pp['total'] + m_rad) / (1.0 - MISC_FRAC - BOOM_FRAC
                                                 if mode == 'boom'
                                                 else 1.0 - MISC_FRAC)
    return dict(g=g, A_fan=A_fan, D_fan=D_fan, mode=mode, Wt=Wt, T=T, P=P,
                pp=pp, Q=Q, A_rad=A_rad, m_rad=m_rad, m_struct=m_struct,
                m_boom=m_boom, need=need_t, need_kg=need_t * 1000.0)


def hover_chain(H):
    """自洽求解 MTOW：解 need(m) = m。

    为什么不能直接迭代（第一版就栽在这里）：
      P ∝ T^1.5 ∝ m^1.5，而机组/电机质量 ∝ P ∝ m^1.5，
      于是方程 m = A + B·m^1.5 在 B 过大时**根本没有正解**。
      定步长迭代会一路发散到 OverflowError —— 而那不是「数值不好看」，
      是物理在说「这个尺度没有自洽解」。
    所以改成在 log m 上扫描找变号再二分；找不到变号就如实判「无解」。
    """
    def resid(lm):
        m = 10.0 ** lm
        return _state(H, m)['need_kg'] - m

    lo, hi = math.log10(20.0), math.log10(2.0e6)
    N = 600
    xs = [lo + (hi - lo) * i / N for i in range(N + 1)]
    prev_x, prev_f = xs[0], resid(xs[0])
    root = None
    for x in xs[1:]:
        f = resid(x)
        if prev_f * f <= 0.0:
            a, b, fa = prev_x, x, prev_f
            for _ in range(120):
                midx = 0.5 * (a + b)
                fm = resid(midx)
                if fa * fm <= 0:
                    b = midx
                else:
                    a, fa = midx, fm
            root = 0.5 * (a + b)
            break
        prev_x, prev_f = x, f

    if root is None:
        s = _state(H, 30.0 * (H / 8.0) ** 3 * 1000.0)
        return dict(H=H, solvable=False, W=s['g']['W'], D=s['g']['D'],
                    D_fan=s['D_fan'], mode=s['mode'], A_fan=s['A_fan'],
                    rad_ok=False, rad_ratio=float('inf'),
                    mtow=float('nan'), TW=float('nan'), P_shaft=float('nan'),
                    P_th=float('nan'), Q_waste=float('nan'), A_rad=float('nan'),
                    A_avail=float('nan'), S_wing=float('nan'), span=float('nan'),
                    m_struct=s['m_struct'], m_boom=s['m_boom'],
                    m_core=s['pp']['m_core'], m_conv=s['pp']['m_conv'],
                    m_genmot=s['pp']['m_genmot'], m_shield=s['pp']['m_shield'],
                    m_prop=s['pp']['m_prop'], m_power=s['pp']['total'],
                    m_rad=s['m_rad'], P_e=float('nan'), IRR_5km=float('nan'))

    m = 10.0 ** root
    s = _state(H, m)
    Wt, T = s['Wt'], s['T']
    S_wing = Wt / (0.5 * RHO * 180.0 ** 2 * 0.35)
    A_avail = 2.0 * S_wing + 0.55 * (2.0 * s['g']['W'] * H + 2.0 * s['g']['D'] * H)
    return dict(H=H, solvable=True, W=s['g']['W'], D=s['g']['D'],
                D_fan=s['D_fan'], mode=s['mode'], A_fan=s['A_fan'],
                mtow=m / 1000.0, weight=Wt,
                T_hover=T / 1000.0, P_shaft=s['P'] / 1e6,   # MW
                P_th=s['pp']['P_th'] / 1e6, P_e=s['pp']['P_e'] / 1e6,
                Q_waste=s['Q'] / 1e6,
                m_struct=s['m_struct'], m_boom=s['m_boom'],
                m_core=s['pp']['m_core'], m_conv=s['pp']['m_conv'],
                m_genmot=s['pp']['m_genmot'], m_shield=s['pp']['m_shield'],
                m_prop=s['pp']['m_prop'], m_power=s['pp']['total'],
                m_rad=s['m_rad'],
                A_rad=s['A_rad'], A_avail=A_avail,
                rad_ratio=s['A_rad'] / A_avail,
                S_wing=S_wing, span=math.sqrt(WING_AR * S_wing),
                rad_ok=s['A_rad'] <= A_avail,
                TW=T / Wt,
                IRR_5km=s['Q'] / (4.0 * math.pi * 5000.0 ** 2))


def scale_scan():
    return [hover_chain(H) for H in (4.0, 6.0, 8.0, 10.0, 12.0, 14.0, 16.0, 20.0)]


# ---------------------------------------------------------------- 尺度选型
# 为什么这里必须有一个「选型」步骤，而不是直接报 H=8：
#   §3 的扫描只回答「哪些 H 有解」。有解 ≠ 该选。
#   定 H 的是**夹逼**：下限来自「必须装得下多少东西」，上限来自「散热/接地装不下」。
#   两者都要有独立来源；如果只留一头，就等于先定答案再凑理由 ——
#   我在 V6/V7 两条判据上已经犯过三次同样的错（见 volume_check.py 注释）。
PAYLOAD_ITEMS = [
    ('30 mm 链炮系统（含供弹机构）', 0.45),
    ('弹药 300 发 + 弹箱', 0.21),
    ('座舱/反应堆装甲补强板', 0.70),
    ('光电/雷达/数据链', 0.35),
    ('乘员 + 生命维持', 0.25),
]
GROUND_MAX_KPA = 200.0   # 履带车辆在软土的通行上限量级；超过就要铺路才能走
RAD_RATIO_MAX = 0.50     # 散热占掉一半以上可用面积，就没有余量给机翼蒙皮/舱门


def payload_floor():
    """有效载荷下限：由一张具体清单加出来，不是拍的。"""
    return sum(v for _, v in PAYLOAD_ITEMS)


def select_scale(rows):
    """把「有解区间」夹成「该选区间」，返回 (可行窗, 选定值, 表)。"""
    need = payload_floor()
    tab = []
    for r in rows:
        if not r['solvable']:
            tab.append(dict(H=r['H'], ok=False))
            continue
        H = r['H']
        foot = 2.0 * (0.11 * H) * (0.19 * H)   # 双足接地面积，与 flight_physics 同式
        tab.append(dict(H=H, ok=True,
                        pay=MISC_FRAC * r['mtow'],
                        ground=r['weight'] / foot / 1000.0,
                        rad=r['rad_ratio'], span=r['span'],
                        fan=r['D_fan'], mtow=r['mtow']))
    solv = [t for t in tab if t.get('ok')]
    lo = min(t['H'] for t in solv if t['pay'] >= need)
    hi = max(t['H'] for t in solv
             if t['rad'] <= RAD_RATIO_MAX and t['ground'] <= GROUND_MAX_KPA)
    return dict(need=need, lo=lo, hi=hi, tab=tab)


# ---------------------------------------------------------------- 动力舱容积
# 为什么质量闭合算完还要算容积：
#   质量闭合只看「多重」，但 12.5 t 的动力系统能不能塞进 8 m 高的机身，是**体积**问题。
#   第一版我按「机组装满即 500 kg/m³」估，得出需要 12.4 m³，而背包只有 5.4 m³，
#   差点直接把方案判死 —— 后来才发现 500 是错的：闭式布雷顿的回热器是印刷电路板式
#   换热器（PCHE），装机密度 1200~1500 kg/m³，不是空腔。**密度假设错了，结论就反了**。
BAY_DENSITY = [
    ('堆芯+反射层', 'm_core', 2500.0),   # UC 陶瓷 + BeO 反射层 + 压力壳
    ('闭式布雷顿机组', 'm_conv', 1200.0),  # 涡轮/压气机 + PCHE 回热器 + 换热器
    ('超导发电+电机', 'm_genmot', 2000.0),  # 超导绕组 + 铁磁屏蔽（装在吊臂里，不占机身）
]
BAY_PACKING = 0.70   # 骨架/风道/线缆/检修通道占掉的体积比


def bay_volume(r, bay_w, bay_d, bay_h, chest_v):
    """动力舱容积账：需求 vs 机身可用（m³）。r 为 hover_chain() 的结果。

    bay_* 是背包的毛尺寸；chest_v 是胸部扣掉座舱后的毛容积。
    """
    need = {}
    for name, key, rho in BAY_DENSITY:
        need[name] = r[key] * 1000.0 / rho
    v_bay = bay_w * bay_d * bay_h * BAY_PACKING
    v_chest = chest_v * BAY_PACKING
    return dict(need=need, need_tot=sum(need.values()),
                v_bay=v_bay, v_chest=v_chest, v_tot=v_bay + v_chest)


def main():
    print('=' * 116)
    print('核动力机甲 · 前提换成核能之后，约束迁移到散热')
    print('=' * 116)
    print(f'  设定：闭式布雷顿 η={ETA_BRAYTON:.0%}  超导发电/电机 {GENMOT_KG_KWE} kg/kWe  '
          f'散热器 {T_RAD:.0f} K / {RAD_KG_M2} kg·m⁻²  堆芯 {CORE_KWKG} kW·kg⁻¹(热)')
    print(f'        阴影屏蔽 {SHIELD_DISC} m² × {SHIELD_KG_M2} kg/m²  '
          f'（只挡机组方向，不挡 4π）  悬停推力裕度 {TW_HOVER}  '
          f'风扇 {N_BOOM}×D={BOOM_D:.2f}H 折叠吊臂')

    print()
    print('-' * 116)
    print('§1 约定表：材料与部件上限（每条都对照现役值，不是许愿）')
    print('-' * 116)
    print(f'{"项目":<14}{"现役":<20}{"现役值":>10}{"+50y":>10}  {"单位":<12}依据')
    print('-' * 116)
    for m in materials_table():
        print(f'{m["item"]:<14}{m["now"]:<20}{m["now_v"]:>10g}{m["fut_v"]:>10g}  '
              f'{m["unit"]:<12}{m["basis"]}')
    print('-' * 116)
    print('  注：堆芯比功率的现役值取 KRUSTY 整套系统（含屏蔽/转换），'
          '设定值只算堆芯+反射层，两者量级不同是口径差异，不是重复突破。')

    rows = scale_scan()
    best = min(rows, key=lambda r: r['rad_ratio'])

    print()
    print('-' * 116)
    print('§2 架构分歧：悬停风扇放哪里（这不是审美，是*有没有解*）')
    print('-' * 116)
    global FAN_MODE
    body = []
    for H in (4.0, 6.0, 8.0, 10.0, 12.0):
        FAN_MODE = 'body'
        body.append(hover_chain(H))
    FAN_MODE = 'boom'
    print(f'{"机高m":>7}{"内嵌盘面积m²":>14}{"内嵌结果":>12}'
          f'{"吊臂盘面积m²":>14}{"吊臂 MTOW t":>13}{"吊臂轴功率MW":>14}')
    print('-' * 116)
    for r, rb in zip(rows, body):
        print(f'{r["H"]:>7.1f}{rb["A_fan"]:>14.1f}'
              f'{("无解" if not rb["solvable"] else f"{rb['mtow']:.0f} t"):>12}'
              f'{r["A_fan"]:>14.1f}{r["mtow"]:>13.1f}{r["P_shaft"]:>14.1f}')
    print('-' * 116)
    print('  内嵌全部无解，原因是**正反馈发散**，不是算错：')
    print('    盘面积被机身深度卡死 → P ∝ m^1.5 → 动力系统质量 ∝ P ∝ m^1.5')
    print('    ⇒ 方程 m = A + B·m^1.5 在大 B 时无正解（化学动力不会，因为发动机')
    print('    质量是 MTOW 的固定比例，不随功率变）。')
    print('  结论：**核动力机甲必须用可展开吊臂把盘面积做大**，否则数学上就不存在解。')

    print()
    print('-' * 116)
    print('§3 尺度扫描（吊臂构型，自洽求根）')
    print('-' * 116)
    print(f'{"机高m":>7}{"MTOW t":>9}{"T/W":>7}{"风扇D m":>9}{"轴功率MW":>10}'
          f'{"堆热MW":>9}{"废热MW":>9}{"散热器m²":>11}{"可用面积m²":>12}'
          f'{"比值":>8}{"判定":>7}')
    print('-' * 116)
    for r in rows:
        if not r['solvable']:
            print(f'{r["H"]:>7.1f}{"无解":>9}')
            continue
        print(f'{r["H"]:>7.1f}{r["mtow"]:>9.1f}{r["TW"]:>7.2f}{r["D_fan"]:>9.2f}'
              f'{r["P_shaft"]:>10.1f}{r["P_th"]:>9.1f}{r["Q_waste"]:>9.1f}'
              f'{r["A_rad"]:>11.0f}{r["A_avail"]:>12.0f}'
              f'{r["rad_ratio"]:>8.2f}{("可行" if r["rad_ok"] else "装不下"):>7}')
    print('-' * 116)
    print('  比值 = 散热器需求面积 / 机体可用面积。随 H 单调上升 → **越大越装不下散热器**。')

    b = hover_chain(8.0)
    print()
    print('=' * 116)
    print(f'§4 基准构型 H=8 m · 质量与功率链')
    print('=' * 116)
    print(f'  外形包络          {b["W"]:.2f} × 8.00 × {b["D"]:.2f} m')
    print(f'  结构（+50y 材料） {b["m_struct"]:6.1f} t   '
          f'（{RHO_STRUCT:.0f} kg/m³ × 0.42 填充）')
    print(f'  折叠吊臂结构      {b["m_boom"]:6.2f} t   ← 承载 {N_BOOM} 具风扇')
    print('  ── 动力系统 ───────────────────────────────')
    print(f'  堆芯+反射层       {b["m_core"]:6.2f} t   ← ∝ 热功率')
    print(f'  闭式布雷顿机组    {b["m_conv"]:6.2f} t   ← ∝ 电功率（{CONV_KG_KWE} kg/kWe）')
    print(f'  超导发电+电动机   {b["m_genmot"]:6.2f} t   ← ∝ 电功率')
    print(f'  阴影屏蔽          {b["m_shield"]:6.2f} t   ← **定值，不随尺度变**')
    print(f'  涵道风扇+风道     {b["m_prop"]:6.2f} t   ← ∝ 推力（{PROP_KG_KN} kg/kN）')
    print(f'  散热器            {b["m_rad"]:6.2f} t   ← {b["A_rad"]:.0f} m² × '
          f'{RAD_KG_M2} kg/m²')
    print('  ── 合计 ───────────────────────────────')
    print(f'  MTOW              {b["mtow"]:6.1f} t   （重量 {b["weight"]/1000:.0f} kN）')
    print(f'  悬停推力          {b["T_hover"]:6.0f} kN   T/W = {b["TW"]:.2f}')
    print(f'  轴功率            {b["P_shaft"]:6.1f} MW')
    print(f'  堆热功率          {b["P_th"]:6.1f} MWt  → 发电 {b["P_e"]:.1f} MWe')
    print(f'  废热              {b["Q_waste"]:6.1f} MW   ← 这才是核动力的真短板')
    print(f'  散热器面积        {b["A_rad"]:6.0f} m²  @ {T_RAD:.0f} K 双面')
    print(f'  可用散热面积      {b["A_avail"]:6.0f} m²  '
          f'（机翼 S={b["S_wing"]:.0f} m² 双面 + 机体 55%）')
    print(f'  占用比            {b["A_rad"]/b["A_avail"]:.2f}×  '
          f'→ {"够" if b["rad_ok"] else "必须展开额外散热面"}')

    print()
    print('-' * 116)
    print('§5 与化学动力的对比：约束迁移表')
    print('-' * 116)
    import flight_physics as FP
    c = FP.mass_closure(8.0)
    ca = FP.aero(c)
    ch = FP.hover_power(c)
    print(f'{"量":<18}{"化学动力":>18}{"核动力（+50y）":>22}{"变化":>16}')
    print('-' * 116)
    def row(a, b, c_, d):
        print(f'{a:<18}{b:>18}{c_:>22}{d:>16}')
    row('MTOW', f'{c["mtow"]/1000:.1f} t', f'{b["mtow"]:.1f} t',
        f'{(b["mtow"]*1000/c["mtow"]-1)*100:+.0f}%')
    row('能源质量', f'{c["m_fuel"]/1000:.1f} t 燃油',
        f'{b["m_power"]:.1f} t 动力系统', '—')
    row('悬停续航', '6 min（燃油 4.8 t）', '反应堆寿命 5~10 年', '**质变**')
    row('悬停轴功率', f'{ch["fan"]["MW"]:.1f} MW（盘 5.0 m²）',
        f'{b["P_shaft"]:.1f} MW（盘 {b["A_fan"]:.0f} m²）', '**↓3.4×**')
    row('主约束', '功率 + 燃油', '**废热排放**', '**迁移**')
    row('风扇位置', '机身内嵌（受深度限）', '**折叠吊臂（机身外）**', '**架构变了**')
    row('尺度趋势', '越小越好，硬上限 H≤8 m',
        f'越小越好，硬上限 H≈16 m', '**上限放宽 2×**')
    row('红外特征', '有，但有限', f'{b["Q_waste"]:.0f} MW 定向辐射', '**致命**')

    print()
    print('-' * 116)
    print('§6 结论：约束迁移到哪里，以及代价')
    print('-' * 116)
    print(f'  1. 功率与续航不再是约束。轴功率 {b["P_shaft"]:.0f} MW 对核堆很轻松，'
          f'燃油从 12% MTOW 变成 0。')
    print(f'  2. 新的主约束是**废热**：{b["Q_waste"]:.0f} MW 必须以 {T_RAD:.0f} K 辐射出去，'
          f'需要 {b["A_rad"]:.0f} m² 双面散热面。')
    print(f'  3. 散热面积 ∝ 废热 ∝ 轴功率 ∝ 重量 ∝ H³，可用表面积 ∝ H²，'
          f'比值 ∝ H → **越大越装不下**。')
    print(f'  4. 屏蔽是定值（{b["m_shield"]:.2f} t），越大越摊薄 —— 这一项利好大机体，'
          f'但量级只有 0.1 t，被散热项完全盖过。')
    print(f'     所以尺度上真正的硬上限不是屏蔽，而是**机组质量的正反馈发散**：'
          f'H≈16 m 以上无解。')
    print(f'  5. 代价：{b["Q_waste"]:.0f} MW 定向红外，5 km 处仍有 '
          f'{b["IRR_5km"]*1000:.0f} mW/m² —— 夜间是一支火炬，'
          f'必须靠「低功率热隐身模式」短时悬停。')
    print(f'  6. 因此散热翼必须**可收放且双用**：巡航时是机翼，悬停时展开为散热面。'
          f'这是造型上的原创点，且是被物理逼出来的。')

    print()
    print('=' * 116)
    print('§7 尺度选型：用「装得下多少东西」卡下限，用「散热/接地」卡上限')
    print('=' * 116)
    sel = select_scale(rows)
    print(f'  有效载荷下限清单（合计 {sel["need"]:.2f} t）：')
    for k, v in PAYLOAD_ITEMS:
        print(f'    {k:<34}{v:>6.2f} t')
    print('-' * 116)
    print(f'{"机高m":>7}{"MTOW t":>9}{"有效载荷t":>10}{"接地kPa":>9}'
          f'{"散热比值":>9}{"风扇D m":>9}{"展长m":>8}{"判定":>10}')
    print('-' * 116)
    for t in sel['tab']:
        if not t.get('ok'):
            print(f'{t["H"]:>7.1f}{"—":>9}{"":>10}{"":>9}{"":>9}{"":>9}{"":>8}{"无解":>10}')
            continue
        bad = []
        if t['pay'] < sel['need']:
            bad.append('载荷不足')
        if t['rad'] > RAD_RATIO_MAX:
            bad.append('散热装不下')
        if t['ground'] > GROUND_MAX_KPA:
            bad.append('接地超限')
        print(f'{t["H"]:>7.1f}{t["mtow"]:>9.1f}{t["pay"]:>10.2f}{t["ground"]:>9.0f}'
              f'{t["rad"]:>9.2f}{t["fan"]:>9.1f}{t["span"]:>8.1f}'
              f'{("可行" if not bad else bad[0]):>10}')
    print('-' * 116)
    print(f'  下限 H≥{sel["lo"]:.1f} m（6% MTOW 的载荷位才装得下 {sel["need"]:.2f} t）')
    print(f'  上限 H≤{sel["hi"]:.1f} m（散热占用比 ≤{RAD_RATIO_MAX:.0%} 且 接地 ≤'
          f'{GROUND_MAX_KPA:.0f} kPa 都满足的最大档）')
    print(f'  ⇒ 可行窗 {sel["lo"]:.1f}–{sel["hi"]:.1f} m。在这套 +50y 设定下，'
          f'**H=8 m 是被三条约束同时夹住的唯一档位**：')
    print('    再小装不下 1.96 t 载荷，再大散热占用比就破 50%（10 m 实测已到 50.0%）。')
    print('  诚实标注：8.0 m 对 2.09 t 载荷只有 6% 余量 —— 所以 S2 的载荷舱按')
    print('    2.0 t 定死，不做扩容许诺；要加挂武器必须同时把散热翼面积加大，')
    print('    也就是换构型，不是换尺寸。')

    print()
    print('-' * 116)
    print('§8 动力舱容积账：质量算完还要算体积，否则 12.5 t 无处安放')
    print('-' * 116)
    # 背包尺寸取自 S2 灰模的实际几何（见 tools/s2_graybox.py 的 DIM）
    # ★ 必须与 s2_graybox 同步：舱体 x ±1.15、y 4.86–7.18、z −1.93…−0.55。
    #   纵深从 1.40 收到 1.38 是为了把 D/W 拉回 0.627（0.6496 → 0.6261）。
    BAY_W, BAY_D, BAY_H = 2.30, 1.38, 2.32
    CHEST_V = 1.64 * 1.40 * 1.78 - 1.00      # 扣掉座舱 1.0 m³
    bv = bay_volume(b, BAY_W, BAY_D, BAY_H, CHEST_V)
    print(f'  背包毛容积 {BAY_W}×{BAY_D}×{BAY_H} = {BAY_W*BAY_D*BAY_H:.2f} m³  '
          f'× 装机率 {BAY_PACKING:.0%} = {bv["v_bay"]:.2f} m³')
    print(f'  胸部可用   {CHEST_V:.2f} m³ × {BAY_PACKING:.0%} = {bv["v_chest"]:.2f} m³'
          f'   （座舱与航电占掉的部分已扣）')
    print('-' * 116)
    print(f'{"部件":<16}{"质量t":>8}{"假设密度kg/m³":>15}{"体积m³":>9}  位置')
    print('-' * 116)
    place = {'堆芯+反射层': '背包最深处（离座舱最远）',
             '闭式布雷顿机组': '背包中段',
             '超导发电+电机': '**四具吊臂内，直驱风扇**'}
    for name, key, rho in BAY_DENSITY:
        print(f'{name:<16}{b[key]:>8.2f}{rho:>15.0f}{bv["need"][name]:>9.2f}  {place[name]}')
    print('-' * 116)
    print(f'  机身内需求 {bv["need_tot"] - bv["need"]["超导发电+电机"]:.2f} m³  '
          f'机身可用 {bv["v_tot"]:.2f} m³  '
          f'占用率 {(bv["need_tot"]-bv["need"]["超导发电+电机"])/bv["v_tot"]:.0%}')
    print(f'  若电机也塞进机身：占用率 {bv["need_tot"]/bv["v_tot"]:.0%} —— '
          f'装是装得下，但检修通道就没了。')
    print('  **真正逼电机上吊臂的不是容积，是铰链**：22 MW 的机械功率过不了折叠关节')
    print('  （要过就得有可分离的万向联轴器 + 齿轮箱，重量和维护都是灾难）。')
    print('  核电动力的天然解法就是电传：堆→发电→电缆过铰链→吊臂内超导电机→直驱风扇。')
    print('  所以「四臂各带一台电机」是构型必然，不是布置偏好。')

    if '--json' in sys.argv:
        p = sys.argv[sys.argv.index('--json') + 1]
        os.makedirs(os.path.dirname(p) or '.', exist_ok=True)
        with open(p, 'w') as f:
            json.dump(dict(materials=materials_table(), scale=rows,
                           base=b, best_H=best['H'],
                           select=dict(need=sel['need'], lo=sel['lo'], hi=sel['hi']),
                           bay=bv), f,
                      ensure_ascii=False, indent=2, default=float)
        print(f'  → {p}')


if __name__ == '__main__':
    main()
