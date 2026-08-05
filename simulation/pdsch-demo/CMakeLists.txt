cmake_minimum_required(VERSION 3.16)
project(pdsch_demo C)

set(CMAKE_C_STANDARD 11)
add_library(pdsch_demo STATIC
  src/pdsch/encoder/encoder.c
  src/pdsch/modulation/modulation.c
  src/pdsch/mapping/mapping.c
)
target_include_directories(pdsch_demo PUBLIC include)
