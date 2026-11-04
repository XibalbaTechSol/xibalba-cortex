# Report — Cortex hero logo resolution

**Verdict: the brief's fallback clause applies. The artwork cannot fill 840x780 from any
source on this machine. The HiDPI softness is the master's resolution ceiling, not a
pipeline defect. No asset was regenerated.**

## 1. Provenance of `cortex-lockup-hero.png` — established, bit-exact

The brief asked that the asset's composition be established before regenerating, so the
same artwork is reproduced rather than a different crop. It is:

```
invert_to_white('~/Pictures/cortex-logos/cortex-brain-compact-transparent.png',
                'public/cortex-lockup-hero.png', out_w=560)   # pad=6, gamma=0.7, dilate=1
```

Verified by regenerating and differencing against the committed file:

| check | result |
| --- | --- |
| regenerated size | 560x520 (matches) |
| `ImageChops.difference(...).getbbox()` | `None` |
| per-channel extrema R/G/B/A | `(0,0)` on all four |

So the shipped asset is bit-identical to the pipeline's output. Nothing is stale, and the
1.08:1 ratio is simply the compact master's ink bounding box, not a hand crop.

## 2. The ceiling — measured

The ink bounding box of every candidate source, measured with the script's own ink rule
(`FRAME=3` trim, luminance `<=200` is ink):

| source | canvas | ink bbox | same artwork? |
| --- | --- | --- | --- |
| `cortex-logos/cortex-brain-compact-transparent.png` | 1280x670 | **551x511** | yes — this is the hero's master |
| `cortex-logos/cortex-brain-compact.jpg` | 1280x670 | 551x511 | yes, same ink, JPEG |
| `cortex-logos/cortex-brain-display-transparent.png` | 1280x670 | 552x572 | no — display variant, 0.97:1 |
| `cortex-logos/cortex-wordmark*.png` | 1280x670 | none / 754x371 | no — wordmark only |
| `Cortex_Assets/cortex-plugin-icon-high-resolution.png` | 1254x1254 | 1122x1108 | **no** — different lockup: tagline *outside* the brain, spiral glyph in the X |
| `Cortex_Assets/CortexBWlogo.png` | 1424x745 | 608x633 | no — same outside-tagline variant, and still < 840 |
| `Cortex_Assets/cortex-logo-ui.png`, `cortex-logo-public-landing.png` | 1440x1000 | full canvas | no — page screenshots, not artwork |
| `Cortex_Assets/xibalba-cortex-logo-drafts.svg` | 1600x1000 | — | no — an unrelated four-direction concept sheet |

Searched `~/Pictures`, `~/Downloads`, `~/Desktop`, `/mnt/storage` for `*cortex*`/`*brain*`
in png/jpg/webp/svg/pdf/tiff. **No vector and no raster of this exact lockup exists above
551px of ink.**

The key number: the shipped asset samples that box at **560 / 563 padded = 0.995:1**. It
already carries every pixel the master has. 840 would be a **1.49x interpolation**.

## 3. Device-pixel ratios

| use | CSS size | asset | DPR at 1x | DPR at 2x | 2x needs |
| --- | --- | --- | --- | --- | --- |
| `Landing.tsx:71` `.xc-landing-mark` | 420x390 (280 under 760px) | 560x520 | 1.33 | **0.67** | 840x780 |
| `SignIn.tsx:134` `.xc-auth-story .xc-brand-lockup` | 300x279 | 560x520 | 1.87 | **0.93** | 600x558 |

So the user's report is real: on a HiDPI screen the landing hero is upscaled ~1.5x by the
browser. It is not fixable from the artwork that exists.

Scope note: below the 760px breakpoint `.xc-landing-mark` caps at 280px, so the existing
560 asset is already exactly **2.00x** there. Only desktop HiDPI is short (and 3x phones,
at 0.67x). This is a desktop-only defect.

## 4. Would an 840 asset help anyway? Measured where stated

Alpha percentiles over ink pixels (alpha > 8), the way the script's docstring states them.

**(a) An 840 regenerated from the master is indistinguishable from a naive upscale of the
shipped 560 — i.e. it carries no new detail:**

| asset | size | ink px | coverage | p10 | p50 | p90 | mean | >= 200 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A. shipped 560 (native) | 560x520 | 70,489 | 24.21% | 18 | 255 | 255 | 201.3 | 72.8% |
| B. pipeline-generated 840 | 840x780 | 158,112 | 24.13% | 21 | 255 | 255 | 201.9 | 72.9% |
| B2. shipped 560 LANCZOS'd to 840, no restretch | 840x780 | 160,611 | 24.51% | 21 | 254 | 255 | 198.3 | 71.1% |

`|B - B2|` alpha: **mean 1.55 / 255, 97.4% of pixels within 16**. Regenerating from the
master recovers essentially nothing over a dumb resize, because the master has nothing
left to recover.

**(b) The docstring's wash-out failure mode does not occur at hero scale.** That mode was
measured on the *rail* mark (248px asset painted at 24-44px, alpha p50 62 against 183).
At 24% ink coverage and 300-420 CSS px the strokes are not hairline, and resampling in
either direction barely moves the alpha. The rows below are PIL `BILINEAR` resamples used
as a stand-in for the browser's resize; no browser decode was read back for them, so treat
them as indicative of the direction and magnitude, not as browser-measured values:

