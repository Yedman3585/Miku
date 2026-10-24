"""
Miku Breakout — арканоид на ПК, управление джойстиком на Arduino,
картинка дублируется на OLED 128x64 (по умолчанию 5 кадров/с).

Запуск:
    python miku_game.py                 # порт Arduino ищется автоматически
    python miku_game.py --port COM5     # указать порт вручную
    python miku_game.py --no-serial     # без Arduino, только клавиатура

Управление:
    джойстик влево/вправо, кнопка джойстика (или наклон вверх/вниз) — старт/запуск мяча
    клавиатура: ←/→ или A/D, Пробел/Enter — старт, P — пауза, Esc — выход
"""
import argparse
import math
import os
import random
import threading
import time

import numpy as np
import pygame

try:
    import serial
    from serial.tools import list_ports
except ImportError:  # pyserial не установлен — играем с клавиатуры
    serial = None

# ============================ НАСТРОЙКИ ============================
BAUD = 115200
OLED_FPS = 5              # сколько кадров в секунду слать на OLED
FLIP_OLED = False         # True, если картинка на OLED вверх ногами
INVERT_JOY_X = False      # True, если ракетка едет в обратную сторону
DEADZONE = 0.15           # "мёртвая зона" джойстика
WINDOW_SCALE = 6          # во сколько раз увеличить окно на ПК
OLED_ON = (57, 197, 187)  # цвет "горящего" пикселя в окне (бирюзовый)
OLED_OFF = (8, 10, 14)

HERE = os.path.dirname(os.path.abspath(__file__))
SPLASH_FILE = os.path.join(HERE, "splash.npz")
SPLASH_AUDIO = [os.path.join(HERE, n) for n in ("splash.mp3", "splash.ogg", "splash.wav")]
HISCORE_FILE = os.path.join(HERE, "highscore.txt")

W, H = 128, 64

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
    "?": "111001011000010",
}
FONT = {k: np.array([c == "1" for c in v], dtype=bool).reshape(5, 3)
        for k, v in _GLYPHS.items()}
HEART = np.array([[c == "1" for c in r] for r in
                  ("01010", "11111", "11111", "01110", "00100")], dtype=bool)


