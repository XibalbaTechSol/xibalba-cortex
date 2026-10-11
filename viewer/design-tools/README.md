# Design tools

The scripts that turn the **running console** into the mockups on the Claude Design canvas, so a
mockup is a snapshot of what is built and cannot drift from it. Nothing here ships; it is for whoever
maintains the mockups. Read `../HANDOFF.md` first.

## The pipeline

```
reseed.sh ──► dev API (:8420) + fixture data
vite dev (:5190, CORTEX_HOME=<fixture home>) ── proxies /cortex-api with a dev operator token
      │
capture.mjs ──► boards-src/<name>.json   (outerHTML of .xc, canvases rasterised to <name>-canvas-N.png)
              + boards-png/<name>.png    (a screenshot, for looking at)
      │
(upload each unique raster to the canvas artifact as an asset; write canvas-images.json: name → /_blob/<id>)
      │
planned.py ──► boards-src/planned-*.json (planned designs: a captured shell + authored markup + a banner)
      │
build_boards.py ──► canvas-publish/project/*.dc.html + canvas.json   and   ../DESIGN.md
measure.mjs      (natural height of the planned boards; run build_boards.py again afterwards)
render.mjs       (renders built boards locally to a PNG, for a quick look; image assets are blank offline)
```

## Environment

| Variable | Meaning | Default |
|---|---|---|
| `DESIGN_WORK` | the working folder: `boards-src/`, `boards-png/`, `canvas-live/`, `canvas-publish/`, `canvas-images.json` | `.` |
| `CORTEX_HOME` | the fixture profile `reseed.sh` seeds and Vite proxies to | `$DESIGN_WORK/cortex-home` |
| `VIEWER_URL` | where Vite is serving | `http://127.0.0.1:5190/` |
| `CHROMIUM_PATH` | a Chromium for Playwright | `/opt/pw-browsers/chromium` |
| `PYTHON` | the interpreter that has `xibalba_cortex` installed | `python3` |

Chromium needs software WebGL for the 3D lens; `capture.mjs` launches it with
`--use-gl=angle --use-angle=swiftshader --enable-unsafe-swiftshader --ignore-gpu-blocklist`.

## Running it

```bash
export DESIGN_WORK=$PWD/work && mkdir -p $DESIGN_WORK/{boards-src,boards-png} && cd $DESIGN_WORK
bash ../design-tools/reseed.sh both                      # fixture + API on :8420
(cd .. && CORTEX_HOME=$DESIGN_WORK/cortex-home npx vite --host 127.0.0.1 --port 5190 &)
node ../design-tools/capture.mjs                         # every board; or: capture.mjs name1,name2
```

- **Restart the API after pulling backend changes.** A stale API process answered `/api/search` with 404
  for a whole session; the code on disk was fine.
- `capture.mjs` takes about 25 minutes for the full set (the 3D lens settles on every board).
- A board that fails prints `FAIL <name>` and leaves `boards-png/<name>-FAIL.png`; fix the selector and
  rerun just that name.

## Honesty rules the boards keep

- A **built** board is the console's own output. Four kinds are stubbed at the network layer because the
  fixture cannot produce them, and each says so in `build_boards.py`'s note and in `DESIGN.md`:
  the signed-in **Account** data, the **sign-in** errors, the **Recall** refusal, and the **empty** graph
  and timeline. The response shapes are the real ones (`accounts.py`, `store.py`), the values are
  illustrative.
- A **planned** board carries a "Planned — not built" banner naming the route it needs. It is composed
  from components the console already has, so building it is wiring, not new design.

## Updating the canvas

`build_boards.py` expects the live `canvas.json` at `canvas-live/project/canvas.json` (read it from the
artifact first) and keeps its `designSystems`, `launch` and round-1 notes. Publish with the Artifact tool
(`root` = `canvas-publish`, `file_path` = its `project/canvas.json`, `files` = the boards that changed).
Upload rasters as assets first; the build reads their urls from `canvas-images.json`.
