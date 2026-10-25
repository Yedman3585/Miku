"""
MIKU RUNNER — бегалка в стиле динозаврика Google.
Miku бежит и прыгает через лук. Управление — джойстик Arduino (или клавиатура).
Картинка одновременно идёт в окно на ПК (цветная) и на OLED 128x64 (чёрно-белая).

Запуск:
    python miku_runner.py                  # порт Arduino ищется автоматически
    python miku_runner.py --port COM5      # указать порт вручную (на Mac: /dev/cu.usbserial-...)
    python miku_runner.py --no-serial      # без Arduino, только клавиатура
    python miku_runner.py --baud 115200    # если на Arduino ещё старая прошивка

Управление:
    прыжок:  кнопка джойстика / джойстик вверх / Пробел / ↑ / W   (держи дольше — прыгнешь выше)
    пригнуться: джойстик вниз / ↓ / S   (в воздухе — быстро упасть)
    F — полный экран, TAB — показать/скрыть превью OLED, M — звук, Esc — выход

Необязательно (положи в папку assets/):
    splash.mp4              — видео для фона заставки
    music.mp3 / .ogg / .wav — музыка (иначе играет встроенная 8-бит мелодия)
"""
import argparse
import json
import math
import os
import random
import threading
import time

import numpy as np
import pygame
from PIL import Image

import pixel_miku

try:
    import serial
    from serial.tools import list_ports
except ImportError:  # pyserial не установлен — играем с клавиатуры
    serial = None

# ============================ НАСТРОЙКИ ============================
BAUD = 500000             # должно совпадать со скетчем Arduino (miku_runner_oled.ino)
OLED_FPS = 30             # максимум кадров/с на OLED (реально ограничит скорость порта и экрана)
FLIP_OLED = False         # True, если картинка на OLED вверх ногами
FLIP_JOY_Y = False        # True, если "вверх" на джойстике работает как "вниз"
DEADZONE = 0.25
WIN_W, WIN_H, BAR = 1024, 512, 28
S = WIN_W // 128          # 1 пиксель OLED = 8 пикселей окна

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets")
HISCORE_FILE = os.path.join(HERE, "highscore.txt")

W, H = 128, 64            # мир игры = экран OLED
GROUND = 54               # линия земли (y, куда ставит ноги Miku)

# --- физика (единицы = пиксели OLED, секунды) ---
GRAVITY = 420.0
JUMP_APEX = 30.0
JUMP_V = math.sqrt(2 * GRAVITY * JUMP_APEX)
START_SPEED, MAX_SPEED, ACCEL = 55.0, 108.0, 1.2
SPR_H = 24.0              # высота Miku на экране (в пикселях OLED)
SPR_W = SPR_H * 166 / 141
PX = 6.0                  # x левого края спрайта Miku
DUCK_H = 12.0
LEEK_SIZES = {"s": (6, 12), "l": (8, 18)}   # (ширина, высота)

# ============================ ШРИФТ 3x5 ============================
_GLYPHS = {
    "0": "111101101101111", "1": "010110010010111", "2": "111001111100111",
    "3": "111001111001111", "4": "101101111001001", "5": "111100111001111",
    "6": "111100111101111", "7": "111001001010010", "8": "111101111101111",
    "9": "111101111001111", "A": "010101111101101", "B": "110101110101110",
    "C": "011100100100011", "D": "110101101101110", "E": "111100110100111",
    "F": "111100110100100", "G": "011100101101011", "H": "101101111101101",
    "I": "111010010010111", "J": "001001001101010", "K": "101101110101101",
    "L": "100100100100111", "M": "101111111101101", "N": "110101101101101",
    "O": "010101101101010", "P": "110101110100100", "Q": "010101101110011",
    "R": "110101110101101", "S": "011100010001110", "T": "111010010010010",
    "U": "101101101101111", "V": "101101101101010", "W": "101101111111101",
    "X": "101101010101101", "Y": "101101010010010", "Z": "111001010100111",
    " ": "000000000000000", "!": "010010010000010", ":": "000010000010000",
    "-": "000000111000000", ".": "000000000000010", "/": "001001010100100",
    "?": "111001011000010", "+": "000010111010000", ">": "100010001010100",
}
FONT = {k: np.array([c == "1" for c in v], dtype=bool).reshape(5, 3)
        for k, v in _GLYPHS.items()}
FONT["M"] = np.array([[c == "1" for c in r] for r in
                      ("10001", "11011", "10101", "10001", "10001")], dtype=bool)
NOTE = np.array([[c == "1" for c in r] for r in
                 ("00111", "00101", "00101", "00100", "11100", "11100")], dtype=bool)


