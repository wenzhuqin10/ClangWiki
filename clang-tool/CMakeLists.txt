cmake_minimum_required(VERSION 3.20)
project(clangwiki_analyzer LANGUAGES CXX)

find_package(LLVM REQUIRED CONFIG)
find_package(Clang REQUIRED CONFIG)

add_executable(clangwiki-analyzer src/main.cpp)
target_compile_features(clangwiki-analyzer PRIVATE cxx_std_17)
target_include_directories(clangwiki-analyzer PRIVATE ${LLVM_INCLUDE_DIRS} ${CLANG_INCLUDE_DIRS})
target_compile_definitions(clangwiki-analyzer PRIVATE ${LLVM_DEFINITIONS})
target_link_libraries(clangwiki-analyzer PRIVATE
  clangAST clangBasic clangFrontend clangTooling clangToolingCore clangToolingInclusions
)

