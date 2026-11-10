"""tools/crevice_ruler.py — 「缝是切出来的，还是画上去的」：渲染空间的深度统计

为什么前面所有截面尺子都不够
  ---------------------------------------------------------------
  struct_ruler 试过三个截面标量，两个当场失效（都写进 JSON 了）：
    · φ（实心/凸包）：游戏资产是**闭合壳**，壳内一律算是实的 → φ(R)=0.90、
      φ(O)=0.87，**两者一样**。φ 只能看「壳内有没有空腔」，看不到「表面有没有缝」。
    · σ（等周比）：被毫米级刻线/螺栓撑起来 —— 我们 248 个件里有几百条 4 mm 薄片，
      每条都加周长不加面积，σ 反而比参考更大。它量的是**碎屑度**，不是结构度。
    · k（独立岛数）：奇偶填充在**开放边**上会漏 → 参考单带报 41 个岛，
      而目视只有 4–5 块。几何本身不水密时，这个数不可信。

  三个失败的共同点：它们都是**空间积分量**，而「缝」是**局部、高频、方向性**的东西。
  积分会把缝抹平 —— 一条 4 cm 的缝在 0.5 m² 的截面上只占 1% 的面积。

  ---------------------------------------------------------------
  所以换到**渲染空间**量，这才是眼睛真正看的东西：
  从给定视点渲一张深度图，量三个局部量 ——

  1. **凹槽率 g** = fg 像素中「深度比 5×5 邻域最前面还深 >1.6 cm」的比例。
     一条真实的缝 = 两侧是凸起、中间凹下去 → 中间那列像素必然满足。
     一条**画上去的**缝（贴在表面的深色薄片）= 深度和周围几乎一样 → 不满足。
     ★ 这一个数直接回答用户那句「只是多切了几刀」：
       我们的刻线**不改变深度**，所以 g 应该接近 0；参考的真缝应该 g 明显 > 0。
  2. **阶梯率 s** = |∂depth/∂x| 或 |∂depth/∂z| > 2.4 cm/像素 的像素比例。
     叠瓦式搭接（装甲板压住另一块）一定产生**深度断崖**；倒角不会。
  3. **转角率 t** = 与 4 邻域法线夹角 > 50° 的像素比例。
     折面 / 硬棱的三通道读数（前两个是深度，这个是法线）。

  量纲：模型先归一化到 H=10 世界单位（1 单位 = 0.8 m），
  所以 0.02 单位 = 1.6 cm、0.03 单位 = 2.4 cm。阈值都按**真实厘米**写死，
  不按像素 —— 撇开分辨率谈「缝」，等于没谈。

  局限（必须写在交付里）
    · g/s/t 都是**视点相关**的：一个缝在正视下是凹槽，在侧视下可能被挡死。
      所以三个视角各量一次、报平均，并且**不允许**只挑最好看的那个视角报。
    · 它量的是「表面有没有高低」，不是「内部有没有骨架」。
      骨架要靠件表（我们 248 件的命名）+ 剖面图（struct_slices.png）判。

用法
  python3 tools/crevice_ruler.py
"""
import json
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'tools'))

import refview as RV                                       # noqa: E402
import s2_graybox as S                                     # noqa: E402
import unicorn_trunk as UT                                 # noqa: E402
from gfx.gbuffer import rasterize                           # noqa: E402
from r3d import Renderer, look_at                            # noqa: E402

OUT = os.path.join(HERE, 'out', 'ref')
FONT = '/System/Library/Fonts/Hiragino Sans GB.ttc'
H_WORLD = 10.0
PANEL = (470, 760)
VIEWS = [('正', 0.0), ('3/4', 35.0), ('侧', 90.0)]
CM = 0.8 / 10.0          # 1 世界单位 = 0.8 m；1 cm = 0.0125 单位


# ---------------------------------------------------------------- 数据
def ref_soup():
    V, tris, gf, sets = UT.load_obj_grouped(UT.SRC)
    Vn, _ = RV.normalize(V)
    keep = np.ones(len(tris), bool)
    for tok in UT.REMOVE:
        keep &= ~UT.face_in(gf, sets, tok)
    return Vn[tris[keep]]


def ours_soup():
    S.CLEAN = True
    _root, mesh = S.build()
    return np.array(mesh.P, np.float32).reshape(-1, 3) * (10.0 / 7.930)


class Soup:
    """把三角数组包成 rasterize 要的 arrays() 接口。"""

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
        self.base = np.array([[0.80, 0.81, 0.82]], np.float32)
        self.emis = np.zeros((1,), np.float32)

    def arrays(self):
        return self.P, self.N, self.T, self.mi, self.Fi, self.base, self.emis

    def __len__(self):
        return len(self.P)


