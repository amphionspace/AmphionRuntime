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

set(TN_ROOT ${CMAKE_CURRENT_SOURCE_DIR}/third_party/transsion_tn)
set(OHOS_ICU_ROOT ${CMAKE_CURRENT_SOURCE_DIR}/third_party/ohos-icu)
include_directories(${TN_ROOT})
include_directories(${TN_ROOT}/third_party)
include_directories(${OHOS_ICU_ROOT}/include)

add_library(litsttsnative SHARED
  lits_tts_native.cpp
  lits_tn_inprocess.cpp
  ${TN_ROOT}/tts_normalizer_engine.cpp
  ${TN_ROOT}/ru_year_spellout.cpp
)

add_library(onnxruntime SHARED IMPORTED)
set_target_properties(onnxruntime
  PROPERTIES
  IMPORTED_LOCATION ${CMAKE_CURRENT_SOURCE_DIR}/libs/${OHOS_ARCH}/libonnxruntime.so
)

target_link_libraries(litsttsnative PUBLIC
  libace_napi.z.so
  libhilog_ndk.z.so
  onnxruntime
  ${OHOS_ICU_ROOT}/lib/libicui18n.a
  ${OHOS_ICU_ROOT}/lib/libicuuc.a
  ${OHOS_ICU_ROOT}/lib/libicudata.a
)
