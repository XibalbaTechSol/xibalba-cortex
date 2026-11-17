FROM ghcr.io/astral-sh/uv:0.11 AS uv
FROM python:3.12-slim
COPY --from=uv /uv /bin/uv
WORKDIR /app/super-cortex

RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Pin integrity-core to exact SHA so Docker layer cache invalidates on pin bump
COPY deploy/integrity-core.ref /tmp/integrity-core.ref
RUN ref=$(tr -d '[:space:]' < /tmp/integrity-core.ref) \
    && git init -q /app/integrity-core \
    && git -C /app/integrity-core fetch -q --depth 1 https://github.com/XibalbaTechSol/integrity-core.git "$ref" \
    && git -C /app/integrity-core checkout -q FETCH_HEAD \
    && test "$(git -C /app/integrity-core rev-parse HEAD)" = "$ref" \
    && uv pip install --system --no-cache /app/integrity-core/integrity-sdk "requests>=2.31.0"

COPY pyproject.toml README.md ./
COPY src ./src
COPY viewer /app/viewer

RUN uv pip install --system --no-cache . \
    && useradd --system --uid 10001 --create-home cortex \
    && install -d -o cortex -g cortex /data/cortex-managed

ENV CORTEX_MANAGED_HOME=/data/cortex-managed
ENV SUPER_CORTEX_DB_PATH=/data/cortex-managed/provenance.db
USER cortex
EXPOSE 10000
VOLUME ["/data/cortex-managed"]
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:10000/healthz', timeout=3)"
CMD ["python", "-m", "super_cortex.api", "--host", "0.0.0.0", "--port", "10000", "--viewer-dist", "/app/viewer"]
