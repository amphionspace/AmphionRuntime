cmake_minimum_required(VERSION 3.22.1)

project(lits_tn LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(LITS_WORKSPACE_ROOT "${CMAKE_CURRENT_LIST_DIR}/../../../../../..")
set(LITS_SOURCE_ROOT_RELATIVE "tts/training/dingqiao_lits")
set(TN_PACKAGE_DIR_NAME "Dingqiao_Multilingual_Text_Normalization_for_TTS")
get_filename_component(SDK_PROJECT_ROOT "${CMAKE_CURRENT_LIST_DIR}/../../../.." ABSOLUTE)
set(LITS_TN_ROOT "${LITS_WORKSPACE_ROOT}/${LITS_SOURCE_ROOT_RELATIVE}/${TN_PACKAGE_DIR_NAME}")
set(ANDROID_ICU_ROOT "${LITS_WORKSPACE_ROOT}/${LITS_SOURCE_ROOT_RELATIVE}/build/android-icu/android-arm64-install")
set(ANDROID_ICU_LIB_DIR "${LITS_WORKSPACE_ROOT}/${LITS_SOURCE_ROOT_RELATIVE}/build/android-icu/android-arm64-build/lib")

add_library(lits_tn SHARED
    lits_tn_jni.cpp
    "${LITS_TN_ROOT}/tts_normalizer_engine.cpp"
    "${LITS_TN_ROOT}/ru_year_spellout.cpp"
)

target_compile_definitions(lits_tn PRIVATE U_STATIC_IMPLEMENTATION)
target_compile_options(lits_tn PRIVATE
    "-ffile-prefix-map=${LITS_TN_ROOT}=/lits_tn_runtime_source"
    "-ffile-prefix-map=${LITS_WORKSPACE_ROOT}/${LITS_SOURCE_ROOT_RELATIVE}=/lits_src_pack_"
    "-ffile-prefix-map=${SDK_PROJECT_ROOT}=/lits_sdk_workspace"
)

target_include_directories(lits_tn PRIVATE
    "${LITS_TN_ROOT}"
    "${ANDROID_ICU_ROOT}/include"
)

add_library(icuuc STATIC IMPORTED)
set_target_properties(icuuc PROPERTIES IMPORTED_LOCATION "${ANDROID_ICU_LIB_DIR}/libicuuc.a")

add_library(icui18n STATIC IMPORTED)
set_target_properties(icui18n PROPERTIES IMPORTED_LOCATION "${ANDROID_ICU_LIB_DIR}/libicui18n.a")

add_library(icudata STATIC IMPORTED)
set_target_properties(icudata PROPERTIES IMPORTED_LOCATION "${ANDROID_ICU_LIB_DIR}/libicudata.a")

target_link_libraries(lits_tn
    icui18n
    icuuc
    icudata
    android
    log
)
