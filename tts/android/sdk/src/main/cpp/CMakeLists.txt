cmake_minimum_required(VERSION 3.22.1)

project(lits_tn LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(TRANSSION_TN_ROOT "${CMAKE_CURRENT_LIST_DIR}/third_party/transsion_tn")
set(ANDROID_ICU_ROOT "${CMAKE_CURRENT_LIST_DIR}/third_party/android-icu")
set(ANDROID_ICU_LIB_DIR "${ANDROID_ICU_ROOT}/lib")

add_library(lits_tn SHARED
    lits_tn_jni.cpp
    "${TRANSSION_TN_ROOT}/tts_normalizer_engine.cpp"
    "${TRANSSION_TN_ROOT}/ru_year_spellout.cpp"
)

target_compile_definitions(lits_tn PRIVATE U_STATIC_IMPLEMENTATION)

target_include_directories(lits_tn PRIVATE
    "${TRANSSION_TN_ROOT}"
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
