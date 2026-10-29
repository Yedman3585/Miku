// Проверка логики игры на ПК (без Arduino): бот играет, смотрим что игра проходима.
//   g++ -O2 -std=c++11 -I arduino/miku_runner_mega tools/test_game_host.cpp arduino/miku_runner_mega/game.cpp -o test_game && ./test_game
#include <cstdio>
#include <cstdlib>
#include "game.h"

int32_t game_random(int32_t lo, int32_t hi) { return lo + rand() % (hi - lo); }

int main() {
  int total = 0, best = 0, runs = 40;
  for (int seed = 0; seed < runs; seed++) {
    srand(seed);
    Game g; g.begin(0); g.start();
    int steps = 0;
    while (g.state == ST_PLAY && steps < 60 * 120) {
      bool jump = false, duck = false;
      Rect pr = g.playerRect();
      float pc = pr.x + pr.w / 2;
      bool jumped = false;
      for (auto& o : g.obs) {
        if (o.kind == OBS_NONE || o.x + o.w < pr.x - 1) continue;
        float oc = o.x + o.w / 2;
        if (o.kind == OBS_FLY && o.top < GROUND - 20) { if (oc - pc < 30) duck = true; }
        else if (!jumped && g.onGround && oc - pc < g.speed * 0.37f + (o.kind != OBS_FLY ? 4 : 0)) { jump = jumped = true; }
      }
      g.update(1.0f / 60, jump, jump || !g.onGround, duck);
      steps++;
    }
    total += g.score; if (g.score > best) best = g.score;
    if (g.state == ST_OVER) printf("seed %2d: умер, счёт %d\n", seed, g.score);
  }
  printf("средний счёт %d, лучший %d (бот, 120 с максимум)\n", total / runs, best);
  return 0;
}
