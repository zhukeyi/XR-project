"""
film2.py — 《钢脊·白鸦》伪 3D 概念片 · 渲染入口

分镜（对齐 S4 全流程与「序章仰视」的 P0 优先级）：
  S1 0.0–3.2  序章 · 仰视      18.2m 机体立于压缩城市，推轨
  S2 3.2–5.2  启动 · 胸舱开启   升到胸舱高度正对，双开舱门，点火
  S3 5.2–7.0  弹射出击         贴地侧甩 + 速度线，40m 滑轨
  S4 7.0–9.4  交战 · 光束步枪   举枪射击，敌机命中爆炸
  S5 9.4–12.0 近战 · 光束军刀   拔刀、展开、劈砍，收尾字幕

用法：
  python3 film2.py probe <t>          构图诊断
  python3 film2.py still <t>          渲染单帧到 out/still_<t>.png
  python3 film2.py seq [W H]          渲染全片序列帧到 frames/
"""
import math
import os
import sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from hud import HUD
from r3d import (Node, Tris, collect, Renderer, look_at,
                 g_box, Mat, T, S, Rx, Ry, Rz, chain)
import mecha_model as MM

FPS = 24
DUR = 12.0
NF = int(round(FPS * DUR))


def lerp(a, b, t):
    return a + (b - a) * t


def clamp(t):
    return 0.0 if t < 0 else (1.0 if t > 1 else t)


def smooth(t):
    t = clamp(t)
    return t * t * (3 - 2 * t)


def ease_in(t):
    t = clamp(t)
    return t ** 3


def seg(t, a, b):
    if b <= a:
        return 1.0 if t >= b else 0.0
    return clamp((t - a) / (b - a))


# ================================================================ 镜头
def camera(t):
    if t < 3.2:
        u = smooth(seg(t, 0.15, 3.2))
        eye = (lerp(3.0, 0.7, u), lerp(1.45, 2.1, u), lerp(34.0, 26.5, u))
        tgt = (0.0, lerp(10.0, 10.9, u), 0.0)
        return eye, tgt, lerp(42, 40, u), lerp(-1.4, 0.0, u)
    if t < 5.2:
        u = smooth(seg(t, 3.2, 5.2))
        eye = (lerp(0.7, 0.25, u), lerp(2.1, 9.6, u), lerp(26.5, 16.5, u))
        tgt = (0.0, lerp(10.9, 12.5, u), 0.0)
        return eye, tgt, lerp(40, 36, u), 0.0
    if t < 7.0:
        u = smooth(seg(t, 5.2, 7.0))
        e = ease_in(u) * 0.55 + u * 0.45
        eye = (lerp(0.25, -17.0, e), lerp(9.6, 5.4, u), lerp(16.5, 30.0, u))
        tgt = (0.0, lerp(12.5, 9.8, u), lerp(0.0, -10.0, u))
        return eye, tgt, lerp(36, 44, u), lerp(0, -9, u)
    if t < 9.4:
        u = smooth(seg(t, 7.0, 9.4))
        eye = (lerp(-27.0, -24.0, u), lerp(9.2, 9.6, u), lerp(17.0, 13.0, u))
        tgt = (-2.0, 11.5, lerp(-2.0, 1.0, u))
        return eye, tgt, 40, lerp(-3.0, 1.0, u)
    u = smooth(seg(t, 9.4, 12.0))
    eye = (lerp(-23.0, -20.0, u), lerp(12.9, 13.2, u), lerp(24.0, 21.0, u))
    tgt = (0.0, 12.2, lerp(-1.0, 0.6, u))
    return eye, tgt, lerp(41, 38, u), lerp(3.0, -1.5, u)


