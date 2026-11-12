# Jev-Interaction call server.  docker compose up   (keys from .env)
# In mainland China: docker build --build-arg PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ .
FROM python:3.12-slim
ARG PIP_INDEX_URL=https://pypi.org/simple
ENV PIP_INDEX_URL=${PIP_INDEX_URL} PIP_NO_CACHE_DIR=1 PYTHONUNBUFFERED=1 PORT=8080
WORKDIR /app
COPY pyproject.toml README.md ./
COPY jev_interaction ./jev_interaction
RUN pip install ".[server]"
COPY server ./server
COPY web ./web
COPY examples ./examples
EXPOSE 8080
CMD ["sh", "-c", "uvicorn server.app:app --host 0.0.0.0 --port ${PORT}"]
