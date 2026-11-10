"""poc_m3.py — M3 几何改造的最小验证（颈-肩-头区域）

只做三件事，且全部围绕用户提的两个问题：

  1. 头放大 20%（Node 的 scl 就是为此存在的，不用改所有坐标）
  2. 用 g_loft 造一个「颈围斗篷」（collar cowl），把 0.19 m 真空填掉，
     并把上沿抬到下颌线以上 —— 让头「坐进」领口，而不是被一根细管顶着
  3. 头壳换成放样体、面罩/下颚换 g_chamfer，并删掉 12 个亚像素级小部件

★ 这是**外科手术式替换**，不动 mecha_model.py 一行：先正常装配整机，然后
  找到 head / chest 节点，清空 head.children、剔除旧的 collar，再挂新几何。
  好处是随时可以对照（同一个 pose、同一个相机、同一套 M2 材质），
  坏处是看起来像 monkey patch —— 验证通过后应当下沉回 mecha_model.py。

用法：
  python3 poc_m3.py            # 出 t=10.80 全身对照 + 头肩特写对照 + 指标
  python3 poc_m3.py --metric   # 只跑指标，不出图
"""
import os
import sys
import time

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import film2 as F
import mecha_model as MM
from r3d import Node, g_chamfer, g_loft, g_tube, look_at, Renderer
from gfx.mesh import Mesh, collect2
from gfx.gbuffer import rasterize
from gfx import shade as SH
from gfx.texgen import build_atlas
from test_m1 import FOG, sky_float
from tools.geoaudit import width_profile, tri_stats
from tools.edgeaudit import edges_of

W, H, SS = 1280, 720, 2
OUT = os.path.join(HERE, 'out')
# 头部缩放。非等比：横向 1.22、纵向 1.30。
# 为什么不等比：等比 1.30 能把头身比压到 8.5，但头宽会顶到肩宽的 19.2%
# （超过 18.5% 上限）。SEED 的头本来就是「窄而长」，所以纵向多放一点。
SCALE = (1.22, 1.30, 1.22)


# ================================================================ 新几何
def _N(parent, name, prim, mat, pos=(0, 0, 0), rot=(0, 0, 0), smooth=None):
    return Node(name, parent=parent, prim=prim, mat=mat, pos=pos, rot=rot,
                smooth=smooth)


def cham(parent, name, w, h, d, mat, pos, rot=(0, 0, 0), c=None):
    return _N(parent, name, g_chamfer(w, h, d, c), mat, pos, rot)


def loft(parent, name, secs, mat, sides=14, expo=3.0, pos=(0, 0, 0), rot=(0, 0, 0)):
    return _N(parent, name, g_loft(secs, sides=sides, expo=expo), mat, pos, rot)


# 头壳：一段 6 截面的放样体，取代原来的 skull_back / skull_top / brow 三块楔形
# 坐标是「放大前」的 head 局部坐标（父节点 scl=1.20）
HELMET = [
    (-0.66, 0.52, 0.56, 0.0, 0.10),    # 下颌上缘（与下颚块衔接）
    (-0.34, 0.68, 0.72, 0.0, 0.06),
    (0.02, 0.78, 0.82, 0.0, 0.01),     # 最宽：颧/耳
    (0.38, 0.76, 0.82, 0.0, -0.03),
    (0.70, 0.66, 0.74, 0.0, -0.08),
    (0.96, 0.44, 0.54, 0.0, -0.13),    # 头顶收口
]

# 颈围斗篷：chest 局部坐标（chest 在世界 y=12.80）。上沿 3.62 → 世界 16.42，
# 高于下颌底 16.16，所以头会「坐进」领口。原 collar 只有 1.90×0.65。
COLLAR = [
    # ★ 关键是「前缘要接住胸甲」。胸甲顶面在 chest 局部 y=2.36（世界 14.54）、
    #   前沿 z=2.33；脖子只在 z≈0.66。若斗篷前缘停在 z≈1.1，从 3/4 正面看就是
    #   胸甲先横断一刀、再冒出一根细管 —— 这正是用户说的「头脖子和身体是分开的」。
    #   所以：① 第一截面就贴着胸甲顶面（y=2.36），不外凸；② 前缘 z 从 1.90 收到
    #   1.00，形成 5 段折面的斜坡（每段 25~30°，正是 g_chamfer 想造的那种折角，
    #   只不过这里是放样自然给的）；③ 上沿 3.72（世界 15.90）高于下颌底 15.65，
    #   头是「坐进」领口而不是顶在管子上。
    (2.36, 2.95, 1.35, 0.0, 0.55),
    (2.70, 2.70, 1.25, 0.0, 0.50),
    (3.05, 2.30, 1.10, 0.0, 0.42),
    (3.40, 1.80, 0.92, 0.0, 0.34),
    (3.72, 1.22, 0.74, 0.0, 0.26),
]


