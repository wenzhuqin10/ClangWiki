#include "pdsch/pdsch.h"

int pdsch_map(const float *symbols, int count, int *resource_grid) {
    if (symbols == 0 || resource_grid == 0 || count <= 0) {
        return -1;
    }
    for (int index = 0; index < count; ++index) {
        resource_grid[index] = symbols[index] > 0.0f ? 1 : 0;
    }
    return 0;
}
