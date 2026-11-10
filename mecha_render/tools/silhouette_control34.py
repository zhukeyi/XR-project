"""tools/silhouette_control34.py — 三分之四视角的「比例已锁定」控制剪影

为什么单独一份：正视图那份（silhouette_control.py）是纯平面坐标，身体各部件
都在 z=0 平面上，转到 3/4 就没法靠「左右移动」表达深度。这里改成一次
正交斜投影：把每个部件定义成 (x, u, z) + (rx, ru, rz) 的三维体块，按
screen_x = x·cosθ + z·sinθ 投影，按 z 从远到近叠画。

θ=32°：足够看出侧面（胸背厚度、裙甲侧片、小腿腓肠肌侧轮廓），又不至于
把肩宽压得太窄导致比例判读失真。

**所有长度以「头高 h」为单位，且与 3D 模型对齐**（h = 18.2 m / 8.6 = 2.12 m）：
肩宽目标 2.80 h（占机高 0.33，对标 RX-78 的 0.30~0.33）——
早先版本只有 2.16 h（0.25 机高），所以读起来偏瘦、偏女性向。这不是审美
主观判断，是肩宽/机高比落在什么区间的问题。

投影口径：
  · 回转体（头盔、腿、喷口）用 hypot(rx·cosθ, rz·sinθ) 取投影半宽，
    球体在任何角度投影宽度都相同，这样头宽不会被 3/4 虚增；
  · 方箱/斜切甲（胸甲、肩甲、裙甲）用 rx·cosθ + rz·sinθ，因为箱体是
    角顶着最外，3/4 视角下肩宽会实测变宽 —— 这不是画错，是几何必然。
  · 因此肩甲用「方箱口径」而不是回转口径，凌厉的折面同时也把肩撑住了。

用法：python3 tools/silhouette_control34.py out/seed_sketch/control34.png --clean
"""
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

W, H = 1024, 1536
HH = 8.6
TOP = 70
h = (H - 2 * TOP) / HH
CX = 500
TH = math.radians(32.0)
C, S = math.cos(TH), math.sin(TH)

SHEAR = 0.035                # 肩线/胯线的轻微倾斜：近侧压低 shear·x，制造左右不等
                             # 3/4 最容易被读成「正面」的原因就是左右对称，剪影层面
                             # 唯一稳的不对称信号就是肩线不是水平的

# ---------------------------------------------------------------- 体量参数
# 每一项都写清「为什么是这个数」，方便下一轮只调一处而不推翻全部
P = dict(
    # 躯干：胸要压住腰，腰不能收太狠（早先 0.55 半宽 + 0.47 过渡 = 沙漏感）
    chest=(0.96, 0.54, 0.66),      # 胸 半宽 x / 半高 / 半深（深 0.56→0.66，
                                   # 3/4 下厚度是「体积感」的主要来源）
    waist=(0.80, 0.58, 0.56),
    pelvis=(0.84, 0.32, 0.54),
    # 肩甲：x 中心 / 半宽 / 半高 / 半深。外缘投影 = 1.33·cos + 0.36·sin + 0.20·cos
    shoulder=(1.30, 0.22, 0.30, 0.38),
    shoulder_u=1.58,               # 肩甲垂直中心（肩线 1.34）
    # 腿：实测原来双腿合计只有 0.87 h = 肩宽的 34%，从骨盆到腿根骤降 48%
    # —— 这才是「一看就不厉害」的形状来源，不是肩宽。现在按
    # 「双腿合计 ≈ 肩宽 0.58」反推：单腿半宽 0.375、中心 ±0.40 → 合计 1.55 h
    thigh=0.450, calf=0.415, ankle=0.195,
    leg_x=0.455,
    # 脚：早先半宽 0.198 站不住；现在跟腿一起加，0.320 / 0.430
    foot_w=0.380, foot_d=0.500,
    # 臂：加粗但外缘必须留在肩甲内侧
    uarm=0.195, farm=0.192,
)


def Y(u):
    return TOP + u * h


def PX(x, z):
    return CX + (x * C + z * S) * h


def depth_scale(z):
    """轻度透视：越靠前（z 小）略微放大，k 很小，避免破坏比例判读"""
    return 1.0 - 0.030 * z


def rnd(rx, rz):
    return math.hypot(rx * C, rz * S)


def box(rx, rz):
    return rx * C + rz * S


