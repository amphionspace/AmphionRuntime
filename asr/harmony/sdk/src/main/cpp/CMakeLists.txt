cmake_minimum_required(VERSION 3.13.0)
project(amphion_asr_native)

set(CMAKE_CXX_STANDARD 17)
set(NATIVERENDER_ROOT_PATH ${CMAKE_CURRENT_SOURCE_DIR})

if(DEFINED PACKAGE_FIND_FILE)
  include(${PACKAGE_FIND_FILE})
endif()

include_directories(${NATIVERENDER_ROOT_PATH})
include_directories(
  ${CMAKE_CURRENT_SOURCE_DIR}/../../../../../../tts/harmony/sdk/src/main/cpp/third_party/onnxruntime/include
  ${CMAKE_CURRENT_SOURCE_DIR}/../../../../../../third_party/sherpa-onnx
  ${CMAKE_CURRENT_SOURCE_DIR}/../../../../../native/audio-processing/include)

add_library(amphion_asr SHARED napi_init.cpp target_speaker_enhancer.cpp speaker_turn_segmenter.cpp agc_bridge.cpp)

add_library(sherpa_onnx_c_api SHARED IMPORTED)
set_target_properties(sherpa_onnx_c_api PROPERTIES
  IMPORTED_LOCATION ${CMAKE_CURRENT_SOURCE_DIR}/libs/${OHOS_ARCH}/libsherpa-onnx-c-api.so)

add_library(onnxruntime SHARED IMPORTED)
set_target_properties(onnxruntime PROPERTIES
  IMPORTED_LOCATION ${CMAKE_CURRENT_SOURCE_DIR}/libs/${OHOS_ARCH}/libonnxruntime.so)

add_library(amphion_audio_processing SHARED IMPORTED)
set_target_properties(amphion_audio_processing PROPERTIES
  IMPORTED_LOCATION ${CMAKE_CURRENT_SOURCE_DIR}/libs/${OHOS_ARCH}/libamphion_audio_processing.so)

target_link_libraries(amphion_asr PUBLIC libace_napi.z.so libhilog_ndk.z.so librawfile.z.so
  sherpa_onnx_c_api onnxruntime amphion_audio_processing)
