FROM python:3.12-slim

# Cortex depends on the sibling integrity-sdk checkout in pyproject.toml.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/xibalba-cortex
COPY integrity-core/integrity-sdk /app/integrity-core/integrity-sdk
COPY xibalba-cortex/pyproject.toml xibalba-cortex/uv.lock xibalba-cortex/README.md ./
COPY xibalba-cortex/src ./src
COPY xibalba-cortex/spec ./spec
# The HTTP API does not import the optional embedding worker. Keep the API image lean; build/run embedding_worker.py separately when model inference is required.
RUN pip install --no-cache-dir /app/integrity-core/integrity-sdk "mcp>=1.0.0" "eth-hash[pycryptodome]>=0.7.0" "sqlite-vec>=0.1.9" "pyyaml>=6.0" "uvicorn>=0.30"
RUN pip install --no-cache-dir . --no-deps

ENV XIBALBA_CORTEX_HOME=/data/cortex
VOLUME ["/data/cortex"]
EXPOSE 8420
CMD ["python", "-m", "xibalba_cortex.local_api", "--home", "/data/cortex", "--host", "0.0.0.0", "--port", "8420", "--allowed-origin", "http://localhost:5173"]