class Canvas:
    def __init__(self):
        self.img = Image.new('L', (W, H), 255)
        self.d = ImageDraw.Draw(self.img)

    def _c(self, x, u, z):
        return CX + (x * C + z * S) * h, TOP + (u + SHEAR * x) * h

    def _k(self, z):
        return depth_scale(z)

    def rotsolid(self, x, u, z, rx, ru, rz, squarish=False):
        """回转体 → 投影椭圆；squarish=True 时改画八边切角块（甲片用）"""
        k = self._k(z)
        cxp, cyp = self._c(x, u, z)
        proj = box if squarish else rnd
        hw, hh = proj(rx, rz) * h * k, ru * h * k
        if not squarish:
            self.d.ellipse([cxp - hw, cyp - hh, cxp + hw, cyp + hh], fill=0)
            return
        cx_, cy_ = hw * 0.52, hh * 0.52
        self.d.polygon([(cxp - hw, cyp - cy_), (cxp - cx_, cyp - hh),
                        (cxp + cx_, cyp - hh), (cxp + hw, cyp - cy_),
                        (cxp + hw, cyp + cy_), (cxp + cx_, cyp + hh),
                        (cxp - cx_, cyp + hh), (cxp - hw, cyp + cy_)], fill=0)

    def octa(self, x, u, z, rx, ru, rz, cham=0.55):
        """带切角的方箱：八顶点斜切，落点是 45° 倒角面而不是 90° 直角。
        这是「不要矩形堆砌」在控制图层面能做的事 —— 剪影的转折处就是斜的。
        """
        k = self._k(z)
        cxp, cyp = self._c(x, u, z)
        hw, hh = box(rx, rz) * h * k, ru * h * k
        cx_, cy_ = hw * cham, hh * cham
        self.d.polygon([(cxp - hw, cyp - cy_), (cxp - cx_, cyp - hh),
                        (cxp + cx_, cyp - hh), (cxp + hw, cyp - cy_),
                        (cxp + hw, cyp + cy_), (cxp + cx_, cyp + hh),
                        (cxp - cx_, cyp + hh), (cxp - hw, cyp + cy_)], fill=0)

    def taper(self, s_pairs, x, z, round_=True):
        """沿 u 逐段收放的柱体（腿/臂）。s_pairs=[(u, 半宽x, 半宽z), ...]

        肢体断面是圆/椭圆，投影半宽必须用 hypot；早先用箱体公式 box()，
        大腿在 3/4 下厚了 37%（0.335h vs 正视 0.245h），两条腿直接糊成一块。
        """
        proj = rnd if round_ else box
        # ★ 曾有一处隐蔽的重复投影：w 已经是用 hypot/box 算好的**投影后**半宽，
        #   却又把 (x±w) 送回 PX() 再乘一次 cosθ，于是所有肢体宽度被压了 0.848 倍。
        #   症状是「怎么加粗都还是细」—— 因为加多少都被吃掉 15%。
        #   正确做法：中心投影一次，半宽直接加在屏幕像素上。
        cxs = PX(x, z)
        left, right = [], []
        for u, rx, rz in s_pairs:
            w = proj(rx, rz) * h * self._k(z)
            uu = u + SHEAR * x
            left.append((cxs - w, Y(uu)))
            right.append((cxs + w, Y(uu)))
        self.d.polygon(left + right[::-1], fill=0)

    def plate(self, pts3):
        """一块板：pts3 = [(x, u, z), ...]"""
        self.d.polygon([self._c(p[0], p[1], p[2]) for p in pts3], fill=0)