# ================================================================ 姿态
def pose(t):
    p = {'idle': t * 2.2}
    launch = smooth(seg(t, 5.3, 6.1)) * (1 - smooth(seg(t, 6.9, 7.7)) * 0.62)
    shoot_up = smooth(seg(t, 6.85, 7.75))
    recoil = smooth(seg(t, 7.95, 8.06)) * (1 - smooth(seg(t, 8.06, 8.75)))
    draw_dn = smooth(seg(t, 9.45, 9.95)) * (1 - smooth(seg(t, 10.05, 10.55)))
    raise_ = smooth(seg(t, 10.4, 10.95))
    slash = smooth(seg(t, 10.95, 11.55))

    p['chest_pitch'] = -9 * launch + 5 * shoot_up + 7 * slash
    p['rot'] = (6 * launch + 2 * shoot_up, 0, -3 * slash)
    p['pos'] = (0, -1.5 * launch - 0.5 * slash, -2.0 * launch)
    p['thrust'] = smooth(seg(t, 4.55, 5.35)) * (1 - smooth(seg(t, 7.3, 8.3)) * 0.86)
    p['eye'] = smooth(seg(t, 3.3, 4.1))
    p['hatch'] = smooth(seg(t, 3.4, 4.5)) * (1 - smooth(seg(t, 4.95, 5.45)))

    crouch = launch * 10 + slash * 12 + shoot_up * 4
    p['hip_pitch-1'] = 3 + crouch * 0.8
    p['hip_pitch1'] = 3 + crouch * 0.8 - slash * 14
    p['knee_pitch-1'] = -6 - crouch * 1.1
    p['knee_pitch1'] = -6 - crouch * 1.1 + slash * 10
    p['ankle-1'] = 4 + crouch * 0.5
    p['ankle1'] = 4 + crouch * 0.5 - slash * 6

    sh1 = 6.0
    sh1 = lerp(sh1, -74.0, shoot_up)
    sh1 += 15.0 * recoil
    sh1 = lerp(sh1, 16.0, draw_dn)
    sh1 = lerp(sh1, -106.0, raise_)
    sh1 = lerp(sh1, -20.0, slash)
    p['sh_pitch1'] = sh1 + 5 * launch
    p['sh_roll1'] = -6 - 10 * slash

    el1 = -10.0
    el1 = lerp(el1, -22.0, shoot_up) - 18 * recoil
    el1 = lerp(el1, -14.0, draw_dn) - 26 * raise_
    el1 = lerp(el1, -8.0, slash)
    p['el_pitch1'] = el1
    p['hand_pitch1'] = 12 * shoot_up + 10 * raise_

    p['sh_pitch-1'] = 6 - 46 * shoot_up + 24 * slash + 5 * launch
    p['el_pitch-1'] = -10 - 30 * shoot_up - 16 * slash
    p['sh_roll-1'] = -6 - 8 * shoot_up

    p['head_pitch'] = -2 + 3 * launch - 4 * shoot_up
    p['rifle_on'] = t > 6.7
    p['muzzle'] = smooth(seg(t, 7.96, 8.02)) * (1 - smooth(seg(t, 8.02, 8.24)))
    p['saber_on'] = smooth(seg(t, 10.05, 10.75)) * (1 - smooth(seg(t, 11.8, 12.0)) * 0.12)
    return p


def enemy_pose(t):
    dead = smooth(seg(t, 8.05, 8.6))
    return {'pos': (38.0, 4.6, -20.0), 'rot': (0, -152, 0),
            'lean': -18 * dead + 6 * smooth(seg(t, 7.0, 7.4)),
            'leg': 10 * dead, 'dead': dead}


