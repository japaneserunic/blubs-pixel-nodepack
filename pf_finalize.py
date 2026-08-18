"""True-pixel finalizer: turn H3 frames into REAL modern pixel art.

Ports the Cel Shading Studio offline engine (flattener.ts / palette.ts) into
the PixelForge post-process, on top of the v2 quantize helpers:

  - edge-preserving BILATERAL flatten at source res (cv2) instead of the
    median filter that carved ragged patch blobs
  - k-means palette + deMuddyCentroid refinement: every palette slot is
    pulled toward the most vibrant core pixel of its cluster instead of the
    washed-out cluster mean -> punchy, saturated, non-muddy colors
  - subject/background segmentation (port of getSegmentPixelMap: redmean
    color-key tolerance + connected-island flood from the borders) so the
    subject gets its own palette budget and the backdrop never contaminates
  - cel-band shading (port of flattenTexture preserveHue mode): luminance
    ratio per pixel, contrast-shaped, optional bayer micro-dither, quantized
    into 2-4 bands -> deliberate light/shadow ramps instead of photo gradient
  - hue-shifted ramps: shadows drift toward indigo, highlights toward amber
    (the modern hi-bit pixel-art look), strictly palette-true output
  - redmean nearest-color decisions (human-perception weighted)
  - PIXEL-GRID SNIFFER: detects the apparent block size + phase H3 already
    drew and locks the downscale onto it (auto mode)
  - silhouette outline pass (outer / inner) in the darkest ramp shade
  - despeckle + crisp 1-bit alpha + nearest-neighbor upscale

Everything is additive: existing PixelForge nodes and workflows are untouched.
"""

import json

import numpy as np
import torch
from PIL import Image, ImageFilter

try:
    import cv2
    _HAS_CV2 = True
except Exception:  # pragma: no cover
    _HAS_CV2 = False

try:
    from scipy import ndimage as _ndi
    _HAS_SCIPY = True
except Exception:  # pragma: no cover
    _HAS_SCIPY = False

from .pf_pixelize import (_RESAMPLE, _bayer8, _BAYER, _despeckle,
                          _kmeans_palette, _merge_palette, _pil_list_to_tensor,
                          _preprocess, _sample_pixels, _tensor_to_pil_list)

# ---------------------------------------------------------------------------
# color helpers (ported from Cel Shading Studio: flattener.ts / palette.ts)


def _luminance(rgb):
    """rgb (...,3) float 0-255 -> (...) perceived luminance (Rec.601)."""
    return (0.299 * rgb[..., 0] + 0.587 * rgb[..., 1]
            + 0.114 * rgb[..., 2])


def _redmean_d2(px, pal):
    """Redmean squared distance. px (P,3) float, pal (N,3) float -> (P,N).

    Human-perception weighted metric from Cel Shading Studio; hue-true for
    saturated sprite colors where plain euclidean RGB goes muddy-gray."""
    rmean = (px[:, 0:1] + pal[None, :, 0]) * 0.5
    dr = px[:, 0:1] - pal[None, :, 0]
    dg = px[:, 1:2] - pal[None, :, 1]
    db = px[:, 2:3] - pal[None, :, 2]
    return ((2.0 + rmean / 256.0) * dr * dr + 4.0 * dg * dg
            + (2.0 + (255.0 - rmean) / 256.0) * db * db)


def _redmean_argmin(px, pal, chunk=65536):
    """px (P,3), pal (N,3) -> (P,) int32 index of nearest palette entry."""
    out = np.empty(px.shape[0], dtype=np.int32)
    for s in range(0, px.shape[0], chunk):
        out[s:s + chunk] = _redmean_d2(px[s:s + chunk], pal).argmin(-1)
    return out


def _dark_line_mask(src_rgb_u8):
    """Near-black px forming THIN CONNECTED structures (hand-drawn outline,
    dark line details). Isolated dark specks (0-1 dark neighbors) are NOT
    protected — the region vote dissolves them into their surround; fat
    shadow-blob interiors (7-8 dark neighbors) are NOT protected either —
    the vote unifies their base color. Lines (2-6 dark neighbors) are."""
    dark = src_rgb_u8.max(-1) < 60
    if not _HAS_SCIPY:
        return dark
    cnt = _ndi.convolve(dark.astype(np.int32), np.ones((3, 3), np.int32),
                        mode="constant", cval=0) - dark.astype(np.int32)
    return dark & (cnt >= 2) & (cnt <= 6)


def _region_vote(idx, protect, sm, n_classes, thresh=5):
    """3x3 one-hot majority vote on a class-index map (base*B+band).

    Per-pixel redmean argmin on noisy grid-res input flips base colors and
    cel bands pixel-by-pixel (measured on run 6b4d97642d: 95.5% of grid-res
    px have no same-color neighbor; look stage output carried ~9.3% isolated
    speckle px = the 'deepfried' crunch + dirty interior dark specks). Only
    subject px vote and only subject px get reassigned; protected px (thin
    dark lines — the outline) keep their class; a class must win >=thresh
    of the 9 votes to reassign (weak majorities keep the original px, which
    protects thin legit detail like the 2px sash).
    """
    h, w = idx.shape
    votes = np.zeros((n_classes, h, w), dtype=np.float32)
    for c in range(n_classes):
        votes[c] = _ndi.uniform_filter(((idx == c) & sm).astype(np.float32),
                                       size=3, mode="nearest")
    win = votes.argmax(0)
    winv = votes.max(0) * 9.0
    re = sm & (win != idx) & (winv >= float(thresh))
    if protect is not None:
        re &= ~protect
    out = idx.copy()
    out[re] = win[re].astype(out.dtype)
    return out


