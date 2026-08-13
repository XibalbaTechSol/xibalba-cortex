# xibalba-cortex viewer

Standalone graph visualization and local operator surface for `xibalba-cortex`. The viewer exposes graph, timeline, lexical Recall, inference task, PARA review, and Integrity views. It is a local prototype and is not a production deployment.

The local API includes both read routes and bounded mutating `POST` routes for recording exchanges, creating propositions, linking entities, lifecycle changes, inference claims/completions, and PARA decisions. Bind it to loopback and set an explicit allowed origin when running the viewer; it has no built-in authentication.

## Run

1. Start the local operator API from the `xibalba-cortex` project root:
   ```bash
   uv run python -m xibalba_cortex.local_api \
     --home ~/.hermes/xibalba-cortex \
     --host 127.0.0.1 \
     --allowed-origin http://localhost:5190
   ```
2. In this directory:
   ```bash
   npm install
   npm run dev
   ```
   Opens on `http://localhost:5190` (fixed, non-default port -- avoids the Dockerized
   `integrity-dashboard` instances on 5173/5174).

Set `VITE_LOCAL_API_URL` to point at a non-default `local_api.py` host/port.
