cmake_minimum_required(VERSION 3.20)
project(cpp_analyzer LANGUAGES CXX)

find_package(LLVM REQUIRED CONFIG)
find_package(Clang REQUIRED CONFIG)

add_executable(cpp-analyzer src/main.cpp)
target_compile_features(cpp-analyzer PRIVATE cxx_std_17)
target_include_directories(cpp-analyzer PRIVATE ${LLVM_INCLUDE_DIRS} ${CLANG_INCLUDE_DIRS})
target_compile_definitions(cpp-analyzer PRIVATE ${LLVM_DEFINITIONS})
target_link_libraries(cpp-analyzer PRIVATE
  clangAST
  clangBasic
  clangFrontend
  clangLex
  clangTooling
)