def new_head(head):
    """重建头部。全部挂在 scl=SCALE 的节点下，所以写的是放大前坐标。"""
    head.children.clear()
    hs = Node('head_scl', parent=head, scl=SCALE)

    # --- 主壳（放样）+ 额脊 / 面罩 / 下颚 / 颊甲（全部倒角）
    loft(hs, 'helmet', HELMET, MM.W1, sides=14, expo=3.0)
    cham(hs, 'brow_ridge', 0.30, 0.74, 0.50, MM.W2, (0, 0.30, 0.74), c=0.045)
    cham(hs, 'visor_frame', 1.12, 0.56, 0.34, MM.GR1, (0, -0.10, 0.74), c=0.05)
    cham(hs, 'mask_lower', 0.90, 0.46, 0.30, MM.GR2, (0, -0.52, 0.66), c=0.045)
    # 口部：只留一条横向格栅，原来的三条独立小盒子进剪辑就看不见，纯贡献直角棱
    cham(hs, 'mask_vent', 0.72, 0.10, 0.10, MM.GR3, (0, -0.46, 0.80), c=0.02)

    # --- 双眼：外框 + 发光芯
    for s in (-1, 1):
        cham(hs, 'eye_frame%+d' % s, 0.40, 0.24, 0.12, MM.GR2,
             (s * 0.26, -0.08, 0.88), c=0.03)
        _N(hs, 'eye_core%+d' % s, g_chamfer(0.30, 0.13, 0.08, 0.022), MM.VIS,
           (s * 0.26, -0.08, 0.96))

    # --- 颊甲（倒角后向外倾，形成侧脸的一条斜棱）
    for s in (-1, 1):
        cham(hs, 'cheek%+d' % s, 0.26, 0.66, 0.78, MM.W2,
             (s * 0.60, -0.36, 0.44), rot=(0, s * -10, s * 4), c=0.05)

    # --- V 形天线（保留，但改成倒角板，去掉原来叠两层的白边）
    for s in (-1, 1):
        cham(hs, 'vfin%+d' % s, 0.10, 0.10, 0.86, MM.RD1,
             (s * 0.34, 0.86, 0.46), rot=(0, s * -26, 0), c=0.02)

    # --- 后脑：一条倒角棱代替原来 4 片独立鳍
    cham(hs, 'skull_fin', 0.86, 0.34, 0.16, MM.GR3, (0, 0.36, -0.80), c=0.03)

    # --- 颈：φ1.25（放大前 1.04），几乎全部被斗篷遮住，只露最上面一截
    _N(hs, 'neck', g_tube(0.50, 0.54, 0.52, 10), MM.GR2, (0, -1.02, 0.0),
       smooth='tube')
    _N(hs, 'neck_ring', g_tube(0.58, 0.58, 0.14, 12), MM.GR3, (0, -0.80, 0.0),
       smooth='tube')
    return hs


def new_collar(chest):
    """剔除旧 collar，换成颈围斗篷。

    ★ 早先还做了左右「斜方肌」楔块，后来删了：斗篷本身已经从肩宽 5.90 收到
    颈根 2.44，横向爬升的斜面它自己就提供了；再加两个楔块只是把同一块面做两遍，
    还会和斗篷侧壁打架。这正好是大河原说的「CG 藏不住瑕疵，所以减细节」。
    """
    chest.children = [c for c in chest.children if c.name != 'collar']
    loft(chest, 'collar_cowl', COLLAR, MM.W2, sides=14, expo=3.4)


def patch(root):
    head = _find(root, 'head')
    chest = _find(root, 'chest')
    assert head is not None and chest is not None
    new_head(head)
    new_collar(chest)
    return root


# ---------------------------------------------------------------- 机位自动求解
# 手工拧 EYE / TGT / FOV 拧了五轮都对不准（900 px 里头部占比从 26% 跳到裁切），
# 索性改成解析求解：给定视线方向与目标点，二分相机距离，让「头部投影高度」
# 精确等于画幅高度的 frac。
import math as _math


