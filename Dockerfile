FROM ghcr.io/astral-sh/uv:0.11 AS uv
FROM python:3.12-slim
COPY --from=uv /uv /bin/uv
WORKDIR /app/super-cortex

COPY pyproject.toml README.md ./
COPY src ./src
COPY viewer /app/viewer

RUN uv pip install --system --no-cache . \
    && useradd --system --uid 10001 --create-home cortex \
    && install -d -o cortex -g cortex /data/super-cortex

ENV CORTEX_MANAGED_HOME=/data/super-cortex
ENV SUPER_CORTEX_DB_PATH=/data/super-cortex/provenance.db
USER cortex
EXPOSE 8420
VOLUME ["/data/super-cortex"]
CMD ["python", "-m", "super_cortex.api", "--host", "0.0.0.0", "--port", "8420", "--viewer-dist", "/app/viewer"]