def build():
    cv = Canvas()
    # ---------- 背包 / 推进器（在最深处，先画）----------
    # 3D 模型里背包挂在 chest 的 z=-2.30 处，双段翼板 + 三段收口喷口。
    # 草图这里照它的真实结构画：中央块 + 左右翼板 + 两个喷口柱，
    # 翼板向上越过肩线、喷口向下压到腰下，这样 3/4 剪影才有「背后有东西」。
    cv.octa(0.0, 2.18, 0.66, 0.46, 0.70, 0.34, cham=0.60)          # 背包主体
    for s in (1, -1):
        # 翼板：从背包上部斜向外上，尖端略低于头，形成两道斜棱（不是矩形挂件）
        cv.plate([(s * 0.20, 1.62, 0.60), (s * 0.78, 1.22, 0.76),
                  (s * 0.86, 1.62, 0.80), (s * 0.30, 2.05, 0.66)])
        cv.plate([(s * 0.24, 2.10, 0.68), (s * 0.72, 1.95, 0.82),
                  (s * 0.66, 2.62, 0.78), (s * 0.22, 2.72, 0.64)])
        # 喷口：三段收口（对应 3D 的 noz_a/b/c），朝后下方
        cv.rotsolid(s * 0.34, 2.86, 0.62, 0.20, 0.24, 0.20)
        cv.rotsolid(s * 0.34, 3.12, 0.62, 0.24, 0.16, 0.24)
        cv.rotsolid(s * 0.34, 3.30, 0.62, 0.17, 0.10, 0.17)

    # ---------- 远侧（z 大）----------
    # 远侧手臂：整条推到躯干后方，只露外侧一截 —— 3/4 最重要的读图线索：
    # 远处肢体被躯干切断，不是并排摆着的
    cv.taper([(1.50, 0.176, 0.176), (2.08, 0.168, 0.170), (2.40, 0.160, 0.164),
              (2.52, 0.146, 0.152), (3.08, 0.172, 0.174), (3.64, 0.166, 0.168),
              (3.78, 0.118, 0.124), (4.06, 0.144, 0.148), (4.46, 0.140, 0.142)],
             -0.82, 0.58)
    cv.taper(_leg(), -P['leg_x'], 0.20)

    # ---------- 躯干 ----------
    cw, ch, cd = P['chest']
    cv.octa(0.0, 1.86, 0.0, cw, ch, cd, cham=0.62)
    ww, wh, wd = P['waist']
    cv.octa(0.0, 2.46, 0.0, ww, wh, wd, cham=0.60)
    pw, ph, pd = P['pelvis']
    cv.octa(0.0, 3.12, 0.0, pw, ph, pd, cham=0.58)
    # 胸口分面：一块向前凸的斜置装甲，3/4 下压出侧棱
    cv.plate([(-0.84, 1.42, -0.38), (0.12, 1.70, -0.50),
              (0.16, 2.46, -0.44), (-0.56, 2.80, -0.32)])
    # 领口：从肩侧斜收到颈根 —— 「头嵌进领口」的关键形
    cv.plate([(-0.80, 1.38, -0.32), (-0.24, 1.04, -0.24),
              (0.24, 1.04, -0.24), (0.80, 1.38, -0.32),
              (0.52, 1.50, -0.34), (-0.52, 1.50, -0.34)])
    # 裙甲：前片 + 两侧片（3/4 下侧片是厚度信息的主要来源）
    cv.plate([(-0.66, 3.30, -0.32), (0.66, 3.30, -0.32),
              (0.58, 3.96, -0.28), (-0.58, 3.96, -0.28)])
    for s in (1, -1):
        cv.plate([(s * 0.62, 3.34, -0.26), (s * 0.72, 3.32, 0.18),
                  (s * 0.66, 3.98, 0.16), (s * 0.56, 4.00, -0.24)])

    # ---------- 肩甲（凌厉：四段折线外缘，不是椭圆）----------
    sx, srx, sru, srz = P['shoulder']
    su = P['shoulder_u']
    for s, zt in ((1, -0.14), (-1, 0.26)):
        # 主甲：外缘两道折线（斜上 → 竖直 → 斜下），内缘贴住领口
        cv.plate([(s * 0.52, su - 0.30, zt - 0.30), (s * (sx + srx), su - 0.16, zt - 0.34),
                  (s * (sx + srx * 0.94), su + 0.16, zt - 0.30), (s * (sx - 0.04), su + 0.30, zt - 0.26),
                  (s * (sx - 0.04), su + 0.30, zt + srz), (s * 0.54, su + 0.22, zt + srz),
                  (s * 0.54, su - 0.26, zt + srz)])
        # 顶盖：压住肩甲上缘，做出「甲片叠压」的层
        cv.plate([(s * 0.58, su - 0.34, zt - 0.24), (s * (sx + srx * 0.8), su - 0.20, zt - 0.24),
                  (s * (sx + srx * 0.8), su - 0.06, zt + srz * 0.8), (s * 0.58, su - 0.18, zt + srz * 0.8)])
        # 前缘红条位置（配色锚点）
        cv.plate([(s * (sx + srx * 0.9), su - 0.30, zt - 0.10), (s * (sx + srx * 0.86), su - 0.30, zt + 0.22),
                  (s * (sx + srx * 0.60), su + 0.04, zt + 0.22), (s * (sx + srx * 0.62), su + 0.04, zt - 0.10)])

    # ---------- 近侧手臂 / 腿（后画，压在前面）----------
    cv.taper([(1.50, 0.176, 0.176), (2.08, 0.168, 0.170), (2.40, 0.160, 0.164),
              (2.52, 0.146, 0.152), (3.08, 0.172, 0.174), (3.64, 0.166, 0.168),
              (3.78, 0.118, 0.124), (4.06, 0.144, 0.148), (4.46, 0.140, 0.142)],
             0.94, -0.24)
    cv.taper(_leg(), P['leg_x'], -0.12)

    # ---------- 颈 / 头（头嵌进领口：颈根 1.06，领口上沿 1.04）----------
    cv.taper([(0.92, 0.160, 0.175), (1.40, 0.182, 0.196)], 0.02, 0.0)
    for u, rx, ru, rz in ((0.22, 0.315, 0.215, 0.360),
                          (0.44, 0.400, 0.235, 0.420),
                          (0.64, 0.415, 0.225, 0.415),
                          (0.82, 0.350, 0.185, 0.360),
                          (0.96, 0.250, 0.130, 0.290)):
        cv.rotsolid(0.055, u, -0.04, rx, ru, rz)
    cv.plate([(-0.26, 0.48, -0.30), (-0.26, 0.86, -0.28),
              (0.20, 0.98, -0.26), (0.26, 0.52, -0.26)])
    cv.plate([(-0.28, 0.74, -0.16), (0.28, 0.74, -0.16),
              (0.18, 1.02, -0.10), (-0.18, 1.02, -0.10)])
    # V 天线：两根斜伸薄板（3/4 下两根不等长，这是透视正确的表现）
    cv.plate([(-0.06, 0.34, -0.22), (-0.50, -0.10, -0.46), (-0.38, 0.24, -0.30)])
    cv.plate([(0.08, 0.34, -0.26), (0.46, -0.06, -0.52), (0.34, 0.26, -0.34)])
    return cv.img


