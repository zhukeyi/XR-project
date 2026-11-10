"""tools/sketch_check.py — 把「草图顺不顺眼」变成可测数字

背景：本会话看不了图（视觉通道不可用），所以不靠肉眼，直接用像素统计验收
线稿/剪影。判据全部来自 SEED 画法分析文档的结论：

  · 头身比 8.2~8.8        → 头顶到颈线 / 全身高
  · 肩宽/头宽 16.5~18.5%  → 即头宽 ≈ 0.17 肩宽（这里反过来报肩宽/头宽 ≈ 2.1~2.6）
  · 横截面收放反转 ≥3 次  → 宽度剖面的一阶差分换号次数
  · 长直边惩罚            → 逐行左/右边缘「零位移」的最长连续行数
  · 折面证据              → 边缘单行位移 1~4 px 的行数占比

用法：
  python3 tools/sketch_check.py out/seed_sketch/xxx.png
"""
import sys

import numpy as np
from PIL import Image


def load_mask(path, thr=110):
    im = Image.open(path).convert('L')
    a = np.asarray(im, float)
    # 反相：黑=1（主体），白=0
    m = a < thr
    # 去掉细碎噪点：只保留最大连通域
    m = largest_cc(m)
    return m, a


def largest_cc(m):
    try:
        from scipy import ndimage as ndi
        lab, n = ndi.label(m)
        if n <= 1:
            return m
        sizes = ndi.sum(m, lab, range(1, n + 1))
        return lab == (int(np.argmax(sizes)) + 1)
    except Exception:
        return m


def row_extents(m):
    H, W = m.shape
    L = np.full(H, np.nan)
    R = np.full(H, np.nan)
    for y in range(H):
        xs = np.nonzero(m[y])[0]
        if len(xs):
            L[y], R[y] = xs.min(), xs.max()
    return L, R


def profile(m, n=50):
    H, W = m.shape
    L, R = row_extents(m)
    ys = np.nonzero(~np.isnan(L))[0]
    if len(ys) == 0:
        return None
    y0, y1 = ys.min(), ys.max()
    rows = np.linspace(y0, y1, n).astype(int)
    w = (R[rows] - L[rows] + 1)
    return dict(y0=y0, y1=y1, H=y1 - y0 + 1, W=W, rows=rows, w=w, L=L, R=R)


def _neck_pinch(span, head_w, y_from, y_to):
    """颈线：头盔最宽行以下，宽度第一次掉到 0.62 头宽以下的行。

    颈宽只有头盔宽度的 ~0.40 倍，分离度很大，而且这个判据与视角无关 ——
    这是它比「宽度超过 2 倍头宽就算肩线」更可靠的原因。
    """
    for y in range(y_from, y_to):
        if span[y] < 0.62 * head_w:
            return y
    return None


def _neck_widen(span, head_w, y_from, y_to, k=6):
    """兜底：领口把脖子糊住时压根没有颈窝，改用「最陡的加宽行」。

    头→肩是全图宽度增长最快的位置（局部细化图实测 163→299 px / 12 行，比值
    1.83），比任何装甲分面都陡，因此不会被肩甲、裙甲或胸甲骗到。
    """
    best_y, best = None, 1.0
    for y in range(y_from + k, y_to):
        a, b = span[y - k], span[y]
        if not (np.isfinite(a) and np.isfinite(b)) or a <= 0:
            continue
        r = b / a
        if r > best:
            best, best_y = r, y
    return best_y if best > 1.45 else None


