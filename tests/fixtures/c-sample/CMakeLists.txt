cmake_minimum_required(VERSION 3.20)
project(clangwiki_fixture C)

add_executable(clangwiki_fixture
  src/main.c
  src/network.c
)
target_include_directories(clangwiki_fixture PRIVATE include)

