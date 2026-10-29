// Чистая логика игры: без Arduino-зависимостей (проверяется на ПК: tools/test_game_host.cpp).
#pragma once
#include <stdint.h>
#include "config.h"

enum GameState : uint8_t { ST_SPLASH, ST_PLAY, ST_OVER };
enum ObsKind   : uint8_t { OBS_NONE, OBS_LEEK_S, OBS_LEEK_L, OBS_FLY };
enum : uint8_t { EV_JUMP = 1, EV_HIT = 2, EV_DING = 4 };   // события для звука

// Случайное число в [lo, hi). Реализуется снаружи (random() на Arduino, rand() на ПК).
int32_t game_random(int32_t lo, int32_t hi);

struct Obstacle {
  uint8_t kind;      // ObsKind
  uint8_t n;         // сколько луков в группе
  float x, top, w, h;
};

struct Rect { float x, y, w, h; };

struct Game {
  GameState state;
  float stateT;
  float py, vy;              // y ног Miku и вертикальная скорость
  float dist, speed, runT, toSpawn, flash;
  uint16_t score, hi, nextDing;
  bool onGround, ducking;
  uint8_t events;            // биты EV_*, читает и сбрасывает main
  Obstacle obs[MAX_OBS];

  void begin(uint16_t hiscore);
  void start();
  void update(float dt, bool jumpPressed, bool jumpHeld, bool duckHeld);
  Rect playerRect() const;
  uint8_t runFrame() const { return (uint8_t)((int)(dist / 5.5f) % 8); }

 private:
  void spawn();
  void die();
};

bool rectsHit(const Rect& a, const Rect& b);
Rect obstacleRect(const Obstacle& o);
