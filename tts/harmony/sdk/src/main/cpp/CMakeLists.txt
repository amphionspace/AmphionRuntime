cmake_minimum_required(VERSION 3.13.0)
project(litsttsnative)

if (NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 17 CACHE STRING "The C++ version to use")
endif()

if (DEFINED PACKAGE_FIND_FILE)
  include(${PACKAGE_FIND_FILE})
endif()

# Do not leak absolute build-machine source paths into the shipped .so (.rodata __FILE__ strings).
add_compile_options(-ffile-prefix-map=${CMAKE_CURRENT_SOURCE_DIR}=. -fmacro-prefix-map=${CMAKE_CURRENT_SOURCE_DIR}=.)
# Do not record the absolute build-dir of the imported onnxruntime.so as an RPATH/RUNPATH.
set(CMAKE_SKIP_BUILD_RPATH TRUE)
set(CMAKE_SKIP_INSTALL_RPATH TRUE)

include_directories(${CMAKE_CURRENT_SOURCE_DIR})
include_directories(${CMAKE_CURRENT_SOURCE_DIR}/third_party/onnxruntime/include)

set(TN_ROOT ${CMAKE_CURRENT_SOURCE_DIR}/third_party/dingqiao_tn)
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

# ONNX Runtime 与 ICU 静态库已不在 Git 里，由 tools/assets 的 tts-onnxruntime-harmony-v1 /
# tts-harmony-icu-v1 恢复；缺失时在 configure 阶段就说清楚，而不是链接期报一串找不到符号。
set(LITS_ONNXRUNTIME_SO ${CMAKE_CURRENT_SOURCE_DIR}/../../../libs/${OHOS_ARCH}/libonnxruntime.so)
if(NOT EXISTS ${LITS_ONNXRUNTIME_SO})
  message(FATAL_ERROR "missing ${LITS_ONNXRUNTIME_SO}: run `python3 tools/assets/sync.py fetch tts-onnxruntime-harmony-v1`")
endif()
foreach(_icu_lib libicui18n.a libicuuc.a libicudata.a)
  if(NOT EXISTS ${OHOS_ICU_ROOT}/lib/${_icu_lib})
    message(FATAL_ERROR "missing ${OHOS_ICU_ROOT}/lib/${_icu_lib}: run `python3 tools/assets/sync.py fetch tts-harmony-icu-v1`")
  endif()
endforeach()

add_library(onnxruntime SHARED IMPORTED)
set_target_properties(onnxruntime
  PROPERTIES
  IMPORTED_LOCATION ${LITS_ONNXRUNTIME_SO}
)

target_link_libraries(litsttsnative PUBLIC
  libace_napi.z.so
  libhilog_ndk.z.so
  onnxruntime
  ${OHOS_ICU_ROOT}/lib/libicui18n.a
  ${OHOS_ICU_ROOT}/lib/libicuuc.a
  ${OHOS_ICU_ROOT}/lib/libicudata.a
)