| resample (PIL BILINEAR stand-in for the browser's — NOT a browser readback) | size | p50 | mean | >= 200 |
| --- | --- | --- | --- | --- |
| 420 box @2x — 560 asset upscaled to 840 | 840x780 | 253 | 190.9 | 67.0% |
| 420 box @2x — 840 asset, 1:1 | 840x780 | 255 | 201.9 | **72.9%** |
| 420 box @1x — 560 asset down to 420 | 420x390 | 250 | 185.8 | 64.0% |
| 420 box @1x — 840 asset down to 420 | 420x390 | 249 | 186.5 | 63.9% |
| 300 box @2x — 560 asset up to 600 | 600x557 | 253 | 192.7 | 67.6% |
| 300 box @2x — 840 asset down to 600 | 600x557 | 253 | 192.0 | 67.8% |
| 300 box @1x — 560 asset down to 300 | 300x279 | 239 | 181.4 | 59.4% |
| 300 box @1x — 840 asset down to 300 | 300x279 | 238 | 180.3 | 59.1% |

So an 840 asset would buy a ~6pp gain in edge contrast at the landing hero on 2x screens
(67.0% -> 72.9% of ink at alpha >= 200), nothing at the sign-in use, and nothing at 1x —
in exchange for 2.25x the pixels and 1.97x the bytes (161,784 against 82,043), all of them
interpolated rather than drawn. A visual A/B
of the wordmark at 2x confirms the character: the 840 version is marginally cleaner at the
stroke edges, and exactly as soft in the letterforms. The blur the user sees is the
artwork, not the resampler.

Under the brief's own rule — "say so with the measurement rather than shipping a soft
upscale" — that is not a fix, so it was not shipped.

## 5. Audit of the other marks — each against its own largest CSS size

| asset | natural | largest CSS use | DPR | verdict |
| --- | --- | --- | --- | --- |
| `cortex-rail-mark.png` | 88x82 | 44px (`.xc-shell[data-collapsed] .xc-brand-mark img`, `.xc-landing-top .xc-brand-mark img`) | **2.00x** | correct, untouched |
| `cortex-brain-compact-dark.png` | 248x230 | 124px (`.xc-brand-lockup` max-width) | **2.00x** | correct, untouched |
| `cortex-mark.png` | 256x256 | — | — | **no `src` references it anywhere** in `src/`, only two CSS/e2e comments. Dead asset; left in place rather than deleted, since deletion is outside this brief. |
| `cortex-lockup-hero.png` | 560x520 | 420px | 1.33x | short; see above |

## 6. Verification

No source file, asset, test, or CSS rule was changed, so there is no before/after test run
to report and nothing was committed: a resolution assertion added here could only be shown
green against the asset that already ships, which is precisely the "check that cannot fail"
this repo treats as a defect. Adding `natural >= 2 * rendered` to `lens-chrome.spec.ts`
would make the suite red with no code able to turn it green, so it was not added.

`npm run build`, `CI=true npx vitest run` and the Playwright brand specs were deliberately
NOT run: with nothing changed they could only restate the tree's existing state, and a
build would write `viewer/dist/` into a tree another agent is working in.

`.superpowers/sdd/.gitignore` is `*`, so this report is deliberately untracked; it could
not be committed without overriding the repo's own ignore rule. **Nothing was committed —
there is no tracked change to commit.** A `viewer/scripts/__pycache__/` directory created
by loading the script during this investigation was removed.

## 7. What would actually fix it

In order of preference:

0. **Accept the interpolated 840 anyway**, if the ~6pp edge-contrast gain at the 2x
   landing hero is judged worth it. `invert_to_white` already takes `out_w`; its
   `__main__` has no flag for it, so add one or call it directly:

   ```
   cd viewer && python3 -IB -c "import importlib.util,os; \
   s=importlib.util.spec_from_file_location('i','scripts/invert_logo_to_white.py'); \
   m=importlib.util.module_from_spec(s); s.loader.exec_module(m); \
   print(m.invert_to_white(os.path.expanduser('~/Pictures/cortex-logos/cortex-brain-compact-transparent.png'), \
   'public/cortex-lockup-hero.png', out_w=840))"
   ```

   Measured gain: ink at alpha >= 200 goes
   67.0% -> 72.9% for the 420px landing hero at 2x; **no change** at the 300px sign-in use
   or at 1x anywhere. The `width`/`height` attributes need no edit. This was not done
   because the brief forbids shipping a soft upscale.
1. **Get a vector (SVG/AI/PDF) or a >= 840px raster export of this exact lockup** — brain
   with "Xibalba / CORTEX / AI MEMORY SYSTEM" *inside* it. Then
   `invert_to_white(src, dst, out_w=840)` produces a genuinely sharp asset and the DPR
   table above goes to 2.00x with no interpolation. This is a request to whoever holds the
   source file; it is not recoverable from anything on this machine.
2. **Or adopt the `cortex-plugin-icon-high-resolution.png` composition** (1122px of ink,
   enough for 840 natively). This is a brand decision, not a resolution fix: the tagline
   moves outside the brain and the X gains a spiral.
3. **Or state the hero at the size the artwork supports** — `.xc-landing-mark` max-width
   420px -> 280px would make the existing 560 asset exactly 2x. The brief forbids moving
   the layout, so this is offered as a decision for the user, not applied.

Options 1 and 2 need artwork the repo does not have; option 3 needs permission to change
the layout. All three are outside what this brief authorises, which is why this report
ships measurements instead of an asset.
