"""
audio.py — 程序化配乐与音效（对齐方案的「程序化音效」定位）

合成而非采样：低频底噪、伺服、推进器、枪声、爆炸、光剑嗡鸣。
输出 out/score.wav（44.1kHz / 16bit / 立体声），供 ffmpeg 与画面混流。
"""
import os
import wave
import numpy as np

SR = 44100
DUR = 12.0
N = int(SR * DUR)
HERE = os.path.dirname(os.path.abspath(__file__))
rng = np.random.default_rng(20261106)


def tt(n):
    return np.arange(n) / SR


def lp(x, fc, order=2):
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    X = X / (1 + (f / max(fc, 1)) ** (2 * order))
    return np.fft.irfft(X, len(x))


def hp(x, fc, order=2):
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    X = X * (1 - 1 / (1 + (f / max(fc, 1)) ** (2 * order)))
    return np.fft.irfft(X, len(x))


def bp(x, f0, bw, order=2):
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    g = np.exp(-((f - f0) ** 2) / (2 * max(bw, 1) ** 2))
    return np.fft.irfft(X * g, len(x))


def env_ad(n, a, tau):
    t = tt(n)
    e = np.minimum(1.0, t / max(a, 1e-5))
    e = e * np.exp(-np.maximum(0.0, t - a) / max(tau, 1e-4))
    return e


def env_ar(n, a, r):
    t = tt(n)
    e = np.minimum(1.0, t / max(a, 1e-5))
    e = e * np.clip((n / SR - t) / max(r, 1e-5), 0, 1)
    return e


def sine(f, n, ph=0.0):
    return np.sin(2 * np.pi * f * tt(n) + ph)


def sweep(f0, f1, n, curve=1.0):
    t = tt(n)
    u = (t / max(t[-1], 1e-6)) ** curve
    f = f0 + (f1 - f0) * u
    ph = 2 * np.pi * np.cumsum(f) / SR
    return np.sin(ph)


def noise(n):
    return rng.standard_normal(n)


def crackle(n, dens=0.02):
    m = (rng.random(n) < dens).astype(float)
    return m * rng.standard_normal(n)


buf = np.zeros((N, 2))


def add(start, sig, gain=1.0, pan=0.0):
    i0 = int(start * SR)
    if i0 >= N:
        return
    n = min(len(sig), N - i0)
    if n <= 0:
        return
    a = (pan + 1) * np.pi / 4
    buf[i0:i0 + n, 0] += sig[:n] * gain * np.cos(a)
    buf[i0:i0 + n, 1] += sig[:n] * gain * np.sin(a)


# ---------------------------------------------------------------- 1 底噪床
t = tt(N)
bed = (0.55 * sine(55, N) + 0.28 * sine(82.5, N) + 0.18 * sine(110, N))
bed += 0.55 * lp(noise(N), 180)
bed *= (0.55 + 0.45 * np.sin(2 * np.pi * 0.11 * t) ** 2)
bed_env = np.clip(t / 1.2, 0, 1) * np.clip((DUR - t) / 1.6, 0, 1)
add(0.0, bed * bed_env, gain=0.105)

# 风声（S1 空旷感）
wind = lp(noise(N), 900)
wind *= (0.6 + 0.4 * np.sin(2 * np.pi * 0.07 * t + 1.2))
wind_env = np.clip(t / 2.0, 0, 1) * np.clip((6.2 - t) / 2.0, 0, 1)
add(0.0, wind * wind_env, gain=0.055, pan=-0.1)

# ---------------------------------------------------------------- 2 启动 S2
# 伺服：带谐波的扫频
n = int(1.5 * SR)
srv = sweep(280, 940, n, 0.8) + 0.4 * sweep(560, 1880, n, 0.8) \
    + 0.18 * sweep(140, 470, n, 0.8)
srv = np.tanh(srv * 1.6) * env_ar(n, 0.06, 0.55)
add(3.30, srv, gain=0.115, pan=-0.15)

# 液压 thud
n = int(0.7 * SR)
th = np.sin(2 * np.pi * np.cumsum(np.linspace(92, 46, n)) / SR) * env_ad(n, 0.004, 0.12)
th += 0.5 * lp(noise(n), 260) * env_ad(n, 0.002, 0.07)
add(3.36, th, gain=0.30, pan=-0.2)

# 舱门锁定：金属 clank
n = int(0.45 * SR)
ck = bp(noise(n), 2300, 900) * env_ad(n, 0.001, 0.035)
ck += 0.7 * bp(noise(n), 4100, 1500) * env_ad(n, 0.001, 0.022)
ck += 0.4 * sine(1180, n) * env_ad(n, 0.001, 0.05)
add(4.62, ck, gain=0.16, pan=0.0)

# 点火：低频上冲
n = int(0.9 * SR)
ig = sweep(60, 220, n, 1.6) * env_ar(n, 0.05, 0.3)
ig += 0.6 * lp(noise(n), 500) * env_ar(n, 0.08, 0.4)
add(4.55, ig, gain=0.26)