def head_and_shoulder(m, p):
    """头高 = 颈线 y − 冠点 y；头宽 = 头盔中下段的最大行宽。

    三代口径踩过的坑都记在这里，别再退回去：
      v1 取「上部 30% 最窄行」当颈线 —— 头顶 V 天线就是全图最窄行，头高读成 0、
         头身比读成 1:1477。
      v2 取「宽度首次 > 2 倍头宽」当肩线、再 ×0.78 —— 正视图勉强能用，但
         3/4 下肩甲投影更宽、判据上移，头高被读成 1.22h，8.6 掉到 7.0；
         局部重绘把领口糊满后，判据落到胸甲（y=445），头高读成 309。
      v3（当前）冠点 → 颈窝（无颈窝则最陡加宽行）→ 用该高度重取一次头宽。
         冠点跳过天线这类细长突起；头宽在头盔中下段重取，排除 V 天线翼展
         （翼展最大 1.04 头宽，不排除会让「肩/头」系统性偏低，且正视与 3/4
         不可比 —— 天线转动后投影会变窄）。
    """
    L, R, H = p['L'], p['R'], p['H']
    y0, y1 = p['y0'], p['y1']
    span = R - L + 1
    body = max(1, y1 - y0 + 1)

    band = span[y0: y0 + max(3, int(H * 0.15))]
    # 冠点：不能用「达到全局最宽的某个比例」——重型机体的头可能只有肩宽的 0.28，
    # 0.45 的阈值会直接跳过整个头、把肩线当冠点（实测出现头宽 470px 的荒谬值）。
    # 改成两段：先用最陡加宽行定位肩线，再在它上方按 0.55 倍「该区间最宽」定冠点。
    sh_probe = _neck_widen(span, 0.5 * float(np.nanmax(band)), y0 + 3,
                           y0 + int(H * 0.35))
    if sh_probe is None:
        sh_probe = y0 + int(H * 0.17)
    hw_top = float(np.nanmax(span[y0: sh_probe])) if sh_probe > y0 + 4 else float(np.nanmax(band))
    crown = y0
    for i in range(0, max(1, sh_probe - y0)):
        if span[y0 + i] >= 0.55 * hw_top:
            crown = y0 + i
            break

    head_w = float(np.nanmax(span[crown: crown + max(3, int(H * 0.10))]))
    y_lo = crown + max(2, int(0.30 * head_w))
    y_hi = min(y1, crown + int(H * 0.24))

    neck_y = _neck_pinch(span, head_w, y_lo, y_hi)
    neck_ok = neck_y is not None
    if neck_y is None:
        neck_y = _neck_widen(span, head_w, y_lo, y_hi)
    if neck_y is None:                       # 都失败就退回按比例估
        neck_y = crown + max(1, int(body * 0.122))

    hh = max(1, neck_y - crown)
    lo, hi = int(crown + 0.34 * hh), int(crown + 0.86 * hh)
    if hi - lo >= 3:
        hw2 = float(np.nanmax(span[lo:hi]))
        if 0.72 * head_w < hw2 <= head_w + 0.5:
            head_w = hw2
    # 头宽换了以后再定一次颈线，但只在合理带内接受，否则保留第一次的结果
    y_lo2 = crown + max(2, int(0.30 * head_w))
    n2 = _neck_pinch(span, head_w, y_lo2, y_hi) or _neck_widen(span, head_w, y_lo2, y_hi)
    if n2 and int(crown + 0.55 * hh) <= n2 <= int(crown + 1.10 * hh):
        neck_y = n2

    head_h = max(1, int(neck_y - crown))
    body_h = y1 - crown + 1
    shoulder = float(np.nanmax(span[neck_y: min(y1, neck_y + int(H * 0.25))]))
    widest_y = int(np.nanargmax(span[crown: y1 + 1])) + crown
    return dict(neck_y=neck_y, crown_y=crown, neck_ok=neck_ok, head_h=head_h,
                head_w=head_w, shoulder=shoulder,
                ratio=body_h / max(head_h, 1), sw_hw=shoulder / max(head_w, 1),
                widest_rel=(widest_y - crown) / max(body_h, 1))


def asym(m, p):
    """左右不对称度：逐行比较「中线到左缘」与「中线到右缘」的相对差。

    这是唯一能纯靠像素区分「正视」和「3/4」的指标 —— 因为左右对称的物体绕竖轴
    旋转后，剪影本身仍然是左右对称的（前后面各自对称、并集也对称），所以
    「看起来像不像 3/4」在剪影层面只能靠姿态不对称（一端肢体前移/外张）来表达。
    实测：正视控制 0.4%、正视线稿 3.5%；3/4 控制 80.0%、3/4 线稿 70.8%。
    """
    L, R = p['L'], p['R']
    mid = (L + R) / 2
    cx = np.nanmedian(mid)
    w = np.maximum(R - L + 1, 1)
    a = np.nanmean(np.abs((cx - L) - (R - cx)) / w)
    return float(a), float(np.nanmean(mid) - cx)


def reversals(w, k=3):
    """宽度剖面的收放反转次数。先用 k 点中值滤波压掉锯齿。

    坑：剖面里只要有空行（两腿之间、手臂与躯干之间）就是 nan，而 nan 会让
    np.convolve 整段变 nan、sgn 为空，反转数恒报 0。所以先把 nan 线性插值补掉。
    """
    w = np.asarray(w, float)
    bad = ~np.isfinite(w)
    if bad.any():
        idx = np.arange(len(w))
        if (~bad).sum() < 2:
            return 0, []
        w = np.interp(idx, idx[~bad], w[~bad])
    if len(w) < 2 * k + 1:
        return 0, []
    s = np.convolve(w, np.ones(k) / k, mode='same')
    d = np.diff(s)
    sgn = np.sign(d)
    sgn = sgn[sgn != 0]
    if len(sgn) == 0:
        return 0, []
    turn = np.nonzero(np.diff(sgn) != 0)[0]
    # 只数幅度足够的转折（相邻极值差 > 4% 画幅宽）
    keep = []
    for i in turn:
        a = s[max(0, i - k)]
        b = s[min(len(s) - 1, i + k)]
        if abs(b - a) > 0.02 * max(w.max(), 1):
            keep.append(i)
    return len(keep), keep


