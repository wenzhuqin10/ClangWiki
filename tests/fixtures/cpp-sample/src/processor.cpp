#include "processor.h"

#include <algorithm>

namespace sample {

static int g_processed = 0;

std::string Processor::transform(const std::string& input) const {
    std::string output = input;
    std::transform(output.begin(), output.end(), output.begin(), ::toupper);
    return output;
}

void Processor::register_callback(Callback callback) {
    callback_ = std::move(callback);
}

void Processor::execute(const std::string& input) {
#if ENABLE_METRICS
    ++g_processed;
#endif
    const auto output = APPLY_TRANSFORM(*this, input);
    if (callback_) {
        callback_(output);
    }
}

int processed_count() {
    return g_processed;
}

}  // namespace sample

