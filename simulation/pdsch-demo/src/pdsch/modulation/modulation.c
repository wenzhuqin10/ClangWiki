#include "pdsch/pdsch.h"

int pdsch_modulate(const int *encoded_bits, int count, float *symbols) {
    if (encoded_bits == 0 || symbols == 0 || count <= 0) {
        return -1;
    }
    for (int index = 0; index < count; ++index) {
        symbols[index] = encoded_bits[index] ? 1.0f : -1.0f;
    }
    return 0;
}
