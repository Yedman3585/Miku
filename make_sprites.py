"""
Нарезает спрайты для Miku Runner из исходников в assets/src/:
    miku_sheet.gif      - гифка с Miku (бег / поёт)
    leek_and_miku.png   - лук (препятствие)
    chibi.png           - чиби-Miku (экран Game Over)
Результат кладётся в assets/*.png. Запускать нужно только если меняешь исходники:
    pip install scipy
    python make_sprites.py
"""
import json
import os

import numpy as np
from PIL import Image
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "assets", "src")
OUT = os.path.join(HERE, "assets")

RUN_FRAMES = [8, 9, 10, 11, 12, 11, 10, 9]   # цикл бега внутри гифки
JUMP_FRAME, IDLE_FRAME = 11, 13
RUN_BOX = (258, 52, 424, 193)                # окно вокруг бегущей Miku (ноги внизу)
SING_BOX = (455, 0, 797, 194)                # окно вокруг поющей Miku + ноты


def largest_parts(alpha, min_px=40):
    lab, n = ndimage.label(alpha, structure=np.ones((3, 3)))
    if n == 0:
        return alpha
    sizes = ndimage.sum(alpha, lab, range(1, n + 1))
    keep = [i + 1 for i, s in enumerate(sizes) if s >= min_px]
    return np.isin(lab, keep)


def key_bg(img, bg, tol=10, min_px=40):
    a = np.array(img.convert("RGBA"))
    diff = np.abs(a[..., :3].astype(int) - np.array(bg)).sum(-1)
    alpha = largest_parts(diff > tol, min_px)
    a[..., 3] = alpha * 255
    return Image.fromarray(a, "RGBA")


def cutout_by_outline(img, dark=110, sat=45, light=None):
    """Вырезает фигуру из светлого фона: контур + заливка дыр внутри."""
    a = np.array(img.convert("RGB")).astype(int)
    lum, s = a.sum(-1) / 3, a.max(-1) - a.min(-1)
    fg = (lum < dark) | (s > sat)
    fg = ndimage.binary_closing(fg, structure=np.ones((3, 3)), iterations=2)
    fg = ndimage.binary_fill_holes(fg)
    lab, n = ndimage.label(fg, structure=np.ones((3, 3)))
    sizes = ndimage.sum(fg, lab, range(1, n + 1))
    keep = lab == (np.argmax(sizes) + 1)
    out = Image.fromarray(np.dstack([a.astype(np.uint8), (keep * 255).astype(np.uint8)]), "RGBA")
    return out.crop(out.getbbox())


def main():
    gif = Image.open(os.path.join(SRC, "miku_sheet.gif"))
    frames = []
    for i in range(gif.n_frames):
        gif.seek(i)
        frames.append(gif.convert("RGBA").copy())
    bg = frames[0].getpixel((0, 0))[:3]

    # --- бег / прыжок / стоит ---
    run = [key_bg(frames[i].crop(RUN_BOX), bg) for i in RUN_FRAMES]
    for k, im in enumerate(run):
        im.save(os.path.join(OUT, f"run_{k}.png"))
    key_bg(frames[JUMP_FRAME].crop(RUN_BOX), bg).save(os.path.join(OUT, "jump.png"))
    key_bg(frames[IDLE_FRAME].crop(RUN_BOX), bg).save(os.path.join(OUT, "idle.png"))

    # --- поёт (заставка): уникальные кадры + порядок ---
    uniq, order, seen = [], [], {}
    for f in frames:
        c = key_bg(f.crop(SING_BOX), bg, min_px=6)
        h = c.tobytes()
        if h not in seen:
            seen[h] = len(uniq)
            uniq.append(c)
        order.append(seen[h])
    w, h = uniq[0].size
    strip = Image.new("RGBA", (w * len(uniq), h), (0, 0, 0, 0))
    for i, c in enumerate(uniq):
        strip.paste(c, (i * w, 0))
    strip.save(os.path.join(OUT, "sing_strip.png"))
    with open(os.path.join(OUT, "sing.json"), "w") as f:
        json.dump({"w": w, "h": h, "n": len(uniq), "order": order,
                   "ms": gif.info.get("duration", 100)}, f)

    # --- лук: стоймя ---
    leek_src = Image.open(os.path.join(SRC, "leek_and_miku.png")).crop((150, 60, 540, 520))
    leek = cutout_by_outline(leek_src)
    leek = leek.rotate(-26, expand=True, resample=Image.NEAREST)
    leek.crop(leek.getbbox()).save(os.path.join(OUT, "leek.png"))

    # --- чиби ---
    chibi = Image.open(os.path.join(SRC, "chibi.png")).crop((118, 40, 790, 760))
    cutout_by_outline(chibi, dark=190, sat=30).save(os.path.join(OUT, "chibi.png"))
    print("готово ->", OUT)


if __name__ == "__main__":
    main()
