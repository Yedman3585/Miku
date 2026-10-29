"""
Превращает спрайты из assets/ в sprites.h для Arduino (RGB565, во флеш-памяти).
Прозрачность = цвет-ключ 0xF81F (пурпурный).

    python tools/export_sprites.py            # перезаписывает arduino/miku_runner_mega/sprites.h
    python tools/export_sprites.py --height 80   # Miku пониже (меньше флеш)
"""
import argparse
import os

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ASSETS = os.path.join(ROOT, "assets")
OUT = os.path.join(ROOT, "arduino", "miku_runner_mega", "sprites.h")
KEY = 0xF81F
UNIT = 3.75          # пикселей экрана на единицу мира (как UNIT_PX в config.h)


def rgb565(r, g, b):
    v = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
    return KEY ^ 0x0001 if v == KEY else v     # настоящий цвет не должен совпасть с ключом


def convert(img, w, h):
    im = img.convert("RGBA").resize((w, h), Image.LANCZOS)
    px = []
    for r, g, b, a in im.get_flattened_data() if hasattr(im, "get_flattened_data") else im.getdata():
        px.append(KEY if a < 128 else rgb565(r, g, b))
    return px


def emit(name, px, w, h):
    rows = []
    for i in range(0, len(px), 12):
        rows.append("  " + ",".join(f"0x{v:04X}" for v in px[i:i + 12]))
    return (f"static const uint16_t {name}_px[] PROGMEM = {{\n" + ",\n".join(rows) + "\n};\n"
            f"static const Sprite {name} = {{{w}, {h}, {name}_px}};\n\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--height", type=int, default=int(24 * UNIT), help="высота Miku в пикселях (по умолчанию 90)")
    a = ap.parse_args()

    out = ["// СГЕНЕРИРОВАНО tools/export_sprites.py — не правь руками.\n",
           "#pragma once\n#include <stdint.h>\n#include <avr/pgmspace.h>\n\n",
           f"#define SPRITE_KEY 0x{KEY:04X}\n",
           "struct Sprite { uint16_t w, h; const uint16_t* px; };\n\n"]
    total = 0

    def add(name, img, h):
        nonlocal total
        w = max(1, round(img.width * h / img.height))
        px = convert(img, w, h)
        total += len(px) * 2
        out.append(emit(name, px, w, h))
        print(f"{name:10s} {w}x{h}  {len(px) * 2 / 1024:.1f} KB")

    run_ids = [0, 2, 4, 6]
    for i, k in enumerate(run_ids):
        add(f"spr_run{i}", Image.open(os.path.join(ASSETS, f"run_{k}.png")), a.height)
    add("spr_jump", Image.open(os.path.join(ASSETS, "jump.png")), a.height)
    add("spr_idle", Image.open(os.path.join(ASSETS, "idle.png")), a.height)
    leek = Image.open(os.path.join(ASSETS, "leek.png"))
    add("spr_leek_s", leek, round(12 * UNIT))
    add("spr_leek_l", leek, round(18 * UNIT))
    fly = leek.rotate(90, expand=True)
    add("spr_fly", fly, round(6 * UNIT))
    out.append("static const Sprite* const SPR_RUN[4] = {&spr_run0, &spr_run1, &spr_run2, &spr_run3};\n")
    with open(OUT, "w") as f:
        f.write("".join(out))
    print(f"всего {total / 1024:.0f} KB флеш-памяти -> {OUT}")


if __name__ == "__main__":
    main()
