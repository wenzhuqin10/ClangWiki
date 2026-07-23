CXX ?= c++
CXXFLAGS ?= -std=c++17 -Iinclude

all: cppwiki-sample

cppwiki-sample: src/main.cpp src/processor.cpp include/processor.h
	$(CXX) $(CXXFLAGS) src/main.cpp src/processor.cpp -o $@

clean:
	rm -f cppwiki-sample

