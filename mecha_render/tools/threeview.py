"""tools/threeview.py — 从 3D 模型渲染同一机体的正/侧/背三视图，并逐格验收

为什么三视图不给 AI 画：
  三视图的验收判据是「同一机体、同一比例、脚底对齐」。我们已经实测过纯提示词
  锁不住比例（两次生成给出肩/头 3.57 与 3.38、最宽行 45%/52%），一次画三格只
  会更糟。只有从一个几何体渲染三个方位，才能保证是同一台机体。

这一步同时充当「可视频化」的证明：能渲出三视图，就说明模型在这条管线里是
完整可动可渲染的，视频只是换相机路径 + 换姿态参数。

正交化手段：fov 取 8°、相机距离拉远到 fov 能覆盖全身，透视误差 <1%，
三个方位共用同一相机距离与同一地面高度，所以脚底天然对齐。
"""
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'tools'))

import mecha_model as MM
from gfx import shade as SH
from gfx.gbuffer import rasterize
from gfx.mesh import Mesh, collect2, from_tris
from r3d import Renderer, look_at

W, H, SS = 720, 1240, 2
# ★ 正交化：fov 2° + 相机 600 m，取景尺寸与原来完全等价
#   （600·tan1° = 10.47 ≈ 150·tan4° = 10.49），但透视误差从 0.74% 降到 0.08%。
#   实测 fov8/150 时三格脚底基线极差 5 px、主体高极差 8 px，不满足「脚底对齐」。
FOV = 2.0
DIST = 600.0
CY = 9.51          # 机体中心高度（机高 19.02）

# 三个方位：root 绕 Y 轴旋转。侧视给 90°，背视 180°
VIEWS = [('正面  FRONT', 0), ('侧面  SIDE', 90), ('背面  BACK', 180)]


def render_view(deg, out, spec=0.9, props=None):
    rd = Renderer(W, H, ss=SS, fov=FOV)
    eye = (0.0, CY, DIST)
    tgt = (0.0, CY, 0.0)
    cm = look_at(eye, tgt, roll=0)
    # 设定表要纯白底，不要天空与雾
    bg = np.ones((rd.HS, rd.WS, 3), np.float32) * 0.98

    mech = Mesh()
    pp = {'rot': (0, deg, 0)}
    pp.update(props or {})
    collect2(MM.build_mecha(pp), mech)
    P, N, T, mi, Fi, b, e = mech.arrays()

    spec_a, rim_a = mech.mat_prop_table()      # 每材质 spec/rim（调色板里分层给的）
    gb, st = rasterize(P, N, T, mi, Fi, cm, FOV, rd.WS, rd.HS)
    hdr, glow = SH.shade(gb, b, e, cm, bg=bg, fov=FOV,
                         fog_a=0.0, fog_b=0.0,
                         mat_spec=spec_a, mat_rim=rim_a,
                         spec_gain=spec, spec_pow=64.0, spec_ambient=0.05,
                         rim_gain=2.20, rim_k=2.6,
                         # 0.35 是实测拐点：再往上最亮的折面被色调映射压平，
                         # mean 从 0.481 掉到 0.396 —— 那是过曝，不是金属
                         env_gain=0.35, env_pow=1.6)
    img = SH.to_image(hdr, glow, glow_radius=10, glow_gain=0.7,
                      vignette_k=0.0).resize((W, H), Image.LANCZOS)
    img.save(out)
    cov = gb.coverage() * 100
    print('  %-14s 三角 %5d  覆盖 %4.1f%%  -> %s'
          % (VIEWS[[v[1] for v in VIEWS].index(deg)][0], st.total, cov,
             os.path.basename(out)))
    return img


def label_panel(img, title, sub):
    d = ImageDraw.Draw(img)
    f1, f2 = font(22), font(17)
    d.text((14, 12), title, font=f1, fill=(20, 20, 20))
    d.text((14, 40), sub, font=f2, fill=(105, 105, 105))
    return img


CJK = ['/System/Library/Fonts/PingFang.ttc',
       '/System/Library/Fonts/Hiragino Sans GB.ttc']


def font(sz):
    for p in CJK:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, sz, index=0)
            except Exception:
                pass
    return ImageFont.load_default()


def main():
    outdir = os.path.join(HERE, 'out', 'threeview')
    os.makedirs(outdir, exist_ok=True)
    panels = []
    for name, deg in VIEWS:
        f = os.path.join(outdir, 'tv_%03d.png' % deg)
        img = render_view(deg, f)
        panels.append((img, name, f))

    GAP, PAD = 12, 20
    Wt = PAD * 2 + sum(p[0].width for p in panels) + GAP * (len(panels) - 1)
    sheet = Image.new('RGB', (Wt, PAD * 2 + H), 'white')
    x = PAD
    for img, name, f in panels:
        sheet.paste(label_panel(img.copy(), name, '3D 渲染 · 同一模型 · 同比例'),
                    (x, PAD))
        x += img.width + GAP
    out = os.path.join(HERE, 'out', 'seed_sketch', 'threeview.png')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    sheet.save(out)
    print('三视图拼版 -> %s (%d, %d)' % (out, Wt, PAD * 2 + H))
    print('分格文件：%s/tv_*.png' % outdir)


if __name__ == '__main__':
    main()
