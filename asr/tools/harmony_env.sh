#!/usr/bin/env bash
# Source this file before using the standalone HarmonyOS Command Line Tools.
# JAVA_HOME must point to an independent JDK when Java is not already on PATH.

export DEVECO_CLI_CLT_PATH="${DEVECO_CLI_CLT_PATH:-$HOME/.local/share/harmony/command-line-tools}"
# An inherited Studio override takes precedence over CLT in DevEco CLI.
unset DEVECO_CLI_STUDIO_PATH
export DEVECO_SDK_HOME="${DEVECO_SDK_HOME:-$DEVECO_CLI_CLT_PATH/sdk}"
export OHOS_SDK_NATIVE_DIR="${OHOS_SDK_NATIVE_DIR:-$DEVECO_SDK_HOME/default/openharmony/native}"
export NODE_HOME="$DEVECO_CLI_CLT_PATH/tool/node"
export PATH="$NODE_HOME/bin:$DEVECO_CLI_CLT_PATH/ohpm/bin:$DEVECO_CLI_CLT_PATH/hvigor/bin:$DEVECO_SDK_HOME/default/openharmony/toolchains${JAVA_HOME:+:$JAVA_HOME/bin}:$PATH"
# Build paths and diagnostics stay local.
export DEVECO_CLI_DISABLE_TELEMETRY=1

NODE="$NODE_HOME/bin/node"
HVIGOR="$DEVECO_CLI_CLT_PATH/hvigor/bin/hvigorw.js"
OHPM="$DEVECO_CLI_CLT_PATH/ohpm/bin/ohpm"
HDC="${HDC:-$DEVECO_SDK_HOME/default/openharmony/toolchains/hdc}"
LLVM_NM="${LLVM_NM:-$OHOS_SDK_NATIVE_DIR/llvm/bin/llvm-nm}"
HAP_SIGN_TOOL_JAR="${HAP_SIGN_TOOL_JAR:-$DEVECO_SDK_HOME/default/openharmony/toolchains/lib/hap-sign-tool.jar}"
JAVA_BIN="${JAVA_BIN:-${JAVA_HOME:+$JAVA_HOME/bin/java}}"
JAVA_BIN="${JAVA_BIN:-$(command -v java || true)}"
