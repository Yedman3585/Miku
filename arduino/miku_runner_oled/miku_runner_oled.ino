// =====================================================================
//  Miku Runner — джойстик + OLED 128x64 для игры на ПК (Python)
// =====================================================================
//  Arduino делает две вещи одновременно:
//   (скорость порта 500000 — в Python по умолчанию так же; для старой прошивки: --baud 115200)
//   1) каждые 20 мс отправляет на ПК состояние джойстика:  "J <x> <y> <btn>"
//   2) принимает с ПК кадры 128x64 (1024 байта) и выводит их на OLED.
//      После каждого кадра отвечает "F" — "готов к следующему".
//
//  Подключение (Arduino Uno / Nano):
//    OLED SSD1306 (I2C):  GND -> GND,  VCC -> 5V,  SCL -> A5,  SDA -> A4
//    Джойстик (KY-023):   GND -> GND,  +5V -> 5V,  VRx -> A0,  VRy -> A1,
//                         SW  -> D2
//
//  Библиотеки (Инструменты -> Управлять библиотеками):
//    "Adafruit SSD1306"  (вместе с ней поставится "Adafruit GFX Library")
// =====================================================================

#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

#define SCREEN_W   128
#define SCREEN_H   64
#define OLED_ADDR  0x3C          // если экран не работает — попробуй 0x3D

const byte PIN_JOY_X  = A0;
const byte PIN_JOY_Y  = A1;
const byte PIN_JOY_SW = 2;

const uint16_t FRAME_SIZE       = 1024;   // 128 * 64 / 8
const unsigned long JOY_PERIOD   = 20;    // мс между отправками джойстика
const unsigned long FRAME_TIMEOUT = 300;  // мс: оборванный кадр сбрасывается

Adafruit_SSD1306 display(SCREEN_W, SCREEN_H, &Wire, -1);

uint8_t* frameBuf;               // память самого дисплея — пишем прямо в неё
uint16_t frameIdx = 0;
unsigned long lastByteTime = 0;
unsigned long lastJoyTime  = 0;

void setup() {
  Serial.begin(500000);          // быстрый порт: кадр уходит за ~20 мс (должно совпадать с BAUD в miku_runner.py)
  pinMode(PIN_JOY_SW, INPUT_PULLUP);

  if (!display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR)) {
    // Экран не найден: мигаем встроенным светодиодом, но джойстик
    // продолжает работать, чтобы можно было играть хотя бы на ПК.
    pinMode(LED_BUILTIN, OUTPUT);
    while (true) {
      digitalWrite(LED_BUILTIN, !digitalRead(LED_BUILTIN));
      sendJoystick();
      delay(100);
    }
  }
  Wire.setClock(400000);         // быстрый I2C — кадр выводится ~25 мс
  frameBuf = display.getBuffer();

  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);
  display.setTextSize(1);
  display.setCursor(10, 20);
  display.print(F("Miku Runner"));
  display.setCursor(10, 36);
  display.print(F("Waiting for PC..."));
  display.display();

  Serial.println(F("R"));        // "Ready" — ПК может слать первый кадр
}

void sendJoystick() {
  Serial.print('J');
  Serial.print(analogRead(PIN_JOY_X));
  Serial.print(' ');
  Serial.print(analogRead(PIN_JOY_Y));
  Serial.print(' ');
  Serial.println(digitalRead(PIN_JOY_SW) == LOW ? 1 : 0);
}

void loop() {
  // 1. Забираем байты кадра, сколько пришло
  while (Serial.available() > 0) {
    frameBuf[frameIdx++] = Serial.read();
    lastByteTime = millis();

    if (frameIdx >= FRAME_SIZE) {
      display.display();         // ПК ждёт "F", поэтому ничего не теряется
      frameIdx = 0;
      Serial.println(F("F"));
    }
  }

  // 2. Кадр оборвался (ПК перезапустили и т.п.) — начинаем заново
  if (frameIdx > 0 && millis() - lastByteTime > FRAME_TIMEOUT) {
    frameIdx = 0;
    Serial.println(F("F"));
  }

  // 3. Джойстик
  if (millis() - lastJoyTime >= JOY_PERIOD) {
    lastJoyTime = millis();
    sendJoystick();
  }
}
