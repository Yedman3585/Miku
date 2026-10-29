// =====================================================================
//  Miku Runner — самостоятельная версия для Arduino Mega 2560
//  Экран: шилд 3.2" TFT 480x320 (MCUFRIEND_kbv). Две кнопки + динамик.
//
//  Библиотеки (Инструменты -> Управлять библиотеками):
//    "MCUFRIEND_kbv"  (и "Adafruit GFX Library")
//  Плата: Arduino Mega or Mega 2560.
//
//  Спрайты лежат в sprites.h (генерируется: python tools/export_sprites.py).
// =====================================================================
#include <EEPROM.h>
#include "config.h"
#include "game.h"
#include "render.h"
#include "sound.h"

Game game;

int32_t game_random(int32_t lo, int32_t hi) { return random(lo, hi); }

static bool prevJump = false;
static uint32_t lastMicros = 0;

static uint16_t loadHi() {
  uint16_t v = 0;
  EEPROM.get(EEPROM_HI_ADDR, v);
  return v == 0xFFFF ? 0 : v;
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_BTN_JUMP, INPUT_PULLUP);
  pinMode(PIN_BTN_DUCK, INPUT_PULLUP);
  randomSeed(analogRead(A15) ^ micros());
  soundInit();
  renderInit();
  game.begin(loadHi());
  renderSplash();
  lastMicros = micros();
}

void loop() {
  uint32_t now = micros();
  float dt = (now - lastMicros) / 1e6f;
  lastMicros = now;
  if (dt > 0.05f) dt = 0.05f;

  bool jumpHeld = digitalRead(PIN_BTN_JUMP) == LOW;
  bool duckHeld = digitalRead(PIN_BTN_DUCK) == LOW;
  bool jumpPressed = jumpHeld && !prevJump;
  prevJump = jumpHeld;

  GameState before = game.state;
  game.update(dt, jumpPressed, jumpHeld, duckHeld);

  if (before != game.state) {
    if (game.state == ST_PLAY) { renderResetScene(); }
    if (game.state == ST_SPLASH) { renderSplash(); }
    if (game.state == ST_OVER) {
      EEPROM.put(EEPROM_HI_ADDR, game.hi);          // рекорд сохраняем при проигрыше
      renderFrame(game);
      renderGameOverBox(game);
    }
  }
  if (game.state == ST_PLAY) renderFrame(game);

  soundEvents(game.events);
  game.events = 0;
  soundUpdate();
}
