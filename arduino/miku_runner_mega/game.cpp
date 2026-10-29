#include <math.h>
#include "game.h"

bool rectsHit(const Rect& a, const Rect& b) {
  return a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
}

Rect obstacleRect(const Obstacle& o) {      // хитбокс чуть меньше картинки — честнее
  return Rect{o.x + 1.5f, o.top + 1.5f, o.w - 3.0f, o.h - 2.5f};
}

static float frand(float lo, float hi) {
  return lo + (hi - lo) * (float)game_random(0, 10000) / 10000.0f;
}

void Game::begin(uint16_t hiscore) {
  hi = hiscore;
  state = ST_SPLASH;
  stateT = 0;
  start();
  state = ST_SPLASH;
}

void Game::start() {
  state = ST_PLAY;
  stateT = 0;
  runT = dist = flash = 0;
  score = 0;
  nextDing = 100;
  speed = START_SPEED;
  py = GROUND;
  vy = 0;
  onGround = true;
  ducking = false;
  toSpawn = 40.0f;
  events = 0;
  for (auto& o : obs) o.kind = OBS_NONE;
}

Rect Game::playerRect() const {
  float h = ducking ? DUCK_H - 1 : SPR_H - 3;
  return Rect{PLAYER_X + 0.47f * SPR_W + 1.5f, py - h, 0.40f * SPR_W - 2, h};
}

void Game::spawn() {
  Obstacle* o = nullptr;
  for (auto& s : obs) if (s.kind == OBS_NONE) { o = &s; break; }
  if (!o) { toSpawn = 20; return; }
  o->x = WORLD_W + 4;
  o->n = 1;
  if (score > 250 && frand(0, 1) < 0.28f) {
    o->kind = OBS_FLY;
    o->w = FLY_W; o->h = FLY_H;
    o->top = (game_random(0, 2) ? GROUND - 13 : GROUND - 23);
  } else {
    bool large; uint8_t n = 1;
    if (score < 120) {
      large = game_random(0, 3) == 1;                       // s, l, s
    } else {
      switch (game_random(0, 6)) {                          // s, l, s2, s3, l2, l
        case 0: large = false; break;
        case 1: large = true; break;
        case 2: large = false; n = 2; break;
        case 3: large = false; n = 3; break;
        case 4: large = true; n = 2; break;
        default: large = true; break;
      }
    }
    o->kind = large ? OBS_LEEK_L : OBS_LEEK_S;
    o->n = n;
    float lw = large ? LEEK_L_W : LEEK_S_W, lh = large ? LEEK_L_H : LEEK_S_H;
    o->w = lw * n + (n - 1);
    o->h = lh;
    o->top = GROUND - lh;
  }
  toSpawn = o->w + speed * 0.76f * frand(1.05f, 1.8f) + 14;
}

void Game::die() {
  events |= EV_HIT;
  if (score > hi) hi = score;
  state = ST_OVER;
  stateT = 0;
}

void Game::update(float dt, bool jumpPressed, bool jumpHeld, bool duckHeld) {
  stateT += dt;
  if (state == ST_SPLASH) {
    if (jumpPressed) start();
    return;
  }
  if (state == ST_OVER) {
    if (jumpPressed && stateT > 0.7f) start();
    return;
  }

  // ---- ход игры ----
  runT += dt;
  speed = START_SPEED + ACCEL * runT;
  if (speed > MAX_SPEED) speed = MAX_SPEED;
  dist += speed * dt;
  score = (uint16_t)(dist * 0.12f);
  if (flash > 0) flash -= dt;
  if (score >= nextDing) { nextDing += 100; flash = 1.0f; events |= EV_DING; }

  const float jumpV = sqrtf(2 * GRAVITY * JUMP_APEX);
  if (jumpPressed && onGround) { vy = -jumpV; onGround = false; events |= EV_JUMP; }
  if (!jumpHeld && vy < -jumpV * 0.4f) vy = -jumpV * 0.4f;     // отпустил — прыжок ниже
  ducking = duckHeld && onGround;
  vy += GRAVITY * ((duckHeld && !onGround) ? 2.6f : 1.0f) * dt;
  py += vy * dt;
  if (py >= GROUND) { py = GROUND; vy = 0; onGround = true; }

  // ---- препятствия ----
  for (auto& o : obs) {
    if (o.kind == OBS_NONE) continue;
    o.x -= speed * dt;
    if (o.x + o.w < -6) o.kind = OBS_NONE;
  }
  toSpawn -= speed * dt;
  if (toSpawn <= 0) spawn();

  Rect pr = playerRect();
  for (auto& o : obs)
    if (o.kind != OBS_NONE && rectsHit(pr, obstacleRect(o))) { die(); return; }
}
