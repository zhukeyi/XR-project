"""tools/visual_ruler.py — 视觉尺：把「Unicorn 好在哪」固化成**图像上**可算的指标

★ 为什么需要它（这是本项目反复改不好的方法论根因）
  之前的尺子全部量**三维几何**：prop_ruler 量横线、silhouette_ruler 量侧影、
  crevice_ruler 量缝、area_ruler 量三角面积。但用户的判据是「**看上去**笨/短/方」——
  那是在**二维图像**上做的判断。尺子与判据不在同一个空间里，
  于是每次三维指标全绿、图像依然不对。本轮把判据搬到图像上。

★ 指标全部来自**可观察的视觉现象**，不来自"我觉得应该这样"：
  V1 空白块   一整块没有信息的平面的面积占比 —— 对应"大冰箱""白模""这块是空的"
  V2 疏密节奏 细节是否**成团**（有视觉焦点），还是**均布**（= 呆板）
  V3 线条方向 斜线边缘的能量占比 —— 对应"线条呆板""像萝卜"
  V4 剪影     等周比 / 凸实度 / 凹口 —— 对应"剪影能不能被记住"
  V5 视觉重心 上下半身的细节能量分布 —— 对应"头重脚轻/五短"
  V6 明度结构 有效明度档数（参考 OBJ 无材质，**此项只用于我们自己**，不与参考比）

用法
  python3 tools/visual_ruler.py            # 出表 + 诊断图 out/ref/visual_*.png + json
"""
import json
import math
import os
import sys
from collections import deque

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'tools'))

import refview as RV                                        # noqa: E402
import s2_graybox as S                                      # noqa: E402
import unicorn_trunk as UT                                  # noqa: E402
from leg_ab import Soup, shade                              # noqa: E402

OUT = os.path.join(HERE, 'out', 'ref')
H10 = 10.0
PANEL = (520, 700)


# ---------------------------------------------------------------- 基础算子
def boxsum(a, r):
    """积分图做盒式求和（无 scipy）。"""
    ii = np.zeros((a.shape[0] + 1, a.shape[1] + 1), np.float64)
    ii[1:, 1:] = np.cumsum(np.cumsum(a, 0), 1)
    H, W = a.shape
    yy = np.arange(H)
    xx = np.arange(W)
    y0 = np.clip(yy - r, 0, H)
    y1 = np.clip(yy + r + 1, 0, H)
    x0 = np.clip(xx - r, 0, W)
    x1 = np.clip(xx + r + 1, 0, W)
    return (ii[np.ix_(y1, x1)] - ii[np.ix_(y0, x1)]
            - ii[np.ix_(y1, x0)] + ii[np.ix_(y0, x0)])


def local_std(g, r=3):
    n = (2 * r + 1) ** 2
    m = boxsum(g, r) / n
    m2 = boxsum(g * g, r) / n
    return np.sqrt(np.maximum(m2 - m * m, 0))


def sobel(g):
    gx = (np.roll(g, -1, 1) - np.roll(g, 1, 1)) * 0.5
    gy = (np.roll(g, -1, 0) - np.roll(g, 1, 0)) * 0.5
    return gx, gy


def components(mask, min_size=24):
    """4-连通域，返回 [(size, (y0,y1,x0,x1)), ...] 按面积降序。纯 python BFS，图小够用。"""
    lab = np.zeros(mask.shape, np.int32)
    out = []
    cur = 0
    H, W = mask.shape
    for y in range(H):
        for x in range(W):
            if not mask[y, x] or lab[y, x]:
                continue
            cur += 1
            q = deque([(y, x)])
            lab[y, x] = cur
            pts = []
            while q:
                cy, cx = q.popleft()
                pts.append((cy, cx))
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ny, nx = cy + dy, cx + dx
                    if 0 <= ny < H and 0 <= nx < W and mask[ny, nx] and not lab[ny, nx]:
                        lab[ny, nx] = cur
                        q.append((ny, nx))
            if len(pts) >= min_size:
                a = np.array(pts)
                out.append((len(pts), (int(a[:, 0].min()), int(a[:, 0].max()),
                                       int(a[:, 1].min()), int(a[:, 1].max()))))
    out.sort(key=lambda t: -t[0])
    return out, lab


