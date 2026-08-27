cmake_minimum_required(VERSION 3.22.1)
project(amphion_police_native)

set(CMAKE_CXX_STANDARD 17)

add_library(amphion_police_jni SHARED lac_person_ner_jni.cpp)
target_include_directories(amphion_police_jni PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}/../../../../../../tts/harmony/sdk/src/main/cpp/third_party/onnxruntime/include)

add_library(onnxruntime SHARED IMPORTED)
set_target_properties(onnxruntime PROPERTIES
  IMPORTED_LOCATION ${CMAKE_CURRENT_SOURCE_DIR}/../../../../sdk/src/main/jniLibs/${ANDROID_ABI}/libonnxruntime.so)

find_library(log-lib log)
target_link_libraries(amphion_police_jni PRIVATE onnxruntime ${log-lib})