def _rgb_to_hsv(rgb):
    """rgb (...,3) float 0-255 -> hsv (...,3), h in [0,1), s/v in [0,1]."""
    c = rgb / 255.0
    r, g, b = c[..., 0], c[..., 1], c[..., 2]
    mx = c.max(-1)
    mn = c.min(-1)
    d = mx - mn
    v = mx
    s = np.where(mx > 1e-6, d / np.maximum(mx, 1e-6), 0.0)
    h = np.zeros_like(mx)
    safe = np.maximum(d, 1e-9)
    h = np.where(mx == r, ((g - b) / safe) % 6.0, h)
    h = np.where(mx == g, (b - r) / safe + 2.0, h)
    h = np.where(mx == b, (r - g) / safe + 4.0, h)
    h = np.where(d > 1e-6, h / 6.0, 0.0)
    return np.stack([h, s, v], axis=-1).astype(np.float32)


def _hsv_to_rgb(hsv):
    """hsv (...,3) -> rgb (...,3) float 0-255."""
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    i = np.floor(h * 6.0).astype(np.int32) % 6
    f = h * 6.0 - np.floor(h * 6.0)
    p = v * (1.0 - s)
    q = v * (1.0 - f * s)
    t = v * (1.0 - (1.0 - f) * s)
    r = np.choose(i, [v, q, p, p, t, v])
    g = np.choose(i, [t, v, v, q, p, p])
    b = np.choose(i, [p, p, t, v, v, q])
    return (np.stack([r, g, b], axis=-1) * 255.0).astype(np.float32)


def _hue_lerp(h, target, amount):
    """Circular lerp of hue h toward target by amount in [0,1]."""
    d = (target - h + 0.5) % 1.0 - 0.5
    return (h + d * amount) % 1.0


# ---------------------------------------------------------------------------
# deMuddyCentroid (port of palette.ts)

def _demuddy_centroid(cluster_px, avg):
    """Pull a k-means centroid toward the most vibrant pixel in its core.

    k-means parks centroids on muddy averages; among the 40% of pixels
    closest to the mean we take the highest-chroma one and blend 75/25
    toward it. Result: saturated, deliberate palette colors."""
    if cluster_px.shape[0] == 0:
        return avg
    d2 = _redmean_d2(cluster_px, avg[None, :])[:, 0]
    order = np.argsort(d2, kind="stable")
    n_core = max(1, min(150, int(cluster_px.shape[0] * 0.4)))
    core = cluster_px[order[:n_core]]
    chroma = core.max(-1) - core.min(-1)
    best = core[int(chroma.argmax())]
    if chroma.max() > 20:
        avg_chroma = float(avg.max() - avg.min())
        if float(chroma.max()) > avg_chroma:
            return np.clip(avg * 0.25 + best * 0.75, 0, 255)
    return avg


def _demuddy_palette(samples, pal_rgb):
    """Refine every palette entry against the sampled pixels (redmean)."""
    pal = np.array(pal_rgb, dtype=np.float32)
    if samples.shape[0] == 0 or pal.shape[0] == 0:
        return pal_rgb
    assign = _redmean_argmin(samples, pal)
    out = []
    for ci in range(pal.shape[0]):
        out.append(_demuddy_centroid(samples[assign == ci], pal[ci]))
    return [tuple(int(round(v)) for v in c) for c in out]


# ---------------------------------------------------------------------------
# segment masking (port of getSegmentPixelMap from flattener.ts)

def _segment_match_map(arr, key_rgb, tolerance):
    """Binary map of pixels matching key_rgb within redmean tolerance.

    arr (H,W,3) uint8 -> (H,W) bool. Port of the matchesColor predicate."""
    px = arr.reshape(-1, 3).astype(np.float32)
    d2 = _redmean_d2(px, np.array(key_rgb, dtype=np.float32)[None, :])[:, 0]
    return (d2 < tolerance * tolerance).reshape(arr.shape[:2])


def _border_connected_bg(match):
    """Keep only match-components touching the image border (flood from
    edges = backdrop), so interior lookalike colors survive. Port of the
    seed-island BFS behavior, vectorized via connected-component labels."""
    if not _HAS_SCIPY:
        return match
    lab, _n = _ndi.label(match)
    border = np.unique(np.concatenate([
        lab[0, :], lab[-1, :], lab[:, 0], lab[:, -1]]))
    border = border[border != 0]
    if border.size == 0:
        return np.zeros_like(match)
    return np.isin(lab, border)


def _auto_subject_mask(frame_rgb, tolerance=28.0):
    """(H,W,3) uint8 -> (H,W) bool subject mask via border-color keying."""
    border = np.concatenate([
        frame_rgb[0, :, :], frame_rgb[-1, :, :],
        frame_rgb[:, 0, :], frame_rgb[:, -1, :]], axis=0)
    key = np.median(border.astype(np.float32), axis=0)
    match = _segment_match_map(frame_rgb, key, tolerance)
    bg = _border_connected_bg(match)
    subject = ~bg
    if subject.mean() < 0.02:      # backdrop keying failed; keep everything
        return np.ones(frame_rgb.shape[:2], dtype=bool)
    return subject


# ---------------------------------------------------------------------------
# pixel-grid detection (sniff the apparent block size H3 already drew)

