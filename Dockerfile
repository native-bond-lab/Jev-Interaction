# Jev-Interaction call server.  docker compose up   (keys from .env)
# In mainland China: docker build --build-arg PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ .
FROM python:3.12-slim
ARG PIP_INDEX_URL=https://pypi.org/simple
ENV PIP_INDEX_URL=${PIP_INDEX_URL} PIP_NO_CACHE_DIR=1 PYTHONUNBUFFERED=1 PORT=8080
RUN apt-get update && apt-get install -y --no-install-recommends libc++1 && rm -rf /var/lib/apt/lists/*   # TEN VAD's native library
WORKDIR /app
COPY pyproject.toml README.md ./
COPY jev_interaction ./jev_interaction
RUN pip install ".[server]"
EXPOSE 8080
# /app is the working folder: .env, runs/ and your own profiles/ are read from here (see docker-compose.yml)
CMD ["sh", "-c", "jev-interaction serve --host 0.0.0.0 --port ${PORT}"]