def straightness(p):
    """长直边检测：左/右边缘连续「零位移」的最长行数 + 折面行占比。"""
    L, R = p['L'], p['R']
    ys = np.nonzero(~np.isnan(L))[0]
    y0, y1 = ys.min(), ys.max()
    out = {}
    for name, E in (('L', L), ('R', R)):
        e = E[y0:y1 + 1]
        d = np.diff(e)
        d = d[~np.isnan(d)]
        run = best = 0
        for v in d:
            if v == 0:
                run += 1
                best = max(best, run)
            else:
                run = 0
        out[name + '_flat'] = best
        out[name + '_bevel'] = float(np.mean((np.abs(d) >= 1) & (np.abs(d) <= 4))) if len(d) else 0
        out[name + '_jump'] = int(np.sum(np.abs(d) > 12))
    return out


def report(path):
    m, gray = load_mask(path)
    p = profile(m)
    if p is None:
        print('空图'); return
    hs = head_and_shoulder(m, p)
    cov = m.mean()
    bg = float(np.mean(gray[:20, :20])) / 255.0
    n, keep = reversals(p['w'])
    st = straightness(p)
    print('文件  %s' % path.split('/')[-1])
    print('画布  %dx%d  主体占比 %.1f%%  左上背景亮度 %.2f（应≈1.00）'
          % (p['W'], m.shape[0], cov * 100, bg))
    print('尺寸  高 %d px  实宽 %d px（画布 %d）'
          % (p['H'], int(np.nanmax(p['R']) - np.nanmin(p['L']) + 1), p['W']))
    if hs:
        print('比例  头高 %d  头身比 1:%.1f（目标 8.2~8.8）  头宽 %d  肩宽 %d  '
              '肩/头 %.2f（目标 2.1~2.6）  最宽行 %.0f%%（应 <25%%，即肩部）'
              % (hs['head_h'], hs['ratio'], hs['head_w'], hs['shoulder'],
                 hs['sw_hw'], hs['widest_rel'] * 100))
    print('剖面  宽度序列（归一，自上而下 %d 采样）:' % len(p['w']))
    wmax = np.nanmax(p['w'])
    w = p['w'] / wmax
    print('      ' + ' '.join('--' if not np.isfinite(v) else '%.2f' % v for v in w))
    a, sh = asym(m, p)
    print('视角  左右不对称 %.1f%%（正视 <5%%，3/4 >=50%%）  重心横移 %+.1f px' % (a * 100, sh))
    print('收放  反转 %d 次（目标 >=3）' % n)
    print('边线  左：最长直段 %d 行 / 折面行占比 %.2f / 突跳(>12px) %d 处'
          % (st['L_flat'], st['L_bevel'], st['L_jump']))
    print('      右：最长直段 %d 行 / 折面行占比 %.2f / 突跳(>12px) %d 处'
          % (st['R_flat'], st['R_bevel'], st['R_jump']))


def ascii_sil(m, cols=48, rows=34):
    Hh, Ww = m.shape
    ys = np.nonzero(m.any(axis=1))[0]
    xs = np.nonzero(m.any(axis=0))[0]
    if len(ys) == 0:
        return ''
    y0, y1 = ys.min(), ys.max()
    x0, x1 = xs.min(), xs.max()
    out = []
    for r in range(rows):
        line = []
        for c in range(cols):
            a = y0 + int((y1 - y0 + 1) * r / rows)
            b = y0 + int((y1 - y0 + 1) * (r + 1) / rows)
            u = x0 + int((x1 - x0 + 1) * c / cols)
            v = x0 + int((x1 - x0 + 1) * (c + 1) / cols)
            f = m[a:max(a + 1, b), u:max(u + 1, v)].mean()
            line.append('#' if f > 0.5 else ('+' if f > 0.15 else '.'))
        out.append(''.join(line))
    return '\n'.join(out)


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    for a in args:
        report(a)
        if '--ascii' in sys.argv:
            m, _ = load_mask(a)
            print(ascii_sil(m))
        print('-' * 90)
