"""把关键帧拼成 contact sheet，便于一次性看清全片分镜。"""
import sys, os, glob
from PIL import Image, ImageDraw

FR = os.path.join(os.path.dirname(__file__), 'frames')
OUT = os.path.join(os.path.dirname(__file__), 'out')

def main():
    tag = sys.argv[1] if len(sys.argv) > 1 else 'v1'
    # 12 秒 × 24fps = 288 帧，按 3×4 网格取 12 个均匀分布的关键帧
    picks = [int(round(i * 287 / 11)) for i in range(12)]
    files = [os.path.join(FR, 'f_%04d.png' % i) for i in picks]
    files = [f for f in files if os.path.exists(f)]
    if not files:
        print('no frames'); return

    cols, rows = 3, 4
    tw, th = 426, 240          # 每格缩略图尺寸（1280×720 的 1/3）
    pad, lab = 8, 20
    W = cols * tw + (cols + 1) * pad
    H = rows * (th + lab) + (rows + 1) * pad
    sheet = Image.new('RGB', (W, H), (14, 16, 20))
    d = ImageDraw.Draw(sheet)

    for k, f in enumerate(files[:cols * rows]):
        im = Image.open(f).convert('RGB').resize((tw, th), Image.LANCZOS)
        c, r = k % cols, k // cols
        x = pad + c * (tw + pad)
        y = pad + r * (th + lab + pad)
        sheet.paste(im, (x, y))
        idx = picks[k]
        d.text((x + 4, y + th + 4), 'f%03d  t=%.2fs' % (idx, idx / 24.0), fill=(150, 200, 215))

    p = os.path.join(OUT, 'sheet_%s.jpg' % tag)
    sheet.save(p, quality=90)
    print('->', p, sheet.size)

if __name__ == '__main__':
    main()