class Canvas:
    """Чёрно-белый холст 128x64 — ровно то, что покажет OLED."""

    def __init__(self):
        self.px = np.zeros((H, W), dtype=bool)

    def clear(self):
        self.px[:] = False

    def rect(self, x, y, w, h, on=True):
        x, y = int(round(x)), int(round(y))
        x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + w, W), min(y + h, H)
        if x1 > x0 and y1 > y0:
            self.px[y0:y1, x0:x1] = on

    def frame(self, x, y, w, h):
        self.rect(x, y, w, 1)
        self.rect(x, y + h - 1, w, 1)
        self.rect(x, y, 1, h)
        self.rect(x + w - 1, y, 1, h)

    def blit(self, mask, x, y, on=True):
        mh, mw = mask.shape
        x0, y0 = max(x, 0), max(y, 0)
        x1, y1 = min(x + mw, W), min(y + mh, H)
        if x1 <= x0 or y1 <= y0:
            return
        sub = mask[y0 - y:y1 - y, x0 - x:x1 - x]
        region = self.px[y0:y1, x0:x1]
        region[sub] = on

    @staticmethod
    def text_width(s, scale=1):
        return max(len(s) * 4 * scale - scale, 0)

    def text(self, s, x, y, scale=1, on=True):
        for ch in s.upper():
            g = FONT.get(ch, FONT["?"])
            if scale > 1:
                g = np.kron(g, np.ones((scale, scale), dtype=bool))
            self.blit(g, x, y, on)
            x += 4 * scale

    def center_text(self, s, y, scale=1, on=True):
        self.text(s, (W - self.text_width(s, scale)) // 2, y, scale, on)


_WEIGHTS = (1 << np.arange(8, dtype=np.uint16)).reshape(1, 8, 1)


def pack_ssd1306(px):
    """bool[64,128] -> 1024 байта в формате буфера SSD1306 (8 страниц по 128 столбцов)."""
    if FLIP_OLED:
        px = px[::-1, ::-1]
    pages = px.reshape(8, 8, W).astype(np.uint16)          # страница, бит, x
    return (pages * _WEIGHTS).sum(axis=1).astype(np.uint8).tobytes()


# ============================ СВЯЗЬ С ARDUINO ============================
class ArduinoLink:
    KNOWN_VIDS = {0x2341, 0x2A03, 0x1A86, 0x0403, 0x10C4, 0x1B4F, 0x239A}

    def __init__(self, port=None):
        self.port_arg = port
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
            if any(k in d for k in ("arduino", "ch340", "usb-serial", "usb serial")):
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
                    self.ser = serial.Serial(port, BAUD, timeout=0.1)
                except Exception as e:
                    self.status = f"{port}: не открывается ({e})"
                    self.ser = None
                    time.sleep(2)
                    continue
                self.port = port
                self.status = f"{port}: ждём Arduino..."
                self._ready = False
                # если "R" потеряется, через ~3 с всё равно начнём слать кадры
                self._sent_at = time.time() + 2.5
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
        self.axis = 0.0
        self.action = False
        self.raw = None

    @staticmethod
    def _norm(v, c):
        a = max(-1.0, min(1.0, (v - c) / 512.0))
        if abs(a) < DEADZONE:
            return 0.0
        return math.copysign((abs(a) - DEADZONE) / (1 - DEADZONE), a)

    def update(self, events):
        keys = pygame.key.get_pressed()
        ax = float((keys[pygame.K_RIGHT] or keys[pygame.K_d])
                   - (keys[pygame.K_LEFT] or keys[pygame.K_a]))
        act = any(e.type == pygame.KEYDOWN and e.key in (pygame.K_SPACE, pygame.K_RETURN)
                  for e in events)
        jact = False
        if self.link and self.link.have_joy:
            x, y, b = self.link.joystick()
            self.raw = (x, y, b)
            if self.cx is None:  # калибровка центра по первому значению
                self.cx = x if 300 < x < 724 else 512
                self.cy = y if 300 < y < 724 else 512
            jx = self._norm(x, self.cx) * (-1 if INVERT_JOY_X else 1)
            jy = self._norm(y, self.cy)
            if abs(jx) > abs(ax):
                ax = jx
            jact = bool(b) or abs(jy) > 0.75
        self.axis = ax
        self.action = act or (jact and not self.prev_jact)
        self.prev_jact = jact


# ============================ ЗВУК ============================
class Sounds:
    def __init__(self):
        self.ok = False
        self.music = next((p for p in SPLASH_AUDIO if os.path.exists(p)), None)
        try:
            pygame.mixer.init()
            sr, _, ch = pygame.mixer.get_init()
            self.ok = True
        except Exception:
            return
        self.s = {
            "paddle": self._beep(sr, ch, 660, 40),
            "brick": self._beep(sr, ch, 990, 35),
            "wall": self._beep(sr, ch, 440, 25),
            "lose": self._beep(sr, ch, 160, 300),
            "level": self._beep(sr, ch, 1320, 200),
        }

    @staticmethod
    def _beep(sr, ch, freq, ms, vol=0.25):
        n = int(sr * ms / 1000)
        t = np.arange(n) / sr
        wave = np.sign(np.sin(2 * np.pi * freq * t)) * np.linspace(1, 0, n)
        wave = (wave * vol * 32767).astype(np.int16)
        if ch > 1:
            wave = np.repeat(wave[:, None], ch, axis=1)
        return pygame.sndarray.make_sound(np.ascontiguousarray(wave))

    def play(self, name):
        if self.ok:
            self.s[name].play()

    def music_on(self):
        if self.ok and self.music and not pygame.mixer.music.get_busy():
            try:
                pygame.mixer.music.load(self.music)
                pygame.mixer.music.play(-1)
            except Exception:
                self.music = None

    def music_off(self):
        if self.ok and self.music:
            pygame.mixer.music.fadeout(500)


# ============================ ЗАСТАВКА ============================
def load_splash():
    if not os.path.exists(SPLASH_FILE):
        return None, 5
    data = np.load(SPLASH_FILE)
    frames = np.unpackbits(data["frames"], axis=-1)[..., :W].astype(bool)
    return frames, int(data["fps"])


# ============================ ИГРА ============================
LEVELS = [
    ["111111111111",
     "111111111111",
     "111111111111",
     "111111111111"],
    ["222222222222",
     "111111111111",
     "1.1.1.1.1.1.",
     ".1.1.1.1.1.1",
     "111111111111"],
    [".....22.....",
     "....1111....",
     "...222222...",
     "..11111111..",
     ".2222222222."],
]


class Game:
    TOP = 8                      # под строкой счёта
    PADDLE_W, PADDLE_H, PADDLE_Y = 18, 2, 59
    PADDLE_SPEED = 110.0
    BALL = 2
    BR_COLS, BR_W, BR_H, BR_X0, BR_Y0 = 12, 9, 3, 4, 10

    def __init__(self, splash, splash_fps, sounds):
        self.splash, self.splash_fps, self.snd = splash, splash_fps, sounds
        self.hiscore = self._load_hi()
        self.t = 0.0
        self.to_splash()

    # ---------- состояние ----------
    def _load_hi(self):
        try:
            with open(HISCORE_FILE) as f:
                return int(f.read().strip())
        except Exception:
            return 0

    def _save_hi(self):
        try:
            with open(HISCORE_FILE, "w") as f:
                f.write(str(self.hiscore))
        except Exception:
            pass

    def to_splash(self):
        self.state, self.state_t = "splash", 0.0
        self.snd.music_on()

    def new_game(self):
        self.snd.music_off()
        self.score, self.lives, self.level = 0, 3, 1
        self.paddle_x = (W - self.PADDLE_W) / 2
        self.load_level()
        self.state, self.state_t = "level", 0.0

    def load_level(self):
        if self.level <= len(LEVELS):
            rows = LEVELS[self.level - 1]
        else:
            rnd = random.Random(self.level)
            p2 = min(0.15 + 0.05 * self.level, 0.6)
            rows = ["".join("." if rnd.random() < 0.25 else ("2" if rnd.random() < p2 else "1")
                            for _ in range(self.BR_COLS)) for _ in range(5)]
        self.bricks = []
        for r, row in enumerate(rows):
            for c, ch in enumerate(row):
                if ch in "12":
                    x = self.BR_X0 + c * (self.BR_W + 1)
                    y = self.BR_Y0 + r * (self.BR_H + 1)
                    self.bricks.append([x, y, int(ch)])
        self.base_speed = 55.0 + 8.0 * (self.level - 1)

    def serve(self):
        self.state = "serve"
        self.speed = self.base_speed
        self._ball_on_paddle()

    def _ball_on_paddle(self):
        self.bx = self.paddle_x + self.PADDLE_W / 2 - self.BALL / 2
        self.by = self.PADDLE_Y - self.BALL

    def launch(self):
        ang = math.radians(random.uniform(-30, 30))
        self.vx, self.vy = self.speed * math.sin(ang), -self.speed * math.cos(ang)
        self.state = "play"

    # ---------- обновление ----------
    def update(self, dt, inp):
        self.t += dt
        self.state_t += dt
        st = self.state
        if st == "splash":
            if inp.action:
                self.new_game()
        elif st == "level":
            if self.state_t > 2.0 or (inp.action and self.state_t > 0.3):
                self.serve()
        elif st == "over":
            if (inp.action and self.state_t > 1.0) or self.state_t > 10:
                self.to_splash()
        elif st == "pause":
            if inp.action:
                self.state = self.paused_from
        elif st in ("serve", "play"):
            self._move_paddle(dt, inp.axis)
            if st == "serve":
                self._ball_on_paddle()
                if inp.action:
                    self.launch()
            else:
                self._step_ball(dt)

    def toggle_pause(self):
        if self.state in ("serve", "play"):
            self.paused_from, self.state = self.state, "pause"
        elif self.state == "pause":
            self.state = self.paused_from

    def _move_paddle(self, dt, axis):
        self.paddle_x += axis * self.PADDLE_SPEED * dt
        self.paddle_x = max(0.0, min(W - self.PADDLE_W, self.paddle_x))

    def _set_speed(self, s):
        k = s / max(math.hypot(self.vx, self.vy), 1e-6)
        self.speed, self.vx, self.vy = s, self.vx * k, self.vy * k

    def _step_ball(self, dt):
        B = self.BALL
        steps = max(1, int(math.ceil(self.speed * dt)))   # не больше 1 пикселя за шаг
        sdt = dt / steps
        for _ in range(steps):
            px, py = self.bx, self.by
            self.bx += self.vx * sdt
            self.by += self.vy * sdt

            if self.bx < 0:
                self.bx, self.vx = 0, abs(self.vx); self.snd.play("wall")
            elif self.bx > W - B:
                self.bx, self.vx = W - B, -abs(self.vx); self.snd.play("wall")
            if self.by < self.TOP:
                self.by, self.vy = self.TOP, abs(self.vy); self.snd.play("wall")

            # ракетка
            if (self.vy > 0 and self.by + B > self.PADDLE_Y and self.by < self.PADDLE_Y + self.PADDLE_H
                    and self.bx + B > self.paddle_x and self.bx < self.paddle_x + self.PADDLE_W):
                half = self.PADDLE_W / 2 + B / 2
                off = ((self.bx + B / 2) - (self.paddle_x + self.PADDLE_W / 2)) / half
                # +небольшой разброс, чтобы мяч не застревал в строго вертикальном полёте
                ang = max(-1.0, min(1.0, off)) * math.radians(60) + math.radians(random.uniform(-8, 8))
                self.vx, self.vy = self.speed * math.sin(ang), -self.speed * math.cos(ang)
                self.by = self.PADDLE_Y - B
                self.snd.play("paddle")

            # кирпичи
            for br in self.bricks:
                x, y, _ = br
                if self.bx + B > x and self.bx < x + self.BR_W and self.by + B > y and self.by < y + self.BR_H:
                    if py + B <= y or py >= y + self.BR_H:
                        self.vy = -self.vy
                    else:
                        self.vx = -self.vx
                    self.bx, self.by = px, py
                    br[2] -= 1
                    if br[2] <= 0:
                        self.bricks.remove(br)
                        self.score += 10 * self.level
                    else:
                        self.score += 5
                    self._set_speed(min(self.speed * 1.01, self.base_speed * 1.8))
                    self.snd.play("brick")
                    break

            if not self.bricks:
                self.level += 1
                self.load_level()
                self.state, self.state_t = "level", 0.0
                self.snd.play("level")
                return

            if self.by > H:
                self.lives -= 1
                self.snd.play("lose")
                if self.lives <= 0:
                    if self.score > self.hiscore:
                        self.hiscore = self.score
                        self._save_hi()
                    self.state, self.state_t = "over", 0.0
                else:
                    self.serve()
                return

    # ---------- рисование ----------
    def blink(self, period=0.8):
        return (self.t % period) < period * 0.6

    def draw(self, cv):
        cv.clear()
        st = self.state
        if st == "splash":
            self._draw_splash(cv)
            return
        if st == "over":
            cv.center_text("GAME OVER", 10, 2)
            cv.center_text(f"SCORE {self.score}", 32)
            cv.center_text(f"HI {self.hiscore}", 40)
            if self.blink():
                cv.center_text("PRESS START", 54)
            return
        if st == "level":
            cv.center_text(f"LEVEL {self.level}", 18, 2)
            cv.center_text("GET READY", 40)
            return

        # HUD
        cv.text(str(self.score), 0, 1)
        cv.center_text(f"L{self.level}", 1)
        for i in range(self.lives):
            cv.blit(HEART, W - 6 * (i + 1), 1)
        cv.rect(0, 7, W, 1)
        # кирпичи: двойные — залитые, одинарные — контуром
        for x, y, hp in self.bricks:
            if hp >= 2:
                cv.rect(x, y, self.BR_W, self.BR_H)
            else:
                cv.frame(x, y, self.BR_W, self.BR_H)
        cv.rect(self.paddle_x, self.PADDLE_Y, self.PADDLE_W, self.PADDLE_H)
        cv.rect(self.bx, self.by, self.BALL, self.BALL)

        if st == "serve" and self.blink():
            cv.center_text("PRESS START", 44)
        if st == "pause":
            cv.rect(36, 26, 56, 13, False)
            cv.frame(36, 26, 56, 13)
            cv.center_text("PAUSE", 30)

    def _draw_splash(self, cv):
        if self.splash is not None and len(self.splash):
            i = int(self.state_t * self.splash_fps) % len(self.splash)
            cv.px[:] = self.splash[i]
            if self.blink(1.2):
                cv.rect(0, 56, W, 8, False)
                cv.center_text("PRESS START", 57)
        else:
            cv.center_text("MIKU", 6, 3)
            cv.center_text("BREAKOUT", 26, 2)
            if self.blink():
                cv.center_text("PRESS START", 50)
            cv.center_text("NO SPLASH.NPZ", 58)


# ============================ MAIN ============================
def main():
    ap = argparse.ArgumentParser(description="Miku Breakout")
    ap.add_argument("--port", help="COM-порт Arduino, например COM5")
    ap.add_argument("--no-serial", action="store_true", help="играть без Arduino")
    args = ap.parse_args()

    pygame.init()
    S = WINDOW_SCALE
    screen = pygame.display.set_mode((W * S, H * S + 28))
    pygame.display.set_caption("Miku Breakout")
    font = pygame.font.SysFont("consolas", 16)

    link = None
    if not args.no_serial:
        if serial is None:
            print("pyserial не установлен: pip install pyserial — играем с клавиатуры")
        else:
            link = ArduinoLink(args.port)

    splash, splash_fps = load_splash()
    game = Game(splash, splash_fps, Sounds())
    inp = Input(link)
    cv = Canvas()
    clock = pygame.time.Clock()
    last_oled = 0.0
    fps_t, fps_n, oled_fps = time.time(), 0, 0.0

    running = True
    while running:
        dt = min(clock.tick(60) / 1000.0, 0.05)
        events = pygame.event.get()
        for e in events:
            if e.type == pygame.QUIT:
                running = False
            elif e.type == pygame.KEYDOWN:
                if e.key == pygame.K_ESCAPE:
                    running = False
                elif e.key == pygame.K_p:
                    game.toggle_pause()

        inp.update(events)
        game.update(dt, inp)
        game.draw(cv)

        # --- на OLED ---
        now = time.time()
        if link and now - last_oled >= 1.0 / OLED_FPS:
            if link.try_send_frame(pack_ssd1306(cv.px)):
                last_oled = now
                fps_n += 1
        if now - fps_t >= 1.0:
            oled_fps, fps_n, fps_t = fps_n / (now - fps_t), 0, now

        # --- в окно ---
        rgb = np.where(cv.px[..., None], OLED_ON, OLED_OFF).astype(np.uint8)
        surf = pygame.surfarray.make_surface(rgb.swapaxes(0, 1))
        screen.fill((0, 0, 0))
        screen.blit(pygame.transform.scale(surf, (W * S, H * S)), (0, 0))
        if link:
            status = link.status
            if inp.raw:
                status += f"   джойстик X={inp.raw[0]} Y={inp.raw[1]} кнопка={inp.raw[2]}"
            status += f"   OLED {oled_fps:.1f} fps"
        else:
            status = "без Arduino: ←/→, Пробел, P — пауза, Esc — выход"
        screen.blit(font.render(status, True, (170, 170, 170)), (8, H * S + 5))
        pygame.display.flip()

    pygame.quit()


if __name__ == "__main__":
    main()
