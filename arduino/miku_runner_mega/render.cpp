// Отрисовка на шилд 3.2" 480x320 (MCUFRIEND_kbv). Фон не хранится в памяти:
// "стирание" = перерисовка кусочка фона из формул (градиент неба + силуэты города + земля).
#include <Arduino.h>
#include <MCUFRIEND_kbv.h>
#include <avr/pgmspace.h>
#include "config.h"
#include "render.h"
#include "sprites.h"

static MCUFRIEND_kbv tft;

#define GROUND_PX   ((int16_t)(GROUND * UNIT_PX))   // 273
#define BAND_H      32
#define NBANDS      ((GROUND_PX + BAND_H - 1) / BAND_H)

static inline int16_t U(float u) { return (int16_t)(u * UNIT_PX + 0.5f); }
static uint16_t C(uint8_t r, uint8_t g, uint8_t b) { return tft.color565(r, g, b); }

// ---------- фон ----------
static uint16_t skyBand(uint8_t b) {            // фиолетовое ночное небо -> розовый горизонт
  uint32_t t = (uint32_t)b * 255 / (NBANDS - 1);    // (на AVR int 16-битный — считаем в 32 битах)
  return C(12 + (uint8_t)(110UL * t / 255), 8 + (uint8_t)(60UL * t / 255), 38 + (uint8_t)(100UL * t / 255));
}

struct Bld { int16_t x, w, h; };
static const Bld BUILDINGS[] PROGMEM = {
  {0, 52, 120}, {58, 40, 80}, {104, 60, 150}, {170, 44, 96}, {220, 56, 130}, {282, 40, 70},
  {328, 62, 160}, {396, 36, 100}, {438, 42, 126},
};
#define NBLD (sizeof(BUILDINGS) / sizeof(BUILDINGS[0]))

static void fillClip(int16_t x, int16_t y, int16_t w, int16_t h, uint16_t col) {
  if (x < 0) { w += x; x = 0; }
  if (y < 0) { h += y; y = 0; }
  if (x + w > SCREEN_W) w = SCREEN_W - x;
  if (y + h > SCREEN_H) h = SCREEN_H - y;
  if (w > 0 && h > 0) tft.fillRect(x, y, w, h, col);
}

// Перерисовать фон в прямоугольнике (x,y,w,h)
static void paintBg(int16_t x, int16_t y, int16_t w, int16_t h) {
  if (x < 0) { w += x; x = 0; }
  if (y < 0) { h += y; y = 0; }
  if (x + w > SCREEN_W) w = SCREEN_W - x;
  if (y + h > SCREEN_H) h = SCREEN_H - y;
  if (w <= 0 || h <= 0) return;
  int16_t y1 = y + h;
  for (uint8_t b = 0; b < NBANDS; b++) {                       // небо
    int16_t by0 = b * BAND_H, by1 = min((int16_t)(by0 + BAND_H), GROUND_PX);
    int16_t ya = max(y, by0), yb = min(y1, by1);
    if (yb > ya) tft.fillRect(x, ya, w, yb - ya, skyBand(b));
  }
  for (uint8_t i = 0; i < NBLD; i++) {                         // город
    Bld b; memcpy_P(&b, &BUILDINGS[i], sizeof(Bld));
    int16_t bx0 = max(x, b.x), bx1 = min((int16_t)(x + w), (int16_t)(b.x + b.w));
    int16_t by0 = max(y, (int16_t)(GROUND_PX - b.h)), by1 = min(y1, GROUND_PX);
    if (bx1 > bx0 && by1 > by0) tft.fillRect(bx0, by0, bx1 - bx0, by1 - by0, (i & 1) ? C(40, 28, 84) : C(30, 20, 66));
  }
  if (y1 > GROUND_PX) {                                        // земля
    int16_t ya = max(y, GROUND_PX);
    tft.fillRect(x, ya, w, y1 - ya, C(20, 40, 56));
    if (ya == GROUND_PX) tft.fillRect(x, GROUND_PX, w, 3, C(8, 16, 24));
  }
}

// ---------- спрайты с прозрачностью (по строкам, сериями непрозрачных пикселей) ----------
static void blit(const Sprite& s, int16_t x, int16_t y) {
  for (uint16_t r = 0; r < s.h; r++) {
    int16_t yy = y + r;
    if (yy < 0 || yy >= SCREEN_H) continue;
    const uint16_t* row = s.px + (uint32_t)r * s.w;
    uint16_t c = 0;
    while (c < s.w) {
      while (c < s.w && pgm_read_word(row + c) == SPRITE_KEY) c++;
      uint16_t c0 = c;
      while (c < s.w && pgm_read_word(row + c) != SPRITE_KEY) c++;
      if (c > c0) {
        int16_t xx = x + c0, n = c - c0;
        if (xx < 0 || xx + n > SCREEN_W) continue;
        tft.setAddrWindow(xx, yy, xx + n - 1, yy);
        tft.pushColors((const uint8_t*)(row + c0), n, true, false);   // из PROGMEM
      }
    }
  }
}

