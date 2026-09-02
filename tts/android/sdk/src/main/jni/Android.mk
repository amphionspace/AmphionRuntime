LOCAL_PATH := $(call my-dir)

LITS_WORKSPACE_ROOT := $(LOCAL_PATH)/../../../../../..
SDK_PROJECT_ROOT := $(LOCAL_PATH)/../../../..
empty :=
LITS_SOURCE_ROOT_RELATIVE := tts/training/dingqiao_lits
TN_PACKAGE_DIR_NAME := Dingqiao_Multilingual_Text_Normalization_for_TTS
LITS_TN_ROOT := $(LITS_WORKSPACE_ROOT)/$(LITS_SOURCE_ROOT_RELATIVE)/$(TN_PACKAGE_DIR_NAME)
ANDROID_ICU_ROOT := $(LITS_WORKSPACE_ROOT)/$(LITS_SOURCE_ROOT_RELATIVE)/build/android-icu/android-arm64-install
ANDROID_ICU_LIB_DIR := $(LITS_WORKSPACE_ROOT)/$(LITS_SOURCE_ROOT_RELATIVE)/build/android-icu/android-arm64-build/lib

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
    $(LITS_TN_ROOT)/tts_normalizer_engine.cpp \
    $(LITS_TN_ROOT)/ru_year_spellout.cpp
LOCAL_C_INCLUDES := \
    $(LITS_TN_ROOT) \
    $(ANDROID_ICU_ROOT)/include
LOCAL_CPPFLAGS := -std=c++17 -fexceptions -frtti -DU_STATIC_IMPLEMENTATION \
    -ffile-prefix-map=$(LITS_TN_ROOT)=/lits_tn_runtime_source \
    -ffile-prefix-map=$(LITS_WORKSPACE_ROOT)/$(LITS_SOURCE_ROOT_RELATIVE)=/lits_src_pack_ \
    -ffile-prefix-map=$(SDK_PROJECT_ROOT)=/lits_sdk_workspace
LOCAL_LDLIBS := -llog -landroid
LOCAL_STATIC_LIBRARIES := icui18n icuuc icudata
include $(BUILD_SHARED_LIBRARY)