# ================================================================ 场景
def build_city(rng=None):
    rng = rng or np.random.default_rng(7)
    t = Tris()

    def add_box(w, h, d, cx, cy, cz, rgb, emis=0.0):
        v, f = g_box(w, h, d)
        v = v + np.array([cx, cy, cz])
        piv = v.mean(axis=0)
        for face in f:
            pts = v[face]
            n = np.cross(pts[1] - pts[0], pts[2] - pts[0])
            ln = np.linalg.norm(n)
            if ln < 1e-9:
                continue
            n = n / ln
            if n @ (pts.mean(axis=0) - piv) < 0:
                n = -n
            t.add(pts, rgb, emis, n)

    for i in range(16):
        z0 = 80 - i * 44
        z1 = z0 - 44
        c = 0.112 - i * 0.0032
        v = np.array([[-1200, 0.02, z0], [1200, 0.02, z0],
                      [1200, 0.02, z1], [-1200, 0.02, z1]], float)
        t.add(v, np.array([c * 1.04, c, c * 1.14]), 0.0, np.array([0.0, 1.0, 0.0]))
    for layer, (zc, n, hmin, hmax) in enumerate([
            (170, 18, 38, 78), (330, 20, 45, 95), (560, 24, 55, 115)]):
        for i in range(n):
            x = rng.uniform(-280, 280)
            z = zc + rng.uniform(-70, 70)
            if abs(x) < 42:
                continue
            w = rng.uniform(18, 46)
            d = rng.uniform(18, 46)
            h = rng.uniform(hmin, hmax)
            base = rng.choice([0.100, 0.118, 0.088])
            add_box(w, h, d, x, h / 2, z, np.array([base, base * 0.95, base * 1.10]))
            if rng.random() < 0.22:
                add_box(1.8, 1.8, 1.8, x, h + 0.9, z, np.array([1.0, 0.40, 0.15]), 1.0)
    for i in range(30):
        x = rng.uniform(-78, 78)
        z = rng.uniform(-20, 95)
        if abs(x) < 27:
            continue
        w = rng.uniform(4, 14)
        h = rng.uniform(2, 9)
        add_box(w, h, w * rng.uniform(0.7, 1.5), x, h / 2, z,
                np.array([0.140, 0.137, 0.150]))
    # 弹射甲板：40m 滑轨 + 枕木
    add_box(1.3, 0.5, 130, -9.2, 0.25, -40, np.array([0.19, 0.20, 0.225]))
    add_box(1.3, 0.5, 130, 9.2, 0.25, -40, np.array([0.19, 0.20, 0.225]))
    for i in range(13):
        add_box(19.6, 0.12, 0.7, 0, 0.44, 10 - i * 10, np.array([0.25, 0.26, 0.28]))
    return t


# ================================================================ HUD 状态
SUBS = [
    (0.0, 3.2, '序章 · 仰视 ／ 18.2m，一次出击的高度'),
    (3.2, 5.2, '启动 ／ 胸舱开启，双发点火'),
    (5.2, 7.0, '弹射出击 ／ 40m 滑轨，离舰'),
    (7.0, 9.4, '交战 ／ 光束步枪，破盾'),
    (9.4, 12.0, '近战 ／ 腰部双刀，光束军刀展开'),
]


def hud_state(t, bb, ebb=None):
    s = {'bbox': bb, 'ebbox': ebb}
    s['alpha'] = smooth(seg(t, 0.15, 0.9))
    s['boot'] = seg(t, 0.0, 0.5)
    s['scanline'] = 1.0 - seg(t, 0.3, 2.4)
    s['lock'] = smooth(seg(t, 1.0, 1.9)) * (1 - smooth(seg(t, 7.0, 7.3)))
    s['header'] = 'SECTOR 07 // CATAPULT DECK'
    mm, ss = divmod(int(t), 60)
    s['clock'] = f'00:{mm:02d}:{ss:02d}'
    s['armor'] = 1.0 - 0.09 * smooth(seg(t, 8.6, 9.2))
    s['thrust_gauge'] = (0.80 - 0.62 * smooth(seg(t, 4.6, 5.5))
                         + 0.46 * smooth(seg(t, 7.6, 8.4)))
    s['scale_label'] = '18.2 m'
    s['lock_label'] = 'HX-07  LOCK'
    s['lock_dist'] = f'{26.5 - 8.0 * seg(t, 0, 3.2):4.1f} m'
    s['model'] = 'HX-07  //  白鸦'
    for a, b, txt in SUBS:
        if a <= t < b:
            s['subtitle'] = txt
    s['flash'] = 0.55 * smooth(seg(t, 8.05, 8.12)) * (1 - smooth(seg(t, 8.12, 8.5)))
    return s


