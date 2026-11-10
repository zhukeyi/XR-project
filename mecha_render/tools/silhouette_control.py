"""tools/silhouette_control.py — 生成「比例已锁定」的控制剪影

为什么需要它：纯文字提示词给不了比例。实测两次——
  v1: 头身比 1:8.2（OK）但肩宽 3.57 头宽，最宽处在身高 45%（双臂外张）
  v2: 肩宽 3.38 头宽，头身比掉到 1:6.2（头被放大）
提示词里写「肩宽 = 2.2 头宽」模型不执行。所以按 SEED 画法分析文档里的结论，
用一个可控的二维骨架把比例钉死，输出 PNG 当 img2img 的结构控制图。

比例全部以「头高 h」为单位（目标 8.4 头身，落在 8.2~8.8 带内）：
  头 0 → 1.0            肩线 1.30（肩宽 2.30 h，即 2.4 个头宽）
  腰 2.90（0.45×肩宽）  胯 3.35（0.55×肩宽）
  膝 5.05                踝 7.90（最窄）
  脚底 8.40
外缘不用直线段堆，全部用椭圆/多段折线，保证边缘是缓折面而不是直角台阶。

用法：python3 tools/silhouette_control.py out/seed_sketch/control_sil.png
"""
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

W, H = 1024, 1536
HH = 8.6                     # 头身比
TOP = 62                     # 头顶 y
h = (H - 2 * TOP) / HH       # 头高（像素）
CX = 512
TURN = 0.055                 # 3/4 转体：整体中线左移（远端右移）的幅度，单位 h


def Y(u):
    return TOP + u * h


def X(u):
    return CX + u * h


