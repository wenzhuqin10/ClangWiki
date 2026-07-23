#include "processor.h"

#include <iostream>

int main() {
    sample::Processor processor;
    processor.register_callback([](const std::string& output) {
        std::cout << output << '\n';
    });
    processor.execute("deepwiki");
    return sample::processed_count() == 1 ? 0 : 1;
}