def _autocorr_candidates(sig, s_min, s_max, top=3):
    """Propose block sizes from the autocorrelation of a 1D gradient
    profile: a period-s pixel grid peaks at lag s (and its multiples)."""
    sig = sig - sig.mean()
    n = sig.shape[0]
    if n < 2 * s_max + 4 or float(np.abs(sig).sum()) < 1e-6:
        return []
    spec = np.fft.rfft(sig, 2 * n)
    ac = np.fft.irfft(spec * np.conj(spec))[:n]
    if ac[0] <= 1e-9:
        return []
    ac = ac / ac[0]
    hi = min(s_max, n // 2 - 1)
    cands = []
    for lag in range(s_min, hi + 1):
        if ac[lag] >= ac[lag - 1] and ac[lag] >= ac[lag + 1] and ac[lag] > 0.05:
            cands.append((float(ac[lag]), lag))
    cands.sort(reverse=True)
    return [lag for _s, lag in cands[:top]]


def _block_score(gray, s, ox, oy):
    """Fraction of variance explained by an s-grid at offset (ox,oy).
    True grid -> block interiors go flat (within-var low)."""
    h, w = gray.shape
    ny = (h - oy) // s
    nx = (w - ox) // s
    if ny < 4 or nx < 4:
        return -1.0
    crop = gray[oy:oy + ny * s, ox:ox + nx * s]
    blocks = crop.reshape(ny, s, nx, s)
    within = float(blocks.var(axis=(1, 3)).mean())
    between = float(blocks.mean(axis=(1, 3)).var())
    return between / (within + between + 1e-6)


def _detect_pixel_grid(frame_rgb, s_min=2, s_max=10):
    """(H,W,3) uint8 -> (block, ox, oy) or None. Detects the apparent pixel
    grid: autocorrelation proposes period candidates per axis, then a
    variance score with phase search picks the winner and its offset."""
    gray = _luminance(frame_rgb.astype(np.float32))
    gx = np.abs(np.diff(gray, axis=1)).sum(0)
    gy = np.abs(np.diff(gray, axis=0)).sum(1)
    cand = _autocorr_candidates(gx, s_min, s_max)
    for c in _autocorr_candidates(gy, s_min, s_max):
        if c not in cand:
            cand.append(c)
    if not cand:
        cand = list(range(s_min, s_max + 1))
    scored = []
    for s in cand[:4]:
        bs = None
        for oy in range(s):
            for ox in range(s):
                sc = _block_score(gray, s, ox, oy)
                if bs is None or sc > bs[0]:
                    bs = (sc, s, ox, oy)
        if bs is not None:
            scored.append(bs)
    if not scored:
        return None
    best_score = max(x[0] for x in scored)
    if best_score < 0.55:   # no convincing grid -> manual mode
        return None
    # Detail-preserving tie-break: bigger blocks ALWAYS score higher on
    # smooth content (fewer, flatter blocks -> higher between-variance), so
    # raw argmax systematically over-reduces and the sprite comes out
    # low-res. Among candidates within 90% of the best score, take the
    # SMALLEST block — keep the finest grid the evidence supports.
    pool = [x for x in scored if x[0] >= 0.9 * best_score]
    _score, s, ox, oy = min(pool, key=lambda x: x[1])
    return s, ox, oy


# ---------------------------------------------------------------------------
# cel-band shading (port of flattenTexture preserveHue mode)

def _band_multipliers(bands, ambient):
    if bands <= 1:
        return np.array([1.0], dtype=np.float32)
    if bands == 2:
        return np.array([ambient + (1.0 - ambient) * 0.4, 1.0],
                        dtype=np.float32)
    if bands == 3:
        return np.array([ambient, ambient + (1.0 - ambient) * 0.65, 1.0],
                        dtype=np.float32)
    return np.array([ambient, ambient + (1.0 - ambient) * 0.45,
                     ambient + (1.0 - ambient) * 0.75, 1.0],
                    dtype=np.float32)


def _ratio_to_band(ratio, bands, ambient, shadow_threshold,
                   highlight_threshold):
    """Quantize a luminance ratio into a band index (port of the cel band
    quantization decision tree)."""
    if bands <= 1:
        return np.zeros(ratio.shape, dtype=np.int32)
    if bands == 2:
        return (ratio >= shadow_threshold).astype(np.int32)
    if bands == 3:
        band = np.ones(ratio.shape, dtype=np.int32)
        band[ratio < shadow_threshold] = 0
        band[ratio >= highlight_threshold] = 2
        return band
    mid1 = shadow_threshold + (highlight_threshold - shadow_threshold) * 0.33
    mid2 = shadow_threshold + (highlight_threshold - shadow_threshold) * 0.66
    band = np.zeros(ratio.shape, dtype=np.int32)
    band[(ratio >= shadow_threshold) & (ratio < mid1)] = 1
    band[(ratio >= mid1) & (ratio < mid2)] = 2
    band[ratio >= mid2] = 3
    return band


_SHADOW_HUE = 250.0 / 360.0    # indigo — classic cool pixel-art shadow
_HIGHLIGHT_HUE = 40.0 / 360.0  # amber — warm sunlit highlight


def _build_ramps(pal_rgb, bands, ambient, hue_shift, vibrancy):
    """(K base colors) x (B bands) shade ramp, hue-shifted + vibrancy-shaped.

    Every output pixel comes from this table, so the final art is strictly
    palettized (countable colors = true pixel art)."""
    pal = np.array(pal_rgb, dtype=np.float32)
    mults = _band_multipliers(bands, ambient)
    B = len(mults)
    hsv = _rgb_to_hsv(pal)                          # (K,3)
    ramp = np.empty((pal.shape[0], B, 3), dtype=np.float32)
    for bi in range(B):
        t = 1.0 if B == 1 else bi / (B - 1)         # 0 = deepest shadow
        h = hsv[:, 0].copy()
        s = hsv[:, 1].copy()
        v = np.clip(hsv[:, 2] * mults[bi], 0.0, 1.0)
        if hue_shift > 0:
            # shadows drift toward indigo, lit band slightly toward amber
            h = _hue_lerp(h, _SHADOW_HUE, hue_shift * (1.0 - t) * 0.8)
            h = _hue_lerp(h, _HIGHLIGHT_HUE, hue_shift * max(0.0, t - 0.5))
            # shadows keep (or gain) saturation — modern hi-bit look
            s = np.clip(s * (1.0 + hue_shift * (1.0 - t) * 0.35), 0.0, 1.0)
        ramp[:, bi, :] = _hsv_to_rgb(np.stack([h, s, v], axis=-1))
    if vibrancy != 1.0:
        lum = _luminance(ramp)
        ramp = np.clip(lum[..., None] + (ramp - lum[..., None]) * vibrancy,
                       0, 255)
    return ramp


# ---------------------------------------------------------------------------
# bilateral flatten (cv2 port of the flattener.ts smoothing stage)

def _bilateral_flatten(pil_img, strength, passes):
    if strength <= 0:
        return pil_img
    arr = np.asarray(pil_img)
    if _HAS_CV2:
        sigma_color = 16.0 + strength * 14.0
        d = 9
        out = arr
        for _ in range(max(1, passes)):
            out = cv2.bilateralFilter(out, d, sigma_color, d)
        return Image.fromarray(out)
    # fallback: repeated small median (weaker, but dependency-free)
    out = pil_img
    for _ in range(max(1, passes)):
        out = out.filter(ImageFilter.MedianFilter(3))
    return out


# ---------------------------------------------------------------------------
# the node

class PixelForgeTruePixel:
    """Final post-process that makes H3 output read as real, modern pixel
    art: grid-sniff -> bilateral flatten -> segment-aware de-muddied palette
    -> cel-band hue-shifted shading -> outline -> despeckle -> upscale."""

    CATEGORY = "PixelForge/pixel"
    FUNCTION = "run"
    RETURN_TYPES = ("IMAGE", "MASK", "MASK", "STRING")
    RETURN_NAMES = ("images", "alpha", "subject_mask", "palette_json")
    DESCRIPTION = ("True pixel-art finalizer. Auto-detects H3's apparent "
                   "pixel grid, edge-preserving flatten, vibrant de-muddied "
                   "palette (subject gets its own color budget), cel-band "
                   "hue-shifted shading ramps, silhouette outline, crisp "
                   "alpha. Chain after Sprite Chroma Key or feed raw H3 "
                   "frames (auto_subject keys the backdrop).")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "pixel_width": ("INT", {"default": 192, "min": 8, "max": 2048, "step": 8,
                                        "tooltip": "True pixel resolution width (manual mode). Height keeps aspect unless pixel_height set."}),
                "pixel_height": ("INT", {"default": 0, "min": 0, "max": 2048, "step": 8}),
                "downsample_filter": (["area", "bilinear", "bicubic", "lanczos", "nearest"],),
                "colors": ("INT", {"default": 32, "min": 2, "max": 256,
                                   "tooltip": "Total palette budget. Subject gets subject_palette_share of it."}),
                "subject_palette_share": ("FLOAT", {"default": 0.75, "min": 0.1, "max": 1.0, "step": 0.05,
                                                    "tooltip": "Fraction of palette reserved for the subject; rest goes to backdrop."}),
                "flatten": ("FLOAT", {"default": 5.0, "min": 0.0, "max": 10.0, "step": 0.5,
                                      "tooltip": "Bilateral edge-preserving smoothing at SOURCE res. Kills VAE grain without patch blobs. 0 = off."}),
                "flatten_passes": ("INT", {"default": 2, "min": 1, "max": 3}),
                "bands": ("INT", {"default": 3, "min": 1, "max": 4,
                                  "tooltip": "Cel shading bands per color ramp. 1 = flat colors, 3 = shadow/mid/lit."}),
                "ambient_brightness": ("FLOAT", {"default": 0.35, "min": 0.05, "max": 0.9, "step": 0.05,
                                                 "tooltip": "Darkest shadow multiplier."}),
                "shadow_threshold": ("FLOAT", {"default": 0.55, "min": 0.05, "max": 0.95, "step": 0.05}),
                "highlight_threshold": ("FLOAT", {"default": 0.85, "min": 0.1, "max": 1.5, "step": 0.05}),
                "cel_contrast": ("FLOAT", {"default": 1.25, "min": 0.5, "max": 2.5, "step": 0.05,
                                           "tooltip": "Shapes the luminance ratio before banding; >1 pushes pixels toward band edges = bolder shapes."}),
                "hue_shift": ("FLOAT", {"default": 0.30, "min": 0.0, "max": 1.0, "step": 0.05,
                                        "tooltip": "Shadows drift toward indigo, highlights toward amber. The modern hi-bit look. 0 = off."}),
                "vibrancy": ("FLOAT", {"default": 1.15, "min": 0.0, "max": 2.5, "step": 0.05}),
                "outline": (["off", "outer", "inner", "both"],
                            {"tooltip": "Silhouette outline in the darkest ramp shade. outer = around sprite, inner = inside edge."}),
                "dither": (["none", "bayer4", "bayer8"],
                           {"tooltip": "Ordered micro-dither on the shade ratio — texture only at band transitions."}),
                "dither_strength": ("FLOAT", {"default": 0.15, "min": 0.0, "max": 1.0, "step": 0.05}),
                "despeckle": ("INT", {"default": 1, "min": 0, "max": 3}),
                "saturation": ("FLOAT", {"default": 1.25, "min": 0.0, "max": 3.0, "step": 0.05}),
                "contrast": ("FLOAT", {"default": 1.10, "min": 0.0, "max": 3.0, "step": 0.05}),
                "sharpen": ("FLOAT", {"default": 0.6, "min": 0.0, "max": 2.0, "step": 0.1}),
                "auto_subject": ("BOOLEAN", {"default": True,
                                             "tooltip": "When no alpha is wired: key the backdrop by border color + connected-region flood (ported segment masking)."}),
                "bg_tolerance": ("FLOAT", {"default": 28.0, "min": 4.0, "max": 120.0, "step": 1.0,
                                           "tooltip": "Redmean tolerance for auto_subject backdrop keying."}),
                "upscale_factor": ("INT", {"default": 2, "min": 0, "max": 16,
                                           "tooltip": "Nearest upscale after processing. 0 = back to cropped input size."}),
                # --- appended last: positional widget safety ---
                "pixel_grid": (["auto", "manual"],
                               {"tooltip": "auto = sniff the apparent pixel grid H3 already drew (block size + phase) and lock the downscale onto it. Overrides pixel_width/height."}),
                "grid_max_block": ("INT", {"default": 10, "min": 2, "max": 24,
                                           "tooltip": "Largest block size the auto grid detector considers."}),
                # --- v6 widget appended (positional compat) ---
                "band_hysteresis": ("FLOAT", {"default": 0.06, "min": 0.0, "max": 0.3, "step": 0.01,
                                              "tooltip": "Temporal band pinning: a pixel's cel band can only flip when its "
                                                         "luminance ratio moves this far PAST the band boundary. Kills "
                                                         "shade-region popping (white<->lavender shimmer). 0 = off."}),
                "shade_smooth": ("BOOLEAN", {"default": True,
                                             "tooltip": "3x3 median on the shade-ratio map before banding: shade regions "
                                                        "become solid shapes instead of speckled mixes. Big anti-shimmer win."}),
                # --- v3.7.8 widgets appended (positional compat) ---
                "region_vote": ("BOOLEAN", {"default": True,
                                            "tooltip": "Spatial coherence: 3x3 majority vote over the final "
                                                       "base+band class per pixel. Kills per-pixel color flips "
                                                       "(deepfried speckle) on noisy grid-res input. Thin dark "
                                                       "lines (the outline) are protected."}),
                "region_vote_thresh": ("INT", {"default": 5, "min": 3, "max": 9,
                                               "tooltip": "Votes (of 9) a class needs to reassign a pixel. "
                                                          "Higher = more conservative (keeps more original detail)."}),
            },
            "optional": {
                "alpha": ("MASK", {"tooltip": "Wire Sprite Chroma Key's alpha here — takes priority over auto_subject."}),
            },
        }

    # -- pipeline -----------------------------------------------------------

    def run(self, images, pixel_width, pixel_height, downsample_filter, colors,
            subject_palette_share, flatten, flatten_passes, bands,
            ambient_brightness, shadow_threshold, highlight_threshold,
            cel_contrast, hue_shift, vibrancy, outline, dither,
            dither_strength, despeckle, saturation, contrast, sharpen,
            auto_subject, bg_tolerance, upscale_factor, pixel_grid="auto",
            grid_max_block=10, band_hysteresis=0.06, shade_smooth=True,
            region_vote=True, region_vote_thresh=5, alpha=None):
        frames = _tensor_to_pil_list(images)
        orig_w, orig_h = frames[0].size
        n = len(frames)

        # 1. pre-boost, then bilateral flatten at SOURCE res (edge-safe)
        frames = _preprocess(frames, saturation, contrast, sharpen)
        frames = [_bilateral_flatten(f, flatten, flatten_passes) for f in frames]

        # 2. pixel-grid sniff: lock the downscale onto the blocks H3 drew
        grid_info = None
        ox = oy = 0
        src_w, src_h = orig_w, orig_h
        if pixel_grid == "auto":
            det = _detect_pixel_grid(np.asarray(frames[0]),
                                     s_max=grid_max_block)
            if det is not None:
                s, ox, oy = det
                new_w = s * ((orig_w - ox) // s)
                new_h = s * ((orig_h - oy) // s)
                if new_w >= 16 and new_h >= 16:
                    frames = [f.crop((ox, oy, ox + new_w, oy + new_h))
                              for f in frames]
                    src_w, src_h = new_w, new_h
                    grid_info = {"block": s, "offset": [ox, oy]}
                    print(f"[PixelForgeTruePixel] auto grid: {s}px block "
                          f"@ ({ox},{oy}) -> {new_w // s}x{new_h // s}px")
        if pixel_grid == "auto" and grid_info is None:
            print("[PixelForgeTruePixel] auto grid: no confident grid, "
                  "falling back to manual pixel_width")

        if grid_info is not None:
            tw = src_w // grid_info["block"]
            th = src_h // grid_info["block"]
        else:
            tw = pixel_width
            th = (pixel_height if pixel_height > 0
                  else max(8, round(src_h * tw / src_w)))

        # 3. subject masks at source res (wired alpha wins, else segment key)
        if alpha is not None:
            m = alpha.cpu().numpy()
            subject_src = []
            for i in range(n):
                a = np.clip(m[min(i, m.shape[0] - 1)], 0, 1)
                a = np.asarray(Image.fromarray((a * 255).astype(np.uint8))
                               .resize((orig_w, orig_h),
                                       Image.Resampling.BILINEAR),
                               dtype=np.float32) / 255.0
                a = a[oy:oy + src_h, ox:ox + src_w]   # match the grid crop
                subject_src.append(a > 0.5)
        elif auto_subject:
            subject_src = [_auto_subject_mask(np.asarray(f), bg_tolerance)
                           for f in frames]
        else:
            subject_src = [np.ones((src_h, src_w), dtype=bool)
                           for _ in frames]

        # drop tiny speck components so they don't get outlined/paletted
        if _HAS_SCIPY:
            min_area = max(8, int(0.0004 * src_w * src_h))
            cleaned = []
            for sm in subject_src:
                if sm.all() or not sm.any():
                    cleaned.append(sm)
                    continue
                lab, nl = _ndi.label(sm)
                if nl <= 1:
                    cleaned.append(sm)
                    continue
                sizes = _ndi.sum_labels(sm, lab, range(1, nl + 1))
                keep = {c + 1 for c, sz in enumerate(sizes) if sz >= min_area}
                cleaned.append(np.isin(lab, list(keep)))
            subject_src = cleaned

        # 4. downscale (premultiplied against subject mask -> zero bleed)
        small, small_subject = [], []
        for i, f in enumerate(frames):
            rgb = np.asarray(f, dtype=np.float32)
            a = subject_src[i].astype(np.float32)
            prem = Image.fromarray(np.clip(rgb * a[..., None], 0, 255)
                                   .astype(np.uint8))
            prem_s = np.asarray(prem.resize((tw, th), _RESAMPLE[downsample_filter]),
                                dtype=np.float32)
            a_s = np.asarray(Image.fromarray((a * 255).astype(np.uint8)).resize(
                (tw, th), _RESAMPLE[downsample_filter]), dtype=np.float32) / 255.0
            sm = a_s > 0.5
            safe = np.maximum(a_s, 1e-3)
            unprem = np.clip(prem_s / safe[..., None], 0, 255)
            unprem[~sm] = 0
            small.append(Image.fromarray(unprem.astype(np.uint8)))
            small_subject.append(sm)

        # 5. palette: subject gets its own budget, backdrop the rest
        any_bg = any((~sm).any() for sm in small_subject)
        # v3.7.9-truecolors: when alpha is WIRED the backdrop is invisible in
        # the output (out_a = subject mask), and its premultiplied-black
        # samples cluster into pure-black bases that win dark subject px in
        # the redmean argmin (dark shading -> nearest "black" base -> ratio
        # clipped -> rendered BLACK). Give the subject the full budget.
        if alpha is not None:
            k_sub = colors
            k_bg = 0
        else:
            k_sub = max(2, int(round(colors * subject_palette_share)))
            k_bg = max(2, colors - k_sub) if any_bg else 0
        sub_masks = list(small_subject)
        pal_sub = _kmeans_palette(small, k_sub, space="lab", masks=sub_masks)
        sub_samples = _sample_pixels(small, masks=sub_masks)
        pal_rgb = list(pal_sub)
        bg_samples = None
        if k_bg > 0:
            bg_masks = [~sm for sm in small_subject]
            pal_bg = _kmeans_palette(small, k_bg, space="lab", masks=bg_masks)
            bg_samples = _sample_pixels(small, masks=bg_masks)
            pal_rgb += list(pal_bg)
        # deMuddy FIRST (counts still match the per-part palettes), merge
        # SECOND — merging before slicing by len(pal_sub) mis-assigns
        # subject/backdrop entries whenever near-duplicate colors collapse.
        pal_rgb = _demuddy_palette(sub_samples, list(pal_sub)) + \
            (_demuddy_palette(bg_samples, list(pal_bg))
             if bg_samples is not None else [])
        pal_rgb = _merge_palette(pal_rgb, threshold=7.0)
        pal = np.array(pal_rgb, dtype=np.float32)

        # 6. shade ramps (strict final palette)
        ramp = _build_ramps(pal_rgb, bands, ambient_brightness, hue_shift,
                            vibrancy)
        B = ramp.shape[1]
        K = pal.shape[0]

        # 7. map every small frame: nearest base color (redmean) -> band
        out_small, idx_maps = [], []
        dmat = None
        if dither != "none" and dither_strength > 0:
            dm = _bayer8() if dither == "bayer8" else _BAYER[dither]
            kk = dm.shape[0]
            dmat = np.tile(dm, (th // kk + 1, tw // kk + 1))[:th, :tw]
        # band boundaries for the temporal hysteresis (Schmitt trigger)
        bounds = []
        if bands == 2:
            bounds = [shadow_threshold]
        elif bands == 3:
            bounds = [shadow_threshold, highlight_threshold]
        elif bands >= 4:
            mid1 = shadow_threshold + (highlight_threshold - shadow_threshold) * 0.33
            mid2 = shadow_threshold + (highlight_threshold - shadow_threshold) * 0.66
            bounds = [shadow_threshold, mid1, mid2]
        prev_band = None
        dark_lines = []
        for i, f in enumerate(small):
            px = np.asarray(f, dtype=np.float32)
            # v3.7.8: classify base color + band from a spatially SMOOTHED
            # copy. Per-pixel redmean argmin on noisy grid-res input
            # (measured 95%% of px with no same-color neighbor on run
            # 6b4d97642d) scatters dark base classes through mid-tone
            # regions = the deepfried speck. Transparent px are filled from
            # the nearest opaque px first so the median doesn't drag
            # matte-black into the silhouette edge. The outline is NOT
            # trusted to this classification — thin dark lines are snapped
            # back deterministically in step 8.
            if region_vote and _HAS_SCIPY:
                _sm0 = small_subject[i]
                if (~_sm0).any():
                    _dt, _ind = _ndi.distance_transform_edt(
                        ~_sm0, return_indices=True)
                    px_f = px[tuple(_ind)]
                else:
                    px_f = px
                px_c = _ndi.median_filter(px_f, size=(3, 3, 1))
                dark_lines.append(
                    _dark_line_mask(np.asarray(f, dtype=np.uint8)) & _sm0)
            else:
                px_c = px
                dark_lines.append(None)
            flat = px_c.reshape(-1, 3)
            base_idx = _redmean_argmin(flat, pal).reshape(th, tw)
            base_col = pal[base_idx]                          # (th,tw,3)
            ratio = _luminance(px_c) / np.maximum(_luminance(base_col), 1.0)
            ratio = 1.0 + (ratio - 1.0) * cel_contrast
            if shade_smooth and _HAS_SCIPY:
                # median-filter the shade map: solid shade shapes instead of
                # speckled band mixes that morph every frame
                ratio = _ndi.median_filter(ratio, size=3)
            if dmat is not None:
                ratio = ratio + (dmat - 0.5) * 0.15 * (dither_strength / 0.15)
            ratio = np.clip(ratio, 0.001, 1.5)
            band = _ratio_to_band(ratio, bands, ambient_brightness,
                                  shadow_threshold, highlight_threshold)
            if prev_band is not None and band_hysteresis > 0 and bounds:
                # near a boundary, hold last frame's band: stops shade
                # regions popping back and forth on sub-threshold noise
                near = np.zeros(ratio.shape, dtype=bool)
                for b in bounds:
                    near |= np.abs(ratio - b) < band_hysteresis
                band = np.where(near, prev_band, band)
            prev_band = band
            idx = base_idx * B + band                         # ramp index
            out_small.append((band, base_idx))
            idx_maps.append(idx)

        # 7b. v3.7.8-regionvote: consolidate per-pixel base/band decisions
        # into regions. Without this, noisy grid-res input (95%% of px with
        # no same-color neighbor measured on run 6b4d97642d) quantizes into
        # ~9%% isolated speckle px = deepfried crunch + interior dark specks
        # that read as a dirty/eaten outline.
        if region_vote and _HAS_SCIPY and B >= 1:
            n_cls = K * B
            for i in range(n):
                for _pass in range(2):
                    idx_maps[i] = _region_vote(idx_maps[i], None,
                                               small_subject[i], n_cls,
                                               region_vote_thresh)
                new_idx = idx_maps[i]
                out_small[i] = (new_idx % B, new_idx // B)

        # 8. outline pass (silhouette) in darkest ramp shade, deeper still
        outline_idx_offset = K * B
        # v3.7.8: ONE global outline color (the darkest base's shade) — the
        # hand-drawn look is a single unbroken near-black line, not a
        # per-base patchwork of navy/brown/black (owner: "coloring is off,
        # parts of the black outline eaten").
        darkest_base = int(_luminance(pal).argmin()) if K else 0
        if outline != "off" and _HAS_SCIPY:
            for i in range(n):
                idx = idx_maps[i]
                _band, base_idx = out_small[i]
                sm = small_subject[i]
                if not sm.any() or sm.all():
                    continue
                dil = _ndi.binary_dilation(sm)
                ero = _ndi.binary_erosion(sm)
                if outline in ("outer", "both"):
                    ring = dil & ~sm
                    if ring.any():
                        # nearest interior pixel's base color
                        _dt, ind = _ndi.distance_transform_edt(
                            ~sm, return_indices=True)
                        near_base = base_idx[tuple(ind[:, ring])]
                        idx[ring] = outline_idx_offset + near_base
                if outline in ("inner", "both"):
                    inner = sm & ~ero
                    if inner.any():
                        idx[inner] = outline_idx_offset + darkest_base
                # v3.7.8: snap the hand-drawn thin dark lines (interior
                # outline strokes the silhouette ring can't reach) to the
                # same global outline color. Isolated dark specks and fat
                # shadow blobs are NOT in this mask — they already
                # dissolved into their regions in step 7/7b.
                if region_vote and i < len(dark_lines) \
                        and dark_lines[i] is not None:
                    idx[dark_lines[i]] = outline_idx_offset + darkest_base

        # 9. final palette table (ramp + outline shades), despeckle, compose
        outline_cols = np.clip(ramp[:, 0, :] * 0.55, 0, 255)  # deeper than shadow
        full_pal = np.concatenate([ramp.reshape(-1, 3), outline_cols], axis=0)
        full_pal_u8 = full_pal.astype(np.uint8)
        quant = []
        for idx in idx_maps:
            if despeckle > 0:
                idx = _despeckle(idx.astype(np.int32), despeckle,
                                 pal=full_pal_u8)
            quant.append(Image.fromarray(
                full_pal_u8[idx.clip(0, len(full_pal_u8) - 1)], "RGB"))

        # 10. crisp alpha + nearest upscale
        if upscale_factor == 0:
            fw, fh = src_w, src_h
        elif upscale_factor > 1:
            fw, fh = tw * upscale_factor, th * upscale_factor
        else:
            fw, fh = tw, th
        if (fw, fh) != (tw, th):
            quant = [f.resize((fw, fh), Image.Resampling.NEAREST) for f in quant]

        out_a = np.zeros((n, fh, fw), dtype=np.float32)
        out_s = np.zeros((n, fh, fw), dtype=np.float32)
        for i in range(n):
            a_img = Image.fromarray(small_subject[i].astype(np.uint8) * 255)
            s_img = a_img.copy()
            if (fw, fh) != (tw, th):
                a_img = a_img.resize((fw, fh), Image.Resampling.NEAREST)
                s_img = s_img.resize((fw, fh), Image.Resampling.NEAREST)
            out_a[i] = np.asarray(a_img, dtype=np.float32) / 255.0
            out_s[i] = np.asarray(s_img, dtype=np.float32) / 255.0

        used = sorted({int(v) for idx in idx_maps for v in np.unique(idx)})
        pal_hex = ["#%02X%02X%02X" % tuple(c) for c in
                   full_pal_u8[used].tolist()]
        info = json.dumps({
            "palette": pal_hex, "palette_size": len(pal_hex),
            "base_colors": ["#%02X%02X%02X" % tuple(c) for c in
                            pal.astype(np.uint8).tolist()],
            "bands": bands, "pixel_size": [tw, th],
            "output_size": [fw, fh], "frames": n,
            "grid": grid_info,
            "engine": "truepixel-cel-v2"})
        return (_pil_list_to_tensor(quant), torch.from_numpy(out_a),
                torch.from_numpy(out_s), info)


# ---------------------------------------------------------------------------
# standalone segment mask node (port of getSegmentPixelMap for workflows)

class PixelForgeSegmentMask:
    """Color-key region/subject extractor: redmean tolerance match with
    connected-island modes. Use it to pull a subject, a clothing region, or
    a backdrop out of H3 frames for targeted processing."""

    CATEGORY = "PixelForge/pixel"
    FUNCTION = "run"
    RETURN_TYPES = ("MASK", "IMAGE")
    RETURN_NAMES = ("mask", "preview")
    DESCRIPTION = ("Segment masking ported from Cel Shading Studio: pick a "
                   "key color, set tolerance, choose connectivity (any match, "
                   "border-connected backdrop, or largest island), get a "
                   "clean MASK for region/subject extraction.")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "key_color": ("STRING", {"default": "#000000",
                                         "tooltip": "Hex color to key on, e.g. #00FF00. 'auto' = median border color."}),
                "tolerance": ("FLOAT", {"default": 28.0, "min": 1.0, "max": 200.0, "step": 1.0,
                                        "tooltip": "Redmean perceptual tolerance."}),
                "connectivity": (["any", "border_connected", "largest_island"],
                                 {"tooltip": "any = all matching pixels; border_connected = only match-islands touching the frame edge (backdrop keying); largest_island = single biggest match-island."}),
                "invert": ("BOOLEAN", {"default": False}),
                "grow": ("INT", {"default": 0, "min": -32, "max": 32,
                                 "tooltip": "Dilate (positive) or erode (negative) the mask in pixels."}),
            },
        }

    def run(self, images, key_color, tolerance, connectivity, invert, grow):
        frames = _tensor_to_pil_list(images)
        n = len(frames)
        h, w = frames[0].size[1], frames[0].size[0]
        masks = np.zeros((n, h, w), dtype=np.float32)
        prev = np.zeros((n, h, w, 3), dtype=np.float32)
        for i, f in enumerate(frames):
            arr = np.asarray(f)
            if key_color.strip().lower() == "auto":
                border = np.concatenate([arr[0], arr[-1], arr[:, 0], arr[:, -1]])
                key = np.median(border.astype(np.float32), axis=0)
            else:
                s = key_color.strip().lstrip("#")
                key = np.array([int(s[j:j + 2], 16) for j in (0, 2, 4)],
                               dtype=np.float32)
            match = _segment_match_map(arr, key, tolerance)
            if connectivity == "border_connected":
                match = _border_connected_bg(match)
            elif connectivity == "largest_island" and _HAS_SCIPY:
                lab, nl = _ndi.label(match)
                if nl > 0:
                    sizes = _ndi.sum_labels(match, lab, range(1, nl + 1))
                    match = lab == (1 + int(np.argmax(sizes)))
            if grow != 0 and _HAS_SCIPY:
                match = (_ndi.binary_dilation(match, iterations=grow) if grow > 0
                         else _ndi.binary_erosion(match, iterations=-grow))
            if invert:
                match = ~match
            masks[i] = match.astype(np.float32)
            tint = arr.astype(np.float32) * 0.25
            tint[match] = np.array([236.0, 72.0, 153.0])
            prev[i] = tint / 255.0
        return (torch.from_numpy(masks), torch.from_numpy(prev))


NODE_CLASS_MAPPINGS = {
    "PixelForgeTruePixel": PixelForgeTruePixel,
    "PixelForgeSegmentMask": PixelForgeSegmentMask,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "PixelForgeTruePixel": "True Pixel Finalize (PixelForge)",
    "PixelForgeSegmentMask": "Segment Color Mask (PixelForge)",
}
