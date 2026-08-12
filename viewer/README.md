# xibalba-cortex viewer

Standalone graph visualization for `xibalba-cortex`. Not yet integrated into
`integrity-mvp` (that app has no routing/API-client scaffold yet) -- run this locally first,
integrate once validated against real data.

## Run

1. Start the read-only local API from the `xibalba-cortex` project root:
   ```
   .venv/bin/python -m xibalba_cortex.local_api --home ~/.hermes/xibalba-cortex --allowed-origin http://localhost:5190
   ```
2. In this directory:
   ```
   npm install
   npm run dev
   ```
   Opens on `http://localhost:5190` (fixed, non-default port -- avoids the Dockerized
   `integrity-dashboard` instances on 5173/5174).

Set `VITE_LOCAL_API_URL` to point at a non-default `local_api.py` host/port.
