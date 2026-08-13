"""Temporal stabilization: kill pixel creep/crawl without touching real motion.

H3 redraws edges slightly differently every frame; after grid recovery each
art pixel is clean per-frame but OSCILLATES across frames (crawl). This node
runs a per-pixel temporal filter over the batch:

  hysteresis (default): a pixel's committed color only changes when a new
  color persists for commit_frames CONSECUTIVE frames (and differs by more
  than threshold). One-frame blips never commit -> crawl dies; real motion
  persists 2+ frames -> passes through with commit_frames-1 frames of delay
  at most. Starvation escape: pixels that never return to their committed
  color for max_hold consecutive frames force-commit to the current color,
  so continuously-moving regions can't freeze on stale colors.

  median3: sliding 3-frame temporal median per pixel per channel. Cheaper,
  softer: also removes legitimate 1-frame events (muzzle flashes, impacts).

Place right AFTER Pixel Grid Recover (small true-grid frames = cheap and each
pixel is one real art pixel), BEFORE chroma key / quantize. Non-destructive:
separate node, 'off' mode is a bit-identical passthrough.
"""

import numpy as np
import torch


def _to_np(images):
    return (images.clamp(0, 1) * 255).round().to(torch.uint8).cpu().numpy()


def _to_tensor(arr_uint8):
    return torch.from_numpy(arr_uint8.astype(np.float32) / 255.0)


def _maxdiff(a, b):
    """(H,W,3) float arrays -> (H,W) max channel abs diff."""
    return np.abs(a - b).max(-1)


def _hysteresis(arr, thr, commit_frames, max_hold):
    """arr (N,H,W,3) uint8 -> stabilized copy.

    commit rule: a pixel changes only when a new color persists for
    commit_frames consecutive frames. STARVATION ESCAPE: if a pixel has
    been unstable (never returned to its committed color) for max_hold
    consecutive frames, it force-commits to the current color — without
    this, continuously-moving regions (legs mid-swing) never reach
    commit_frames and freeze on a stale color (the 'sandblasted' look).
    True crawl still dies: oscillation that periodically returns to the
    committed color resets the stale counter before it can fire."""
    n = arr.shape[0]
    if n < 3:
        return arr
    f = arr.astype(np.float32)
    committed = f[0].copy()
    cand = committed.copy()
    run = np.zeros(committed.shape[:2], dtype=np.int32)
    stale = np.zeros(committed.shape[:2], dtype=np.int32)
    out = np.empty_like(f)
    out[0] = committed
    flips = 0
    held = 0
    escaped = 0
    for t in range(1, n):
        ft = f[t]
        stable = _maxdiff(ft, committed) <= thr
        match = _maxdiff(ft, cand) <= thr
        run = np.where(match, run + 1, 1)
        cand = np.where(match[..., None], cand, ft)
        stale = np.where(stable, 0, stale + 1)
        persist_fire = run >= commit_frames
        escape_fire = stale >= max_hold
        fire = (~stable) & (persist_fire | escape_fire)
        held += int((~stable & ~fire).sum())
        flips += int((fire & persist_fire).sum())
        escaped += int((fire & ~persist_fire).sum())
        committed = np.where(fire[..., None], ft, committed)
        # reset candidate tracker wherever we just committed or are stable
        reset = fire | stable
        cand = np.where(reset[..., None], committed, cand)
        run = np.where(reset, 0, run)
        stale = np.where(reset, 0, stale)
        out[t] = committed
    print("[PixelForgeTemporalStabilize] hysteresis: %d px-frames committed, "
          "%d force-committed (starvation escape), %d blip px-frames held "
          "(thr=%.1f, commit=%d, max_hold=%d)"
          % (flips, escaped, held, thr, commit_frames, max_hold))
    return out.round().astype(np.uint8)


def _despike(arr, thr, alpha=None):
    """Non-causal 1-frame blip removal. arr (N,H,W,3) uint8.

    A pixel's color at frame t is replaced by frame t-1's (corrected) color
    ONLY when it differs from t-1 by more than thr AND t+1 matches t-1 again
    — i.e. a lone 1-frame deviation. Real motion persists 2+ frames and is
    never touched, so unlike hysteresis this CANNOT paint stale colors into
    newly-moved regions (the 'eating itself' failure) and adds zero lag.

    When alpha (N,H,W float 0..1) is wired, the same blip rule is applied to
    the matte itself (kills 1-frame edge flicker holes/spikes)."""
    n = arr.shape[0]
    if n < 3:
        return arr if alpha is None else (arr, alpha)
    f = arr.astype(np.float32)
    out = f.copy()
    killed = 0
    for t in range(1, n - 1):
        prev = out[t - 1]
        curr = f[t]
        nxt = f[t + 1]
        blip = (_maxdiff(curr, prev) > thr) & (_maxdiff(nxt, prev) <= thr)
        if blip.any():
            killed += int(blip.sum())
            out[t] = np.where(blip[..., None], prev, curr)
    print("[PixelForgeTemporalStabilize] despike: %d blip px-frames removed "
          "(thr=%.1f)" % (killed, thr))
    out_u8 = out.round().astype(np.uint8)
    if alpha is None:
        return out_u8
    a = alpha
    aout = a.copy()
    akilled = 0
    for t in range(1, n - 1):
        prev = aout[t - 1] > 0.5
        curr = a[t] > 0.5
        nxt = a[t + 1] > 0.5
        blip = (curr != prev) & (nxt == prev)
        if blip.any():
            akilled += int(blip.sum())
            aout[t] = np.where(blip, aout[t - 1], a[t])
    print("[PixelForgeTemporalStabilize] despike: %d alpha blip px-frames "
          "removed" % akilled)
    return out_u8, aout