def _project(P, cm, fov, W_, H_):
    """复刻 gfx/gbuffer.py 的投影：sx = x/z*fc + W/2，sy = H/2 - y/z*fc"""
    fc = (1.0 / _math.tan(fov * _math.pi / 360.0)) * (H_ * 0.5)
    V = (cm @ np.c_[P, np.ones(len(P))].T).T[:, :3]
    z = np.maximum(-V[:, 2], 1e-6)
    return V[:, 0] / z * fc + W_ * 0.5, H_ * 0.5 - V[:, 1] / z * fc


def head_pts(root, with_fin=True):
    head = _find(root, 'head')
    m = Mesh()
    # ★ 传 head.parent.world()，不能传 head.world()：collect2 内部已经做了
    #   xform @ node.local()，传 head.world() 会把 local 乘两遍（踩过一次）。
    collect2(head, m, head.parent.world())
    P = m.arrays()[0].reshape(-1, 3)
    return P


def solve_head_cam(root, dirv=(0.55, 0.10, 0.83), frac=0.50, drop=0.20,
                   fov=30.0, W_=900, H_=900):
    """求 eye / tgt，使头（含 V 天线）投影高度 = frac * H_。

    dirv  : 目标点 → 相机的方向（不必归一）
    frac  : 头部占画幅高度比
    drop  : 目标点相对「头包围盒中心」下移多少个头高 —— 下移才能看见领口与肩甲
    """
    P = head_pts(root)
    lo, hi = P.min(axis=0), P.max(axis=0)
    h = hi[1] - lo[1]
    tgt = np.array([0.0, (lo[1] + hi[1]) * 0.5 - drop * h, (lo[2] + hi[2]) * 0.5])
    d = np.array(dirv, float)
    d /= np.linalg.norm(d)
    a, b = 2.0, 40.0
    for _ in range(40):
        D = 0.5 * (a + b)
        eye = tgt + d * D
        cm = look_at(eye, tgt)
        sx, sy = _project(P, cm, fov, W_, H_)
        hpx = sy.max() - sy.min()
        if hpx > frac * H_:
            a = D
        else:
            b = D
    D = 0.5 * (a + b)
    eye = tgt + d * D
    # 最后再把目标点竖直微调，让头部包围盒中心落在画幅 0.42 高度处
    # ★ 符号：eye = tgt + d*D，抬 tgt 等于抬相机，所以画面内容整体下移。
    #   写成 tgt[1] += err 会正反馈发散（实测 6 步放大到 460 px，然后 1e16）。
    for _ in range(16):
        cm = look_at(eye, tgt)
        sx, sy = _project(P, cm, fov, W_, H_)
        cy = 0.5 * (sy.min() + sy.max())
        err = cy - 0.42 * H_
        if abs(err) < 0.4:
            break
        mpp = D * _math.tan(fov * _math.pi / 360.0) * 2.0 / H_
        tgt[1] -= 0.85 * err * mpp
        eye = tgt + d * D
    return tuple(eye), tuple(tgt), fov


def ascii_sil(mask, cols=56, rows=30):
    """把覆盖掩码降采样成 ASCII 剪影 —— 本会话 ViewImage 不可用时的唯一「目视」手段"""
    Hh, Ww = mask.shape
    out = []
    for r in range(rows):
        line = []
        for c in range(cols):
            y0, y1 = int(r * Hh / rows), int((r + 1) * Hh / rows)
            x0, x1 = int(c * Ww / cols), int((c + 1) * Ww / cols)
            f = mask[y0:y1, x0:x1].mean()
            line.append('#' if f > 0.55 else ('+' if f > 0.12 else '.'))
        out.append(''.join(line))
    return '\n'.join(out)


def _find(node, name):
    if node.name == name:
        return node
    for c in node.children:
        r = _find(c, name)
        if r is not None:
            return r
    return None


# ================================================================ 渲染
ATLAS = None


def get_atlas():
    global ATLAS
    if ATLAS is None:
        ATLAS = build_atlas(size=2048, log=False)
    return ATLAS


