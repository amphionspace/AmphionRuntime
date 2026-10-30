cmake_minimum_required(VERSION 3.22.1)
project(amphion_dingqiao_native)

set(CMAKE_CXX_STANDARD 17)

# community_diarization.cpp and its headers used to be compiled straight out of the Harmony
# module. 0.3.26 replaced Harmony's diarization chain with Sortformer and deleted them there,
# while Android still ships the Community chain, so this module now owns the sources. The file
# keeps its `#ifndef __ANDROID__` guards and includes community_diarization_jni.inc on Android.
add_library(amphion_diarization_jni SHARED speaker_turn_segmenter_jni.cpp
  community_diarization.cpp)

target_include_directories(amphion_diarization_jni PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}
  ${CMAKE_CURRENT_SOURCE_DIR}/../../../../../../tts/harmony/sdk/src/main/cpp/third_party/onnxruntime/include)

add_library(onnxruntime SHARED IMPORTED)
set_target_properties(onnxruntime PROPERTIES
  IMPORTED_LOCATION ${CMAKE_CURRENT_SOURCE_DIR}/../../../../sdk/src/main/jniLibs/${ANDROID_ABI}/libonnxruntime.so)

find_library(log-lib log)
target_link_libraries(amphion_diarization_jni PRIVATE onnxruntime ${log-lib})