def _median3(arr):
    n = arr.shape[0]
    if n < 3:
        return arr
    f = arr.astype(np.float32)
    pad = np.concatenate([f[:1], f, f[-1:]], axis=0)
    out = np.empty_like(f)
    for t in range(n):
        out[t] = np.median(pad[t:t + 3], axis=0)
    return out.round().astype(np.uint8)


class PixelForgeTemporalStabilize:
    """Per-pixel temporal filter that kills pixel crawl between frames."""

    CATEGORY = "PixelForge/pixel"
    FUNCTION = "run"
    RETURN_TYPES = ("IMAGE", "MASK")
    RETURN_NAMES = ("images", "alpha")
    DESCRIPTION = ("Kill pixel creep/crawl between frames. mode 'despike' "
                   "(default) removes lone 1-frame color/matte deviations "
                   "with zero lag and no stale-color bleed — safe everywhere "
                   "in the chain, best right after TruePixel (label space). "
                   "'hysteresis' (legacy) commits changes only after "
                   "commit_frames persistent frames. 'median3' = 3-frame "
                   "temporal median. 'off' = passthrough. Wire alpha to also "
                   "despike the matte (kills 1-frame edge flicker).")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "mode": (["despike", "hysteresis", "median3", "off"],
                         {"tooltip": "despike = remove lone 1-frame blips "
                                     "(color returns next frame) — zero lag, "
                                     "cannot hold stale colors, safest. "
                                     "hysteresis = commit changes only after "
                                     "commit_frames persistent frames "
                                     "(legacy; can trail motion). median3 = "
                                     "3-frame temporal median (softer, also "
                                     "eats legit 1-frame events). off = "
                                     "passthrough."}),
                "threshold": ("FLOAT", {
                    "default": 10.0, "min": 0.0, "max": 128.0, "step": 1.0,
                    "tooltip": "Min color distance (0-255, max channel) that "
                               "counts as a real change. Below this the pixel "
                               "is considered 'same'. Raise for noisy sources, "
                               "lower to preserve subtle shading shifts."}),
                "commit_frames": ("INT", {
                    "default": 2, "min": 2, "max": 5,
                    "tooltip": "hysteresis only: frames a new color must "
                               "persist before the pixel commits to it."}),
                # --- v4 widget appended (positional compat) ---
                "max_hold": ("INT", {
                    "default": 3, "min": 2, "max": 8,
                    "tooltip": "hysteresis only: starvation escape — if a "
                               "pixel has NOT matched its committed color for "
                               "this many consecutive frames, force-commit to "
                               "the current color."}),
            },
            # --- v5: optional matte despike (positional compat) ---
            "optional": {"alpha": ("MASK",)},
        }

    def run(self, images, mode, threshold, commit_frames, max_hold=3,
            alpha=None):
        a_np = None
        if alpha is not None:
            a_np = alpha.cpu().numpy().astype(np.float32)
            if a_np.ndim == 4:
                a_np = a_np[..., 0]
        if mode == "off":
            out_a = alpha if alpha is not None else torch.ones(
                images.shape[0], images.shape[1], images.shape[2])
            return (images, out_a)
        arr = _to_np(images)
        if mode == "median3":
            out = _median3(arr)
            out_a = torch.ones(arr.shape[0], arr.shape[1], arr.shape[2]) \
                if alpha is None else alpha
        elif mode == "despike":
            if a_np is not None:
                out, a_d = _despike(arr, float(threshold), alpha=a_np)
                out_a = torch.from_numpy(a_d.astype(np.float32))
            else:
                out = _despike(arr, float(threshold))
                out_a = torch.ones(arr.shape[0], arr.shape[1], arr.shape[2])
        else:
            out = _hysteresis(arr, float(threshold), int(commit_frames),
                              int(max_hold))
            out_a = torch.ones(arr.shape[0], arr.shape[1], arr.shape[2]) \
                if alpha is None else alpha
        return (_to_tensor(out), out_a)


NODE_CLASS_MAPPINGS = {"PixelForgeTemporalStabilize": PixelForgeTemporalStabilize}
NODE_DISPLAY_NAME_MAPPINGS = {
    "PixelForgeTemporalStabilize": "Temporal Stabilize / Crawl Killer (PixelForge)"}