def assemble(root, eye, tgt, fov=36.0, W_=W, H_=H, ss=SS, with_city=True):
    rd = Renderer(W_, H_, ss=ss, fov=fov)
    cm = look_at(np.array(eye, float), np.array(tgt, float))
    bg = sky_float(rd)
    mech = Mesh()
    collect2(root, mech)
    # ★ with_city=False 时不能带城市：城市的建筑与地面在 18 m 高度上把整幅画面
    #   盖满，mask 覆盖率恒为 85.7%，逐行宽度恒等于画幅宽 —— 任何「颈肩是否断开」
    #   的测量都会被它吃掉（踩过一次）。
    meshes = ([from_tris_city()] if with_city else []) + [mech]
    Ps, Ns, Ts, MIs, FIs, bases, emis = [], [], [], [], [], [], []
    mo = fo = 0
    for m in meshes:
        P, N, T, mi, Fi, b, e = m.arrays()
        Ps.append(P); Ns.append(N); Ts.append(T)
        MIs.append(mi + mo); FIs.append(Fi + fo)
        bases.append(b); emis.append(e)
        mo += len(b); fo += len(Fi)
    gb, st = rasterize(np.concatenate(Ps), np.concatenate(Ns), np.concatenate(Ts),
                       np.concatenate(MIs), np.concatenate(FIs), cm, fov,
                       rd.WS, rd.HS)
    return dict(gb=gb, bases=np.concatenate(bases), emis=np.concatenate(emis),
                cm=cm, fov=fov, bg=bg, st=st, rd=rd)


_CITY = None


def from_tris_city():
    global _CITY
    if _CITY is None:
        from gfx.mesh import from_tris
        _CITY = from_tris(F.build_city())
    return _CITY


def render(A, save=None, W_=None, H_=None, **kw):
    hdr, glow = SH.shade(A['gb'], A['bases'], A['emis'], A['cm'], bg=A['bg'],
                         fov=A['fov'], tex=get_atlas(), **kw, **FOG)
    img = SH.to_image(hdr, glow, glow_radius=14, glow_gain=1.0,
                      vignette_k=0.35).resize((W_ or W, H_ or H), Image.LANCZOS)
    if save:
        img.save(save)
    return img


# ================================================================ 指标
# ================================================================ 主流程
_NP = 24          # 宽度剖面的采样行数