def _leg():
    """腿：大腿 → 膝 → 腓肠肌外扩 → 踝收窄 → 脚。一整条不断，
    早先给每段各画一个 quad，小腿 6.34→7.20 之间漏画，剪影断成两截。"""
    return [(3.12, P['thigh'], P['thigh'] * 0.92),
            (3.60, P['thigh'] + 0.025, P['thigh'] * 0.94),
            (4.55, P['thigh'] - 0.020, P['thigh'] * 0.94),
            (4.92, P['thigh'] - 0.060, P['thigh'] * 0.90),
            (5.10, P['calf'] - 0.050, P['calf'] * 0.96),
            (5.46, P['calf'] - 0.055, P['calf'] * 0.96),
            (5.96, P['calf'], P['calf'] * 0.94),      # 腓肠肌外扩（3/4 下最宽处）
            (6.56, P['calf'] - 0.060, P['calf'] * 0.92),
            (7.10, 0.300, 0.300),
            (7.56, 0.236, 0.250),
            (7.88, P['ankle'], P['ankle'] * 1.15),     # 踝最窄
            (8.04, 0.258, 0.340),
            (8.24, P['foot_w'] * 0.92, P['foot_d'] * 0.88),
            (8.40, P['foot_w'], P['foot_d'])]


def construction_lines(img):
    g = Image.new('L', (W, H), 255)
    d = ImageDraw.Draw(g)
    for u in (0.0, 1.04, 1.34, 2.92, 3.36, 5.05, 7.88):
        y = Y(u)
        for x in range(0, W, 26):
            d.line([(x, y), (x + 13, y)], fill=205, width=2)
    for y in range(0, H, 26):
        d.line([(CX, y), (CX, y + 13)], fill=215, width=2)
    out = Image.composite(Image.new('L', (W, H), 255), g, img.point(lambda v: 255 - v))
    return Image.fromarray(np.minimum(np.asarray(img), np.asarray(out)))


if __name__ == '__main__':
    out = sys.argv[1] if len(sys.argv) > 1 else 'out/seed_sketch/control34.png'
    os.makedirs(os.path.dirname(out) or '.', exist_ok=True)
    im = build() if '--clean' in sys.argv else construction_lines(build())
    im.convert('RGB').save(out)
    print('3/4 控制剪影 -> %s  (%dx%d, %.1f 头身, θ=%.0f°)' % (out, W, H, HH, math.degrees(TH)))
