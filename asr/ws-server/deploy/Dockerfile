FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY asr/ws-server /app/asr/ws-server

RUN python3 -m pip install --no-cache-dir --upgrade pip \
    && python3 -m pip install --no-cache-dir \
        "sherpa-onnx==1.13.3+cuda12.cudnn9" \
        -f https://k2-fsa.github.io/sherpa/onnx/cuda.html \
    && python3 -m pip install --no-cache-dir -e /app/asr/ws-server --no-deps

EXPOSE 8010 9100

ENTRYPOINT ["amphion-asr-ws"]
CMD ["--listen=0.0.0.0:8010", "--metrics-listen=0.0.0.0:9100", "--provider=cuda", "--manifest=/etc/asr-ws/manifest.json", "--max-batch-size=50", "--max-wait-ms=10"]
