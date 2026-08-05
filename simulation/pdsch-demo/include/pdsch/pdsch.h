#ifndef PDSCH_H
#define PDSCH_H

typedef struct {
    int harq_id;
    int mcs;
    int resource_blocks;
} pdsch_request_t;

int pdsch_encode(const pdsch_request_t *request, int *encoded_bits);
int pdsch_modulate(const int *encoded_bits, int count, float *symbols);
int pdsch_map(const float *symbols, int count, int *resource_grid);

#endif
