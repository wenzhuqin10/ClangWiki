cmake_minimum_required(VERSION 3.20)
project(clangwiki_analyzer LANGUAGES CXX)

set(LLVM_ROOT "" CACHE PATH "LLVM installation root containing include/clang-c and lib/libclang")

find_path(LIBCLANG_INCLUDE_DIR
  NAMES clang-c/Index.h
  HINTS "${LLVM_ROOT}/include" "$ENV{LLVM_ROOT}/include"
  PATHS "C:/Program Files/LLVM/include"
)
find_library(LIBCLANG_LIBRARY
  NAMES libclang clang
  HINTS "${LLVM_ROOT}/lib" "$ENV{LLVM_ROOT}/lib"
  PATHS "C:/Program Files/LLVM/lib"
)

if(NOT LIBCLANG_INCLUDE_DIR OR NOT LIBCLANG_LIBRARY)
  message(FATAL_ERROR "libclang development files were not found. Set LLVM_ROOT to the LLVM installation directory.")
endif()

add_executable(clangwiki-analyzer src/main.cpp)
target_compile_features(clangwiki-analyzer PRIVATE cxx_std_17)
target_include_directories(clangwiki-analyzer PRIVATE "${LIBCLANG_INCLUDE_DIR}")
target_link_libraries(clangwiki-analyzer PRIVATE "${LIBCLANG_LIBRARY}")

if(MSVC)
  target_compile_options(clangwiki-analyzer PRIVATE /W4 /EHsc)
else()
  target_compile_options(clangwiki-analyzer PRIVATE -Wall -Wextra -Wpedantic)
endif()