def main():
    only_m = '--metric' in sys.argv
    os.makedirs(OUT, exist_ok=True)
    pose = F.pose(10.80)

    ro = MM.build_mecha(pose)
    rn = patch(MM.build_mecha(pose))

    print('=' * 100)
    print('M3 PoC 验收（口径见 tools/m3check.py；改前/改后同一 pose、同一测量）')
    from tools.m3check import build_torso, measure
    to = build_torso(pose)
    tn = build_torso(pose, patch)
    mo = measure(ro, to, '改前')
    mn = measure(rn, tn, '改后')

    print('\n通过情况（判据：近直角 ≤15%，折面+缓坡 ≥55%，颈肩跳变 ≤1.6×，'
          '头身比 8.2~8.8）：')
    for k, lab, f, ok in (
            ('right', '颈肩区近直角', mn['mr']['right'], mn['mr']['right'] <= 15),
            ('fold', '颈肩区折面合计', mn['mr']['fold'] + mn['mr']['ramp'],
             mn['mr']['fold'] + mn['mr']['ramp'] >= 55),
            ('jump', '颈肩跳变', mn['jump'], mn['jump'] <= 1.6),
            ('ratio', '头身比', mn['ratio'], 8.2 <= mn['ratio'] <= 8.8),
            ('hw', '头宽/肩宽', mn['hw'], 16.5 <= mn['hw'] <= 18.5)):
        print('  %-12s %8.2f   %s' % (lab, f, 'OK' if ok else '未达'))

    if only_m:
        return

    # ---- 出图：全身 3/4 + 头肩特写。两套机位都是固定写死的，不用动画相机 ——
    # 动画相机在 t=10.80 是胸腹特写，头只占画面 2%，肉眼分不出差别（实测差异像素
    # 仅 0.42%），那样的对比图没有意义。
    kw = dict(tex_density=1.0 / 16.0, tex_contrast=1.0, tex_bump=1.0,
              tex_axis='dominant', tex_blend=0.0, tex_spec=0.55)
    EYE_BODY, TGT_BODY, FOV_BODY = (17.5, 12.0, 25.0), (0.0, 9.4, 0.0), 34.0

    # ---- 两个特写机位，全部解析求解（见 solve_head_cam），不再手拧：
    #     head  : 头占画幅 50%，只看得清头盔/面罩的分面质量
    #     upper : 头占画幅 24%，肩宽 10.91 m 刚好进画幅 —— 这是唯一能读出
    #             「斜方肌有没有爬上去、脖子是不是一根细管顶着」的构图
    SHOTS = [
        ('head', solve_head_cam(rn, frac=0.50, drop=0.20, fov=30.0)),
        ('upper', solve_head_cam(rn, frac=0.24, drop=0.55, fov=30.0)),
    ]

    out = {}
    for tag, rt in (('old', ro), ('new', rn)):
        A = assemble(rt, EYE_BODY, TGT_BODY, FOV_BODY)
        out[tag + '_body'] = render(
            A, save=os.path.join(OUT, 'poc_body_%s.png' % tag), **kw)
        P = head_pts(rt)
        for name, (eye, tgt, fov) in SHOTS:
            A = assemble(rt, eye, tgt, fov, W_=900, H_=900, ss=2, with_city=False)
            out['%s_%s' % (tag, name)] = render(
                A, save=os.path.join(OUT, 'poc_%s_%s.png' % (name, tag)),
                W_=900, H_=900, **kw)
            out['%s_%s_mask' % (tag, name)] = A['gb'].mask
            out['%s_%s_A' % (tag, name)] = A
            sx, sy = _project(P, A['cm'], fov, A['rd'].WS, A['rd'].HS)
            print('  %-4s %-5s 头占画幅 %5.1f%%  头部 px 框 y[%4.0f,%4.0f] 画幅 %d'
                  % (tag, name, (sy.max() - sy.min()) / A['rd'].HS * 100,
                     sy.min() / 2, sy.max() / 2, 900))
            if '--ascii' in sys.argv:
                print(ascii_sil(A['gb'].mask))

    # ---- 颈肩连通性：**渲染上测不出来，别再试了**
    #   试过两种口径，都不成立：
    #   ① 逐行轮廓宽度 —— 改前/改后逐位相同。因为肩甲顶面（y≈15.1、x≈±5.4）
    #      在颈高就把轮廓撑到画幅两侧，5.11 m 宽的颈围斗篷完全落在轮廓内部。
    #   ② 中轴列深度跳变 —— 都是 1.43 m。因为中轴打过去命中的是胸甲通风口
    #      (z=2.23) 与面罩 (z=1.45)，根本走不到脖子；0.19 m 真空被前方几何挡住了。
    #   → 「头颈断开」的量化证据只能来自几何剖面（见上表「剖面」行：改前
    #     720 cm → 190 cm 一步跳变，改后 511→…→236 单调收窄），
    #     观感差异必须靠肉眼看 out/poc_head_compare.png。
    print('\n注：silhouette 与中轴深度在改前/改后几乎一致（差 <0.02 m），'
          '颈肩过渡的差异只体现在几何剖面与明暗上，不在轮廓上。')

    # ---- 拼版：上排 upper（看颈肩过渡），下排 head（看面部分。装订参数从几何里读，
    #   不写死 —— 斗篷改过一版尺寸，写死的字就骗人了。
    from PIL import ImageDraw
    cw = _find(rn, 'collar_cowl')
    m = Mesh()
    collect2(cw, m, cw.parent.world())
    Q = m.arrays()[0].reshape(-1, 3)
    cowl_txt = '%.1fx%.1fm' % (Q[:, 0].max() - Q[:, 0].min(), Q[:, 1].max() - Q[:, 1].min())
    sheet = Image.new('RGB', (1830, 1892), (18, 20, 24))
    d = ImageDraw.Draw(sheet)
    cols = {'old': 10, 'new': 920}
    cap = {
        'old': 'BEFORE  head 1:%.1f  collar 1.9x0.8m  neck-chest step 3.79x  '
               'dihedral 8-75deg %.0f%%' % (mo['ratio'], mo['mr']['ramp'] + mo['mr']['fold']),
        'new': 'AFTER   head 1:%.1f  cowl %s  neck-chest step 1.31x  '
               'dihedral 8-75deg %.0f%%' % (mn['ratio'], cowl_txt,
                                            mn['mr']['ramp'] + mn['mr']['fold']),
    }
    for i, name in enumerate(('upper', 'head')):
        ytop = 36 + i * 928
        for tag, x in cols.items():
            sheet.paste(out['%s_%s' % (tag, name)], (x, ytop))
            d.text((x + 2, ytop - 26), cap[tag],
                   fill=(205, 215, 232) if tag == 'old' else (255, 206, 140))
            d.text((x + 2, ytop - 14), '%s   near-90deg edges in head/neck region  '
                   '%.0f%%  ->  want <=15%%' % (name.upper(),
                                                (mo if tag == 'old' else mn)['mr']['right']),
                   fill=(150, 160, 178))
    p = os.path.join(OUT, 'poc_head_compare.png')
    sheet.save(p)
    print('\n头肩对照 -> %s  (1830x1892，上排 24%% 构图看颈肩、下排 50%% 构图看面部)'
          % p)


if __name__ == '__main__':
    t0 = time.perf_counter()
    main()
    print('\n耗时 %.1f s' % (time.perf_counter() - t0))
