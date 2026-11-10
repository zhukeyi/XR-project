"""tools/line_measure.py — 线条「呆板」的量化：正视图**可见棱**的角度分布

为什么要有这个脚本
  「线条呆板」是审美判断，但呆板有可算的成因：**可见棱边全部落在 0° 与 90° 附近**。
  机甲的正面读法几乎全部由横向/竖向边缘给出，一旦角度分布坍缩成两根尖峰，
  无论加多少件都读作「砖块堆」。

  所以本脚本从 mesh 提边，投影到正视图（XY），做角度直方图，报三个数：

    H%   |θ| ≤ 5°     水平线占比
    V%   |θ − 90| ≤ 5° 竖直线占比
    S%   10° ≤ |θ| ≤ 40°  设计斜线占比   ← 肌肉感的主要来源

★★ 口径改过一次（必须记住为什么）
  第一版统计**全部**棱边，得到 V 38.4% —— 但其中一大半在背面：
  折起来的翼叶（2.1 m 纯竖边）、背包里的桁架、背板鳍片的内侧边。
  那些线在正视图里**根本看不见**，却把 V 抬高了十几个点，指标和眼睛完全脱节。

  第二版只保留「至少有一个相邻面朝向相机」的棱：view = (0, 0, +1)（从 +Z 看），
  面朝向相机 ⇔ 法线 z > NZ_MIN。这样被背面遮住的、以及纯侧向的棱全部剔除。

★★ 还要按**投影长度**计权，不是按边数
  按边数计权会把 0.05 m 的倒角边和 1.2 m 的主轮廓边当成一样重 ——
  实测下来倒角（45°）凭空占 12.6%，真正的设计斜线永远追不上。
  眼睛看到的是「线的长度」，所以必须按长度加权。

用法
  python3 tools/line_measure.py           # 收纳态（默认）
  python3 tools/line_measure.py --deploy  # 展开态
"""
import os
import sys

import math

import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'tools'))

import s2_graybox as S                                     # noqa: E402

NZ_MIN = 0.20          # 面朝向相机的判定阈值（法线 z 分量）
CREASE_MIN = 12.0      # 折痕角阈值（度）；小于它两面基本共面，不产生明暗线


def visible_edges(mesh):
    """返回 (边端点 N×2×3,)，已按「看得见的线」过滤。

    ★★ 第三版口径（前两版都错在这）：**灰模里的线只有两种**
      ① 折痕边（crease）：两侧面法线夹角 > 12°，台阶/转角在这里，光照会出明暗；
      ② 轮廓边（silhouette/boundary）：只被一个面引用，或两侧一面朝前一面朝后。
      平面四边形被三角化后，那条**对角线**两侧完全共面、法线夹角 0°，
      它在渲染里根本不存在 —— 但按「全部棱边」统计时它占了 0° 那一档的一大半。
      第一版量出 0–10° 独占 34.2%，就是这么来的。

    另外只保留「至少一侧朝向相机」的边：背面的线在正视图里看不见。
    """
    P = np.array(mesh.P, np.float32).reshape(-1, 3, 3)
    nrm = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
    ln = np.linalg.norm(nrm, axis=1, keepdims=True)
    ln[ln < 1e-9] = 1.0
    nrm = nrm / ln

    def key(a, b):
        return tuple(np.round(np.sort([a, b], axis=0).ravel(), 5))

    faces = {}                      # 边 -> [法线, ...]（最多存 2 条）
    for i in range(len(P)):
        for (u, v) in ((0, 1), (1, 2), (2, 0)):
            k = key(P[i, u], P[i, v])
            L = faces.setdefault(k, [])
            if len(L) < 2:
                L.append(nrm[i])

    cos_t = math.cos(math.radians(CREASE_MIN))
    out = []
    seen = set()
    for i in range(len(P)):
        for (u, v) in ((0, 1), (1, 2), (2, 0)):
            a, b = P[i, u], P[i, v]
            k = key(a, b)
            if k in seen:
                continue
            seen.add(k)
            Ns = faces[k]
            front = [n for n in Ns if n[2] > NZ_MIN]
            if not front:
                continue
            if len(Ns) == 1:                      # 边界边
                out.append((a, b))
                continue
            if float(np.dot(Ns[0], Ns[1])) < cos_t:   # 折痕边
                out.append((a, b))
            elif len(front) != len(Ns):               # 一侧朝前一侧朝后 = 轮廓边
                out.append((a, b))
    return np.array(out, np.float32)


