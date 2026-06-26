# AmphionRuntime ASR gRPC 服务端 —— CPU 推理镜像。
# GPU(CUDA) 部署见同目录 Dockerfile.gpu（推荐，并发更高，见 ../BENCHMARK.md）。
#
# 多阶段构建：
#   1) builder：ubuntu:22.04 + 工具链，编 sherpa-onnx(CPU) + asr_service
#   2) runtime：ubuntu:22.04，只带运行期 .so + 二进制
#
# 构建（在仓库根目录执行）：
#   docker build -t your-registry/asr-service:1.1.0 \
#                -f asr/server/deploy/Dockerfile .
#
# 运行：
#   docker run --rm -it -p 50051:50051 \
#       -v /abs/path/model:/etc/asr-service/model:ro \
#       -v /abs/path/manifest.json:/etc/asr-service/manifest.json:ro \
#       your-registry/asr-service:1.1.0
#   注意 manifest.json 里的 model_dir 要写成容器内路径 /etc/asr-service/model。

# =================================== Builder ===================================
FROM ubuntu:22.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl wget git unzip \
        build-essential cmake ninja-build pkg-config \
        protobuf-compiler libprotobuf-dev \
        libgrpc++-dev protobuf-compiler-grpc \
        nlohmann-json3-dev \
        libgflags-dev \
        libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src

# 只拷构建所需的两棵源码树，避免把其它模块/敏感物带进镜像。
COPY third_party/sherpa-onnx /src/third_party/sherpa-onnx
COPY asr/server             /src/asr/server

# 1) 编 sherpa-onnx cxx-api（CPU）。会联网下载 onnxruntime(CPU)。
RUN cmake -S /src/third_party/sherpa-onnx -B /tmp/sherpa-build \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX=/opt/sherpa-onnx \
        -DBUILD_SHARED_LIBS=ON \
        -DSHERPA_ONNX_ENABLE_GPU=OFF \
        -DSHERPA_ONNX_ENABLE_C_API=ON \
        -DSHERPA_ONNX_ENABLE_PYTHON=OFF \
        -DSHERPA_ONNX_ENABLE_TESTS=OFF \
        -DSHERPA_ONNX_ENABLE_BINARY=OFF \
        -DSHERPA_ONNX_ENABLE_PORTAUDIO=OFF \
        -DSHERPA_ONNX_ENABLE_TTS=OFF \
        -DSHERPA_ONNX_BUILD_C_API_EXAMPLES=OFF \
    && cmake --build /tmp/sherpa-build -j"$(nproc)" \
    && cmake --install /tmp/sherpa-build

# 2) 编 asr_service。
RUN cmake -S /src/asr/server -B /tmp/asr-build \
        -DCMAKE_BUILD_TYPE=Release \
        -DSHERPA_ONNX_DIR=/opt/sherpa-onnx \
        -DCMAKE_INSTALL_PREFIX=/opt/asr-service \
    && cmake --build /tmp/asr-build -j"$(nproc)" \
    && cmake --install /tmp/asr-build

# =================================== Runtime ===================================
FROM ubuntu:22.04 AS runtime

ENV DEBIAN_FRONTEND=noninteractive

# 运行期共享库：libgrpc++1 会自动带出 libgrpc10 / libprotobuf23 / libabsl* / 反射库。
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        libgrpc++1 \
        libgflags2.2 \
        libssl3 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/sherpa-onnx/lib/        /usr/local/lib/
COPY --from=builder /opt/asr-service/bin/asr_service /usr/local/bin/asr_service

RUN ldconfig

ENV LD_LIBRARY_PATH=/usr/local/lib:${LD_LIBRARY_PATH}

EXPOSE 50051

HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
    CMD bash -c 'echo > /dev/tcp/127.0.0.1/50051' || exit 1

ENTRYPOINT ["/usr/local/bin/asr_service"]
CMD ["--listen=0.0.0.0:50051", \
     "--manifest=/etc/asr-service/manifest.json", \
     "--provider=cpu", \
     "--num_threads=4", \
     "--metrics_listen="]
