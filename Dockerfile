# Jev-Interaction call server.  docker compose up   (keys from .env)
# In mainland China: docker build --build-arg PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ .
FROM python:3.12-slim
ARG PIP_INDEX_URL=https://pypi.org/simple
ENV PIP_INDEX_URL=${PIP_INDEX_URL} PIP_NO_CACHE_DIR=1 PYTHONUNBUFFERED=1 PORT=8080
RUN apt-get update && apt-get install -y --no-install-recommends libc++1 && rm -rf /var/lib/apt/lists/*   # TEN VAD's native library
WORKDIR /app
COPY pyproject.toml README.md ./
COPY jev_interaction ./jev_interaction
# The caller's voiceprint (speechbrain + CPU-only torch, ~1 GB more image): on by default, as in our product.
# docker build --build-arg VOICEPRINT=0 . leaves it out; the call then runs without it.
ARG VOICEPRINT=1
# The sound of the voice for "have they finished" (SmartTurn v3.2, onnxruntime, ~20 MB): on by default; --build-arg SOUND=0
ARG SOUND=1
RUN EXTRAS=server; [ "$SOUND" = "1" ] && EXTRAS="$EXTRAS,sound"; \
    if [ "$VOICEPRINT" = "1" ]; then pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu \
      && pip install ".[$EXTRAS,voiceprint]"; else pip install ".[$EXTRAS]"; fi
EXPOSE 8080
# /app is the working folder: .env, runs/ and your own profiles/ are read from here (see docker-compose.yml)
CMD ["sh", "-c", "jev-interaction serve --host 0.0.0.0 --port ${PORT}"]
