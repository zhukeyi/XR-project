"""tools/mirror_check.py — 对称性检验：这套描述里缺的那个量

为什么单独量这个
  ---------------------------------------------------------------
  上一份文档给的是「形状」的六层描述（尺寸链 / 折线 / 包络 / 截面 / 曲率 / 深度统计）。
  按定义它们全都是 **|x| 的无符号函数** —— 把左半边翻到右半边，六个层的读数一格不变。
  也就是说：**这套模型在数学上无法表达「不对称」，而不对称是设计的一部分**
  （独角兽的 V 天线偏向、 psycho-frame 外露段、单侧挂载、甚至站姿）。

  更直接的问题：`unicorn_matrix` 的 ΔR 出现 ±0.6–0.9 的左右差，
  我当时把它记成「对齐基准不一致 / 疑似附件」。如果参考本体就是不对称的，
  那这不是标定误差，而是**我的描述缺失了一维**。这个脚本就是去分辨这两种可能。

方法
  ---------------------------------------------------------------
  体素化（4 mm 网格，H=10 单位下 0.005）→ 求镜像重合率
      s(x0) = |A ∩ M_{x0}(A)| / |A|
  在 x0 ∈ [-0.15, +0.15] 上扫一遍取最大，得到**最佳对称面**和该面上的重合率。
  s = 1 → 严格左右对称；s = 0.6 → 四成的料在对面找不到对应。

  ★ 体素分辨率必须小于最薄的特征（我们最薄 30 mm 的刻线 → 4 mm 够）。
  ★ 只量顶点会漏掉大面片内部，所以顶点 + 三边中点一起投。

用法
  python3 tools/mirror_check.py
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'tools'))

import refview as RV                                       # noqa: E402
import s2_graybox as S                                     # noqa: E402
import unicorn_trunk as UT                                 # noqa: E402

Q = 0.005                  # 体素边长（H=10 单位 → 4 mm @8 m）
NB = 20                    # 高度带数


def ref_soup():
    V, tris, gf, sets = UT.load_obj_grouped(UT.SRC)
    Vn, _ = RV.normalize(V)
    keep = np.ones(len(tris), bool)
    for tok in UT.REMOVE:
        keep &= ~UT.face_in(gf, sets, tok)
    return Vn[tris[keep]]


def ours_soup():
    S.CLEAN = True
    _r, mesh = S.build()
    return np.array(mesh.P, np.float32).reshape(-1, 3) * (10.0 / 7.930)


def dens(P, cap=250000):
    """顶点 + 三边中点，必要时子采样（参考 33 万三角 → 130 万点太慢）。"""
    F = P.reshape(-1, 3, 3)
    Qs = [P.reshape(-1, 3)]
    for i, j in ((0, 1), (1, 2), (2, 0)):
        Qs.append(0.5 * (F[:, i] + F[:, j]))
    V = np.concatenate(Qs, 0)
    if len(V) > cap:
        V = V[np.random.default_rng(0).choice(len(V), cap, replace=False)]
    return V


def keys(P, x0=0.0):
    """顶点 + 三边中点 → int64 键（体素编号）。x0 为镜像面。"""
    F = P.reshape(-1, 3, 3)
    Qs = [P.reshape(-1, 3)]
    for i, j in ((0, 1), (1, 2), (2, 0)):
        Qs.append(0.5 * (F[:, i] + F[:, j]))
    V = np.concatenate(Qs, 0).astype(np.float64)
    if len(V) > 250000:
        V = V[np.random.default_rng(1).choice(len(V), 250000, replace=False)]
    V[:, 0] -= x0
    idx = np.floor(V / Q).astype(np.int64)
    idx[:, 0] += 3000                     # 保证非负（x 范围 ±15）
    idx[:, 2] += 3000
    return (idx[:, 0] * 8000000 + idx[:, 1] * 4000 + idx[:, 2])


def overlap(P, x0):
    a = keys(P, 0.0)
    # 镜像：x 索引翻号。这里用「把 x 减 x0 后取负」实现：等价于镜像后重新量化
    F = P.reshape(-1, 3, 3)
    Qs = [P.reshape(-1, 3)]
    for i, j in ((0, 1), (1, 2), (2, 0)):
        Qs.append(0.5 * (F[:, i] + F[:, j]))
    V = np.concatenate(Qs, 0).astype(np.float64)
    if len(V) > 250000:
        V = V[np.random.default_rng(1).choice(len(V), 250000, replace=False)]
    V[:, 0] = 2.0 * x0 - V[:, 0]                       # 关于 x = x0 镜像
    idx = np.floor(V / Q).astype(np.int64)
    idx[:, 0] += 3000
    idx[:, 2] += 3000
    c = idx[:, 0] * 8000000 + idx[:, 1] * 4000 + idx[:, 2]
    A = np.unique(a)
    hit = np.isin(A, np.unique(c))
    return float(hit.mean()), A, hit


def bands(P, x0):
    """逐高度带的重合率。"""
    F = P.reshape(-1, 3, 3)
    Qs = [P.reshape(-1, 3)]
    for i, j in ((0, 1), (1, 2), (2, 0)):
        Qs.append(0.5 * (F[:, i] + F[:, j]))
    V = np.concatenate(Qs, 0).astype(np.float64)
    ylo = V[:, 1].min()
    h = V[:, 1].max() - ylo
    bin_y = np.clip(((V[:, 1] - ylo) / h * NB).astype(np.int64), 0, NB - 1)
    idx = np.floor(V / Q).astype(np.int64)
    idx[:, 0] += 3000
    idx[:, 2] += 3000
    a = np.unique(idx[:, 0] * 8000000 + idx[:, 1] * 4000 + idx[:, 2])
    Vm = V.copy()
    Vm[:, 0] = 2.0 * x0 - Vm[:, 0]
    im = np.floor(Vm / Q).astype(np.int64)
    im[:, 0] += 3000
    im[:, 2] += 3000
    c = np.unique(im[:, 0] * 8000000 + im[:, 1] * 4000 + im[:, 2])
    out = []
    for b in range(NB):
        m = bin_y == b
        if m.sum() < 50:
            out.append(None)
            continue
        ka = np.unique(idx[m, 0] * 8000000 + idx[m, 1] * 4000 + idx[m, 2])
        out.append(float(np.isin(ka, c).mean()))
    return out


def main():
    print('读参考…')
    Pr = ref_soup()
    Pv = Pr.reshape(-1, 3)
    print('  参考主干 bbox 中心 x = %+.4f（相对原 bbox 中心，H=10 单位）'
          % (0.5 * (Pv[:, 0].min() + Pv[:, 0].max())))
    print('读我们…')
    Po = ours_soup()

    best = {}
    for tag, P in (('ref', Pr), ('ours', Po)):
        # ★ 扫描范围必须 ±1.0，不是 ±0.15：参考 OBJ 的 bbox 中心被单侧武器拉偏，
        #   剔掉武器之后主干的对称面离 bbox 中心约 0.5（H=10 单位）。
        #   第一版只扫 ±0.15，于是「最佳」停在边界、重合率虚低到 0.34 —— 不是模型不对称。
        grid = np.arange(-1.0, 1.001, 0.05)
        s = [overlap(P, x0)[0] for x0 in grid]
        i = int(np.argmax(s))
        # 细一档
        g2 = np.arange(grid[i] - 0.05, grid[i] + 0.0501, 0.005)
        s2 = [overlap(P, x0)[0] for x0 in g2]
        j = int(np.argmax(s2))
        best[tag] = (float(g2[j]), float(s2[j]))
        print('  %-4s 最佳对称面 x = %+.4f   重合率 %.4f' % (tag, g2[j], s2[j]))

    print('\n  逐高度带镜像重合率（x0 = 各自最佳对称面）')
    print('  %-6s %8s %8s' % ('高度', '参考', '我们'))
    br = bands(Pr, best['ref'][0])
    bo = bands(Po, best['ours'][0])
    for b in range(NB):
        u = (b + 0.5) / NB
        print('  %-6.0f%% %8s %8s'
              % (100 * u,
                 ('%.3f' % br[b]) if br[b] is not None else '—',
                 ('%.3f' % bo[b]) if bo[b] is not None else '—'))


if __name__ == '__main__':
    main()
