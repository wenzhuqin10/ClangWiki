#include "pdsch/pdsch.h"

int pdsch_encode(const pdsch_request_t *request, int *encoded_bits) {
    if (request == 0 || encoded_bits == 0 || request->resource_blocks <= 0) {
        return -1;
    }
    *encoded_bits = request->resource_blocks * (request->mcs + 1);
    return 0;
}
