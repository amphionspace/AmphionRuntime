#ifndef AMPHION_AUDIO_PROCESSING_H_
#define AMPHION_AUDIO_PROCESSING_H_

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct AmphionAgc AmphionAgc;

/** Creates the conservative speech AGC2 preset for mono PCM. */
AmphionAgc* amphion_agc_create(int sample_rate_hz);

/** Processes exactly one 10 ms float PCM frame in-place. Returns 0 on success. */
int amphion_agc_process(AmphionAgc* agc, float* samples, size_t sample_count);

void amphion_agc_destroy(AmphionAgc* agc);

#ifdef __cplusplus
}
#endif

#endif  // AMPHION_AUDIO_PROCESSING_H_
