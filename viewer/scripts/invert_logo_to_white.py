"""Invert a dark-ink-on-white Cortex logo export into a solid-white-on-transparent mark.

How public/cortex-brain-compact-dark.png is derived, kept here so the asset is reproducible:

    python3 -I scripts/invert_logo_to_white.py \
        ~/Pictures/cortex-logos/cortex-brain-compact-transparent.png \
        public/cortex-brain-compact-dark.png


The sources in ~/Pictures/cortex-logos are flat artwork: ~6% near-black line art on a white
field, alpha 255 everywhere. Inverting the COLOUR alone would give white ink on a black field,
so the field has to become transparency instead: the inverted luminance IS the alpha, and RGB is
forced to pure white because for a monochrome mark the colour channel carries no information.

Three details decide whether the result reads as solid white or as the grey ghost it replaces:

  * INK_HI. The source's strokes are anti-aliased and sit mostly between luminance 55 and 200,
    so a ramp that only reaches full alpha at near-black leaves the whole mark at about half
    coverage. Everything at or below 200 is ink, full stop; 243 and up is paper.
  * A 1px dark frame runs along the source's outer edge, so the margin is trimmed before the
    bounding box is taken -- otherwise the crop keeps the entire 1280px canvas and the artwork
    lands a third of the size it should be.
  * The line art is hairline, and the alpha stretch has to be the LAST thing that happens to it.
    Shipping the mark at 4x and letting the browser resample it to 124px averages each stroke
    back down to about a third coverage -- measured: alpha p50 62 against 183 -- because the
    browser's resize comes after the stretch and undoes it. So the mark is resampled here, once,
    to twice its display size, and stretched at that size.
"""
import sys
from PIL import Image

INK_LO, INK_HI = 243, 200   # source luminance: >= INK_LO is paper, <= INK_HI is full ink
FRAME = 3                    # px of outer edge to drop before measuring the artwork
OUT_W = 248                  # 2x the rail's 124px lockup, and just over the 208px sign-in use
GAMMA = 0.7                  # alpha stretch applied after resampling

def invert_to_white(src: str, dst: str, out_w: int = OUT_W, pad: int = 6, gamma: float = GAMMA):
    # The ink is read from RGB alone, NOT from the image composited over white. These exports
    # carry the artwork at full strength in RGB and a PARTIAL alpha over it, so compositing
    # first washes the ink out -- measured on the compact lockup: minimum luminance 190 instead
    # of 0, and 0.8% of the canvas below 200 instead of 6.2%. The alpha we want is the one we
    # are about to compute, so the source's own is discarded.
    rgb = Image.open(src).convert('RGB')
    w, h = rgb.size
    lum = rgb.convert('L').crop((FRAME, FRAME, w - FRAME, h - FRAME))

    span = INK_LO - INK_HI
    alpha = lum.point(lambda v: 255 if v <= INK_HI else 0 if v >= INK_LO else round(255 * (INK_LO - v) / span))
    box = alpha.getbbox()
    x0, y0, x1, y1 = box
    alpha = alpha.crop((max(0, x0 - pad), max(0, y0 - pad),
                        min(alpha.size[0], x1 + pad), min(alpha.size[1], y1 + pad)))

    if out_w and alpha.size[0] != out_w:
        alpha = alpha.resize((out_w, round(alpha.size[1] * out_w / alpha.size[0])), Image.LANCZOS)
    alpha = alpha.point(lambda v: 0 if v == 0 else min(255, round(255 * (v / 255) ** gamma)))

    mark = Image.new('RGBA', alpha.size, (255, 255, 255, 0))
    mark.putalpha(alpha)
    mark.save(dst)
    return mark.size

def restate_white(src: str, dst: str, out_w: int, pad: int = 2, gamma: float = GAMMA):
    """The same last step for a mark that is ALREADY white-on-transparent.

    cortex-mark.png needs no inversion -- its RGB is pure white and the artwork lives in alpha --
    but it has the same hairline problem: shipped at 256px and painted at 40px, the browser
    averages every stroke down to about a third coverage (measured alpha p50 85). Resampling it
    to twice its painted size here, and stretching afterwards, states it at the size it is seen.
    """
    im = Image.open(src).convert('RGBA')
    alpha = im.getchannel('A')
    box = alpha.getbbox()
    x0, y0, x1, y1 = box
    alpha = alpha.crop((max(0, x0 - pad), max(0, y0 - pad),
                        min(alpha.size[0], x1 + pad), min(alpha.size[1], y1 + pad)))
    alpha = alpha.resize((out_w, round(alpha.size[1] * out_w / alpha.size[0])), Image.LANCZOS)
    alpha = alpha.point(lambda v: 0 if v == 0 else min(255, round(255 * (v / 255) ** gamma)))
    mark = Image.new('RGBA', alpha.size, (255, 255, 255, 0))
    mark.putalpha(alpha)
    mark.save(dst)
    return mark.size

def rail_mark(src: str, dst: str, out_w: int = 88):
    """Keep the complete lockup in the collapsed rail, with breathing room on every side.

    The earlier crown crop removed the wordmark and lower half of the brain. Small navigation
    must preserve the same complete artwork as the expanded rail, even at a smaller scale.
    """
    return invert_to_white(src, dst, out_w=out_w, pad=12, gamma=0.55)

if __name__ == '__main__':
    if sys.argv[1] == '--rail':
        print(rail_mark(sys.argv[2], sys.argv[3], int(sys.argv[4]) if len(sys.argv) > 4 else 88))
    elif sys.argv[1] == '--restate':
        print(restate_white(sys.argv[2], sys.argv[3], int(sys.argv[4])))
    else:
        print(invert_to_white(*sys.argv[1:3]))
