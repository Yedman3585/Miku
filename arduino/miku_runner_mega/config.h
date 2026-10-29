// =====================================================================
//  Miku Runner (Arduino Mega) — настройки: экран, пины, физика
//  Физика и размеры повторяют miku_runner.py (мир 128 единиц в ширину).
// =====================================================================
#pragma once
#include <stdint.h>

// ---------------- экран: шилд 3.2" 480x320, альбомная ориентация ----------------
#define SCREEN_W      480
#define SCREEN_H      320
#define LCD_ROTATION  1          // 1 или 3 — если картинка перевёрнута
#define UNIT_PX       3.75f      // 1 единица мира = 3.75 пикселя экрана (128 * 3.75 = 480)

// ---------------- пины (проверь, что шилд их не занимает) ----------------
#define PIN_BTN_JUMP  2          // кнопка "прыжок":  пин -> GND (внутренняя подтяжка)
#define PIN_BTN_DUCK  3          // кнопка "пригнуться"
#define PIN_SPEAKER   6          // динамик через резистор 100-220 Ом на GND

// ---------------- мир (в единицах, как в Python-версии) ----------------
#define WORLD_W       128
#define GROUND        73         // линия земли (y, куда Miku ставит ноги); 73 * 3.75 = 274 px
#define MAX_OBS       4

// ---------------- физика ----------------
#define GRAVITY       420.0f
#define JUMP_APEX     30.0f      // высота прыжка
#define START_SPEED   55.0f
#define MAX_SPEED     108.0f
#define ACCEL         1.2f
#define SPR_H         24.0f      // высота Miku (единицы)
#define SPR_W         (SPR_H * 166.0f / 141.0f)
#define PLAYER_X      6.0f       // x левого края спрайта Miku
#define DUCK_H        12.0f
#define LEEK_S_W      6
#define LEEK_S_H      12
#define LEEK_L_W      8
#define LEEK_L_H      18
#define FLY_W         14
#define FLY_H         6

#define EEPROM_HI_ADDR 0
