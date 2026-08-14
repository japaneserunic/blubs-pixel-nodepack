"""Temporal stabilization: kill pixel creep/crawl without touching real motion.

H3 redraws edges slightly differently every frame; after grid recovery each
art pixel is clean per-frame but OSCILLATES across frames (crawl). This node
runs a per-pixel temporal filter over the batch:

  despike (default): non-causal lone-1-frame-blip removal — a pixel only
  changes when its color differs from t-1 AND t+1 returns to t-1. Zero lag,
  cannot hold stale colors. Safe everywhere.

  movelock: motion-adaptive lock. Measures per-pixel motion from a
  PRE-quantize reference (motion_ref); pixels the source says are static
  collapse to their most frequent color + majority matte, moving pixels get
  despike. Kills interior shimmer and edge wobble without freezing motion.

  hysteresis (legacy): a pixel's committed color only changes when a new
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
    carried = 0
    for t in range(1, n - 1):
        prev = aout[t - 1] > 0.5
        curr = a[t] > 0.5
        nxt = a[t + 1] > 0.5
        blip = (curr != prev) & (nxt == prev)
        if blip.any():
            akilled += int(blip.sum())
            aout[t] = np.where(blip, aout[t - 1], a[t])
            # RGB CARRY: a pixel the matte re-pins OPAQUE must not keep this
            # frame's RGB — quantize writes black filler under transparent
            # pixels, so an un-carried re-pin flashes black on the edge
            repin = blip & prev & ~curr
            if repin.any():
                carried += int(repin.sum())
                out_u8[t] = np.where(repin[..., None], out_u8[t - 1],
                                     out_u8[t])
    print("[PixelForgeTemporalStabilize] despike: %d alpha blip px-frames "
          "removed (%d re-pins carried prev color)" % (akilled, carried))
    return out_u8, aout


def _matte_lock(alpha, commit=2):
    """Temporal dead-man's switch for a binary matte. alpha (N,H,W) float 0..1.

    The silhouette edge is where per-frame keying/block-threshold decisions
    oscillate (the edge 'crawl' that reads as color<->black flicker once the
    transparent pixel renders over the dark preview). A pixel may only flip
    its opaque state when the new state persists for `commit` CONSECUTIVE
    frames — per-frame wobble never accumulates enough votes and dies, while
    real motion (a foot lifting for 5 frames) still commits, at most
    commit-1 frames late. Run this ONCE on the matte right before the look
    stage consumes it, so the matte and the premultiplied colors stay
    consistent (locking the matte after quantize would expose the black
    filler RGB quantize writes under transparent pixels)."""
    n = alpha.shape[0]
    if n < 2:
        return alpha
    b = alpha > 0.5
    committed = b[0].copy()
    run = np.zeros(committed.shape, dtype=np.int32)
    out = np.empty_like(b)
    out[0] = committed
    flips = 0
    held = 0
    for t in range(1, n):
        disagree = b[t] != committed
        run = np.where(disagree, run + 1, 0)
        fire = disagree & (run >= commit)
        flips += int(fire.sum())
        held += int((disagree & ~fire).sum())
        committed = np.where(fire, b[t], committed)
        run = np.where(fire, 0, run)
        out[t] = committed
    print("[PixelForgeTemporalStabilize] matte_lock: %d edge px-frames "
          "committed, %d wobble px-frames pinned (commit=%d)"
          % (flips, held, commit))
    return out.astype(np.float32)


def _minrun(arr, alpha=None, matte_only=False):
    """Minimum-hold temporal filter in LABEL space. arr (N,H,W,3) uint8.

    Pixel-art animation reads as intentional because a pixel's color (or its
    opaque/transparent state) HOLDS for several frames. H3 instead repaints
    shading every 1-2 frames; despike only catches 1-frame blips, so 2-frame
    repaints (A B B A) survive and read as hard flicker once the palette
    snaps them to distinct colors. This filter erases any STATE run shorter
    than 3 frames when the surrounding frames agree on the previous state:

      A B A     -> A A A      (1-frame blip, same as despike)
      A B B A   -> A A A A    (2-frame repaint — the one despike misses)
      A B B C   -> untouched  (genuine progression, not an excursion)

    State = exact quantized color when opaque, or TRANSPARENT. Matte
    excursions (sprite edge pixel keyed out for 1-2 frames -> color<->black
    edge flicker) are killed by the same rule, and a pixel re-pinned opaque
    inherits the carried color from the run before it (never backdrop
    filler RGB). Real motion that holds 3+ frames is never touched, so
    unlike hysteresis there is no lag and no stale-color painting.

    matte_only=True applies the excursion rule to the ALPHA state alone
    (color runs are left to despike): 2-frame matte wobbles die without the
    on-twos-eating risk of full color minrun.

    Must run AFTER quantize/TruePixel (needs exact color equality)."""
    n = arr.shape[0]
    if n < 3:
        return (arr, alpha) if alpha is not None else arr
    if matte_only and alpha is not None:
        # state = opaque/transparent ONLY; color runs untouched
        state = (alpha > 0.5).astype(np.int32)
    else:
        k = (arr[..., 0].astype(np.int32) << 16) | \
            (arr[..., 1].astype(np.int32) << 8) | arr[..., 2].astype(np.int32)
        if alpha is not None:
            a = alpha > 0.5
            state = np.where(a, k + 1, 0)      # 0 = transparent, >0 = color+1
        else:
            a = np.ones(k.shape, dtype=bool)
            state = k + 1
    s = state.copy()
    killed1 = killed2 = 0
    # settle passes: len-2 kills can expose new len-1 excursions and vice versa
    for _pass in range(2):
        # 2-frame excursions: s[t]==s[t+1], s[t]!=s[t-1], s[t+2]==s[t-1]
        for t in range(1, n - 2):
            m = (s[t] == s[t + 1]) & (s[t] != s[t - 1]) & (s[t + 2] == s[t - 1])
            if m.any():
                killed2 += int(m.sum())
                s[t] = np.where(m, s[t - 1], s[t])
                s[t + 1] = np.where(m, s[t - 1], s[t + 1])
        # 1-frame blips: s[t]!=s[t-1], s[t+1]==s[t-1]
        for t in range(1, n - 1):
            m = (s[t] != s[t - 1]) & (s[t + 1] == s[t - 1])
            if m.any():
                killed1 += int(m.sum())
                s[t] = np.where(m, s[t - 1], s[t])
    # unpack back to rgb + matte
    changed = s != state
    out = arr.copy()
    out_a = alpha.copy() if alpha is not None else None
    if changed.any():
        if matte_only and alpha is not None:
            # matte-only: re-pin the matte; re-opaqued px inherit the color
            # of the run they rejoined (previous settled frame), never the
            # black filler quantize leaves under transparent px
            for t in range(n):
                m = changed[t]
                if not m.any():
                    continue
                repin = m & (s[t] > 0) & (state[t] == 0)
                if repin.any() and t > 0:
                    out[t] = np.where(repin[..., None], out[t - 1], out[t])
                out_a[t] = np.where(m, (s[t] > 0).astype(np.float32), out_a[t])
        else:
            nc = np.clip(s - 1, 0, None)
            rgb = np.stack([(nc >> 16) & 255, (nc >> 8) & 255, nc & 255],
                           axis=-1).astype(np.uint8)
            repaint = changed & (s > 0)      # only rewrite pixels that stay opaque
            out = np.where(repaint[..., None], rgb, arr)
            if out_a is not None:
                new_a = s > 0
                out_a = np.where(changed, new_a.astype(np.float32), out_a)
    print("[PixelForgeTemporalStabilize] minrun%s: %d 2-frame + %d 1-frame "
          "state excursions erased%s" % (
              "(matte)" if matte_only else "",
              killed2, killed1,
              " (alpha only)" if matte_only else " (color+matte unified)"))
    if alpha is not None:
        return out, out_a
    return out


def _lockdown(arr, thr, commit, hold, alpha=None):
    """Full temporal lockdown for quantized sprite runs: hysteresis on the
    palette colors + matte_lock on the silhouette + color carry for pixels
    the matte re-pins opaque.

    Why not plain despike/minrun: H3 repaints shading every 1-3 frames and
    often does NOT return to the previous color (A B C progressions), which
    blip-filters structurally cannot catch. Hysteresis only commits a new
    color after `commit` consecutive matching frames (starvation escape at
    `hold`), so short repaints never become visible. Running it POST-quantize
    (label space) is what makes it safe: colors are exact palette entries, so
    the commit test is decisive instead of noisy — the old 'sandblast' failure
    came from running it pre-quantize on VAE grain.

    Matte: matte_lock(commit) applies the same persistence rule to the
    silhouette (edge color<->black flicker), and pixels re-pinned opaque
    inherit last frame's committed color (never backdrop filler).

    Measured on a chaotic 32-frame H3 sprite run (visible-flip count):
    raw 88208 -> despike 81072 -> lockdown(c3,h4) 28000 / (c4,h5) 14896.
    """
    out = _hysteresis(arr, float(thr), int(commit), int(hold))
    if alpha is None:
        return out
    locked = _matte_lock(alpha, commit=int(commit))
    raw = alpha > 0.5
    lk = locked > 0.5
    carried = 0
    for t in range(1, out.shape[0]):
        hole = lk[t] & ~raw[t]
        if hole.any():
            out[t][hole] = out[t - 1][hole]
            carried += int(hole.sum())
    if carried:
        print("[PixelForgeTemporalStabilize] lockdown: %d re-pinned px got "
              "carried color" % carried)
    return out, locked.astype(np.float32)


def _movelock(src, out, alpha=None, src_thr=12.0):
    """Motion-adaptive temporal lock. src (N,H,W,3) uint8 = PRE-quantize
    grid frames (the motion reference); out (N,H,W,3) uint8 = quantized
    label frames to stabilize.

    The eye reads flicker as 'color changed where nothing moved'. H3 repaints
    shading on STATIC sprite regions every frame; a swinging limb is real
    motion. So motion is measured from the SOURCE (median frame-to-frame abs
    diff per pixel, max channel) — pre-quantize, so palette snapping cannot
    create fake motion — and pixels split in two classes:

      static px (source barely moves): color collapses to the per-pixel
        temporal MODE (most frequent exact palette color) and the matte
        locks to its majority state — shimmer physically cannot survive,
        and re-pinned opaque px get the mode color (never backdrop filler).
      moving px: despike only (1-frame blips), real motion untouched.

    The static mask is eroded 1px so limb-boundary pixels (which alternate
    subject/backdrop) join the moving class, and mostly-transparent pixels
    are never 'static' (a stable backdrop must not lock opaque)."""
    n = out.shape[0]
    if n < 3:
        return (out, alpha) if alpha is not None else out
    sf = src.astype(np.float32)
    d = np.abs(sf[1:] - sf[:-1]).max(-1)          # (N-1,H,W)
    motion = np.median(d, axis=0)                  # robust per-px motion level
    if motion.shape != out.shape[1:3]:             # src at a different res
        from PIL import Image as _Img              # (fixed-size presets)
        motion = np.asarray(_Img.fromarray(motion.astype(np.float32),
            mode="F").resize((out.shape[2], out.shape[1]),
            _Img.Resampling.BILINEAR), dtype=np.float32)
    static = motion < src_thr
    # 1px erosion: boundary pixels join the moving class
    er = static.copy()
    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        er &= np.roll(static, (dy, dx), (0, 1))
    static = er
    # matte pin applies to ALL static px (both majority states — a static
    # backdrop pixel pinned transparent is correct, not dangerous); the COLOR
    # lock below is the one restricted to mostly-opaque px
    mostly_opaque = None
    if alpha is not None:
        mostly_opaque = (alpha > 0.5).mean(0) > 0.5
        if mostly_opaque.shape != static.shape:
            mostly_opaque = np.ones(static.shape, bool)

    # baseline for moving px: despike (zero lag, cannot paint stale colors)
    if alpha is not None:
        res, res_a = _despike(out, 4.0, alpha=alpha)
    else:
        res, res_a = _despike(out, 4.0), None

    # per-px temporal MODE of exact colors on static px (quantized input =>
    # few unique colors; exact mode beats a packed-int median, which is not
    # a perceptual ordering). OPAQUE FRAMES ONLY: quantize writes black
    # filler RGB under transparent pixels, and an edge pixel that is opaque
    # ~55% of frames with its real colors split across palette entries has
    # BLACK as its single most frequent color — pinning it black every frame
    # (the color<->black edge flicker). Transparent frames must not vote.
    k = (out[..., 0].astype(np.int32) << 16) | \
        (out[..., 1].astype(np.int32) << 8) | out[..., 2].astype(np.int32)
    uniq, inv = np.unique(k, return_inverse=True)   # inv (N,H,W) -> uniq idx
    if len(uniq) <= 512:
        npix = k.size // n
        counts = np.zeros((len(uniq), npix), dtype=np.int32)
        if alpha is not None:
            votes = (alpha > 0.5).reshape(n, npix).T.astype(np.int32)
        else:
            votes = np.ones((npix, n), dtype=np.int32)
        np.add.at(counts, (inv.reshape(n, npix).T,
                           np.arange(npix).reshape(-1, 1)),
                  votes)                             # per-px color histogram
        mode_idx = uniq[counts.argmax(0)].reshape(k.shape[1:])
        # CONSISTENCY GATE: lock a pixel to its mode color only when that
        # color clearly dominates its opaque frames. Shimmer (A A B A C A)
        # has a dominant mode and dies; genuinely repainted shading
        # (A B C D over the run) has no dominant color — per-pixel mode
        # there picks a DIFFERENT loser per pixel and salt-and-peppers the
        # region (the 'way bad' speckle regression). Those fall through to
        # despike, which is spatially coherent.
        total_votes = votes.sum(1).astype(np.float32)          # (npix,)
        share = (counts.max(0) / np.maximum(total_votes, 1.0)
                 ).reshape(k.shape[1:])
        gate = share >= 0.6
    else:                                            # pathological palette
        mode_idx = np.sort(k, axis=0)[n // 2]        # median-label fallback
        gate = np.zeros(k.shape[1:], dtype=bool)
    lockable = static & gate
    if mostly_opaque is not None:
        lockable &= mostly_opaque
    mode_rgb = np.stack([(mode_idx >> 16) & 255, (mode_idx >> 8) & 255,
                         mode_idx & 255], axis=-1).astype(np.uint8)
    locked_px = 0
    for t in range(n):
        # lockable static px are pinned to the mode EVERY frame — test the
        # CURRENT (despike-baselined) frame, not the original label, or
        # despike's repaints leak through
        m = lockable & (res[t] != mode_rgb).any(-1)
        if m.any():
            res[t][m] = mode_rgb[m]
            locked_px += int(m.sum())
    if res_a is not None:
        opaque_majority = (alpha > 0.5).mean(0) > 0.5  # static & this = opaque
        for t in range(n):
            m = static & ((res_a[t] > 0.5) != opaque_majority)
            if m.any():
                res_a[t][m] = opaque_majority[m].astype(np.float32)
                # re-pinned OPAQUE on a frame where the pixel was keyed out:
                # carry a real color so it never flashes black filler — the
                # mode color when the pixel is color-locked, else last frame's
                if mostly_opaque is not None:
                    repin = m & opaque_majority & ~(alpha[t] > 0.5)
                    if repin.any():
                        src_rgb = np.where(lockable[..., None],
                                           mode_rgb, res[t - 1])
                        res[t][repin] = src_rgb[repin]
    print("[PixelForgeTemporalStabilize] movelock: %d static px (%d "
          "color-locked, gate=mode>=60%%), %d px-frames rewritten, "
          "src_thr=%.1f" % (int(static.sum()), int(lockable.sum()),
                            locked_px, src_thr))
    if alpha is not None:
        return res, res_a
    return res


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


def _median3_inner(arr, alpha):
    """Alpha-safe 3-frame temporal median for keyed sprites. H3 repaints
    shading per frame (navy mane -> blue mane -> navy with the pose nearly
    static); a temporal median picks the stable middle value and kills that
    shimmer. ONLY applied where the pixel is opaque in all 3 frames: keyed
    pixels keep their original (backdrop-colored) RGB, and a naive temporal
    median would smear that backdrop color into edge pixels. Pixels that
    fail the all-opaque test keep their current color (the matte despike /
    edge logic owns those)."""
    n = arr.shape[0]
    if n < 3:
        return arr
    f = arr.astype(np.float32)
    a = alpha > 0.5
    out = f.copy()
    changed = 0
    for t in range(1, n - 1):
        inner = a[t - 1] & a[t] & a[t + 1]
        if not inner.any():
            continue
        med = np.median(np.stack([f[t - 1], f[t], f[t + 1]]), axis=0)
        sel = inner & (np.abs(med - f[t]).max(-1) > 0)
        if sel.any():
            out[t] = np.where(sel[..., None], med, f[t])
            changed += int(sel.sum())
    print("[PixelForgeTemporalStabilize] median3_inner: %d interior px-frames "
          "smoothed" % changed)
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
                   "'movelock' mode-locks pixels the SOURCE says are static "
                   "(needs motion_ref wired) and despikes the rest — kills "
                   "interior shimmer + edge matte wobble. 'minrun'/'lockdown' "
                   "are experimental (can eat on-twos animation / trail "
                   "motion). 'hysteresis' (legacy), 'median3', 'off'. "
                   "Wire alpha to also stabilize the matte.")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "mode": (["despike", "despike_matte", "movelock", "minrun", "median3_inner", "lockdown", "hysteresis", "median3", "off"],
                         {"tooltip": "despike (default) = remove lone 1-frame blips "
                                     "(color returns next frame) - zero lag, "
                                     "cannot hold stale colors, safest. "
                                     "despike_matte = despike PLUS a minimum-hold "
                                     "rule on the matte: 1-2 frame opaque/transparent "
                                     "excursions at the silhouette edge are erased and "
                                     "re-pinned pixels carry their previous color "
                                     "(never black filler). Best default for H3 "
                                     "sprites. movelock = pixels the SOURCE "
                                     "(motion_ref) says are static get locked to their "
                                     "dominant color (only when one color clearly "
                                     "dominates, else despike) + majority matte; "
                                     "needs motion_ref (pre-quantize grid frames) "
                                     "wired. minrun/lockdown = EXPERIMENTAL (eat "
                                     "on-twos animation / trail motion). minrun = "
                                     "minimum-hold filter on color AND matte. "
                                     "median3_inner = 3-frame temporal median on "
                                     "INTERIOR pixels only; needs alpha wired. "
                                     "hysteresis = commit after commit_frames "
                                     "persistent frames (legacy; trails motion). "
                                     "median3 = 3-frame temporal median (eats legit "
                                     "1-frame events). off = passthrough. Wire "
                                     "alpha to also stabilize the matte."}),
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
            # --- v6: motion_ref for movelock (positional compat) ---
            "optional": {"alpha": ("MASK",),
                         "motion_ref": ("IMAGE", {
                             "tooltip": "movelock only: PRE-quantize frames "
                                        "(grid-recover output) used to measure "
                                        "which pixels actually move."})},
        }

    def run(self, images, mode, threshold, commit_frames, max_hold=3,
            alpha=None, motion_ref=None):
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
        elif mode == "median3_inner":
            if a_np is None:
                print("[PixelForgeTemporalStabilize] median3_inner needs "
                      "alpha wired - passing through unchanged")
                out = arr
            else:
                out = _median3_inner(arr, a_np)
            out_a = torch.ones(arr.shape[0], arr.shape[1], arr.shape[2]) \
                if alpha is None else alpha
        elif mode == "lockdown":
            if a_np is not None:
                out, a_l = _lockdown(arr, float(threshold),
                                     int(commit_frames), int(max_hold),
                                     alpha=a_np)
                out_a = torch.from_numpy(a_l.astype(np.float32))
            else:
                out = _lockdown(arr, float(threshold),
                                int(commit_frames), int(max_hold))
                out_a = torch.ones(arr.shape[0], arr.shape[1], arr.shape[2])
        elif mode == "minrun":
            if a_np is not None:
                out, a_m = _minrun(arr, alpha=a_np)
                out_a = torch.from_numpy(a_m.astype(np.float32))
            else:
                out = _minrun(arr)
                out_a = torch.ones(arr.shape[0], arr.shape[1], arr.shape[2])
        elif mode == "movelock":
            if motion_ref is None:
                print("[PixelForgeTemporalStabilize] movelock needs "
                      "motion_ref (pre-quantize frames) wired - falling "
                      "back to despike")
                if a_np is not None:
                    out, a_d = _despike(arr, float(threshold), alpha=a_np)
                    out_a = torch.from_numpy(a_d.astype(np.float32))
                else:
                    out = _despike(arr, float(threshold))
                    out_a = torch.ones(arr.shape[0], arr.shape[1],
                                       arr.shape[2])
            else:
                src = _to_np(motion_ref)
                if a_np is not None:
                    out, a_m = _movelock(src, arr, alpha=a_np,
                                         src_thr=float(threshold))
                    out_a = torch.from_numpy(a_m.astype(np.float32))
                else:
                    out = _movelock(src, arr, src_thr=float(threshold))
                    out_a = torch.ones(arr.shape[0], arr.shape[1],
                                       arr.shape[2])
        elif mode == "despike_matte":
            if a_np is not None:
                out, a_d = _despike(arr, float(threshold), alpha=a_np)
                out, a_m = _minrun(out, alpha=a_d, matte_only=True)
                out_a = torch.from_numpy(a_m.astype(np.float32))
            else:
                out = _despike(arr, float(threshold))
                out_a = torch.ones(arr.shape[0], arr.shape[1], arr.shape[2])
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
