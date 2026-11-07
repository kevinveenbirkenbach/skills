FROM python:3.12-slim AS whisper

RUN apt-get update && apt-get install --yes --no-install-recommends build-essential cmake git && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 --branch v1.9.5 https://github.com/ggml-org/whisper.cpp /src \
    && test "$(cd /src && git rev-parse HEAD)" = d1be6fde11ac6e0407606b4e42fe72d34add8037 \
    && cmake -S /src -B /build -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF -DGGML_OPENMP=OFF -DWHISPER_BUILD_TESTS=OFF \
    && cmake --build /build --config Release --target whisper-cli --parallel \
    && install -D --mode=0755 /build/bin/whisper-cli /out/whisper-cli

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install --yes --no-install-recommends git && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --root-user-action=ignore --requirement /app/requirements.txt

COPY requirements-piper.txt /opt/piper/requirements.txt
RUN python3 -m venv --without-pip /opt/piper \
    && pip --python /opt/piper/bin/python install --no-cache-dir --root-user-action=ignore --require-hashes --only-binary=:all: --requirement /opt/piper/requirements.txt

ADD --checksum=sha256:9127a559e11603f10b366d1a20ac7426826081dbc521de4c2420c57728d73f0f --chmod=0644 \
    https://huggingface.co/rhasspy/piper-voices/resolve/e7229f7d33a10e145e109b886d661984201ac3c4/en/en_US/libritts/high/en_US-libritts-high.onnx \
    /opt/voices/en_US-libritts-high.onnx
ADD --checksum=sha256:2efdc6d7f954588b8180132cbd9b8001933fdd00932c92bc92fd0d2028a9eb3d --chmod=0644 \
    https://huggingface.co/rhasspy/piper-voices/resolve/e7229f7d33a10e145e109b886d661984201ac3c4/en/en_US/libritts/high/en_US-libritts-high.onnx.json \
    /opt/voices/en_US-libritts-high.onnx.json
ADD --checksum=sha256:c577b9a86e7e048a0b7eada054f4dd79a56bbfa911fbdacf900ac5b567cbb7d9 --chmod=0644 \
    https://huggingface.co/ggerganov/whisper.cpp/resolve/5359861c739e955e79d9a303bcbc70fb988958b1/ggml-base-q8_0.bin \
    /opt/whisper/ggml-base-q8_0.bin
COPY --from=whisper /out/whisper-cli /opt/whisper/whisper-cli
# ADD --chmod=0644 also gives the directories it creates mode 0644; without the search bit the non-root hub finds no voice and no whisper.cpp
RUN chmod 0755 /opt/voices /opt/whisper

COPY server.py /app/server.py
COPY kvb_orchestrator /app/kvb_orchestrator
COPY client/signing.py /app/client/signing.py
COPY templates /app/templates
COPY vendor /app/vendor

ENTRYPOINT ["python3", "/app/server.py"]