class Canvas:
    """Чёрно-белый холст 128x64 — ровно то, что покажет OLED."""

    def __init__(self):
        self.px = np.zeros((H, W), dtype=bool)

    def clear(self):
        self.px[:] = False

    def rect(self, x, y, w, h, on=True):
        x, y, w, h = int(round(x)), int(round(y)), int(round(w)), int(round(h))
        x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + w, W), min(y + h, H)
        if x1 > x0 and y1 > y0:
            self.px[y0:y1, x0:x1] = on

    def frame(self, x, y, w, h):
        self.rect(x, y, w, 1)
        self.rect(x, y + h - 1, w, 1)
        self.rect(x, y, 1, h)
        self.rect(x + w - 1, y, 1, h)

    def blit(self, mask, x, y, on=True):
        x, y = int(round(x)), int(round(y))
        mh, mw = mask.shape
        x0, y0 = max(x, 0), max(y, 0)
        x1, y1 = min(x + mw, W), min(y + mh, H)
        if x1 <= x0 or y1 <= y0:
            return
        sub = mask[y0 - y:y1 - y, x0 - x:x1 - x]
        self.px[y0:y1, x0:x1][sub] = on

    @staticmethod
    def text_width(s, scale=1):
        n = sum(FONT.get(ch, FONT["?"]).shape[1] + 1 for ch in s.upper())
        return max(n - 1, 0) * scale

    def text(self, s, x, y, scale=1, on=True):
        for ch in s.upper():
            g = FONT.get(ch, FONT["?"])
            if scale > 1:
                g = np.kron(g, np.ones((scale, scale), dtype=bool))
            self.blit(g, x, y, on)
            x += g.shape[1] + scale

    def center_text(self, s, y, scale=1, on=True):
        self.text(s, (W - self.text_width(s, scale)) // 2, y, scale, on)


_WEIGHTS = (1 << np.arange(8, dtype=np.uint16)).reshape(1, 8, 1)


def pack_ssd1306(px):
    """bool[64,128] -> 1024 байта в формате буфера SSD1306 (8 страниц по 128 столбцов)."""
    if FLIP_OLED:
        px = px[::-1, ::-1]
    pages = px.reshape(8, 8, W).astype(np.uint16)
    return (pages * _WEIGHTS).sum(axis=1).astype(np.uint8).tobytes()


# ============================ СПРАЙТЫ ============================
def load_png(name):
    return Image.open(os.path.join(ASSETS, name)).convert("RGBA")


class Sprites:
    """Все картинки: PIL-оригиналы, версии для окна (pygame) и для OLED (маски)."""

    def __init__(self):
        self.run = [load_png(f"run_{i}.png") for i in range(8)]
        self.jump, self.idle = load_png("jump.png"), load_png("idle.png")
        self.leek, self.chibi = load_png("leek.png"), load_png("chibi.png")
        with open(os.path.join(ASSETS, "sing.json")) as f:
            self.sing_meta = json.load(f)
        strip = load_png("sing_strip.png")
        sw, sh = self.sing_meta["w"], self.sing_meta["h"]
        self.sing = [strip.crop((i * sw, 0, (i + 1) * sw, sh)) for i in range(self.sing_meta["n"])]

        # ---- для окна ----
        def pg(img, h, wscale=1.0):
            w = max(1, round(img.width * h / img.height * wscale))
            im = img.resize((w, int(h)), Image.LANCZOS)
            return pygame.image.frombuffer(im.tobytes(), im.size, "RGBA").convert_alpha()
        self.pg = pg
        ph = int(SPR_H * S)
        self.pc_run = [pg(i, ph) for i in self.run]
        self.pc_jump, self.pc_idle = pg(self.jump, ph), pg(self.idle, ph)
        self.pc_duck = pg(self.run[0], int(DUCK_H * S), 1.25)
        self.pc_leek = {k: pg(self.leek, h * S) for k, (_, h) in LEEK_SIZES.items()}
        self.pc_fly = {a: pygame.transform.rotozoom(pg(self.leek, 12 * S), 90 + a, 1.0)
                       for a in (-14, 0, 14)}
        self.pc_chibi = pg(self.chibi, 300)
        self._sing_cache = {}

        # ---- для OLED: нарисованные вручную 1-битные спрайты (pixel_miku.py) ----
        f = pixel_miku.build()
        self.m_run, self.m_jump, self.m_idle, self.m_duck = f["run"], f["jump"], f["idle"], f["duck"]
        self.m_leek = {"s": f["leek_s"], "l": f["leek_l"]}
        self.m_fly = f["fly"]

    def pc_sing(self, i, h=355):
        if i not in self._sing_cache:
            self._sing_cache[i] = self.pg(self.sing[i], h)
        return self._sing_cache[i]


# ============================ СВЯЗЬ С ARDUINO ============================
class ArduinoLink:
    KNOWN_VIDS = {0x2341, 0x2A03, 0x1A86, 0x0403, 0x10C4, 0x1B4F, 0x239A}

    def __init__(self, port=None, baud=BAUD):
        self.port_arg, self.baud = port, baud
        self.port = None
        self.ser = None
        self.status = "поиск Arduino..."
        self._lock = threading.Lock()
        self._joy = (512, 512, 0)
        self.have_joy = False
        self._ready = False
        self._sent_at = 0.0
        self.frames_sent = 0
        threading.Thread(target=self._run, daemon=True).start()

    def _find_port(self):
        if self.port_arg:
            return self.port_arg
        ports = list(list_ports.comports())
        for p in ports:
            if p.vid in self.KNOWN_VIDS:
                return p.device
        for p in ports:
            d = (p.description or "").lower()
            if any(k in d for k in ("arduino", "ch340", "usb-serial", "usb serial", "usbserial")):
                return p.device
        return None

    def _close(self, why):
        try:
            self.ser.close()
        except Exception:
            pass
        self.ser = None
        self.have_joy = False
        self.status = why

    def _run(self):
        while True:
            if self.ser is None:
                port = self._find_port()
                if not port:
                    self.status = "Arduino не найдена — играем с клавиатуры"
                    time.sleep(2)
                    continue
                try:
                    self.ser = serial.Serial(port, self.baud, timeout=0.1)
                except Exception as e:
                    self.status = f"{port}: не открывается ({e})"
                    self.ser = None
                    time.sleep(2)
                    continue
                self.port = port
                self.status = f"{port}: ждём Arduino..."
                self._ready = False
                self._sent_at = time.time() + 2.5   # если "R" потеряется — всё равно начнём
            try:
                line = self.ser.readline()
            except Exception:
                self._close(f"{self.port}: отключено")
                time.sleep(1)
                continue
            if line:
                self._parse(line)

    def _parse(self, line):
        s = line.decode("ascii", "ignore").strip()
        if not s:
            return
        if s[0] == "J":
            parts = s[1:].split()
            if len(parts) == 3:
                try:
                    x, y, b = (int(v) for v in parts)
                except ValueError:
                    return
                with self._lock:
                    self._joy = (x, y, b)
                self.have_joy = True
                if "ждём" in self.status:
                    self.status = f"{self.port}: подключено"
        elif s in ("R", "F"):
            if s == "R":
                self.status = f"{self.port}: подключено"
            self._ready = True

    def joystick(self):
        with self._lock:
            return self._joy

    def try_send_frame(self, data):
        ser = self.ser
        if ser is None:
            return False
        now = time.time()
        if not self._ready and now - self._sent_at > 0.6:
            self._ready = True          # подтверждение потерялось — пробуем снова
        if not self._ready:
            return False
        try:
            ser.write(data)
        except Exception:
            return False
        self._ready = False
        self._sent_at = now
        self.frames_sent += 1
        return True


# ============================ ВВОД ============================
class Input:
    def __init__(self, link):
        self.link = link
        self.cx = self.cy = None
        self.prev_jact = False
        self.jump_pressed = self.jump_held = self.duck_held = False
        self.click = None
        self.raw = None

    @staticmethod
    def _norm(v, c):
        a = max(-1.0, min(1.0, (v - c) / 512.0))
        if abs(a) < DEADZONE:
            return 0.0
        return math.copysign((abs(a) - DEADZONE) / (1 - DEADZONE), a)

    def update(self, events):
        keys = pygame.key.get_pressed()
        held = keys[pygame.K_SPACE] or keys[pygame.K_UP] or keys[pygame.K_w]
        duck = keys[pygame.K_DOWN] or keys[pygame.K_s]
        pressed = False
        self.click = None
        for e in events:
            if e.type == pygame.KEYDOWN and e.key in (pygame.K_SPACE, pygame.K_UP, pygame.K_w,
                                                      pygame.K_RETURN):
                pressed = True
            elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                self.click = e.pos
        jact = False
        if self.link and self.link.have_joy:
            x, y, b = self.link.joystick()
            self.raw = (x, y, b)
            if self.cy is None:   # калибровка центра по первому значению
                self.cx = x if 300 < x < 724 else 512
                self.cy = y if 300 < y < 724 else 512
            jy = self._norm(y, self.cy) * (-1 if FLIP_JOY_Y else 1)
            up, down = jy < -0.6, jy > 0.6
            jact = bool(b) or up
            held = held or jact
            duck = duck or down
        self.jump_held, self.duck_held = bool(held), bool(duck)
        self.jump_pressed = pressed or (jact and not self.prev_jact)
        self.prev_jact = jact


# ============================ ЗВУК ============================
def _note_hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


class Sounds:
    SR = 44100

    # Звук в видео — смонтированные куски песни. (время в видео, смещение в песне music.mp3):
    SYNC = ((0.0, 10.945), (14.35, 15.23), (43.1, 31.30))

    def __init__(self, volume=0.5):
        self.ok, self.muted = False, False
        self.intro, self.intro_len, self.intro_t0, self.phase = None, 64.8069, time.time(), "intro"
        self.music_path = next((os.path.join(ASSETS, n) for n in
                                ("music.mp3", "music.ogg", "music.wav")
                                if os.path.exists(os.path.join(ASSETS, n))), None)
        try:
            pygame.mixer.init(self.SR, -16, 2, 512)
            self.ok = True
        except Exception:
            return
        self.volume = volume
        ip = os.path.join(ASSETS, "intro.mp3")
        if os.path.exists(ip):
            try:
                self.intro = pygame.mixer.Sound(ip)
                self.intro_len = self.intro.get_length()
            except Exception:
                self.intro = None
        self.s = {
            "jump": self._sweep(330, 700, 140),
            "hit": self._sweep(300, 70, 380, noise=0.5),
            "ding": self._sweep(988, 1319, 220, step=True),
        }
        self.chip = None
        if not self.music_path:
            self.chip = self._chiptune()

    def _stereo(self, wave):
        wave = np.clip(wave, -1, 1)
        w = (wave * 32767).astype(np.int16)
        return np.ascontiguousarray(np.repeat(w[:, None], 2, axis=1))

    def _sweep(self, f0, f1, ms, vol=0.3, noise=0.0, step=False):
        n = int(self.SR * ms / 1000)
        t = np.arange(n) / self.SR
        if step:
            f = np.where(np.arange(n) < n // 2, f0, f1)
        else:
            f = np.linspace(f0, f1, n)
        ph = np.cumsum(f) / self.SR
        wave = np.sign(np.sin(2 * np.pi * ph)) * 0.8 + noise * np.random.uniform(-1, 1, n)
        wave *= np.linspace(1, 0, n) ** 1.5 * vol
        return pygame.sndarray.make_sound(self._stereo(wave))

    def _chiptune(self):
        """Маленькая 8-бит мелодия (A minor, 150 bpm), 8 тактов, зациклена."""
        sr, step = self.SR, 0.1                       # шаг = 1/16 ноты
        bars = [("Am", 45, (57, 60, 64)), ("F", 41, (57, 60, 65)),
                ("C", 48, (60, 64, 67)), ("G", 43, (59, 62, 67))]
        lead_a = {"Am": [76, 0, 72, 76, 79, 0, 76, 72], "F": [77, 0, 72, 77, 81, 0, 77, 72],
                  "C": [76, 0, 72, 76, 79, 0, 76, 79], "G": [74, 0, 71, 74, 79, 0, 74, 71]}
        lead_b = {"Am": [81, 79, 76, 0, 79, 76, 72, 0], "F": [81, 77, 76, 77, 81, 0, 84, 0],
                  "C": [79, 76, 72, 76, 79, 0, 84, 0], "G": [83, 79, 74, 79, 83, 0, 86, 0]}
        total = int(sr * step * 16 * 8)
        buf = np.zeros(total)

        def add(start_step, m, dur_steps, kind, vol):
            i0 = int(start_step * step * sr)
            n = int(dur_steps * step * sr)
            t = np.arange(n) / sr
            ph = (_note_hz(m) * t) % 1.0
            if kind == "sq25":
                w = np.where(ph < 0.25, 1.0, -1.0)
            elif kind == "sq50":
                w = np.where(ph < 0.5, 1.0, -1.0)
            else:   # triangle
                w = 4 * np.abs(ph - 0.5) - 1
            env = np.exp(-t * (6 if kind != "tri" else 3)) * np.minimum(1, t * 400)
            end = min(total, i0 + n)
            buf[i0:end] += (w * env * vol)[:end - i0]

        for bar in range(8):
            name, bass, tri = bars[bar % 4]
            lead = (lead_a if bar < 4 else lead_b)[name]
            for beat in range(4):
                add(bar * 16 + beat * 4, bass, 3.5, "tri", 0.30)
            for k in range(16):
                add(bar * 16 + k, tri[k % 3] + 12, 1.5, "sq50", 0.06)
            for k, m in enumerate(lead):
                if m:
                    add(bar * 16 + k * 2, m, 3, "sq25", 0.13)
            for k in range(2, 16, 4):   # хэт
                i0 = int((bar * 16 + k) * step * sr)
                n = int(0.04 * sr)
                buf[i0:i0 + n] += np.random.uniform(-1, 1, n) * np.linspace(1, 0, n) * 0.05
        buf /= max(1.0, np.abs(buf).max() * 1.05)
        return pygame.sndarray.make_sound(self._stereo(buf * 0.8))

    def play(self, name):
        if self.ok and not self.muted:
            self.s[name].set_volume(self.volume)
            self.s[name].play()

    def music_on(self, start=0.0, fade_ms=0):
        if not self.ok or self.muted:
            return
        if self.music_path:
            if not pygame.mixer.music.get_busy():
                try:
                    pygame.mixer.music.load(self.music_path)
                    pygame.mixer.music.set_volume(self.volume)
                    try:
                        pygame.mixer.music.play(-1, start=start, fade_ms=fade_ms)
                    except Exception:
                        pygame.mixer.music.play(-1)
                except Exception:
                    self.music_path = None
        elif self.chip and self.chip.get_num_channels() == 0:
            self.chip.set_volume(self.volume * 0.7)
            self.chip.play(-1)

    # ---- интро: звук из видео + переход на полную песню с того же места ----
    def intro_on(self):
        self.phase, self.intro_t0 = "intro", time.time()
        if self.ok and self.intro and not self.muted:
            self.intro.set_volume(self.volume)
            self.intro.play(loops=-1)

    def intro_time(self):
        return (time.time() - self.intro_t0) % self.intro_len

    def song_pos(self, t):
        off = self.SYNC[0][1]
        for t0, o in self.SYNC:
            if t >= t0:
                off = o
        return t + off

    def open_game(self):
        """Нажали OPEN GAME: интро плавно уходит, песня продолжается с этого же места."""
        pos = self.song_pos(self.intro_time() + 0.15)
        self.phase = "game"
        if self.ok and self.intro:
            self.intro.fadeout(600)
        self.music_on(start=pos, fade_ms=600)

    def music_off(self):
        if self.ok and self.music_path:
            pygame.mixer.music.fadeout(400)
        elif self.ok and self.chip:
            self.chip.fadeout(400)

    def toggle_mute(self):
        self.muted = not self.muted
        if self.muted:
            pygame.mixer.stop()
            pygame.mixer.music.stop()
        elif self.phase == "intro":
            self.intro_on()
        else:
            self.music_on()


# ============================ ИГРА (логика) ============================
class Obstacle:
    def __init__(self, kind, x, **kw):
        self.kind, self.x = kind, float(x)
        if kind == "leek":
            self.size, self.n = kw["size"], kw["n"]
            lw, lh = LEEK_SIZES[self.size]
            self.w, self.h = lw * self.n + (self.n - 1), lh
            self.top = GROUND - lh
        else:   # летающий лук
            self.w, self.h = 14, 6
            self.top = kw["top"]
            self.phase = random.uniform(0, 6)

    def rect(self):
        """Хитбокс (чуть меньше картинки, чтобы было честно)."""
        return (self.x + 1.5, self.top + 1.5, self.w - 3, self.h - 2.5)


class Game:
    def __init__(self, snd):
        self.snd = snd
        self.hi = self._load_hi()
        self.t = 0.0
        self.state, self.state_t = "gate", 0.0   # пустой экран с кнопкой OPEN GAME
        self.reset()

    def _load_hi(self):
        try:
            with open(HISCORE_FILE) as f:
                return int(f.read().strip())
        except Exception:
            return 0

    def _save_hi(self):
        try:
            with open(HISCORE_FILE, "w") as f:
                f.write(str(self.hi))
        except Exception:
            pass

    def to_splash(self):
        self.state, self.state_t = "splash", 0.0
        self.reset()
        self.snd.music_on()

    def reset(self):
        self.run_t = 0.0
        self.dist = 0.0
        self.score = 0
        self.speed = START_SPEED
        self.py, self.vy = float(GROUND), 0.0
        self.on_ground, self.ducking = True, False
        self.obs = []
        self.to_spawn = 40.0
        self.flash = 0.0
        self.next_ding = 100
        self.dust, self.notes, self._dust_t, self._note_t = [], [], 0.0, 0.0

    def start(self):
        self.reset()
        self.state, self.state_t = "play", 0.0
        self.snd.music_on()

    # ---- хитбокс игрока ----
    def player_rect(self):
        h = DUCK_H - 1 if self.ducking else SPR_H - 3
        x = PX + 0.47 * SPR_W + 1.5
        return (x, self.py - h, 0.40 * SPR_W - 2, h)

    @staticmethod
    def _hit(a, b):
        return a[0] < b[0] + b[2] and a[0] + a[2] > b[0] and a[1] < b[1] + b[3] and a[1] + a[3] > b[1]

    # ---- обновление ----
    def update(self, dt, inp):
        self.t += dt
        self.state_t += dt
        if self.state == "gate":
            if inp.jump_pressed or inp.click:
                self.snd.open_game()      # песня продолжается с места видео
                self.to_splash()
        elif self.state == "splash":
            if inp.jump_pressed or inp.click:
                self.start()
        elif self.state == "over":
            if (inp.jump_pressed and self.state_t > 0.7) or self.state_t > 20:
                self.start()
        elif self.state == "play":
            self._play(dt, inp)

    def _play(self, dt, inp):
        self.run_t += dt
        self.speed = min(MAX_SPEED, START_SPEED + ACCEL * self.run_t)
        self.dist += self.speed * dt
        self.score = int(self.dist * 0.12)
        self.flash = max(0.0, self.flash - dt)
        if self.score >= self.next_ding:
            self.next_ding += 100
            self.flash = 1.0
            self.snd.play("ding")

        # --- прыжок / приседание ---
        if inp.jump_pressed and self.on_ground:
            self.vy = -JUMP_V
            self.on_ground = False
            self.snd.play("jump")
        if not inp.jump_held and self.vy < -JUMP_V * 0.4:
            self.vy = -JUMP_V * 0.4            # отпустил кнопку — прыжок ниже
        self.ducking = inp.duck_held and self.on_ground
        g = GRAVITY * (2.6 if (inp.duck_held and not self.on_ground) else 1.0)
        self.vy += g * dt
        self.py += self.vy * dt
        if self.py >= GROUND:
            self.py, self.vy, self.on_ground = float(GROUND), 0.0, True

        # --- препятствия ---
        for o in self.obs:
            o.x -= self.speed * dt
        self.obs = [o for o in self.obs if o.x + o.w > -6]
        self.to_spawn -= self.speed * dt
        if self.to_spawn <= 0:
            o = self._spawn()
            self.to_spawn = o.w + self.speed * 0.76 * random.uniform(1.05, 1.8) + 14

        # --- столкновение ---
        pr = self.player_rect()
        for o in self.obs:
            if self._hit(pr, o.rect()):
                self._die()
                return

        # --- эффекты (пыль, ноты) ---
        self._dust_t -= dt
        if self.on_ground and self._dust_t <= 0:
            self._dust_t = 0.07
            self.dust.append([PX + 15, GROUND - 0.5, -random.uniform(10, 25), -random.uniform(2, 14), 0.4])
        self._note_t -= dt
        if self._note_t <= 0:
            self._note_t = random.uniform(0.4, 0.8)
            self.notes.append([PX + 3, self.py - 18, -random.uniform(12, 22), -random.uniform(8, 16),
                               1.1, random.random() < 0.5])
        for p in self.dust:
            p[0] += p[2] * dt
            p[1] += p[3] * dt
            p[4] -= dt
        for p in self.notes:
            p[0] += p[2] * dt
            p[1] += p[3] * dt
            p[4] -= dt
        self.dust = [p for p in self.dust if p[4] > 0]
        self.notes = [p for p in self.notes if p[4] > 0]

    def _spawn(self):
        r = random.random()
        if self.score > 250 and r < 0.28:
            o = Obstacle("fly", W + 4, top=random.choice((GROUND - 13, GROUND - 23)))
        else:
            if self.score < 120:
                size, n = random.choice([("s", 1), ("l", 1), ("s", 1)])
            else:
                size, n = random.choice([("s", 1), ("l", 1), ("s", 2), ("s", 3), ("l", 2), ("l", 1)])
            o = Obstacle("leek", W + 4, size=size, n=n)
        self.obs.append(o)
        return o

    def _die(self):
        self.snd.play("hit")
        if self.score > self.hi:
            self.hi = self.score
            self._save_hi()
        self.state, self.state_t = "over", 0.0

    def run_frame(self):
        return int(self.dist / 5.5) % 8

    # ---- бот для автотеста ----
    def bot(self, inp):
        inp.jump_pressed = inp.duck_held = False
        inp.jump_held = False
        if self.state != "play":
            inp.jump_pressed = True
            return
        pr = self.player_rect()
        pc = pr[0] + pr[2] / 2
        jumped = False
        for o in self.obs:
            oc = o.x + o.w / 2
            if o.x + o.w < pr[0] - 1:
                continue
            if o.kind == "fly" and o.top < GROUND - 20:
                if oc - pc < 30:
                    inp.duck_held = True
            elif not jumped and self.on_ground and oc - pc < self.speed * 0.37 + (4 if o.kind == "leek" else 0):
                inp.jump_pressed = jumped = True
        inp.jump_held = inp.jump_pressed or not self.on_ground


# ============================ ПРОРИСОВКА: OLED ============================
def draw_oled(cv, g, spr):
    cv.clear()
    if g.state == "gate":
        cv.center_text("MIKU RUNNER", 22, 1)
        if int(g.t * 2) % 2 == 0:
            cv.center_text("PRESS START", 36, 1)
        return
    if g.state == "splash":
        draw_oled_splash(cv, g, spr)
        return
    # земля
    cv.rect(0, GROUND, W, 1)
    off = int(g.dist) if g.state != "splash" else 0
    for i in range(0, 40):
        x = (i * 23 + 7 - off) % W
        cv.rect(x, GROUND + 3 + (i * 5) % 7, 1 + (i % 3 == 0), 1)
    # облака
    for cx, cy in ((20, 14), (75, 22), (110, 12)):
        x = (cx - off * 0.12) % (W + 20) - 10
        cv.rect(x + 2, cy, 8, 1)
        cv.rect(x, cy + 1, 12, 1)
    # препятствия
    for o in g.obs:
        if o.kind == "leek":
            lw, _ = LEEK_SIZES[o.size]
            m = spr.m_leek[o.size]
            for i in range(o.n):
                cv.blit(m, o.x + i * (lw + 1), GROUND - m.shape[0])
        else:
            m = spr.m_fly
            wob = int(round(math.sin(g.t * 14 + o.phase) * 1))
            cv.blit(m, o.x, o.top + wob)
    # Miku
    if g.state == "over":
        m, y = spr.m_idle, g.py
    elif g.ducking:
        m, y = spr.m_duck, g.py
    elif not g.on_ground:
        m, y = spr.m_jump, g.py
    else:
        m, y = spr.m_run[(g.run_frame() // 2) % 4], g.py
    cv.blit(m, PX, y - m.shape[0])
    # HUD
    cv.text(f"HI {g.hi:05d}", 1, 1)
    if g.flash <= 0 or int(g.flash * 8) % 2 == 0:
        cv.text(f"{g.score:05d}", W - 20, 1)
    if g.state == "over":
        cv.rect(20, 14, 88, 26, False)
        cv.frame(20, 14, 88, 26)
        cv.center_text("GAME OVER", 18, 2)
        if int(g.t * 2) % 2 == 0:
            cv.center_text("PRESS START", 32)


def draw_oled_splash(cv, g, spr):
    m = np.kron(spr.m_run[int(g.t * 8) % 4], np.ones((2, 2), dtype=bool))
    bob = int(abs(math.sin(g.t * 8)) * 2)
    cv.blit(m, W - m.shape[1] - 6, 14 - bob)
    cv.rect(W - 50, 59, 46, 1)
    for k in range(3):   # ноты
        t = (g.t * 0.5 + k / 3) % 1
        cv.blit(NOTE, W - 56 + k * 4, int(50 - t * 44))
    cv.text("MIKU", 3, 4, 3)
    cv.text("RUNNER", 3, 22, 2)
    if int(g.t * 2) % 2 == 0:
        cv.text("PRESS", 3, 46)
        cv.text("START", 3, 53)
    cv.text(f"HI {g.hi:05d}", 40, 57)


# ============================ ПРОРИСОВКА: ОКНО ПК ============================
def lerp(a, b, t):
    return tuple(int(x + (y - x) * t) for x, y in zip(a, b))


def vgradient(w, h, stops):
    surf = pygame.Surface((w, h))
    n = len(stops) - 1
    for y in range(h):
        p = y / max(1, h - 1) * n
        i = min(int(p), n - 1)
        pygame.draw.line(surf, lerp(stops[i], stops[i + 1], p - i), (0, y), (w, y))
    return surf


def skyline(seed, hmin, hmax, body, window, wprob=0.35):
    rnd = random.Random(seed)
    surf = pygame.Surface((WIN_W, GROUND * S), pygame.SRCALPHA)
    x = 0
    while x < WIN_W:
        w = min(rnd.randrange(48, 120, 8), WIN_W - x)
        h = rnd.randrange(hmin, hmax, 8)
        top = GROUND * S - h
        pygame.draw.rect(surf, body, (x, top, w, h))
        if rnd.random() < 0.3 and w > 56:
            pygame.draw.rect(surf, body, (x + w // 2 - 2, top - 24, 4, 24))
        for wy in range(top + 12, GROUND * S - 8, 16):
            for wx in range(x + 8, x + w - 10, 16):
                if rnd.random() < wprob:
                    pygame.draw.rect(surf, window, (wx, wy, 6, 8))
        x += w + rnd.choice((0, 0, 8, 16))
    return surf


class PCView:
    def __init__(self, spr, video=None):
        self.spr, self.video = spr, video
        gh = GROUND * S
        self.sky = [vgradient(WIN_W, gh, [(255, 232, 242), (205, 240, 244), (160, 232, 232)]),
                    vgradient(WIN_W, gh, [(10, 8, 38), (66, 30, 100), (230, 96, 150)])]
        self.far = [skyline(1, 80, 200, (140, 205, 214), (190, 235, 238), 0.15),
                    skyline(1, 80, 200, (52, 36, 96), (255, 150, 190), 0.22)]
        self.near = [skyline(7, 40, 140, (96, 170, 188), (170, 228, 232), 0.12),
                     skyline(7, 40, 140, (30, 20, 64), (255, 214, 120), 0.3)]
        self.ground = [self._ground((64, 150, 160), (36, 100, 116), (150, 220, 222)),
                       self._ground((26, 22, 56), (14, 12, 36), (96, 70, 150))]
        for lay in (self.far, self.near):
            lay[1].set_alpha(255)
        rnd = random.Random(3)
        self.stars = [(rnd.randrange(WIN_W), rnd.randrange(int(gh * 0.6)), rnd.choice((2, 3, 4)),
                       rnd.random() * 6) for _ in range(70)]
        self.star_layer = pygame.Surface((WIN_W, gh), pygame.SRCALPHA)
        cloud = ["..XXX.....", ".XXXXXX...", "XXXXXXXXXX"]
        self.cloud = pygame.Surface((80, 24), pygame.SRCALPHA)
        for y, row in enumerate(cloud):
            for x, c in enumerate(row):
                if c == "X":
                    pygame.draw.rect(self.cloud, (255, 255, 255, 255), (x * 8, y * 8, 8, 8))
        self.splash_dim = pygame.Surface((WIN_W, WIN_H), pygame.SRCALPHA)
        self.splash_dim.fill((10, 6, 30, 110))
        self.dim = pygame.Surface((WIN_W, WIN_H), pygame.SRCALPHA)
        self.dim.fill((8, 6, 24, 150))
        self.btn = pygame.Rect(0, 0, 320, 84)
        self.btn.center = (800, 330)
        self.gate_btn = pygame.Rect(0, 0, 380, 80)
        self.gate_btn.center = (WIN_W // 2, WIN_H - 62)
        self.gate_bg = vgradient(WIN_W, WIN_H, [(12, 9, 34), (24, 14, 56)])
        self._text_cache = {}

    @staticmethod
    def _ground(c1, c2, spot):
        h = WIN_H - GROUND * S
        surf = vgradient(WIN_W, h, [c1, c2])
        rnd = random.Random(11)
        for _ in range(70):
            pygame.draw.rect(surf, lerp(c2, spot, 0.5),
                             (rnd.randrange(WIN_W), rnd.randrange(14, h - 4), rnd.choice((8, 16, 24)), 4))
        pygame.draw.rect(surf, lerp(c2, (0, 0, 0), 0.5), (0, 0, WIN_W, 6))
        return surf

    # ---- текст пиксельным шрифтом ----
    def text(self, dst, s, x, y, scale, color=(255, 255, 255), shadow=(10, 10, 30), center=False):
        key = (s, scale, color)
        if key not in self._text_cache:
            w = Canvas.text_width(s)
            small = pygame.Surface((max(w, 1), 5), pygame.SRCALPHA)
            cx = 0
            for ch in s.upper():
                g = FONT.get(ch, FONT["?"])
                for yy in range(5):
                    for xx in range(g.shape[1]):
                        if g[yy, xx]:
                            small.set_at((cx + xx, yy), color)
                cx += g.shape[1] + 1
            self._text_cache[key] = pygame.transform.scale(small, (small.get_width() * scale, 5 * scale))
        surf = self._text_cache[key]
        if center:
            x -= surf.get_width() // 2
        if shadow:
            skey = (s, scale, shadow)
            if skey not in self._text_cache:
                self._text_cache[skey] = pygame.mask.from_surface(surf).to_surface(
                    setcolor=shadow + (255,), unsetcolor=(0, 0, 0, 0))
            dst.blit(self._text_cache[skey], (x + max(2, scale // 4), y + max(2, scale // 4)))
        dst.blit(surf, (x, y))

    # ---- фон ----
    def night_level(self, g):
        if g.state == "splash":
            return 1.0
        return (1 - math.cos(2 * math.pi * g.dist * 0.12 / 1400)) / 2

    def background(self, dst, g):
        night = self.night_level(g)
        scroll = g.dist * S if g.state != "splash" else g.t * 40
        dst.blit(self.sky[0], (0, 0))
        if night > 0.01:
            self.sky[1].set_alpha(int(255 * night))
            dst.blit(self.sky[1], (0, 0))
            layer = self.star_layer
            layer.fill((0, 0, 0, 0))
            for x, y, sz, ph in self.stars:
                a = night * (0.55 + 0.45 * math.sin(g.t * 2 + ph))
                pygame.draw.rect(layer, (255, 255, 255, int(255 * a)), (x, y, sz, sz))
            dst.blit(layer, (0, 0))
        # солнце / луна
        body = lerp((255, 160, 175), (238, 240, 255), night)
        mx = 470 if g.state == "splash" else 800
        pygame.draw.circle(dst, body, (mx, 120), 46)
        if night > 0.5:
            pygame.draw.circle(dst, (66, 30, 100), (mx + 22, 108), 38)
        # облака
        self.cloud.set_alpha(int(210 * (1 - night * 0.85)))
        for cx, cy, k in ((100, 70, 0.05), (480, 130, 0.07), (860, 50, 0.04), (300, 40, 0.06)):
            x = (cx - scroll * k) % (WIN_W + 160) - 80
            dst.blit(self.cloud, (x, cy))
        # город (параллакс)
        for lay, k in ((self.far, 0.12), (self.near, 0.3)):
            off = int(scroll * k) % WIN_W
            lay[1].set_alpha(int(255 * night))
            for surf in (lay[0], lay[1]):
                if surf is lay[1] and night < 0.01:
                    continue
                dst.blit(surf, (-off, 0))
                dst.blit(surf, (WIN_W - off, 0))
        off = int(scroll) % WIN_W
        gy = GROUND * S
        dst.blit(self.ground[0], (-off, gy))
        dst.blit(self.ground[0], (WIN_W - off, gy))
        if night > 0.01:
            self.ground[1].set_alpha(int(255 * night))
            dst.blit(self.ground[1], (-off, gy))
            dst.blit(self.ground[1], (WIN_W - off, gy))

    # ---- сцена игры ----
    def draw_game(self, dst, g):
        spr = self.spr
        # тень
        sh = pygame.Surface((150, 20), pygame.SRCALPHA)
        pygame.draw.ellipse(sh, (0, 0, 0, 70), sh.get_rect())
        height_k = max(0.4, 1 - (GROUND - g.py) / 40)
        shs = pygame.transform.scale(sh, (int(150 * height_k), int(20 * height_k)))
        dst.blit(shs, (PX * S + 0.62 * SPR_W * S - shs.get_width() // 2, GROUND * S - 4))
        # пыль
        for x, y, vx, vy, life in g.dust:
            a = max(0, min(255, int(life / 0.4 * 160)))
            d = pygame.Surface((10, 10), pygame.SRCALPHA)
            d.fill((255, 255, 255, a))
            dst.blit(d, (x * S, y * S))
        # ноты
        for x, y, vx, vy, life, pink in g.notes:
            a = max(0, min(255, int(life / 1.1 * 255)))
            col = (255, 120, 170, a) if pink else (80, 220, 210, a)
            for yy in range(6):
                for xx in range(5):
                    if NOTE[yy, xx]:
                        r = pygame.Surface((4, 4), pygame.SRCALPHA)
                        r.fill(col)
                        dst.blit(r, (x * S + xx * 4, y * S + yy * 4))
        # препятствия
        for o in g.obs:
            if o.kind == "leek":
                lw, lh = LEEK_SIZES[o.size]
                img = spr.pc_leek[o.size]
                for i in range(o.n):
                    dst.blit(img, ((o.x + i * (lw + 1)) * S - 4, GROUND * S - img.get_height() + 4))
            else:
                ang = (-14, 0, 14)[int(g.t * 10 + o.phase) % 3]
                img = spr.pc_fly[ang]
                cx, cy = (o.x + o.w / 2) * S, (o.top + o.h / 2) * S
                dst.blit(img, (cx - img.get_width() / 2, cy - img.get_height() / 2))
        # Miku
        if g.state == "over":
            img = spr.pc_idle
        elif g.ducking:
            img = spr.pc_duck
        elif not g.on_ground:
            img = spr.pc_jump
        else:
            img = spr.pc_run[g.run_frame()]
        dst.blit(img, (PX * S, g.py * S - img.get_height() + 2))

    # ---- заставка ----
    def draw_splash(self, dst, g, mouse):
        if True:
            self.background(dst, g)
            dst.blit(self.splash_dim, (0, 0))
            for k in range(7):   # плавающие ноты
                t = (g.t * 0.12 + k / 7) % 1
                x = 60 + k * 140 + math.sin(g.t + k) * 20
                y = 480 - t * 520
                for yy in range(6):
                    for xx in range(5):
                        if NOTE[yy, xx]:
                            pygame.draw.rect(dst, (255, 140, 190) if k % 2 else (90, 230, 215),
                                             (x + xx * 6, y + yy * 6, 6, 6))
        spr = self.spr
        i = spr.sing_meta["order"][int(g.t * 1000 / spr.sing_meta["ms"]) % len(spr.sing_meta["order"])]
        img = spr.pc_sing(i)
        dst.blit(img, (10, 150))
        bounce = int(math.sin(g.t * 3) * 4)
        self.text(dst, "MIKU", 800, 60 + bounce, 18, (90, 235, 220), (255, 90, 150), center=True)
        self.text(dst, "RUNNER", 800, 170 + bounce, 11, (255, 255, 255), (255, 90, 150), center=True)
        hover = self.btn.collidepoint(mouse)
        pulse = 1.0 + 0.04 * math.sin(g.t * 5)
        r = self.btn.inflate(int(self.btn.w * (pulse - 1) + (14 if hover else 0)), int(self.btn.h * (pulse - 1) + (8 if hover else 0)))
        pygame.draw.rect(dst, (30, 10, 50), r.move(6, 6))
        pygame.draw.rect(dst, (255, 110, 170) if hover else (240, 80, 140), r)
        pygame.draw.rect(dst, (255, 230, 240), r, 4)
        self.text(dst, "START", r.centerx, r.centery - 20, 8, (255, 255, 255), (150, 20, 80), center=True)
        self.text(dst, "BUTTON / SPACE", 800, 400, 4, (230, 230, 255), (10, 10, 40), center=True)
        self.text(dst, f"HI {g.hi:05d}", 800, 440, 5, (255, 220, 120), (10, 10, 40), center=True)

    def draw_hud(self, dst, g):
        if g.state in ("gate", "splash"):
            return
        self.text(dst, f"HI {g.hi:05d}", 24, 20, 5, (170, 170, 200))
        if g.flash <= 0 or int(g.flash * 8) % 2 == 0:
            self.text(dst, f"{g.score:05d}", 330, 20, 5, (255, 255, 255))

    def draw_over(self, dst, g):
        dst.blit(self.dim, (0, 0))
        dst.blit(self.spr.pc_chibi, (110, 70))
        self.text(dst, "GAME OVER", 640, 90, 10, (255, 255, 255), (240, 80, 140), center=True)
        self.text(dst, f"SCORE {g.score:05d}", 640, 215, 6, (90, 235, 220), center=True)
        self.text(dst, f"BEST  {g.hi:05d}", 640, 275, 6, (255, 220, 120), center=True)
        if int(g.t * 2) % 2 == 0:
            self.text(dst, "PRESS START", 640, 370, 6, (255, 255, 255), (240, 80, 140), center=True)

    def draw_gate(self, dst, g, mouse):
        if self.video:
            dst.blit(self.video.frame(g.snd.intro_time()), (0, 0))
        else:
            dst.blit(self.gate_bg, (0, 0))
        hover = self.gate_btn.collidepoint(mouse)
        r = self.gate_btn.inflate(14 if hover else 0, 8 if hover else 0)
        pygame.draw.rect(dst, (8, 30, 48), r.move(6, 6))
        pygame.draw.rect(dst, (90, 235, 220) if hover else (57, 197, 187), r)
        pygame.draw.rect(dst, (8, 30, 48), r, 4)
        self.text(dst, "OPEN GAME", r.centerx, r.centery - 12, 5, (255, 255, 255), (8, 70, 90), center=True)

    def draw(self, dst, g, mouse):
        if g.state == "gate":
            self.draw_gate(dst, g, mouse)
            return
        if g.state == "splash":
            self.draw_splash(dst, g, mouse)
            return
        self.background(dst, g)
        self.draw_game(dst, g)
        self.draw_hud(dst, g)
        if g.state == "over":
            self.draw_over(dst, g)


class VideoBG:
    """Видео первого экрана (assets/splash.mp4). Кадр выбирается по времени t (в секундах)."""

    def __init__(self, path):
        import cv2
        self.cv2 = cv2
        self.cap = cv2.VideoCapture(path)
        self.ok = self.cap.isOpened()
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30
        self.count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        self.n = 0          # сколько кадров уже прочитано
        self.surf = pygame.Surface((WIN_W, WIN_H))

    def frame(self, t):
        want = int(t * self.fps)
        if self.count:
            want = min(want, self.count - 1)
        if want < self.n - 1 or want > self.n + 90:      # зациклилось или рывок — перемотка
            self.cap.set(self.cv2.CAP_PROP_POS_FRAMES, want)
            self.n = want
        img = None
        while self.n <= want and self.ok:
            if self.n < want:
                self.cap.grab()
                self.n += 1
                continue
            ok, img = self.cap.read()
            self.n += 1
            if not ok:
                img = None
            break
        if img is not None:
            h, w = img.shape[:2]
            k = max(WIN_W / w, WIN_H / h)
            img = self.cv2.resize(img, (int(w * k) + 1, int(h * k) + 1))
            y0, x0 = (img.shape[0] - WIN_H) // 2, (img.shape[1] - WIN_W) // 2
            img = self.cv2.cvtColor(img[y0:y0 + WIN_H, x0:x0 + WIN_W], self.cv2.COLOR_BGR2RGB)
            self.surf = pygame.image.frombuffer(img.tobytes(), (WIN_W, WIN_H), "RGB")
        return self.surf


# ============================ MAIN ============================
def main():
    global BAUD, OLED_FPS, FLIP_JOY_Y, FLIP_OLED
    ap = argparse.ArgumentParser(description="Miku Runner")
    ap.add_argument("--port", help="порт Arduino, например COM5 или /dev/cu.usbserial-1410")
    ap.add_argument("--no-serial", action="store_true", help="играть без Arduino")
    ap.add_argument("--baud", type=int, default=BAUD)
    ap.add_argument("--oled-fps", type=float, default=OLED_FPS)
    ap.add_argument("--flip-y", action="store_true", help="поменять местами вверх/вниз на джойстике")
    ap.add_argument("--flip-oled", action="store_true", help="повернуть картинку на OLED на 180°")
    ap.add_argument("--no-video", action="store_true")
    ap.add_argument("--bot", action="store_true", help="(тест) играет сам")
    ap.add_argument("--shots", help="(тест) папка для скриншотов, работает вместе с --bot")
    args = ap.parse_args()
    BAUD, OLED_FPS = args.baud, args.oled_fps
    FLIP_JOY_Y, FLIP_OLED = args.flip_y, args.flip_oled

    pygame.mixer.pre_init(44100, -16, 2, 512)
    pygame.init()
    flags = 0
    screen = pygame.display.set_mode((WIN_W, WIN_H + BAR), flags)
    pygame.display.set_caption("Miku Runner")
    font = pygame.font.SysFont("menlo,consolas,dejavusansmono", 14)

    link = None
    if not args.no_serial and not args.bot:
        if serial is None:
            print("pyserial не установлен: pip install pyserial — играем с клавиатуры")
        else:
            link = ArduinoLink(args.port, args.baud)

    spr = Sprites()
    video = None
    vp = os.path.join(ASSETS, "splash.mp4")
    if os.path.exists(vp) and not args.no_video:
        try:
            video = VideoBG(vp)
            if not video.ok:
                video = None
        except ImportError:
            print("Для видео-фона нужен opencv: python -m pip install opencv-python")
            video = None
    view = PCView(spr, video)
    snd = Sounds()
    snd.intro_on()
    game = Game(snd)
    inp = Input(link)
    cv = Canvas()
    scene = pygame.Surface((WIN_W, WIN_H))
    clock = pygame.time.Clock()
    last_oled, fps_t, fps_n, oled_fps = 0.0, time.time(), 0, 0.0
    show_oled, fullscreen = True, False
    frame_no = 0
    shots_at = {60: "splash", 200: "play1", 700: "play2", 1500: "play3"}

    running = True
    while running:
        dt = min(clock.tick(60) / 1000.0, 0.05)
        if args.bot:
            dt = 1 / 60
        events = pygame.event.get()
        for e in events:
            if e.type == pygame.QUIT:
                running = False
            elif e.type == pygame.KEYDOWN:
                if e.key == pygame.K_ESCAPE:
                    running = False
                elif e.key == pygame.K_TAB:
                    show_oled = not show_oled
                elif e.key == pygame.K_m:
                    snd.toggle_mute()
                elif e.key == pygame.K_f:
                    fullscreen = not fullscreen
                    pygame.display.set_mode((WIN_W, WIN_H + BAR), pygame.FULLSCREEN | pygame.SCALED if fullscreen else 0)
        inp.update(events)
        btn = view.gate_btn if game.state == "gate" else view.btn
        if inp.click and not btn.collidepoint(inp.click):
            inp.click = None
        if args.bot:
            game.bot(inp)
            if game.state == "splash" and frame_no < 120:
                inp.jump_pressed = False
        game.update(dt, inp)
        draw_oled(cv, game, spr)

        # --- на OLED ---
        now = time.time()
        if link and now - last_oled >= 1.0 / OLED_FPS:
            if link.try_send_frame(pack_ssd1306(cv.px)):
                last_oled = now
                fps_n += 1
        if now - fps_t >= 1.0:
            oled_fps, fps_n, fps_t = fps_n / (now - fps_t), 0, now

        # --- в окно ---
        view.draw(scene, game, pygame.mouse.get_pos())
        screen.blit(scene, (0, 0))
        if show_oled and game.state not in ("gate", "splash"):
            rgb = np.where(cv.px[..., None], (57, 197, 187), (8, 10, 14)).astype(np.uint8)
            surf = pygame.surfarray.make_surface(rgb.swapaxes(0, 1))
            surf = pygame.transform.scale(surf, (256, 128))
            ix = WIN_W - 272
            pygame.draw.rect(screen, (255, 255, 255), (ix, 8, 264, 136), border_radius=6)
            screen.blit(surf, (ix + 4, 12))
        pygame.draw.rect(screen, (14, 14, 24), (0, WIN_H, WIN_W, BAR))
        if link:
            status = link.status
            if inp.raw:
                status += f"   X={inp.raw[0]} Y={inp.raw[1]} кнопка={inp.raw[2]}"
            status += f"   OLED {oled_fps:.1f} fps"
        else:
            status = "без Arduino: Пробел/↑ — прыжок, ↓ — пригнуться, TAB — OLED, M — звук, F — экран"
        screen.blit(font.render(status, True, (170, 170, 190)), (10, WIN_H + 6))
        pygame.display.flip()

        frame_no += 1
        if args.shots and frame_no in shots_at:
            os.makedirs(args.shots, exist_ok=True)
            pygame.image.save(screen, os.path.join(args.shots, f"pc_{shots_at[frame_no]}.png"))
            Image.fromarray((cv.px * 255).astype(np.uint8)).resize((512, 256), Image.NEAREST).save(
                os.path.join(args.shots, f"oled_{shots_at[frame_no]}.png"))
        if args.bot and frame_no > (1600 if args.shots else 3000):
            print(f"бот: счёт {game.score}, рекорд {game.hi}, состояние {game.state}")
            running = False

    pygame.quit()


if __name__ == "__main__":
    main()
