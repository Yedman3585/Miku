"""
Делает заставку для игры из любого видео: splash.npz (кадры 128x64, 1 бит).

Пример:
    python make_splash.py miku.mp4 --start 10 --duration 30

Параметры:
    --fps 5           кадров в секунду (под OLED — 5)
    --start 10        с какой секунды видео брать
    --duration 30     сколько секунд (0 = до конца)
    --fit crop|pad    crop — заполнить экран с обрезкой краёв, pad — целиком с полосами
    --mode dither|threshold   dither — с "зерном" (лучше для лиц), threshold — чистый ч/б
    --threshold 128   порог для режима threshold
    --contrast 1.3    усиление контраста
    --invert          инвертировать цвета
Рядом сохраняется splash_preview.gif — посмотреть, как это будет выглядеть.
"""
import argparse
import math
import os

import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageOps

W, H = 128, 64
LANCZOS = getattr(Image, "Resampling", Image).LANCZOS
NEAREST = getattr(Image, "Resampling", Image).NEAREST


def convert(bgr, a):
    im = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)).convert("L")
    if a.fit == "crop":
        im = ImageOps.fit(im, (W, H), LANCZOS)
    else:
        im = ImageOps.pad(im, (W, H), LANCZOS, color=0)
    im = ImageOps.autocontrast(im, cutoff=1)
    im = ImageEnhance.Contrast(im).enhance(a.contrast)
    if a.invert:
        im = ImageOps.invert(im)
    if a.mode == "dither":
        bw = im.convert("1")  # Floyd–Steinberg
    else:
        bw = im.point(lambda p: 255 if p >= a.threshold else 0).convert("1")
    return np.array(bw, dtype=bool)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description="Видео -> заставка для OLED 128x64")
    ap.add_argument("video")
    ap.add_argument("--out", default=os.path.join(here, "splash.npz"))
    ap.add_argument("--fps", type=float, default=5)
    ap.add_argument("--start", type=float, default=0)
    ap.add_argument("--duration", type=float, default=30)
    ap.add_argument("--fit", choices=("crop", "pad"), default="crop")
    ap.add_argument("--mode", choices=("dither", "threshold"), default="dither")
    ap.add_argument("--threshold", type=int, default=128)
    ap.add_argument("--contrast", type=float, default=1.3)
    ap.add_argument("--invert", action="store_true")
    a = ap.parse_args()

    cap = cv2.VideoCapture(a.video)
    if not cap.isOpened():
        raise SystemExit(f"Не могу открыть видео: {a.video}")
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    first = int(a.start * src_fps)
    if first:
        cap.set(cv2.CAP_PROP_POS_FRAMES, first)
    end = a.start + a.duration if a.duration > 0 else math.inf

    frames, i, next_t = [], 0, a.start
    while True:
        ok, img = cap.read()
        if not ok:
            break
        t = (first + i) / src_fps
        i += 1
        if t >= end:
            break
        if t + 1e-6 >= next_t:
            frames.append(convert(img, a))
            next_t += 1.0 / a.fps
            if len(frames) % 25 == 0:
                print(f"  {len(frames)} кадров...")
    cap.release()
    if not frames:
        raise SystemExit("Не получилось взять ни одного кадра (проверь --start).")

    arr = np.stack(frames)
    np.savez_compressed(a.out, frames=np.packbits(arr, axis=-1), fps=int(round(a.fps)))

    preview = os.path.splitext(a.out)[0] + "_preview.gif"
    imgs = [Image.fromarray((f * 255).astype(np.uint8)).resize((W * 4, H * 4), NEAREST) for f in arr]
    imgs[0].save(preview, save_all=True, append_images=imgs[1:], duration=int(1000 / a.fps), loop=0)

    print(f"Готово: {len(frames)} кадров ({len(frames) / a.fps:.1f} с) -> {a.out}")
    print(f"Предпросмотр: {preview}")


if __name__ == "__main__":
    main()
