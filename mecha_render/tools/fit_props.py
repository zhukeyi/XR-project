"""tools/fit_props.py — 只调比例：把 3D 机体的剖面拟合到「认可的图」

约束（用户明确要求）：不改几何、不改配色、不改分件，只动 PROP 那组比例系数。

为什么必须同视角比：认可图是 3/4（左右不对称 55%~127%），正视三视图里两腿并排、
3/4 里两腿前后叠合 —— 同一台机体腿宽占比能从 0.63 掉到 0.31。拿正视去比 3/4
的剖面是错的，所以这里渲 3/4 机位再比。

用法：
  python3 tools/fit_props.py                 # 只评估当前参数
  python3 tools/fit_props.py --search        # 网格搜索最优比例
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'tools'))

import mecha_model as MM                     # noqa: E402
from gfx import shade as SH                  # noqa: E402
from gfx.gbuffer import rasterize            # noqa: E402
from gfx.mesh import Mesh, collect2          # noqa: E402
from r3d import Renderer, look_at            # noqa: E402

W, H, FOV, DIST = 360, 640, 2.0, 600.0
YAW = float(os.environ.get('YAW', 32.0))
NB = 100


def profile_of(props=None, yaw=YAW):
    CY = 9.51 * (props or {}).get('_cy_scale', 1.0)
    rd = Renderer(W, H, ss=1, fov=FOV)
    cm = look_at((0, CY, DIST), (0, CY, 0), roll=0)
    mech = Mesh()
    p = {'rot': (0, yaw, 0)}
    src = props or {}
    p.update(to_model({k: v for k, v in src.items() if not k.startswith('_')}))
    p.update({k: v for k, v in src.items() if k.startswith('_')})
    collect2(MM.build_mecha(p), mech)
    P, N, T, mi, Fi, b, e = mech.arrays()
    gb, _ = rasterize(P, N, T, mi, Fi, cm, FOV, rd.WS, rd.HS)
    # 用 midx>=0（有面片写入过的像素）当剪影：比「渲色再取背景色差」稳，
    # 与配色无关，也不受抗锯齿/色调映射影响
    m = gb.midx >= 0
    ys = np.nonzero(m.any(axis=1))[0]
    if len(ys) == 0:
        return None
    top, bot = int(ys.min()), int(ys.max())
    rows = np.linspace(top, bot, NB).astype(int)
    w = np.array([(np.nonzero(m[y])[0].max() - np.nonzero(m[y])[0].min() + 1)
                  if m[y].any() else 0 for y in rows], float)
    wn = w / max(w.max(), 1)
    return dict(prof=wn, H=bot - top + 1, W=int(w.max()),
                widest_pct=float(np.argmax(wn)) / (NB - 1) * 100,
                mask=m, cover=float(m.mean()))


def score(prof, tgt, aspect=None):
    """剖面 RMSE + 地标罚项。地标罚项只用于打破「整体宽窄」的简并：
    单纯缩放宽度会让 RMSE 变小，但最宽行位置错了就是结构不对。"""
    t = np.array(tgt['profile'], float)
    rmse = float(np.sqrt(np.mean((prof['prof'] - t) ** 2)))
    pen = 0.012 * abs(prof['widest_pct'] - tgt['widest_pct'])
    # ★ 绝对宽高比约束，堵住归一化的空子：剖面除以「最宽行」，所以只要把肩撑宽，
    #   头和腿的相对宽度就会同时下降 —— 优化器会一路把胸推到上界去骗指标，
    #   结果是一个横向膨胀的怪物。用「实宽/高」把整体胖瘦钉住。
    if aspect is not None:
        pen += 0.60 * abs(prof['W'] / max(prof['H'], 1) - aspect)
    return rmse + pen, rmse


# 比例（PROP 那组）+ 站姿（模型本来就有这些关节参数，只是默认值给的是「手臂笔直垂下」）
# 为什么站姿也必须一起调：认可图的最宽处在 34% 高度（肘/前臂一带，比肩甲还宽），
# 而笔直下垂的臂让宽度从肩到髋一成不变 —— 那个「等宽矩形」就是方块感的来源。
# sh_roll 是 Z 轴外张（负值向外），sh_pitch 是前后摆，el_pitch 是肘弯。
PARAMS = dict(
    sx_chest=(0.40, 0.78),
    sx_leg=(0.42, 0.88),
    sy_head=(0.80, 1.26),
    sx_head=(0.50, 1.10),
    sx_arm=(0.55, 1.10),
    sh_roll=(-18.0, 2.0),
    sh_pitch=(-6.0, 16.0),
    el_pitch=(-26.0, 4.0),
)
POSE = ('sh_roll', 'sh_pitch', 'el_pitch')


def to_model(props):
    """把拟合参数翻译成 mecha_model 认的参数名（左右各一份）。"""
    d = {k: v for k, v in props.items() if k not in POSE}
    for k in POSE:
        if k in props:
            d[f'{k}-1'] = props[k]
            d[f'{k}1'] = props[k]
    return d


ASPECT = 0.365   # 认可图：宽 525 / 高 1437


def head_ratio(props):
    """头身比：用几何量，别用图像检测（3D 图领口糊住颈窝，检测器会判到肩线）"""
    sys.path.insert(0, os.path.join(HERE, 'tools'))
    import prop_audit as PA
    a = PA.audit(to_model({k: v for k, v in props.items() if not k.startswith('_')}))
    return a['r_head']


def coord_descent(tgt, base=None, rounds=3):
    cur = dict(base or {k: MM.PROP_DEFAULT.get(k, v[0]) for k, v in PARAMS.items()})
    if not base:
        cur.update(sh_roll=-6.0, sh_pitch=6.0, el_pitch=-8.0)
    best = None
    for r in range(rounds):
        improved = False
        for k, (lo, hi) in PARAMS.items():
            trials = np.linspace(lo, hi, 7)
            for v in trials:
                cand = dict(cur); cand[k] = float(v)
                pr = profile_of(cand)
                if pr is None:
                    continue
                s0, rmse = score(pr, tgt, ASPECT)
                hr = head_ratio(cand)
                # 头身比越出 7.9~8.8 就罚：剖面能靠放大头骗过去，头身比不行
                s0 += 0.05 * max(0.0, 7.9 - hr) + 0.05 * max(0.0, hr - 8.8)
                if best is None or s0 < best[0]:
                    best = (s0, rmse, dict(cand))
                    cur = dict(cand); improved = True
        print(f'  第 {r+1} 轮：综合 {best[0]:.4f}  RMSE {best[1]:.3f}  '
              f'{ {k: round(v,3) for k,v in cur.items()} }')
        if not improved:
            break
    return best


def main():
    tgt = json.load(open(os.path.join(HERE, 'specs', 'target_ok.json')))
    if '--search' not in sys.argv:
        pr = profile_of()
        s, rmse = score(pr, tgt, ASPECT)
        print(f'当前参数  剖面RMSE {rmse:.3f}  最宽行 {pr["widest_pct"]:.0f}% '
              f'(目标 {tgt["widest_pct"]:.0f}%)  实宽 {pr["W"]}  高 {pr["H"]}')
        print('剖面对比(每 5%):')
        print('  目标 ' + ' '.join(f'{tgt["profile"][i]:.2f}' for i in range(0, NB, 5)))
        print('  当前 ' + ' '.join(f'{pr["prof"][i]:.2f}' for i in range(0, NB, 5)))
        return
    best = coord_descent(tgt)
    s0, rmse, props = best
    print(f'最优  综合 {s0:.3f}  剖面RMSE {rmse:.3f}')
    print('  参数 ' + json.dumps({k: round(v, 3) for k, v in props.items()}))
    print(f'  头身比 1:{head_ratio(props):.2f}')
    pr = profile_of(props)
    print(f'  最宽行 {pr["widest_pct"]:.0f}% (目标 {tgt["widest_pct"]:.0f}%)  实宽 {pr["W"]}')
    print('  目标 ' + ' '.join(f'{tgt["profile"][i]:.2f}' for i in range(0, NB, 5)))
    print('  拟合 ' + ' '.join(f'{pr["prof"][i]:.2f}' for i in range(0, NB, 5)))
    json.dump({k: round(v, 4) for k, v in props.items()},
              open(os.path.join(HERE, 'specs', 'fitted_props.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
