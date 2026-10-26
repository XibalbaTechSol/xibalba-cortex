# Build context is this repository; the SDK is a separate named context.
# Local operator data and credentials are excluded by .dockerignore.
FROM node:22-slim AS viewer
WORKDIR /build
COPY viewer/package.json viewer/package-lock.json ./
RUN npm ci
COPY viewer/ ./
ENV VITE_CORTEX_EDITION=managed
RUN npm run build

FROM ghcr.io/astral-sh/uv:0.11 AS uv
FROM python:3.12-slim
COPY --from=uv /uv /bin/uv
WORKDIR /app/xibalba-cortex
COPY --from=integrity_sdk / /app/integrity-core/integrity-sdk
COPY pyproject.toml uv.lock README.md ./
# Inference/embeddings are explicitly disabled in this service. Pruning the
# worker's ML stack avoids shipping Torch/model dependencies in the control-plane image.
RUN uv export --frozen --extra managed --no-dev --prune sentence-transformers --no-emit-project --output-file /tmp/requirements.txt \
    && uv pip install --system --no-cache -r /tmp/requirements.txt \
    && useradd --system --uid 10001 --create-home cortex \
    && install -d -o cortex -g cortex /data/cortex-managed
COPY src ./src
RUN uv pip install --system --no-deps .
COPY --from=viewer /build/dist /app/viewer
ENV CORTEX_MANAGED_HOME=/data/cortex-managed
USER cortex
EXPOSE 8430
VOLUME ["/data/cortex-managed"]
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8430/healthz', timeout=3)"
CMD ["python", "-m", "xibalba_cortex.managed.api", "--host", "0.0.0.0", "--port", "8430", "--viewer-dist", "/app/viewer"]