# ================================================================ 屏幕特效
def post_fx(img, t, anchor=None):
    """速度线 + 光剑拖影 + 冲击。在 HUD 之前叠加。"""
    W, H = img.size
    from PIL import ImageDraw
    ov = img.convert('RGBA')
    d = ImageDraw.Draw(ov)

    # S3 速度线
    k = smooth(seg(t, 5.28, 5.62)) * (1 - smooth(seg(t, 6.65, 7.05)))
    if k > 0.01:
        rng = np.random.default_rng(int(t * FPS) * 7919 + 13)
        cx, cy = W * 0.5, H * 0.42
        for i in range(30):
            a = rng.uniform(0, 2 * math.pi)
            r0 = rng.uniform(200, 470)
            ln = rng.uniform(120, 380) * k
            x0 = cx + math.cos(a) * r0
            y0 = cy + math.sin(a) * r0 * 0.60
            x1 = cx + math.cos(a) * (r0 + ln)
            y1 = cy + math.sin(a) * (r0 + ln) * 0.60
            al = int(90 * k * rng.uniform(0.4, 1.0))
            d.line([(x0, y0), (x1, y1)], fill=(205, 238, 255, al),
                   width=int(1 + 2 * k))

    # S4 光束：枪口 -> 敌机屏幕位置
    ax, ay = anchor if anchor else (W * 0.60, H * 0.60)
    bt = seg(t, 7.96, 8.12)
    if 0 < bt < 1:
        x0, y0 = W * 0.295, H * 0.52
        x1 = x0 + (ax - x0) * smooth(bt)
        y1 = y0 + (ay - y0) * smooth(bt)
        d.line([(x0, y0), (x1, y1)], fill=(190, 244, 255, 200),
               width=max(2, int(9 * (1 - bt * 0.6))))
        d.line([(x0, y0), (x1, y1)], fill=(255, 255, 255, 235),
               width=max(1, int(4 * (1 - bt * 0.6))))

    # S5 光剑挥砍弧
    sw = smooth(seg(t, 11.0, 11.35)) * (1 - smooth(seg(t, 11.5, 11.9)))
    if sw > 0.02:
        cx, cy = W * 0.60, H * 0.30
        r = W * 0.30
        a0 = math.radians(-118 + 96 * (1 - sw))
        a1 = math.radians(-118 + 96 * (1 - sw) + 52 * sw)
        d.arc([cx - r, cy - r * 0.85, cx + r, cy + r * 0.85],
              math.degrees(a0), math.degrees(a1),
              fill=(150, 236, 255, int(150 * sw)), width=int(3 + 8 * sw))
        d.arc([cx - r * 0.97, cy - r * 0.82, cx + r * 0.97, cy + r * 0.82],
              math.degrees(a0), math.degrees(a1),
              fill=(255, 255, 255, int(190 * sw)), width=int(1 + 3 * sw))

    # 敌机命中爆炸星芒
    ex = seg(t, 8.05, 8.55)
    if 0 < ex < 1:
        rng = np.random.default_rng(99)
        cx, cy = ax, ay
        for i in range(16):
            a = rng.uniform(0, 2 * math.pi)
            r0 = 18 + 120 * ex * rng.uniform(0.4, 1.0)
            r1 = r0 + 40 * (1 - ex) * rng.uniform(0.5, 1.6)
            d.line([(cx + math.cos(a) * r0, cy + math.sin(a) * r0),
                    (cx + math.cos(a) * r1, cy + math.sin(a) * r1)],
                   fill=(255, 236, 190, int(210 * (1 - ex))),
                   width=int(1 + 3 * (1 - ex)))
        rr = 30 + 90 * ex
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr],
                  outline=(255, 210, 150, int(160 * (1 - ex))),
                  width=int(1 + 3 * (1 - ex)))

    return ov.convert('RGB')


# ================================================================ 渲染
def mech_bbox(tris, cam_m, fov, W, H):
    f = 1.0 / math.tan(fov * math.pi / 360.0)
    if len(tris) == 0:
        return None
    pts = np.concatenate([(cam_m @ np.hstack([p, np.ones((len(p), 1))]).T).T[:, :3]
                          for p in tris.pts])
    vis = pts[pts[:, 2] < -0.6]
    if len(vis) == 0:
        return None
    z = -vis[:, 2]
    sx = (vis[:, 0] / z) * f * (H / 2) + W / 2
    sy = H / 2 - (vis[:, 1] / z) * f * (H / 2)
    return (float(sx.min()), float(sy.min()), float(sx.max()), float(sy.max()))


