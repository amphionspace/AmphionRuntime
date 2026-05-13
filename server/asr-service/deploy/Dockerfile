# AmphionRuntime ASR gRPC 服务的容器镜像；CPU 推理版本。
#
# 多阶段构建：
#   1) builder：基于 ubuntu:22.04 + 完整工具链编译 sherpa-onnx + asr_service
#   2) runtime：基于 ubuntu:22.04-slim，只带运行时所需的 .so + 二进制
#
# 构建：
#   docker build -t your-registry/asr-service:1.1.0 \
#                -f server/asr-service/deploy/Dockerfile .
#
# 运行：
#   docker run --rm -it -p 50051:50051 -p 9090:9090 \
#       -v $PWD/model:/etc/asr-service/model:ro \
#       -v $PWD/manifest.json:/etc/asr-service/manifest.json:ro \
#       your-registry/asr-service:1.1.0

# =================================== Builder ===================================
FROM ubuntu:22.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl wget git \
        build-essential cmake ninja-build pkg-config \
        protobuf-compiler libprotobuf-dev \
        libgrpc++-dev protobuf-compiler-grpc \
        nlohmann-json3-dev \
        libgflags-dev \
        libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# prometheus-cpp 必须从源码编（apt 上没有 1.x 稳定版本）
RUN git clone --depth 1 --branch v1.2.4 https://github.com/jupp0r/prometheus-cpp.git /tmp/pcpp \
    && cd /tmp/pcpp && git submodule update --init \
    && mkdir build && cd build \
    && cmake -DBUILD_SHARED_LIBS=ON -DENABLE_PUSH=OFF -DENABLE_COMPRESSION=OFF .. \
    && cmake --build . -j$(nproc) \
    && cmake --install . \
    && rm -rf /tmp/pcpp

WORKDIR /src

# 拷源代码（包含 sherpa-onnx 仓库本身）
COPY . /src

# 1) 编 sherpa-onnx cxx-api（动态库 + 头文件 install 到 /opt/sherpa-onnx）
RUN mkdir -p /src/build-linux \
    && cd /src/build-linux \
    && cmake -DCMAKE_BUILD_TYPE=Release \
             -DCMAKE_INSTALL_PREFIX=/opt/sherpa-onnx \
             -DBUILD_SHARED_LIBS=ON \
             -DSHERPA_ONNX_ENABLE_PYTHON=OFF \
             -DSHERPA_ONNX_ENABLE_TESTS=OFF \
             -DSHERPA_ONNX_ENABLE_BINARY=OFF \
             -DSHERPA_ONNX_ENABLE_PORTAUDIO=OFF \
             -DSHERPA_ONNX_BUILD_C_API_EXAMPLES=OFF \
             .. \
    && cmake --build . -j$(nproc) \
    && cmake --install .

# 2) 编 asr_service
RUN mkdir -p /src/server/asr-service/build \
    && cd /src/server/asr-service/build \
    && cmake -DCMAKE_BUILD_TYPE=Release \
             -DSHERPA_ONNX_DIR=/opt/sherpa-onnx \
             -DCMAKE_INSTALL_PREFIX=/opt/asr-service \
             .. \
    && cmake --build . -j$(nproc) \
    && cmake --install .

# =================================== Runtime ===================================
FROM ubuntu:22.04 AS runtime

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        libstdc++6 libc6 libssl3 \
    && rm -rf /var/lib/apt/lists/*

# sherpa-onnx 动态库 + onnxruntime
COPY --from=builder /opt/sherpa-onnx/lib/* /usr/local/lib/
COPY --from=builder /opt/asr-service/bin/asr_service /usr/local/bin/asr_service
COPY --from=builder /usr/local/lib/libprometheus-cpp-* /usr/local/lib/

RUN ldconfig

EXPOSE 50051 9090

# 健康检查（k8s liveness 推荐用 grpc_health_probe；这里用 timeout + bash + nc 兜底）
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
    CMD bash -c 'echo > /dev/tcp/127.0.0.1/50051' || exit 1

ENTRYPOINT ["/usr/local/bin/asr_service"]
CMD ["--listen=0.0.0.0:50051", \
     "--metrics_listen=0.0.0.0:9090", \
     "--manifest=/etc/asr-service/manifest.json", \
     "--num_threads=4"]
