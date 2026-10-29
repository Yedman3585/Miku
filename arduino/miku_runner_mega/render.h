#pragma once
#include "game.h"

void renderInit();                       // инициализация экрана и фона
void renderSplash();                     // заставка (один раз при входе в состояние)
void renderGameOverBox(const Game& g);   // плашка Game Over поверх сцены
void renderFrame(const Game& g);         // один кадр игры: стереть старое, нарисовать новое
void renderResetScene();                 // перерисовать фон при старте новой игры
