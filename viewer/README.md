# xibalba-cortex viewer

Standalone graph visualization and local operator surface for `xibalba-cortex`. The viewer exposes graph, timeline, lexical Recall, inference task, PARA review, and Integrity views. It is a local prototype and is not a production deployment.

The local API includes both read routes and bounded mutating `POST` routes for recording exchanges, creating propositions, linking entities, lifecycle changes, inference claims/completions, and PARA decisions. Bind it to loopback and set an explicit allowed origin when running the viewer. Every route except `/healthz`, `/readyz`, and `/metrics` requires the same bearer-token auth as the streamable-HTTP MCP transport -- there is no unauthenticated fallback.

## Run

1. Issue a token for the viewer (once per profile home):
   ```bash
   uv run xibalba-cortex-ingest-tokens --home ~/.hermes/xibalba-cortex issue --label viewer --role reader
   ```
   Use `--role writer` instead if you'll use the viewer's write actions (e.g. "Build Exchanges").
   Save the printed token -- it's shown once.
2. Start the local operator API from the `xibalba-cortex` project root:
   ```bash
   uv run python -m xibalba_cortex.local_api \
     --home ~/.hermes/xibalba-cortex \
     --host 127.0.0.1 \
     --allowed-origin http://localhost:5190
   ```
3. In this directory, start the viewer:
   ```bash
   npm install
   npm run dev
   ```
4. Open the viewer and enter the token from step 1. The token is stored only in the current
   browser tab's `sessionStorage`; it is not embedded into the Vite bundle or persisted after
   the tab closes. `VITE_LOCAL_API_URL` may still be set when the API is not at
   `http://localhost:8420`.
   Opens on `http://localhost:5190` (fixed, non-default port -- avoids the Dockerized
   `integrity-dashboard` instances on 5173/5174).

Set `VITE_LOCAL_API_URL` to point at a non-default `local_api.py` host/port.
