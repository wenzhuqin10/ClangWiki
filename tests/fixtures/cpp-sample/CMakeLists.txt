cmake_minimum_required(VERSION 3.16)
project(cppwiki_sample LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 17)
add_library(processor src/processor.cpp)
target_include_directories(processor PUBLIC include)
add_executable(cppwiki_sample src/main.cpp)
target_link_libraries(cppwiki_sample PRIVATE processor)