def render_frame(rd, city, t, with_hud=True, with_enemy=True):
    tris = Tris()
    tris.merge(city)
    mech = Tris()
    collect(MM.build_mecha(pose(t)), mech)
    tris.merge(mech)
    en = Tris()
    if with_enemy and t > 6.6:
        collect(MM.build_enemy(enemy_pose(t)), en)
        tris.merge(en)
    eye, tgt, fov, roll = camera(t)
    rd.fov = fov
    rd.f = 1.0 / math.tan(fov * math.pi / 360.0)
    cm = look_at(eye, tgt, roll=roll)
    # 曝光补偿：S5 机位位于机体背光侧（主光来自 +x，相机在 -x），需抬亮避免发灰
    ex = 1.0 + 0.46 * smooth(seg(t, 9.32, 9.95))
    base = rd.sky(top=(0.030, 0.040, 0.070), bot=(0.215, 0.243, 0.292),
                  horizon_y=0.55, sun=(0.78, 0.46, 0.34), sun_k=0.42)
    img = rd.render(tris, cm, base=base, fog_col=(0.132, 0.158, 0.198),
                    fog_a=0.0016, fog_b=0.000008, exposure=ex)
    eb = mech_bbox(en, cm, fov, rd.W, rd.H) if len(en) else None
    anchor = ((eb[0] + eb[2]) / 2, (eb[1] + eb[3]) / 2) if eb else None
    img = post_fx(img, t, anchor)
    if with_hud:
        bb = mech_bbox(mech, cm, fov, rd.W, rd.H)
        img = HUD(rd.W, rd.H).draw(img, t, hud_state(t, bb, eb))
    return img


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else 'still'
    city = build_city()
    if mode == 'probe':
        rd = Renderer(1280, 720, ss=1)
        for tt in [float(x) for x in sys.argv[2:]] or [0.5, 1.6, 3.0]:
            tris = Tris()
            collect(MM.build_mecha(pose(tt)), tris)
            eye, tgt, fov, roll = camera(tt)
            cm = look_at(eye, tgt, roll=roll)
            bb = mech_bbox(tris, cm, fov, 1280, 720)
            print(f't={tt:5.2f} fov={fov:4.1f} tris={len(tris):4d} '
                  f'bbox=({bb[0]:6.0f},{bb[1]:6.0f})-({bb[2]:6.0f},{bb[3]:6.0f}) '
                  f'w={100*(bb[2]-bb[0])/1280:5.1f}% h={100*(bb[3]-bb[1])/720:5.1f}%')
        return

    if mode == 'still':
        tt = float(sys.argv[2]) if len(sys.argv) > 2 else 1.6
        rd = Renderer(1280, 720, ss=2, fov=40)
        img = render_frame(rd, city, tt)
        out = os.path.join(HERE, 'out', f'still_{tt:.2f}.png')
        img.save(out)
        print('->', out)
        return

    # 序列帧
    W = int(sys.argv[2]) if len(sys.argv) > 2 else 1280
    H = int(sys.argv[3]) if len(sys.argv) > 3 else 720
    rd = Renderer(W, H, ss=2, fov=40)
    fd = os.path.join(HERE, 'frames')
    os.makedirs(fd, exist_ok=True)
    import time
    t0 = time.time()
    for i in range(NF):
        tt = i / FPS
        img = render_frame(rd, city, tt)
        img.save(os.path.join(fd, f'f_{i:04d}.png'))
        if i % 24 == 0:
            el = time.time() - t0
            print(f'  {i}/{NF}  {el:5.1f}s  eta {el/max(1,i)*(NF-i):5.1f}s',
                  flush=True)
    print(f'done {NF} frames in {time.time()-t0:.1f}s')


if __name__ == '__main__':
    main()