def hull_area(pts):
    """Andrew monotone chain。pts = (N,2) (x,y)。"""
    P = sorted(set(map(tuple, pts)))
    if len(P) < 3:
        return 0.0

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lo = []
    for p in P:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], p) <= 0:
            lo.pop()
        lo.append(p)
    up = []
    for p in reversed(P):
        while len(up) >= 2 and cross(up[-2], up[-1], p) <= 0:
            up.pop()
        up.append(p)
    h = lo[:-1] + up[:-1]
    a = 0.0
    for i in range(len(h)):
        x0, y0 = h[i]
        x1, y1 = h[(i + 1) % len(h)]
        a += x0 * y1 - x1 * y0
    return abs(a) * 0.5


def v_gap(cov):
    """V7 剪影内空隙 + V8 宽窄变化 —— 补上「像萝卜」的两个直接量。

    ★ 为什么必须单独量（本轮新加，量出来才知道前面的诊断漏了主项）：
      「白模感」被归因到大平板（area_ruler），但两张正视图并排一看，
      最刺眼的差别是**参考的剪影内部破成好多块有缝的件**，我们的是实心的；
      而且参考每条肢体都是「粗—细—粗—细」（肩粗/肘细/前臂粗/腕细）,
      我们每条肢体是**等宽柱子**。这两件事与三角数、与大平板都无关。

    void_pct  ：逐行取「该行最左到最右之间未被覆盖的像素」，对全剪影面积取比。
                = 剪影内部真正透出背景的部分（腋下、腿间、肘后、裆口）。
    runs      ：逐行覆盖段的平均个数（1 = 一条连通的带；3 = 左右臂 + 躯干三段）。
    w_cv      ：逐行宽度序列的变异系数（等宽柱子 → 小；纺锤 → 大）。
    n_pinch   ：宽度序列里「先减后增」的局部极小个数，且两侧落差 > 0.02 H。
                对应「关节把肢体掐断」的次数。
    """
    H, W = cov.shape
    ys = np.where(cov.any(1))[0]
    if len(ys) == 0:
        return dict(void_pct=0.0, runs=0.0, w_cv=0.0, n_pinch=0, wamp=0.0)
    y0, y1 = int(ys.min()), int(ys.max())
    widths, voids, runss = [], [], []
    for y in range(y0, y1 + 1):
        row = cov[y]
        xs = np.where(row)[0]
        if len(xs) == 0:
            continue
        lo, hi = int(xs.min()), int(xs.max())
        span = hi - lo + 1
        n = int(row.sum())
        widths.append(span)
        voids.append(span - n)
        # 该行连通段数
        d = np.diff(np.concatenate(([0], row.astype(np.int8), [0])))
        runss.append(int((d == 1).sum()))
    widths = np.array(widths, np.float64)
    Hn = float(y1 - y0 + 1)
    area = float(cov.sum())
    # 平滑宽度序列（5 行滑动平均），避免锯齿造成的假极值
    if len(widths) >= 5:
        k = np.ones(5) / 5.0
        sw = np.convolve(widths, k, 'same')
        sw[:2], sw[-2:] = widths[:2], widths[-2:]
    else:
        sw = widths
    n_pinch = 0
    for i in range(2, len(sw) - 2):
        if not (sw[i] < sw[i - 1] and sw[i] <= sw[i + 1]):
            continue
        lft = sw[max(0, i - 12):i].max()
        rgt = sw[i + 1:i + 13].max() if i + 13 <= len(sw) else sw[i + 1:].max()
        if min(lft, rgt) - sw[i] > 0.02 * Hn:
            n_pinch += 1
    return dict(void_pct=float(100.0 * sum(voids) / max(area, 1)),
                runs=float(np.mean(runss)),
                w_cv=float(sw.std() / max(sw.mean(), 1e-9)),
                n_pinch=int(n_pinch),
                wamp=float(100.0 * (sw.max() - sw.min()) / max(sw.max(), 1)))