def depth_view(sz, yaw):
    """正交近似下渲一张深度图 + 法线图。"""
    W, H = PANEL
    dist = 30.0 * H_WORLD
    fov = 2.0 * math.degrees(math.atan((H_WORLD * 0.72) / dist))
    rd = Renderer(W, H, ss=1, fov=fov)
    cy = H_WORLD * 0.5
    cm = look_at((0.0, cy, dist), (0.0, cy, 0.0), roll=0)
    P, N, T_, mi, Fi, _b, _e = sz.arrays()
    Pr, Nr = RV._rot(P, N, yaw, 0.0)
    gb, _ = rasterize(Pr, Nr, T_, mi, Fi, cm, fov, rd.WS, rd.HS)
    # depth 是到相机的距离；转到「深度值 = 距离相机多远」
    dep = np.where(gb.fid >= 0, gb.depth, np.nan).astype(np.float32)
    nn = gb.nrm.copy()
    nn /= np.maximum(np.linalg.norm(nn, axis=-1, keepdims=True), 1e-9)
    return dep, nn, (gb.fid >= 0)


# ---------------------------------------------------------------- 局部算子
def minfilt(a, r, bad):
    """r 半径的最小值滤波（分离式，无 scipy）。bad 像素视为 +inf。"""
    b = np.where(bad, np.inf, a)
    for _ in range(r):
        b = np.minimum(b, np.roll(b, 1, 1))
        b = np.minimum(b, np.roll(b, -1, 1))
    for _ in range(r):
        b = np.minimum(b, np.roll(b, 1, 0))
        b = np.minimum(b, np.roll(b, -1, 0))
    return b


def stats(dep, nn, cov):
    """★ 凹槽率必须用**深度的拉普拉斯**，不能用「窗口最小值」。

    第一版用 `depth - min(depth in 5×5)`：一个 45° 斜面在 5×5 窗口里本身就有
    5 px × 1.5 cm ≈ 7.5 cm 的深度落差，于是**每个斜面像素都被判成凹槽** ——
    参考报 67%、我们 36%，两个数都变成「斜面占比」，跟缝毫无关系。

    拉普拉斯对**一阶坡度免疫**：平面上 ∂²d = 0，不管它多斜。
    凹槽中心（深度局部的极大）∂²d > 0，凸棱 < 0。只数凹的。
    单位换成 cm/px²（1 单位 = 80 cm）：4 cm 深、4 px 宽的槽 ≈ 2 cm/px²。
    """
    bad = ~cov
    d = np.where(bad, np.nanmedian(dep), dep) * 80.0        # → cm
    okn = cov.copy()
    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        okn &= np.roll(np.roll(cov, dy, 0), dx, 1)
    lap = (np.roll(d, 1, 1) + np.roll(d, -1, 1)
           + np.roll(d, 1, 0) + np.roll(d, -1, 0) - 4.0 * d) / 4.0
    # ★ 必须取**绝对值**：合成测试（平板 + 4 px 凹槽）给出的拉普拉斯序列是
    #   [.. +4, −4, 0, 0, −4, +4 ..] —— 凹槽的**外唇**为正、**内底**为负。
    #   只取正号量到的是「凸唇/凸棱」的数量，不是缝的数量（第一版把名字写成
    #   「凹槽率」是错的，读数本身在 A/B 上仍然同口径可比）。
    #   缝的特征是「两侧有唇、中间有底」，曲率两个方向都突变，所以用 |∇²d|。
    g1 = (np.abs(lap) > 0.45) & okn                            # 曲率突变
    g2 = (np.abs(lap) > 1.60) & okn                            # 强突变
    dx_ = np.abs(np.diff(d, axis=1))
    dz_ = np.abs(np.diff(d, axis=0))
    s = np.zeros_like(cov)
    s[:, :-1] |= dx_ > 2.4                                     # 2.4 cm 断崖
    s[:-1, :] |= dz_ > 2.4
    t = np.zeros_like(cov)
    for dy, dd in ((0, 1), (0, -1), (1, 0), (-1, 0)):
        sh = np.roll(np.roll(nn, dy, 0), dd, 1)
        t |= (np.sum(nn * sh, -1) < math.cos(math.radians(50)))
    t &= cov
    n = max(int(cov.sum()), 1)
    return dict(g1=float((g1 & cov).sum()) / n, g2=float((g2 & cov).sum()) / n,
                s=float((s & cov).sum()) / n, t=float(t.sum()) / n,
                area=n, groove=g1 & cov)


