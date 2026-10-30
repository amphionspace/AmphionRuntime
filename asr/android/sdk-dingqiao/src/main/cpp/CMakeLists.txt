cmake_minimum_required(VERSION 3.22.1)
project(amphion_dingqiao_native)

set(CMAKE_CXX_STANDARD 17)

# Sortformer 与鸿蒙共用同一份实现，平台差异在文件内按 __ANDROID__ 分开；
# JNI 绑定由该文件在 Android 下包含 sortformer_diarization_jni.inc 提供。
add_library(amphion_diarization_jni SHARED speaker_turn_segmenter_jni.cpp
  sortformer_diarization.cpp)

target_include_directories(amphion_diarization_jni PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}
  ${CMAKE_CURRENT_SOURCE_DIR}/../../../../../../tts/harmony/sdk/src/main/cpp/third_party/onnxruntime/include)

add_library(onnxruntime SHARED IMPORTED)
set_target_properties(onnxruntime PROPERTIES
  IMPORTED_LOCATION ${CMAKE_CURRENT_SOURCE_DIR}/../../../../sdk/src/main/jniLibs/${ANDROID_ABI}/libonnxruntime.so)

find_library(log-lib log)
target_link_libraries(amphion_diarization_jni PRIVATE onnxruntime ${log-lib})
