# syntax=docker/dockerfile:1.7
FROM node:22-bookworm-slim AS web
WORKDIR /src
RUN corepack enable
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/package.json
COPY apps/desktop/package.json apps/desktop/package.json
RUN pnpm install --frozen-lockfile --filter @aibox/web...
COPY apps/web apps/web
RUN pnpm --filter @aibox/web build

FROM python:3.12-slim AS runtime
ARG INSTALL_CUDA=0
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY services/api /app/api
COPY examples /app/examples
RUN if [ "$INSTALL_CUDA" = "1" ]; then \
        python -m pip install "/app/api[asr,cuda12]"; \
    else \
        python -m pip install "/app/api[asr]"; \
    fi
COPY --from=web /src/apps/web/dist /app/web
RUN useradd --create-home --uid 10001 aibox \
    && mkdir -p /data \
    && chown -R aibox:aibox /data /app
USER aibox
ENV AIBOX_WEB_DIST=/app/web \
    AIBOX_REPO_ROOT=/app \
    AIBOX_DATA_DIR=/data \
    AIBOX_HOST=0.0.0.0 \
    AIBOX_PORT=8765 \
    AIBOX_GRPC_HOST=0.0.0.0 \
    AIBOX_GRPC_PORT=50051 \
    AIBOX_MRCP_HOST=0.0.0.0 \
    AIBOX_MRCP_PORT=8060 \
    AIBOX_MRCP_CONTROL_PORT=8061 \
    AIBOX_MRCP_RTP_PORT_START=50000 \
    AIBOX_MRCP_RTP_PORT_END=50100
EXPOSE 8765 50051 8060/udp 8061/tcp 50000-50100/udp
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=3)"
CMD ["python", "-m", "aibox_api", "--host", "0.0.0.0", "--port", "8765"]