# ---------------------------------------------------------------- 3 弹射 S3
# 推进器：棕噪声 + 低频，5.2-7.6 逐渐增强
n = int(2.9 * SR)
brn = np.cumsum(noise(n))
brn = brn - lp(brn, 25)
brn = np.tanh(brn / (np.abs(brn).max() + 1e-9) * 1.5)
thr = 0.8 * lp(brn, 620) + 0.5 * lp(noise(n), 1800)
thr += 0.55 * sweep(70, 130, n, 1.2)
ramp = np.clip(tt(n) / 0.55, 0, 1) * np.clip((2.9 - tt(n)) / 0.9, 0, 1)
add(5.05, thr * ramp, gain=0.40, pan=0.05)

# 弹射冲击
n = int(1.1 * SR)
la = sweep(150, 42, n, 1.8) * env_ad(n, 0.003, 0.16)
la += 0.7 * lp(noise(n), 700) * env_ad(n, 0.002, 0.10)
add(5.30, la, gain=0.42)

# 速度感 whoosh
n = int(1.4 * SR)
wh = bp(noise(n), 1500, 1100) * env_ar(n, 0.35, 0.6)
add(5.35, wh, gain=0.10, pan=-0.35)

# ---------------------------------------------------------------- 4 交战 S4
# 充能
n = int(0.95 * SR)
ch = sweep(720, 2500, n, 1.4) + 0.4 * sweep(1440, 5000, n, 1.4)
ch *= env_ar(n, 0.30, 0.12)
add(7.02, ch, gain=0.085, pan=0.1)

# 枪声：瞬态噪声 + 低频
n = int(0.55 * SR)
sh = hp(noise(n), 1200) * env_ad(n, 0.0008, 0.028)
sh += 0.8 * np.sin(2 * np.pi * np.cumsum(np.linspace(190, 60, n)) / SR) * env_ad(n, 0.001, 0.07)
sh += 0.35 * bp(noise(n), 3400, 1400) * env_ad(n, 0.001, 0.05)
add(7.98, sh, gain=0.50, pan=0.15)

# 命中爆炸
n = int(1.7 * SR)
ex = lp(noise(n), 1400) * env_ad(n, 0.004, 0.30)
ex += 0.9 * np.sin(2 * np.pi * np.cumsum(np.linspace(85, 30, n)) / SR) * env_ad(n, 0.004, 0.22)
ex += 0.5 * bp(noise(n), 2600, 1600) * env_ad(n, 0.002, 0.10)
ex += 0.35 * crackle(n, 0.003) * np.exp(-tt(n) / 0.35)
add(8.04, ex, gain=0.46, pan=0.55)

# 余烬碎片
n = int(1.4 * SR)
em = crackle(n, 0.0016) * np.exp(-tt(n) / 0.5)
add(8.30, bp(em, 3200, 1800), gain=0.16, pan=0.5)

# ---------------------------------------------------------------- 5 近战 S5
# 拔刀：金属摩擦
n = int(0.75 * SR)
dr = bp(noise(n), 2100, 1400) * env_ar(n, 0.18, 0.28)
dr += 0.4 * sine(760, n) * env_ar(n, 0.2, 0.3)
add(9.55, dr, gain=0.13, pan=-0.1)

# 光剑展开 + 嗡鸣
n = int(2.5 * SR)
ex2 = sweep(320, 1050, n, 0.7) * env_ar(n, 0.28, 0.35)
add(10.05, ex2, gain=0.16)
tn = tt(n)
hum = (0.55 * sine(98, n) + 0.30 * sine(196, n) + 0.14 * sine(294, n))
hum *= (0.72 + 0.28 * np.sin(2 * np.pi * 6.5 * tn))
hum *= np.clip(tn / 0.3, 0, 1) * np.clip((2.5 - tn) / 0.5, 0, 1)
add(10.30, np.tanh(hum * 1.4), gain=0.115)

# 挥砍 whoosh
n = int(0.85 * SR)
sw = bp(noise(n), 2400, 1500) * env_ar(n, 0.20, 0.22)
sw += 0.5 * sweep(1400, 400, n, 0.6) * env_ar(n, 0.18, 0.2)
add(10.95, sw, gain=0.28, pan=-0.25)

# 收尾低频
n = int(2.0 * SR)
fn = np.sin(2 * np.pi * np.cumsum(np.linspace(44, 32, n)) / SR) * env_ar(n, 0.4, 1.4)
add(10.9, fn, gain=0.22)

# ---------------------------------------------------------------- 简易混响
def reverb(x, delays=((0.031, 0.28), (0.047, 0.22), (0.071, 0.16), (0.113, 0.10))):
    y = x.copy()
    for d, g in delays:
        k = int(d * SR)
        y[k:] += x[:-k] * g
    return y


buf[:, 0] = reverb(buf[:, 0])
buf[:, 1] = reverb(buf[:, 1])

# 母带：软限幅 + 归一化
peak = np.abs(buf).max()
buf = buf / (peak + 1e-9) * 1.05
buf = np.tanh(buf * 1.25) / np.tanh(1.25)
buf *= 0.92

out = os.path.join(HERE, 'out', 'score.wav')
os.makedirs(os.path.dirname(out), exist_ok=True)
pcm = (np.clip(buf, -1, 1) * 32767).astype('<i2')
with wave.open(out, 'wb') as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes(pcm.tobytes())
print(f'score -> {out}  {DUR}s  peak={np.abs(buf).max():.3f}')
