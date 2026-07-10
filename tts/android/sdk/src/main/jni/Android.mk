LOCAL_PATH := $(call my-dir)

TRANSSION_TN_ROOT := $(LOCAL_PATH)/../cpp/third_party/transsion_tn
ANDROID_ICU_ROOT := $(LOCAL_PATH)/../cpp/third_party/android-icu
ANDROID_ICU_LIB_DIR := $(ANDROID_ICU_ROOT)/lib

include $(CLEAR_VARS)
LOCAL_MODULE := icui18n
LOCAL_SRC_FILES := $(ANDROID_ICU_LIB_DIR)/libicui18n.a
include $(PREBUILT_STATIC_LIBRARY)

include $(CLEAR_VARS)
LOCAL_MODULE := icuuc
LOCAL_SRC_FILES := $(ANDROID_ICU_LIB_DIR)/libicuuc.a
include $(PREBUILT_STATIC_LIBRARY)

include $(CLEAR_VARS)
LOCAL_MODULE := icudata
LOCAL_SRC_FILES := $(ANDROID_ICU_LIB_DIR)/libicudata.a
include $(PREBUILT_STATIC_LIBRARY)

include $(CLEAR_VARS)
LOCAL_MODULE := lits_tn
LOCAL_SRC_FILES := \
    ../cpp/lits_tn_jni.cpp \
    $(TRANSSION_TN_ROOT)/tts_normalizer_engine.cpp \
    $(TRANSSION_TN_ROOT)/ru_year_spellout.cpp
LOCAL_C_INCLUDES := \
    $(TRANSSION_TN_ROOT) \
    $(ANDROID_ICU_ROOT)/include
LOCAL_CPPFLAGS := -std=c++17 -fexceptions -frtti -DU_STATIC_IMPLEMENTATION
LOCAL_LDLIBS := -llog -landroid
LOCAL_STATIC_LIBRARIES := icui18n icuuc icudata
include $(BUILD_SHARED_LIBRARY)
