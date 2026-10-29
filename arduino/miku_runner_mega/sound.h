// Звук без блокировки: короткие эффекты + мелодия на одном динамике (tone()).
#pragma once
#include <Arduino.h>
#include <avr/pgmspace.h>
#include "config.h"
#include "game.h"

// нота: частота (Гц, 0 = пауза), длительность (мс)
struct Note { uint16_t hz, ms; };
static const Note MELODY[] PROGMEM = {
  {659,150},{0,50},{523,150},{659,150},{784,300},{0,100},{659,150},{523,150},
  {698,150},{0,50},{523,150},{698,150},{880,300},{0,100},{698,150},{523,150},
  {659,150},{0,50},{523,150},{659,150},{784,300},{0,100},{784,150},{659,150},
  {587,150},{0,50},{494,150},{587,150},{784,300},{0,100},{587,150},{494,150},
};
#define MELODY_LEN (sizeof(MELODY) / sizeof(MELODY[0]))

static uint32_t sfxUntil = 0, noteUntil = 0;
static uint8_t noteIdx = 0;
static bool musicOn = true;

inline void soundInit() { pinMode(PIN_SPEAKER, OUTPUT); }
inline void soundMusic(bool on) { musicOn = on; if (!on) noTone(PIN_SPEAKER); }

inline void soundEvents(uint8_t ev) {            // events из Game
  uint32_t now = millis();
  if (ev & EV_JUMP) { tone(PIN_SPEAKER, 700, 90);  sfxUntil = now + 90; }
  if (ev & EV_DING) { tone(PIN_SPEAKER, 1319, 180); sfxUntil = now + 180; }
  if (ev & EV_HIT)  { tone(PIN_SPEAKER, 140, 400);  sfxUntil = now + 400; noteUntil = sfxUntil; }
}

inline void soundUpdate() {                      // вызывать каждый кадр
  uint32_t now = millis();
  if (!musicOn || now < sfxUntil || now < noteUntil) return;
  Note n; memcpy_P(&n, &MELODY[noteIdx], sizeof n);
  noteIdx = (noteIdx + 1) % MELODY_LEN;
  if (n.hz) tone(PIN_SPEAKER, n.hz, n.ms * 9 / 10); else noTone(PIN_SPEAKER);
  noteUntil = now + n.ms;
}