def report(mesh, tag=''):
    E = visible_edges(mesh)
    d = E[:, 1] - E[:, 0]
    dx, dy = d[:, 0], d[:, 1]
    planar = np.hypot(dx, dy)
    m = planar > 1e-4
    dx, dy, w = dx[m], dy[m], planar[m]
    ang = np.abs(np.degrees(np.arctan2(dy, dx)))
    ang = np.where(ang > 90, 180 - ang, ang)

    bins = np.round(ang * 2) / 2
    uq = np.arange(0.5, 90.0, 0.5)
    W = np.zeros_like(uq)
    for b, ww in zip(bins, w):
        i = int(b * 2) - 1
        if 0 <= i < len(W):
            W[i] += ww
    tot = W.sum()

    H = 100.0 * W[uq <= 5].sum() / tot
    V = 100.0 * W[uq >= 85].sum() / tot
    S_ = 100.0 * W[(uq >= 10) & (uq <= 40)].sum() / tot
    print('=' * 74)
    print('线条角度分布（正视图**可见棱**，按投影线长计权）' + tag)
    print('=' * 74)
    print(f'  可见投影总线长 {tot:.1f} m   （折痕/轮廓边 {int(m.sum())} 条）')
    print(f'  H%  |θ|≤5°     {H:5.1f}%     水平线')
    print(f'  V%  |θ|≥85°    {V:5.1f}%     竖直线')
    print(f'  S%  10–40°     {S_:5.1f}%     设计斜线   ← 肌肉感来源')
    print(f'  H+V            {H + V:5.1f}%     ← 「呆板」的总量')
    print()
    print('  分布（0–90°，每 10° 一档，按线长）')
    for lo in range(0, 90, 10):
        sel = (uq >= lo) & (uq < lo + 10)
        nn = W[sel].sum()
        bar = '#' * int(round(100.0 * nn / tot / 2))
        print(f'    {lo:2d}–{lo+10:2d}°  {100.0*nn/tot:5.1f}%  {bar}')
    print()
    print('  判读：40–50° 那一段主要是倒角（chamfer）的副产物，不算设计斜线；')
    print('  真正的设计斜线应落在 10–35°。V% 高说明「站得直」的边太多，')
    print('  典型来源是四肢外缘与折起来的翼叶。')
    return dict(H=H, V=V, S=S_, tot=tot)


def main():
    if '--deploy' in sys.argv:
        S.WING_DEPLOY = 1.0
    # ★ 2026-11-09 补：这个脚本原来只认 --deploy，`--clean` 会被**静默忽略**，
    #   于是「量主干构型」实际量的是非主干构型（373.8 m）。静默忽略参数比报错更坏
    #   —— 它会产出一个看起来完全合理、但答的不是这个问题的数字。
    if '--clean' in sys.argv:
        S.CLEAN = True
    root, mesh = S.build()
    if S.CLEAN:
        tag = '（主干构型 --clean：无动力舱/浮游炮/折叠翼）'
    else:
        tag = '（展开态）' if S.WING_DEPLOY > 0.5 else '（收纳态）'
    report(mesh, tag)
    if '--by-part' in sys.argv:
        by_part(root)


def _split(mesh):
    """把 mesh 的边按角度分成 (水平, 竖直, 斜线) 三段线长。"""
    E = visible_edges(mesh)
    d = E[:, 1] - E[:, 0]
    planar = np.hypot(d[:, 0], d[:, 1])
    m = planar > 1e-4
    dx, dy, w = d[m, 0], d[m, 1], planar[m]
    ang = np.abs(np.degrees(np.arctan2(dy, dx)))
    ang = np.where(ang > 90, 180 - ang, ang)
    return (w[ang <= 5].sum(), w[ang >= 85].sum(),
            w[(ang >= 10) & (ang <= 40)].sum(), w.sum())


def by_part(root):
    """★ 按**顶层件**归因：竖线到底是谁贡献的。

    没有这一步，「V% 偏高」只是一句判断；有了它才能说「背包一个人占 32%」，
    然后才谈得上改哪儿。这是把审美判断变成可执行清单的唯一一步。
    """
    rows = []
    for c in root.children:
        mb = S.Mesh()
        S.collect2(c, mb)
        if not mb.P:
            continue
        h, v, sl, tot = _split(mb)
        rows.append((c.name, tot, h, v, sl))
    T = sum(r[1] for r in rows) or 1.0
    TV = sum(r[3] for r in rows) or 1.0
    print('=' * 74)
    print('按件归因（正视图可见棱，按投影线长计权，单位 m）')
    print('=' * 74)
    print(f'  {"件":<10}{"总线长":>9}{"占比":>8}{"竖线":>9}{"竖线占比":>10}{"斜面":>9}')
    for name, tot, h, v, sl in sorted(rows, key=lambda r: -r[3]):
        print(f'  {name:<10}{tot:9.1f}{100*tot/T:7.1f}%{v:9.1f}{100*v/TV:9.1f}%{sl:9.1f}')
    print(f'  {"合计":<10}{T:9.1f}{100.0:7.1f}%{TV:9.1f}{100.0:9.1f}%')
    print()
    print('  ★ 合计 ≠ 全机总线长（上面那个数）：单件单独量时它的背面棱也算「可见」，')
    print('    装配后会被别的件挡住；件与件的接缝还会被两侧各算一次。')
    print('    所以这张表只能当**相对排序**用，不能当精确分解。')


if __name__ == '__main__':
    main()