// ---------- что нарисовано в прошлом кадре (чтобы стереть) ----------
struct Box { int16_t x, y, w, h; bool on; };
static Box prevPlayer, prevObs[MAX_OBS], prevDash[10];
static uint16_t lastScore = 0xFFFF, lastHi = 0xFFFF;

static void eraseBox(Box& b) { if (b.on) { paintBg(b.x, b.y, b.w, b.h); b.on = false; } }

static void hud(const Game& g) {
  tft.setTextSize(3);
  tft.setTextColor(0xFFFF, skyBand(0));
  char buf[20];
  if (g.hi != lastHi) { snprintf(buf, sizeof buf, "HI %05u", g.hi); tft.setCursor(12, 8); tft.print(buf); lastHi = g.hi; }
  if (g.score != lastScore) { snprintf(buf, sizeof buf, "%05u", g.score); tft.setCursor(300, 8); tft.print(buf); lastScore = g.score; }
}

void renderResetScene() {
  paintBg(0, 0, SCREEN_W, SCREEN_H);
  prevPlayer.on = false;
  for (auto& b : prevObs) b.on = false;
  for (auto& b : prevDash) b.on = false;
  lastScore = lastHi = 0xFFFF;
}

void renderInit() {
  tft.reset();
  uint16_t id = tft.readID();
  tft.begin(id);
  tft.setRotation(LCD_ROTATION);
  Serial.print(F("LCD id=0x")); Serial.println(id, HEX);
  renderResetScene();
}

void renderSplash() {
  renderResetScene();
  tft.setTextSize(8);  tft.setTextColor(C(90, 235, 220));
  tft.setCursor(40, 70);  tft.print(F("MIKU"));
  tft.setTextColor(0xFFFF);
  tft.setCursor(40, 140); tft.print(F("RUNNER"));
  tft.setTextSize(3);     tft.setTextColor(C(255, 110, 170));
  tft.setCursor(40, 230); tft.print(F("PRESS JUMP"));
  blit(spr_idle, 330, GROUND_PX - spr_idle.h);
}

void renderGameOverBox(const Game& g) {
  tft.fillRect(90, 70, 300, 120, C(12, 8, 38));
  tft.drawRect(90, 70, 300, 120, 0xFFFF);
  tft.setTextSize(4); tft.setTextColor(C(255, 110, 170), C(12, 8, 38));
  tft.setCursor(115, 90); tft.print(F("GAME OVER"));
  tft.setTextSize(2); tft.setTextColor(0xFFFF, C(12, 8, 38));
  tft.setCursor(115, 140); tft.print(F("SCORE ")); tft.print(g.score);
  tft.setCursor(115, 162); tft.print(F("BEST  ")); tft.print(g.hi);
}

void renderFrame(const Game& g) {
  // 1) стираем то, что было
  eraseBox(prevPlayer);
  for (auto& b : prevObs) eraseBox(b);
  for (auto& b : prevDash) eraseBox(b);

  // 2) земля: бегущие чёрточки
  for (uint8_t i = 0; i < 10; i++) {
    int16_t x = (int16_t)(((i * 53 + 17) * 7 - (int32_t)(g.dist * UNIT_PX)) % (SCREEN_W + 40));
    if (x < 0) x += SCREEN_W + 40;
    x -= 20;
    Box d = {x, (int16_t)(GROUND_PX + 12 + (i * 11) % 24), 14, 3, true};
    if (d.x >= 0 && d.x + d.w <= SCREEN_W) { tft.fillRect(d.x, d.y, d.w, d.h, C(48, 84, 108)); prevDash[i] = d; }
  }

  // 3) препятствия
  for (uint8_t i = 0; i < MAX_OBS; i++) {
    const Obstacle& o = g.obs[i];
    if (o.kind == OBS_NONE) continue;
    if (o.kind == OBS_FLY) {
      int16_t x = U(o.x), y = U(o.top);
      if (x < 0 || x + spr_fly.w >= SCREEN_W) continue;
      blit(spr_fly, x, y);
      prevObs[i] = {x, y, (int16_t)spr_fly.w, (int16_t)spr_fly.h, true};
    } else {
      const Sprite& s = (o.kind == OBS_LEEK_L) ? spr_leek_l : spr_leek_s;
      int16_t lw = (o.kind == OBS_LEEK_L) ? LEEK_L_W : LEEK_S_W;
      int16_t x0 = U(o.x), y = GROUND_PX - s.h, wTot = 0;
      for (uint8_t k = 0; k < o.n; k++) {
        int16_t x = U(o.x + k * (lw + 1));
        if (x >= 0 && x + s.w < SCREEN_W) { blit(s, x, y); wTot = x + s.w - x0; }
      }
      prevObs[i] = {x0, y, wTot, (int16_t)s.h, wTot > 0};
    }
  }

  // 4) Miku
  const Sprite* s = (g.state == ST_OVER) ? &spr_idle : (!g.onGround) ? &spr_jump : SPR_RUN[(g.runFrame() / 2) & 3];
  int16_t px = U(PLAYER_X), py = U(g.py) - s->h;
  blit(*s, px, py);
  prevPlayer = {px, py, (int16_t)s->w, (int16_t)s->h, true};

  hud(g);
}
