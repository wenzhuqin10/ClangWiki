#pragma once

#include <functional>
#include <string>

#define ENABLE_METRICS 1
#define APPLY_TRANSFORM(processor, value) ((processor).transform(value))

namespace sample {

class BaseProcessor {
public:
    virtual ~BaseProcessor() = default;
    virtual std::string transform(const std::string& input) const = 0;
};

class Processor final : public BaseProcessor {
public:
    using Callback = std::function<void(const std::string&)>;

    std::string transform(const std::string& input) const override;
    void register_callback(Callback callback);
    void execute(const std::string& input);

private:
    Callback callback_;
};

int processed_count();

}  // namespace sample

