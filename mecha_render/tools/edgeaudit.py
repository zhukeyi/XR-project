"""edgeaudit.py — 测「块感」的最硬指标：硬边二面角分布

为什么这条比法线分布更关键：
  「矩形块拼接感」在视觉上不是由「面的朝向」决定的，而是由**棱**决定的。
  一条长直棱 + 90° 二面角 = 积木；同一条棱切成两段 30°+30° = 装甲折面。
  所以真正的判据是：模型上「长且接近 90° 的棱」占全部棱长的多少。

  而且这条指标是可编程验收的 —— 改完之后跑同一个脚本，数字下降就是有效，
  不依赖「看起来有没有变好」这种主观判断。

二面角定义：相邻两三角面法线的夹角。0° = 共面（棱不可见），
90° = 直角（积木感），>120° = 锐利折边（装甲感）。

统计口径全部**按棱长加权**，因为视觉权重正比于棱长；并按长度分档，
因为镜头里只有长棱会被看成结构线，短棱看起来只是细节。

用法：
  python3 tools/edgeaudit.py
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from tools.geoaudit import load, load_torso                     # noqa: E402


def edges_of(P, N, A):
    """返回 (边长, 二面角) 数组，只保留恰好被两个三角共享的棱。"""
    T = len(P)
    fn = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
    fn /= np.maximum(np.linalg.norm(fn, axis=1, keepdims=True), 1e-12)

    key = np.round(P, 4)                      # (T,3,3)
    recs = {}
    for t in range(T):
        for a, b in ((0, 1), (1, 2), (2, 0)):
            ka = tuple(key[t, a])
            kb = tuple(key[t, b])
            k = (ka, kb) if ka < kb else (kb, ka)
            recs.setdefault(k, []).append(t)

    L, ANG = [], []
    for k, ts in recs.items():
        if len(ts) != 2:
            continue
        pa = np.array(k[0])
        pb = np.array(k[1])
        L.append(float(np.linalg.norm(pb - pa)))
        c = float(np.clip(fn[ts[0]] @ fn[ts[1]], -1, 1))
        ANG.append(np.degrees(np.arccos(c)))
    return np.array(L), np.array(ANG)


def report(tag, L, ANG):
    tot = L.sum()
    print('\n[%s] 棱 %d 条，总棱长 %.1f m' % (tag, len(L), tot))
    bands = [(0, 8, '共面/看不出棱'), (8, 30, '缓坡（倒角后的斜面）'),
             (30, 75, '折面（想要的装甲折角）'), (75, 105, '★ 近直角（积木感来源）'),
             (105, 180.1, '锐求/内凹折边')]
    for lo, hi, nm in bands:
        m = (ANG >= lo) & (ANG < hi)
        print('    %-24s %5.1f%%   %8.2f m' % (nm, L[m].sum() / tot * 100,
                                               L[m].sum()))
    m90 = (ANG >= 75) & (ANG < 105)
    print('    近直角棱的平均长度 %.2f m；最长的一条 %.2f m'
          % (L[m90].mean() if m90.any() else 0, L[m90].max() if m90.any() else 0))
    # 长棱里有多少是近直角 —— 这才是真正扎眼的
    long = L > 1.0
    print('    长度 >1 m 的棱中，近直角占 %.1f%%（%.1f m / %.1f m）'
          % (L[long & m90].sum() / max(L[long].sum(), 1e-9) * 100,
             L[long & m90].sum(), L[long].sum()))


def main():
    # 只审计机体：城市用另一套图元，混进来会把数字带偏
    root, mech, P, N = load()
    A = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
    A = 0.5 * np.linalg.norm(A, axis=1)
    print('=' * 74)
    print('棱审计  三角 %d  表面积 %.1f m²' % (len(P), A.sum()))
    L, ANG = edges_of(P, N, A)
    report('整机', L, ANG)

    Pt, Nt = load_torso()
    Lt, ANGt = edges_of(Pt, Nt, None)
    report('躯干', Lt, ANGt)

    # 头顶到胸甲这一段单独看
    ymask = (P[:, :, 1].min(axis=1) > 14.5) & (P[:, :, 1].max(axis=1) < 18.5)
    Pn, Nn = P[ymask], N[ymask]
    if len(Pn):
        Ln, ANGn = edges_of(Pn, Nn, None)
        report('头颈段 y∈(14.5, 18.5)', Ln, ANGn)


if __name__ == '__main__':
    main()