# ---------------------------------------------------------------- 六个指标
def v_blank(g, cov):
    """V1 空白块：局部标准差极低、且不在剪影边缘 3px 内的区域。"""
    er = cov.copy()
    for _ in range(3):
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            er &= np.roll(np.roll(cov, dy, 0), dx, 1)
    blank = cov & er & (local_std(g, 3) < 3.0)       # 灰度 0-255，3 = 几乎无变化
    small = np.array(Image.fromarray((blank * 255).astype(np.uint8)).resize(
        (cov.shape[1] // 2, cov.shape[0] // 2), Image.BILINEAR)) > 127
    comps, _ = components(small)
    area = float(cov.sum())
    if not comps:
        return dict(max_pct=0.0, total_pct=0.0, n_big=0), blank, []
    scale = area / float(small.shape[0] * small.shape[1])
    sizes = [(c[0] * scale / (small.shape[0] * small.shape[1])) * 100 for c in comps]
    tot = 100.0 * blank.sum() / area
    n_big = sum(1 for s in sizes if s > 1.0)
    return dict(max_pct=float(sizes[0]), total_pct=float(tot), n_big=int(n_big)), blank, comps[:6]


def v_rhythm(g, cov, gx, gy):
    """V2 疏密节奏：6×8 网格的边缘能量，看细节是成团还是均布。"""
    mag = np.hypot(gx, gy) * cov
    ys, xs = np.where(cov)
    if len(ys) == 0:
        return dict(focus=0.0, cv=0.0)
    y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
    cells = []
    for r in range(8):
        for c in range(6):
            ya = int(y0 + (y1 - y0) * r / 8)
            yb = int(y0 + (y1 - y0) * (r + 1) / 8)
            xa = int(x0 + (x1 - x0) * c / 6)
            xb = int(x0 + (x1 - x0) * (c + 1) / 6)
            sub = mag[ya:yb, xa:xb]
            covsub = cov[ya:yb, xa:xb]
            cells.append(float(sub.sum() / max(covsub.sum(), 1)))
    a = np.array(cells)
    k = max(1, int(len(a) * 0.2))
    focus = float(np.sort(a)[-k:].mean() / max(a.mean(), 1e-9))
    cv = float(a.std() / max(a.mean(), 1e-9))
    return dict(focus=focus, cv=cv)


def v_direction(gx, gy, cov):
    """V3 线条方向：边缘能量按方向的分布。"""
    mag = np.hypot(gx, gy) * cov
    ang = (np.degrees(np.arctan2(gy, gx)) + 180) % 180     # 无向，0–180
    m = mag > np.percentile(mag[cov], 70) if cov.any() else mag > 0
    a = ang[m]
    w = mag[m]
    if len(a) == 0:
        return dict(diag_pct=0.0, hv_pct=0.0)
    horiz = ((a < 12) | (a > 168))
    vert = (np.abs(a - 90) < 12)
    diag = (a > 20) & (a < 70) | ((a > 110) & (a < 160))
    return dict(diag_pct=float(100 * w[diag].sum() / w.sum()),
                hv_pct=float(100 * (w[horiz | vert].sum() / w.sum())))


def v_silhouette(cov):
    """V4 剪影：等周比、凸实度、边界点数。"""
    er = cov.copy()
    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        er &= np.roll(np.roll(cov, dy, 0), dx, 1)
    bnd = cov & ~er
    area = float(cov.sum())
    per = float(bnd.sum())
    ys, xs = np.where(bnd)
    hull = hull_area(list(zip(xs[::3], ys[::3]))) if len(xs) > 12 else area
    iso = float(per * per / (4 * math.pi * max(area, 1)))
    return dict(isoperimetric=iso, solidity=float(area / max(hull, 1)),
                bnd_pct=float(100 * per / max(area, 1)))


def v_weight(mag, cov):
    """V5 视觉重心：上 / 中 / 下三段细节能量的分配。"""
    ys, _ = np.where(cov)
    if len(ys) == 0:
        return dict(top=0.0, mid=0.0, bot=0.0)
    y0, y1 = ys.min(), ys.max()
    e = []
    for r in range(3):
        ya = int(y0 + (y1 - y0) * r / 3)
        yb = int(y0 + (y1 - y0) * (r + 1) / 3)
        e.append(float(mag[ya:yb].sum()))
    t = sum(e) or 1.0
    return dict(top=100 * e[0] / t, mid=100 * e[1] / t, bot=100 * e[2] / t)


def v_value(g, cov):
    """V6 明度结构：有效档数 = exp(熵)。**只用于我们自己**（参考 OBJ 无材质）。"""
    v = g[cov]
    if len(v) == 0:
        return dict(bins_eff=0.0, dominant_pct=0.0)
    h, _ = np.histogram(v, bins=10, range=(0, 256))
    p = h / max(h.sum(), 1)
    p = p[p > 0]
    ent = -float((p * np.log(p)).sum())
    return dict(bins_eff=float(math.exp(ent)), dominant_pct=float(100 * p.max()))


def metrics(img, cov):
    g = img.astype(np.float64).mean(2)
    gx, gy = sobel(g)
    mag = np.hypot(gx, gy) * cov
    b, blank, comps = v_blank(g, cov)
    r = v_rhythm(g, cov, gx, gy)
    d = v_direction(gx, gy, cov)
    s = v_silhouette(cov)
    w = v_weight(mag, cov)
    v = v_value(g, cov)
    p = v_gap(cov)
    return dict(blank=b, rhythm=r, direction=d, sil=s, weight=w, value=v, gap=p), blank


# ---------------------------------------------------------------- 两条来源
def ours():
    S.CLEAN = True
    root, mesh = S.build()
    P = np.array(mesh.P, np.float32).reshape(-1, 3)
    y0 = float(P[:, 1].min())
    k = H10 / (float(P[:, 1].max()) - y0)
    Q = P * k
    Q[:, 1] = (P[:, 1] - y0) * k
    mi, base, _e = mesh.mat_table()
    nt = len(mesh.P)
    if len(mi) != nt:
        mi = np.pad(mi, (0, max(0, nt - len(mi))))[:nt]
    return Soup(Q.reshape(-1, 3, 3), mi, base)


def ref():
    V, tris, gf, sets = UT.load_obj_grouped(UT.SRC)
    Vn, _ = RV.normalize(V)
    keep = np.ones(len(tris), bool)
    for t in UT.REMOVE:
        keep &= ~UT.face_in(gf, sets, t)
    P = Vn[tris[keep]].astype(np.float32)
    return Soup(P)


def main():
    os.makedirs(OUT, exist_ok=True)
    sz = {'我们': ours(), '参考': ref()}
    res = {}
    for view, yaw in (('front', 0.0), ('q35', 35.0), ('side', 90.0)):
        print('\n' + '=' * 74)
        print('视角 %s (yaw=%g)' % (view, yaw))
        print('=' * 74)
        for name, s in sz.items():
            img, cov = shade(s, yaw, PANEL)
            m, blank = metrics(img, cov)
            res['%s_%s' % (view, name)] = m
            Image.fromarray(img).save(os.path.join(OUT, 'visual_%s_%s.png' % (view, name)))
            ov = img.copy()
            ov[blank] = (ov[blank] * 0.35 + np.array([235, 60, 40]) * 0.65).astype(np.uint8)
            Image.fromarray(ov).save(os.path.join(OUT, 'visual_%s_%s_blank.png' % (view, name)))
            print('  %s：空白 最大块 %.2f%% / 合计 %.1f%% / >1%% 的块 %d 个' %
                  (name, m['blank']['max_pct'], m['blank']['total_pct'], m['blank']['n_big']))
            print('        疏密 focus %.2f  cv %.2f ｜ 斜线 %.1f%%  水平竖直 %.1f%%' %
                  (m['rhythm']['focus'], m['rhythm']['cv'],
                   m['direction']['diag_pct'], m['direction']['hv_pct']))
            print('        剪影 等周比 %.2f  凸实度 %.3f ｜ 上中下细节 %.0f/%.0f/%.0f ｜ 明度档 %.2f' %
                  (m['sil']['isoperimetric'], m['sil']['solidity'],
                   m['weight']['top'], m['weight']['mid'], m['weight']['bot'],
                   m['value']['bins_eff']))
            print('        空隙 %.1f%% ｜ 每行段数 %.2f ｜ 宽度 cv %.3f ｜ 掐腰 %.0f 处 ｜ 幅 %.0f%%' %
                  (m['gap']['void_pct'], m['gap']['runs'], m['gap']['w_cv'],
                   m['gap']['n_pinch'], m['gap']['wamp']))
    dst = os.path.join(OUT, 'visual_ruler.json')
    json.dump(res, open(dst, 'w'), ensure_ascii=False, indent=1)
    print('\n→ ' + dst)


if __name__ == '__main__':
    main()
