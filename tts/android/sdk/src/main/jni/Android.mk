LOCAL_PATH := $(call my-dir)

LITS_WORKSPACE_ROOT := $(LOCAL_PATH)/../../../../../../..
TRANSSION_TN_ROOT := $(LITS_WORKSPACE_ROOT)/transsion_lits/Transsion_Multilingual_Text_Normalization_for_TTS
ANDROID_ICU_ROOT := $(LITS_WORKSPACE_ROOT)/transsion_lits/build/android-icu/android-arm64-install
ANDROID_ICU_LIB_DIR := $(LITS_WORKSPACE_ROOT)/transsion_lits/build/android-icu/android-arm64-build/lib

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
