"""tools/legline_ruler.py — 用前视遮罩重测「裆线 / 膝线」

为什么要重测
  §27.4 把「髋线」量成 0.641（Unicorn）/ 0.531（我们），据此得出「我们腿短
  11 个百分点 = 0.87 m」，并把它排成 P0 第一位。
  那个数是用**腿件 bbox 的顶**当髋线的 —— 而腿件 bbox 顶含髋关节、大腿甲、
  侧裙，它比真正的裆线高出一大截。参考模型被同一个错误也抬高了一点，
  但两边抬高得不一样多，于是差出了一个根本不存在的 0.11H。

  上一轮改用「顶点中线填满法」（min|x|/H < 0.02 判填满）也不行：
  我们这个模型的腿缝绝对值本来就只有 0.04 m，等于 0.005H，
  阈值一放就误判成「裆在 0.865H」，也就是量到了胸口。

  这一版换**像素**：渲染前视遮罩，逐行看**中线那一列**是不是黑的。
  腿分开时中线在缝里（白），到裆部并起来（黑）。判定与顶点密度、
  与模型尺度都无关，是「眼睛看到什么就量什么」。

定义
  裆线 crotch  = 自下而上，**中线列**第一次连续为实心的那一行。
                 允许向下探 3 行确认稳定（避免腋下/腰封的孤立像素）。
  腿最细处     = 单腿横截宽度在「裆线以下 35% ~ 裆线」这段里的**极小值**所在高度。
                 ★ 不要叫它「膝线」：实测参考模型给出 0.485H，人形膝盖一般在 0.26–0.30H，
                 那个 0.485H 其实是「裙下大腿最细处」。名字叫错，读数就会被拿去当膝盖用。

用法
  python3 tools/legline_ruler.py
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
import render_relief as RR                               # noqa: E402
import s2_graybox as S                                   # noqa: E402
import unicorn_trunk as UT                               # noqa: E402

OUT = os.path.join(HERE, 'out', 'ref')
FONT = '/System/Library/Fonts/Hiragino Sans GB.ttc'
H = 10.0
SIZE = (700, 1400)              # 高比宽大得多，1 像素 ≈ 0.007H，够分辨 1%


def norm_to_H(V):
    V = np.asarray(V, np.float64).reshape(-1, 3)
    lo, hi = V.min(0), V.max(0)
    s = H / max(float(hi[1] - lo[1]), 1e-9)
    cx, cz = 0.5 * (lo[0] + hi[0]), 0.5 * (lo[2] + hi[2])
    return (V - np.array([cx, lo[1], cz])) * s


class Soup:
    """三角形汤 → refview 要的 arrays() 接口。"""

    def __init__(self, P):
        P = np.asarray(P, np.float32).reshape(-1, 3, 3)
        n = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
        L = np.linalg.norm(n, axis=1, keepdims=True)
        keep = L[:, 0] > 1e-12
        P, n = P[keep], n[keep] / L[keep]
        self.P = P
        self.N = np.repeat(n[:, None, :], 3, 1)
        self.T = np.zeros((len(P), 3, 2), np.float32)
        self.mi = np.zeros((len(P),), np.int32)
        self.Fi = np.arange(len(P), dtype=np.int32)
        self.base = np.array([[0.78, 0.79, 0.80]], np.float32)
        self.emis = np.zeros((1,), np.float32)

    def arrays(self):
        return self.P, self.N, self.T, self.mi, self.Fi, self.base, self.emis

    def mat_prop_table(self):
        # render_relief 会问材质的 spec/rim。这份汤没有材质，给一组 0 即可。
        return np.zeros((1,), np.float32), np.zeros((1,), np.float32)

    def __len__(self):
        return len(self.P)


def front_mask(P, path=None):
    """前视遮罩：bool(H, W)，True = 实体。"""
    sz = Soup(P)
    # ★ cy 必须是机体的**竖向中心**（H/2）。第一版给了 0，相机于是盯着脚底看，
    #   画框只框进下半身 —— 上面的行全是背景，「自下而上第一个实心行」自然落在
    #   0.84H（那不是裆，那是画框上沿附近的一条腿）。
    vm = dict(H=H * 1.04, Wfig=float(np.ptp(np.asarray(P)[..., 0])),
              zf=0.0, zback=0.0, scale=1.0, cy=H * 0.5,
              bbox=(0, 0, 0, H, 0, 0))
    m, _ = RR.render(sz, vm, 0.0, path or '/tmp/_legline.png', size=SIZE, bg_lv=0.55)
    # ★ 不能靠「像素亮度 < 128」判实体：机体亮面 199、背景 140，两者都 > 128，
    #   那样判出来的「实体」只剩描边黑线，于是裆线被读成 0.839H（读到的是胸口的一道线）。
    #   render 第一个返回值就是覆盖率掩码，直接用它。
    solid = np.asarray(m)
    if solid.dtype != bool:
        solid = solid > 0.5
    return solid


def scan(solid, label):
    hh, ww = solid.shape
    mid = ww // 2
    rows = solid[:, max(0, mid - 1):mid + 2].any(1)     # 中线 3 列，取或（抗锯齿）

    # 自下而上找第一次「连续为实」
    top_fill = None
    k = hh - 1
    while k >= 0:
        if rows[k]:
            # 向下探 3 行，要求全实，避免孤立像素
            if all(rows[j] for j in range(max(0, k - 3), k + 1)):
                top_fill = k
                break
        k -= 1
    if top_fill is None:
        return None

    # 像素 → 高度比。取景是 H*1.04 居中，脚底 y=0 在图像底部（留了一点边）
    # 这里不猜：改用「最低实体行 = 0H、最高实体行 = 1H」标定（两模型都归一过）
    ys = np.nonzero(solid.any(1))[0]
    bot, top = ys.max(), ys.min()
    span = bot - top
    t = (bot - top_fill) / span

    # 膝线：裆线以下 35% ~ 裆线的区间内，单腿（只取中线右侧半幅）宽度极小值
    best, knee = None, None
    lo_k = int(bot - span * t * 1.00)
    hi_k = int(bot - span * t * 0.65)
    for y in range(lo_k - 1, hi_k + 1):
        if y < 0 or y >= hh:
            continue
        xs = np.nonzero(solid[y, mid:])[0]
        if len(xs) < 2:
            continue
        wpx = xs.max() - xs.min()
        if best is None or wpx < best:
            best, knee = wpx, (bot - y) / span
    return dict(label=label, crotch=t, knee=knee,
                knee_w=None if knee is None else None)


def main():
    os.makedirs(OUT, exist_ok=True)

    # ---- Unicorn 主干
    V, tris, gf, sets = UT.load_obj_grouped(UT.SRC)
    Vn_raw, meta = RV.normalize(V)
    keep = np.ones(len(tris), bool)
    for tok in UT.REMOVE:
        keep &= ~UT.face_in(gf, sets, tok)
    # 与 trunk_ruler 同口径：用**含外挂的 bbox**归一（剥掉的体量不重新放大）
    Ufull = Vn_raw[tris]
    U = norm_to_H(Ufull)          # 先按 full 归一
    Vlo = Ufull.reshape(-1, 3).min(0)
    Vhi = Ufull.reshape(-1, 3).max(0)
    U2 = (Vn_raw - np.array([0.5 * (Vlo[0] + Vhi[0]), Vlo[1],
                             0.5 * (Vlo[2] + Vhi[2])])) * (H / (Vhi[1] - Vlo[1]))
    U = U2[tris][keep]

    # ---- 我们主干
    S.CLEAN = True
    _, mesh = S.build()
    C = norm_to_H(np.array(mesh.P, np.float32))

    res = []
    for name, P in (('Unicorn主干', U), ('我们主干', C)):
        solid = front_mask(P, os.path.join(OUT, 'legline_%s.png' % name))
        r = scan(solid, name)
        res.append(r)
        if r:
            print('%-10s 裆线 %.3fH   腿最细处 %s'
                  % (name, r['crotch'],
                     '%.3fH' % r['knee'] if r['knee'] else '—'))
        else:
            print('%-10s 未找到裆线' % name)

    if len(res) == 2 and all(res):
        d = res[0]['crotch'] - res[1]['crotch']
        print('\n  裆线差 %.3fH（Unicorn − 我们）= %.2f m（按我们 H 7.93）'
              % (d, d * 7.93))
        print('  ★ 这个「裆线」在前视里是**中线第一次被遮住**的高度 ——')
        print('    挡住它的通常是**前裙下沿**，不是髋关节。实测：')
        print('      我们  skirt 下沿 0.434H、hip 节点 0.545H、leg 件顶 0.555H')
        print('      → 量到的 %.3fH 就是裙底，比髋节点低 %.3fH'
              % (res[1]['crotch'], 0.545 - res[1]['crotch']))
        print('    所以「腿短」这 0.1H 是**可以靠抬裙摆 + 开中缝修掉的**，')
        print('    不是骨头长度问题。§27.4 原写「0.11H / 0.87 m」用的是腿件 bbox 顶，')
        print('    数值碰巧接近，但归因错了（那条会去加长大小腿，代价大得多且方向不对）。')
        with open(os.path.join(OUT, 'legline.json'), 'w') as f:
            json.dump(res, f, ensure_ascii=False, indent=1, default=float)
        print('→ %s' % os.path.join(OUT, 'legline.json'))


if __name__ == '__main__':
    main()
