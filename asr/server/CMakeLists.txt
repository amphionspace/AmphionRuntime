cmake_minimum_required(VERSION 3.18)
project(asr_service CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
option(ASR_ENABLE_PROMETHEUS "Build with prometheus-cpp metrics exporter" OFF)

# 外部依赖
find_package(Protobuf REQUIRED)
find_package(PkgConfig REQUIRED)
pkg_check_modules(GRPCPP REQUIRED grpc++)
find_program(GRPC_CPP_PLUGIN grpc_cpp_plugin REQUIRED)
find_package(nlohmann_json 3.10 REQUIRED)
if(ASR_ENABLE_PROMETHEUS)
    find_package(prometheus-cpp CONFIG REQUIRED)
endif()
find_package(gflags REQUIRED)
find_package(Threads REQUIRED)

# sherpa-onnx：调用方传 -DSHERPA_ONNX_DIR 指向 install 目录
if(NOT SHERPA_ONNX_DIR)
    message(FATAL_ERROR "请用 -DSHERPA_ONNX_DIR=<sherpa-onnx install 目录> 配置 cmake")
endif()
set(SHERPA_ONNX_INC "${SHERPA_ONNX_DIR}/include")
set(SHERPA_ONNX_LIB "${SHERPA_ONNX_DIR}/lib")
include_directories(${SHERPA_ONNX_INC})
link_directories(${SHERPA_ONNX_LIB})

# proto 生成
set(PROTO_SRC ${CMAKE_CURRENT_SOURCE_DIR}/proto/asr.proto)
set(PROTO_OUT ${CMAKE_CURRENT_BINARY_DIR}/proto-gen)
file(MAKE_DIRECTORY ${PROTO_OUT})

set(PROTO_HDRS ${PROTO_OUT}/asr.pb.h ${PROTO_OUT}/asr.grpc.pb.h)
set(PROTO_SRCS ${PROTO_OUT}/asr.pb.cc ${PROTO_OUT}/asr.grpc.pb.cc)

add_custom_command(
    OUTPUT ${PROTO_HDRS} ${PROTO_SRCS}
    COMMAND ${Protobuf_PROTOC_EXECUTABLE}
        --proto_path=${CMAKE_CURRENT_SOURCE_DIR}/proto
        --cpp_out=${PROTO_OUT}
        --grpc_out=${PROTO_OUT}
        --plugin=protoc-gen-grpc=${GRPC_CPP_PLUGIN}
        ${PROTO_SRC}
    DEPENDS ${PROTO_SRC}
    VERBATIM
)
include_directories(${PROTO_OUT})

# 主服务
add_executable(asr_service
    src/main.cc
    src/asr_service.cc
    src/decode_engine.cc
    src/decode_engine_pool.cc
    src/recognizer_factory.cc
    src/manifest.cc
    src/metrics.cc
    src/flags.cc
    ${PROTO_SRCS}
)

target_link_libraries(asr_service
    PRIVATE
    sherpa-onnx-cxx-api
    sherpa-onnx-c-api
    onnxruntime
    ${GRPCPP_LIBRARIES}
    grpc++_reflection
    protobuf::libprotobuf
    nlohmann_json::nlohmann_json
    gflags
    Threads::Threads
)

if(ASR_ENABLE_PROMETHEUS)
    target_compile_definitions(asr_service PRIVATE ASR_ENABLE_PROMETHEUS)
    target_link_libraries(asr_service
        PRIVATE
        prometheus-cpp::core
        prometheus-cpp::pull
    )
endif()

install(TARGETS asr_service DESTINATION bin)