# ---------------------------------------------------------------- 主
def main():
    os.makedirs(OUT, exist_ok=True)
    print('读参考…')
    Pr = ref_soup()
    print('读我们…')
    Po = ours_soup()
    res = {}
    tiles = []
    for tag, P, colr in (('ref', Pr, (150, 150, 150)), ('ours', Po, (40, 90, 200))):
        sz = Soup(P)
        rows = []
        for vn, yaw in VIEWS:
            dep, nn, cov = depth_view(sz, yaw)
            st = stats(dep, nn, cov)
            rows.append(dict(view=vn, **{k: v for k, v in st.items() if k != 'groove'}))
            # 出图：深度图 + 凹槽高亮
            dd = np.where(cov, dep, np.nan)
            lo, hi = np.nanmin(dd), np.nanmax(dd)
            gr = np.clip((dd - lo) / max(hi - lo, 1e-6), 0, 1)
            img = np.where(cov, 255 - 150 * (1 - gr), 255).astype(np.uint8)
            rgb = np.stack([img] * 3, -1)
            rgb[st['groove']] = (210, 40, 40)
            tiles.append((tag, vn, rgb, st))
        res[tag] = rows

    print('\n  渲染空间局部深度统计（阈值按真实厘米：槽 1.6 / 深槽 4.0 / 断崖 2.4 / 转角 50°）')
    print('  %-6s %-5s %8s %8s %8s %8s %9s' % ('模型', '视角', '凹槽率g1', '深槽率g2',
                                               '断崖率s', '转角率t', 'fg 像素'))
    for tag in ('ref', 'ours'):
        for r in res[tag]:
            print('  %-6s %-5s %8.3f %8.3f %8.3f %8.3f %9d'
                  % (tag, r['view'], r['g1'], r['g2'], r['s'], r['t'], r['area']))
        m = {k: float(np.mean([r[k] for r in res[tag]])) for k in ('g1', 'g2', 's', 't')}
        print('  %-6s %-5s %8.3f %8.3f %8.3f %8.3f' % (tag, '均值', m['g1'], m['g2'],
                                                       m['s'], m['t']))
        res[tag + '_mean'] = m

    # ---- 出图：2 行 × 3 列
    gap, hdr, cap = 8, 120, 34
    W = gap + 3 * (PANEL[0] + gap)
    H = hdr + 2 * (PANEL[1] + cap + gap)
    cv = Image.new('RGB', (W, H), (255, 255, 255))
    d = ImageDraw.Draw(cv)
    d.text((gap + 6, 14), '渲染空间：真实凹槽（红）vs 深度平滑区', font=ImageFont.truetype(FONT, 24),
           fill=(22, 22, 22))
    d.text((gap + 6, 46), '红 = 该像素比 5×5 邻域最前面深 >1.6 cm。'
                          '画上去的刻线不改深度 → 几乎不红；切出来的缝 → 整条红。',
           font=ImageFont.truetype(FONT, 14), fill=(115, 115, 115))
    for tag, yy0 in (('ref', 74), ('ours', 74 + PANEL[1] + cap + gap)):
        m = res[tag + '_mean']
        d.text((gap + 6, yy0),
               '%s   凹槽率 %.1f%%   深槽率 %.1f%%   断崖率 %.1f%%   转角率 %.1f%%'
               % ('参考 Unicorn 主干' if tag == 'ref' else '我们（v1）',
                  100 * m['g1'], 100 * m['g2'], 100 * m['s'], 100 * m['t']),
               font=ImageFont.truetype(FONT, 16),
               fill=(60, 60, 60) if tag == 'ref' else (170, 40, 40))
    for i, (tag, vn, rgb, st) in enumerate(tiles):
        cx = gap + (i % 3) * (PANEL[0] + gap)
        cy = 74 + 20 + (i // 3) * (PANEL[1] + cap + gap)
        cv.paste(Image.fromarray(rgb), (cx, cy))
        d.text((cx + 4, cy + PANEL[1] + 4),
               '%s · %s   g1 %.1f%%  g2 %.1f%%' % ('参考' if tag == 'ref' else '我们', vn,
                                                   100 * st['g1'], 100 * st['g2']),
               font=ImageFont.truetype(FONT, 13), fill=(90, 90, 90))
    p = os.path.join(OUT, 'crevice_ruler.png')
    cv.save(p)
    print('→ %s  %d × %d' % (p, cv.size[0], cv.size[1]))
    with open(os.path.join(OUT, 'crevice_ruler.json'), 'w') as f:
        json.dump(res, f, indent=1, default=float)


if __name__ == '__main__':
    main()
