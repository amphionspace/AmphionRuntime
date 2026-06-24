cmake_minimum_required(VERSION 3.13.0)
project(litsttsnative)

if (NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 17 CACHE STRING "The C++ version to use")
endif()

if (DEFINED PACKAGE_FIND_FILE)
  include(${PACKAGE_FIND_FILE})
endif()

include_directories(${CMAKE_CURRENT_SOURCE_DIR})
include_directories(${CMAKE_CURRENT_SOURCE_DIR}/third_party/onnxruntime/include)

add_library(litsttsnative SHARED
  lits_tts_native.cpp
)

add_library(onnxruntime SHARED IMPORTED)
set_target_properties(onnxruntime
  PROPERTIES
  IMPORTED_LOCATION ${CMAKE_CURRENT_SOURCE_DIR}/libs/${OHOS_ARCH}/libonnxruntime.so
)

target_link_libraries(litsttsnative PUBLIC
  libace_napi.z.so
  onnxruntime
)
