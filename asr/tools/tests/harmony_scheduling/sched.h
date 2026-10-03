#pragma once
#include_next <sched.h>
#ifdef __APPLE__
#include <cstring>
struct cpu_set_t { unsigned char bits[128]; };
#define CPU_SETSIZE 128
#define CPU_ZERO(s) memset(s, 0, sizeof(cpu_set_t))
#define CPU_SET(i, s) ((s)->bits[i] = 1)
#define CPU_ISSET(i, s) ((s)->bits[i] != 0)
#define CPU_EQUAL(a, b) (memcmp(a, b, sizeof(cpu_set_t)) == 0)
inline void CPU_AND(cpu_set_t *out, const cpu_set_t *a, const cpu_set_t *b) {
  for (int i = 0; i < CPU_SETSIZE; ++i) out->bits[i] = a->bits[i] & b->bits[i];
}
inline int CPU_COUNT(const cpu_set_t *cpus) {
  int count = 0;
  for (int i = 0; i < CPU_SETSIZE; ++i) count += CPU_ISSET(i, cpus);
  return count;
}
#endif
#define sched_getaffinity amphion_test_getaffinity
#define sched_setaffinity amphion_test_setaffinity
int amphion_test_getaffinity(int, unsigned long, cpu_set_t *);
int amphion_test_setaffinity(int, unsigned long, const cpu_set_t *);
