# Brief — fix the Cortex logo's resolution on the landing page

The user reports the Cortex logo renders at poor resolution on the landing page. Fix it.

## The measured diagnosis (already done — start from this, do not redo it)

`viewer/public/cortex-lockup-hero.png` is **560x520**, and it is rendered at:
- `viewer/src/console/Landing.tsx:71` — `width={420} height={390}` (the landing hero)
- `viewer/src/console/SignIn.tsx:134` — `width={300} height={279}`

560/420 = **1.33x**. A 2x display needs 840x780, so the browser upscales the hero by ~1.5x
on any HiDPI screen. That is the blur. The sign-in use at 300x279 needs 600x558 and is
therefore also short, though less badly.

Other marks, for reference — check each against its own largest CSS size before touching it,
and leave the ones that are already >= 2x alone:
- `cortex-mark.png` 256x256
- `cortex-rail-mark.png` 88x82 (rail, `Landing.tsx:53`, `Shell.tsx:81`)
- `cortex-brain-compact-dark.png` 248x230 (`Shell.tsx:80`) — the script's `OUT_W = 248`
  comment says this one is deliberately 2x of a 124px rail lockup, so it is likely correct.

## The master artwork and the pipeline

Masters live OUTSIDE the repo at `~/Pictures/cortex-logos/` (1280x670 and 1280x626):
`cortex-brain-display-transparent.png`, `cortex-brain-compact-transparent.png`,
`cortex-wordmark-transparent.png`, and `*-derived` variants. Treat that directory as
**read-only input** — do not modify or delete anything in it.

`viewer/scripts/invert_logo_to_white.py` is the reproducible pipeline and its docstring
encodes hard-won detail you must respect rather than rediscover:
- The ink is read from **RGB alone**, not from the image composited over white; compositing
  first washes the ink out.
- A dark frame runs along the source's outer edge, so `FRAME` px are trimmed **before** the
  bounding box is taken, or the crop keeps the whole 1280px canvas and the artwork lands a
  third of the size it should.
- **The alpha stretch must be the LAST operation.** Shipping at 4x and letting the browser
  resample down averages each hairline stroke back to about a third coverage (measured:
  alpha p50 62 against 183), because the browser's resize comes after the stretch and undoes
  it. So resample once, here, to the intended size, and stretch at that size.

That last point is the crux: **do not simply export a bigger PNG and let CSS shrink it.**
Generate at exactly the pixel size the 2x display needs.

## What to do

1. Work in the existing worktree
   `/mnt/storage/xibalba/Projects/worktrees/xibalba-cortex/account-registration-design`.
   Do NOT create a worktree, clone, rebase, or push. Commit your work on the current branch.
2. Determine `cortex-lockup-hero.png`'s true composition and which master it derives from
   (it is 1.08:1, while the masters are 1.91:1, so it is cropped or composed — establish how
   before regenerating, so you reproduce the same artwork and not a different crop).
3. Regenerate it at **2x its largest display use: 840x780**, through the existing script's
   approach (extend the script with a parameter or add a sibling function — keep it
   reproducible and keep the command in a docstring, as the existing one does). If the
   artwork cannot fill 840x780 from a 1280px master at acceptable quality, say so with the
   measurement rather than shipping a soft upscale.
4. Keep the rendered CSS size identical. This is a resolution fix, not a redesign: the
   `width`/`height` attributes on both `<img>` tags must stay as they are, so layout does
   not move.
5. The design system is **dark-only** (Industry steel). The mark is white-on-transparent.
   Do not introduce a light-mode variant.

## Verification — measurement, not eyeballing

This repo's standing rule: **a check that cannot fail has measured nothing.** A green
conformance pass that was structurally incapable of failing is treated as a defect here.

- Report the before/after natural pixel size and the resulting device-pixel ratio against
  each CSS size.
- Report alpha percentiles of the strokes before and after, the way the script's docstring
  does, to show the ink did not wash out.
- `cd viewer && npx playwright test e2e/collapsed-logo.spec.ts` must stay green, plus any
  other spec that touches the brand marks — find them with
  `grep -rln 'brand-lockup\|brand-mark\|landing-mark\|cortex-' e2e/`.
- Run `npm run build` and `CI=true npx vitest run` (expect 368 passed).
- If you add an assertion about image resolution, you must demonstrate it can fail: show it
  red against the old 560x520 asset, then green against the new one. Report both runs.

Do not dispatch subagents of your own. Write your report to
`.superpowers/sdd/2026-11-02-cortex-production-readiness/logo-resolution-report.md` and
return a short summary: what you changed, the before/after measurements, the test results,
and anything you could not do.