def build():
    img = Image.new('L', (W, H), 255)
    d = ImageDraw.Draw(img)

    def blk(**kw):
        d.polygon(kw['pts'], fill=0)

    def ell(u, v, ru, rv, turn=0.0):
        """以头部单位为坐标画实心椭圆；turn>0 向右侧偏移（近端）"""
        cx = X(u + turn * TURN)
        cy = Y(v)
        d.ellipse([cx - ru * h, cy - rv * h, cx + ru * h, cy + rv * h], fill=0)

    def quad(p1, p2, p3, p4, turn=0.0):
        d.polygon([(X(p1[0] + turn * TURN), Y(p1[1])), (X(p2[0] + turn * TURN), Y(p2[1])),
                   (X(p3[0] + turn * TURN), Y(p3[1])), (X(p4[0] + turn * TURN), Y(p4[1]))],
                  fill=0)

    def limb(s, turn, xc, spans):
        """沿 y 逐段收放的一条肢体。spans=[(u, 半宽), ...]，两端自动封口。

        早先版本给小分腿各画一个 quad，结果小腿 6.34→7.20 之间留了一道横缝，
        ASCII 剪影里直接断成两截。
        """
        left = [(X(xc * s + turn * TURN - w), Y(u)) for u, w in spans]
        right = [(X(xc * s + turn * TURN + w), Y(u)) for u, w in reversed(spans)]
        d.polygon(left + right, fill=0)

    # ---------------- 远侧肢体（先画，让近端压在上面）
    for s, turn in ((-1, -0.35), (1, 0.55)):
        # 上臂 → 肘 → 前臂 → 手（贴身，肘不外张，外缘不超肩线 1.12h）
        limb(s, turn, 0.865, [(1.42, 0.145), (2.02, 0.140), (2.34, 0.135),
                              (2.46, 0.125), (3.05, 0.150), (3.62, 0.145),
                              (3.74, 0.100), (4.02, 0.125), (4.40, 0.120)])

        # 大腿 → 膝 → 小腿（腓肠肌外扩）→ 踝 → 脚，一整条不断
        limb(s, turn, 0.365, [(3.12, 0.215), (3.60, 0.245), (4.60, 0.215),
                              (4.92, 0.200), (5.10, 0.230), (5.45, 0.225),
                              (5.95, 0.265), (6.55, 0.220), (7.10, 0.170),
                              (7.55, 0.130), (7.88, 0.105), (8.02, 0.130),
                              (8.28, 0.185), (8.40, 0.200)])

    # ---------------- 躯干：倒三角 + 收腰 + 胯略放
    quad((0, 1.34), (0, 1.34), (0, 1.34), (0, 1.34))     # 占位，避免空 polygon 报错
    d.polygon([(X(-0.70), Y(1.34)), (X(0.70), Y(1.34)), (X(0.62), Y(2.20)),
               (X(0.47), Y(2.92)), (X(0.60), Y(3.36)), (X(-0.60), Y(3.36)),
               (X(-0.47), Y(2.92)), (X(-0.62), Y(2.20))], fill=0)

    # 胸甲分面：用两块略窄的多边形压出斜面暗示（控制图也带一点结构）
    d.polygon([(X(-0.68), Y(1.40)), (X(-0.10), Y(1.62)), (X(-0.16), Y(2.55)),
               (X(-0.46), Y(2.88))], fill=0)
    d.polygon([(X(0.68), Y(1.40)), (X(0.10), Y(1.62)), (X(0.16), Y(2.55)),
               (X(0.46), Y(2.88))], fill=0)

    # 领口：从肩宽斜收到颈根（这是「头颈不脱节」的关键形状）
    d.polygon([(X(-0.66), Y(1.36)), (X(-0.20), Y(1.06)), (X(0.20), Y(1.06)),
               (X(0.66), Y(1.36)), (X(0.44), Y(1.44)), (X(-0.44), Y(1.44))], fill=0)

    # 裙甲 / 骨盆
    d.polygon([(X(-0.58), Y(3.30)), (X(0.58), Y(3.30)), (X(0.52), Y(3.86)),
               (X(-0.52), Y(3.86))], fill=0)
    d.polygon([(X(-0.24), Y(3.40)), (X(0.24), Y(3.40)), (X(0.20), Y(4.02)),
               (X(-0.20), Y(4.02))], fill=0)

    # ---------------- 肩甲（把肩线撑到 1.15h 半宽，不超过）
    for s, turn in ((-1, -0.30), (1, 0.50)):
        ell(s * 0.93, 1.52, 0.205, 0.255, turn)
        ell(s * 0.95, 1.74, 0.185, 0.135, turn)

    # ---------------- 颈 / 头
    quad((0.0 - 0.15, 0.94), (0.0 + 0.15, 0.94), (0.0 + 0.17, 1.36), (0.0 - 0.17, 1.36))
    # 头盔：上宽下收，颧部最宽
    for i, (v, ru, rv) in enumerate(((0.20, 0.36, 0.22), (0.42, 0.43, 0.24),
                                    (0.62, 0.42, 0.22), (0.80, 0.36, 0.20),
                                    (0.94, 0.26, 0.14))):
        ell(0, v, ru, rv, 0.0)
    # 下颌
    d.polygon([(X(-0.30), Y(0.72)), (X(0.30), Y(0.72)), (X(0.20), Y(1.00)),
               (X(-0.20), Y(1.00))], fill=0)
    # V 天线（短，0.42h，避免顶部一根长刺干扰比例判读）
    d.polygon([(X(-0.06), Y(0.30)), (X(-0.52), Y(-0.10)), (X(-0.40), Y(0.22))], fill=0)
    d.polygon([(X(0.06), Y(0.30)), (X(0.52), Y(-0.10)), (X(0.40), Y(0.22))], fill=0)

    return img


def construction_lines(img):
    """加极淡的构造线：中线 + 头/肩/腰/胯/膝/踝基准线。用来提示骨架，不做装饰。"""
    g = Image.new('L', (W, H), 255)
    d = ImageDraw.Draw(g)
    for u, lab in ((0.0, 'top'), (1.0, 'chin'), (1.34, 'shoulder'),
                   (2.90, 'waist'), (3.36, 'hip'), (5.05, 'knee'), (7.90, 'ankle')):
        y = Y(u)
        for x in range(0, W, 26):
            d.line([(x, y), (x + 13, y)], fill=205, width=2)
    for y in range(0, H, 26):
        d.line([(CX, y), (CX, y + 13)], fill=215, width=2)
    out = Image.composite(Image.new('L', (W, H), 255), g, img.point(lambda v: 255 - v))
    # 上面这行把主体挖掉：只要在主体外显示构造线
    return Image.fromarray(np.minimum(np.asarray(img), np.asarray(out)))


if __name__ == '__main__':
    out = sys.argv[1] if len(sys.argv) > 1 else 'out/seed_sketch/control_sil.png'
    os.makedirs(os.path.dirname(out), exist_ok=True)
    if '--clean' in sys.argv:
        # 送进 img2img 用干净剪影：构造线是虚线，模型很容易把它当成装饰线照抄
        im = build()
    else:
        im = construction_lines(build())
    im.convert('RGB').save(out)
    print('控制剪影 -> %s  (%dx%d, %.1f 头身)' % (out, W, H, HH))
