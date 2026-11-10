"""
hud.py — 战术 HUD 层

视觉语言对齐方案 2.2「界面视觉」与「克制特效」要求：
细线、青白色、低不透明度、等宽数字、角括号，不使用花哨装饰。
中文用 PingFang SC，数字与型号用 HelveticaNeue-Condensed。
"""
import math
import numpy as np
from PIL import Image, ImageDraw, ImageFont

CN_FONT = '/System/Library/Fonts/PingFang.ttc'
EN_FONT = '/System/Library/Fonts/Helvetica.ttc'
MONO = '/System/Library/Fonts/SFNSMono.ttf'

CY = (150, 232, 246)
CY_D = (72, 132, 148)
WARN = (255, 150, 60)
RED = (255, 90, 78)


def _font(path, size, index=0):
    try:
        return ImageFont.truetype(path, size, index=index)
    except Exception:
        for alt in (CN_FONT, EN_FONT):
            try:
                return ImageFont.truetype(alt, size)
            except Exception:
                continue
    return ImageFont.load_default()


class HUD:
    def __init__(self, W=1280, H=720):
        self.W, self.H = W, H
        self.f_big = _font(MONO, 26)
        self.f_mid = _font(MONO, 17)
        self.f_small = _font(MONO, 13)
        self.f_cn = _font(CN_FONT, 15)
        self.f_cn_s = _font(CN_FONT, 12)
        self.f_title = _font(EN_FONT, 34)

    # ---------- 图元
    def corner(self, d, x, y, w, h, ln, col, wd=2):
        """四角括号。dx/dy 由 w,h 符号决定方向。"""
        pts = [
            [(x, y + ln * (1 if h > 0 else -1)), (x, y), (x + ln * (1 if w > 0 else -1), y)],
            [(x + w - ln * (1 if w > 0 else -1), y), (x + w, y),
             (x + w, y + ln * (1 if h > 0 else -1))],
            [(x, y + h - ln * (1 if h > 0 else -1)), (x, y + h),
             (x + ln * (1 if w > 0 else -1), y + h)],
            [(x + w - ln * (1 if w > 0 else -1), y + h), (x + w, y + h),
             (x + w, y + h - ln * (1 if h > 0 else -1))],
        ]
        for p in pts:
            d.line(p, fill=col, width=wd, joint='curve')

    def bracket(self, d, x0, y0, x1, y1, ln, col, wd=2):
        self.corner(d, x0, y0, x1 - x0, y1 - y0, ln, col, wd)

    def tick_row(self, d, x, y, n, step, ln, col, up=True):
        for i in range(n):
            xx = x + i * step
            d.line([(xx, y), (xx, y - ln if up else y + ln)], fill=col, width=1)

    # ---------- 主绘制
    def draw(self, img, t, state):
        """在 1280x720 画布上叠加 HUD。state: 含 bbox/lock/armor/thrust 等。"""
        W, H = self.W, self.H
        ov = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(ov)
        a_global = state.get('alpha', 1.0)
        boot = state.get('boot', 1.0)

        def C(col, a=1.0):
            return (col[0], col[1], col[2], int(255 * a * a_global))

        # --- 上下细框线
        d.line([(36, 40), (W - 36, 40)], fill=C(CY_D, 0.5), width=1)
        d.line([(36, H - 44), (W - 36, H - 44)], fill=C(CY_D, 0.5), width=1)
        self.tick_row(d, 48, H - 44, 28, 44, 7, C(CY_D, 0.45), up=True)

        # --- 顶部任务条
        head = state.get('header', 'SECTOR 07 // CATAPULT DECK')
        d.text((44, 20), head, font=self.f_small, fill=C(CY, 0.85))
        tt = state.get('clock', '00:00:00')
        tw = d.textlength(tt, font=self.f_small)
        d.text((W - 44 - tw, 20), tt, font=self.f_small, fill=C(CY, 0.6))

        # --- 左侧竖标尺（机体高度基准）
        b = state.get('bbox')
        if b and state.get('show_scale', True):
            x0, y0, x1, y1 = b
            sx = max(70, x0 - 46)
            d.line([(sx, y0), (sx, y1)], fill=C(CY, 0.55), width=1)
            for i in range(6):
                yy = y0 + (y1 - y0) * i / 5
                d.line([(sx - 7, yy), (sx, yy)], fill=C(CY, 0.55), width=1)
            lab = state.get('scale_label', '18.2 m')
            d.text((sx - 46, y0 - 20), lab, font=self.f_mid, fill=C(CY, 0.9))
            d.text((sx - 46, y0 - 4), 'HX-07', font=self.f_small, fill=C(CY_D, 0.9))

        # --- 锁定框
        if b and state.get('lock', 0) > 0:
            k = state['lock']
            x0, y0, x1, y1 = b
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            hw = (x1 - x0) / 2 * (1.06 + 0.30 * (1 - k))
            hh = (y1 - y0) / 2 * (1.02 + 0.24 * (1 - k))
            self.bracket(d, cx - hw, cy - hh, cx + hw, cy + hh, 26,
                         C(CY, 0.82 * k), 2)
            # 中心十字
            d.line([(cx - 13, cy), (cx - 4, cy)], fill=C(CY, 0.8 * k), width=1)
            d.line([(cx + 4, cy), (cx + 13, cy)], fill=C(CY, 0.8 * k), width=1)
            d.line([(cx, cy - 13), (cx, cy - 4)], fill=C(CY, 0.8 * k), width=1)
            d.line([(cx, cy + 4), (cx, cy + 13)], fill=C(CY, 0.8 * k), width=1)
            # 标签
            d.text((cx - hw, cy - hh - 22), state.get('lock_label', 'TGT-01  LOCK'),
                   font=self.f_small, fill=C(CY, 0.85 * k))
            dist = state.get('lock_dist', '26.5 m')
            d.text((cx + hw - d.textlength(dist, font=self.f_small), cy - hh - 22),
                   dist, font=self.f_small, fill=C(CY, 0.7 * k))

        # --- 左下：装甲 / 动力
        armor = state.get('armor', 1.0)
        bx, by = 48, H - 96
        d.text((bx, by - 18), 'ARMOR', font=self.f_small, fill=C(CY_D, 0.95))
        seg_n = 12
        for i in range(seg_n):
            on = i < round(armor * seg_n)
            col = C(CY, 0.8) if on else C(CY_D, 0.22)
            d.rectangle([bx + i * 17, by, bx + i * 17 + 12, by + 7], fill=col)
        d.text((bx, by + 14), f'{armor*100:5.1f}%', font=self.f_small, fill=C(CY, 0.75))

        # --- 右下：推进剂
        th = state.get('thrust_gauge', 0.72)
        gx, gy = W - 108, H - 116
        d.text((gx - 58, gy - 18), 'PROP', font=self.f_small, fill=C(CY_D, 0.95))
        for i in range(10):
            on = i < round(th * 10)
            col = C(WARN if th > 0.85 else CY, 0.85) if on else C(CY_D, 0.2)
            d.rectangle([gx + i * 6, gy + (9 - i) * 9, gx + i * 6 + 4,
                         gy + (9 - i) * 9 + 6], fill=col)

        # --- 底部型号
        model = state.get('model', 'HX-07  //  BAIYA')
        mw = d.textlength(model, font=self.f_cn)
        d.text((W / 2 - mw / 2, H - 76), model, font=self.f_cn, fill=C(CY, 0.7))

        # --- 开机扫描线
        if 0 < boot < 1:
            yy = int(H * boot)
            d.line([(0, yy), (W, yy)], fill=C(CY, 0.55), width=2)
            d.rectangle([0, 0, W, yy], fill=C((10, 30, 40), 0.0))

        # --- 入场时全屏水平扫描纹理
        if state.get('scanline', 0) > 0:
            s = state['scanline']
            for i in range(0, H, 4):
                d.line([(0, i), (W, i)], fill=C(CY, 0.03 * s), width=1)

        # --- 字幕（分镜说明）
        sub = state.get('subtitle')
        if sub:
            f = _font(CN_FONT, 19)
            sw = d.textlength(sub, font=f)
            d.text((W / 2 - sw / 2, H - 40), sub, font=f, fill=C((235, 244, 250), 0.9))

        # --- 冲击白闪 / 红闪
        flash = state.get('flash', 0.0)
        if flash > 0:
            d.rectangle([0, 0, W, H], fill=(255, 255, 255, int(230 * flash)))
        rflash = state.get('red_flash', 0.0)
        if rflash > 0:
            d.rectangle([0, 0, W, H], fill=(255, 70, 50, int(90 * rflash)))

        out = img.convert('RGBA')
        out = Image.alpha_composite(out, ov)
        return out.convert('RGB')
