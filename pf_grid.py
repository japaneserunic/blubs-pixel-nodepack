"""Pixel-grid recovery: undo H3's blocky 'pixel-ish' render before pixelizing.

H3 draws 'pixel art' as blocks of several screen pixels (commonly 4x4). When
the quantize/finalize step downscales straight from video res, those blocks get
averaged into mush and a 64x64 target reads like 16x16. This node detects the
source block grid (size + phase), block-reduces every frame back to the TRUE
art grid (majority/median/nearest per block), and hands downstream nodes clean
1:1 pixels. Non-destructive: a separate node, old workflows untouched.
"""

import json
import warnings

import numpy as np
import torch

from .pf_finalize import (_detect_pixel_grid,
                          _detect_pixel_grid_frac)


def _to_np(images):
    return (images.clamp(0, 1) * 255).round().to(torch.uint8).cpu().numpy()


def _to_tensor(arr_uint8):
    return torch.from_numpy(arr_uint8.astype(np.float32) / 255.0)


def _trimmed_mean(px, widths=(8.0,), win=None):
    """px (B, N, 3) float -> (B, 3). Median-anchored iterative trimmed mean:
    start at the per-block median (robust to outlier pixels), then average
    only pixels within +-width of the running center (max channel distance),
    tightening the window each round. Median-anchored windows cut SYMMETRIC
    slices of the noise distribution, so the result stays unbiased (unlike
    fixed color-bin selection, which clips an off-center slice of the noise
    whenever the true color sits near a bin edge -> bin-center bias)."""
    m = np.nanmedian(px, axis=1)                       # (B,3)
    base = np.nan_to_num(m, nan=0.0)
    for w in widths:
        d = np.abs(px - m[:, None, :]).max(-1)         # (B,N)
        sel = d <= w
        if win is not None:
            sel &= win
        cnt = sel.sum(1)
        ssum = np.where(sel[..., None], px, 0.0).sum(1)
        out = ssum / np.maximum(cnt, 1)[:, None]
        none = cnt == 0
        if none.any():
            out[none] = base[none]
        m = out
    return m


def _reduce_blocks(crop, s, mode):
    """crop (H,W,3) uint8 with H,W multiples of s -> (H//s, W//s, 3) uint8."""
    gh, gw = crop.shape[0] // s, crop.shape[1] // s
    blocks = crop.reshape(gh, s, gw, s, 3)
    if mode == "nearest":
        c = s // 2
        return blocks[:, c, :, c, :].copy()
    ss = s * s
    px = blocks.transpose(0, 2, 1, 3, 4).reshape(-1, ss, 3).astype(np.float32)
    if mode == "median":
        # single wide trim: best for noisy but single-color blocks
        return _trimmed_mean(px, (8.0,)).round().astype(np.uint8).reshape(gh, gw, 3)
    # majority: two rounds, window tightens 12 -> 6. The median anchor lands
    # in the dominant color cluster even for edge-straddle blocks; the
    # tightening second round snaps to that cluster and drops the minority
    # side + stray outliers, staying unbiased for symmetric noise.
    return _trimmed_mean(px, (12.0, 8.0)).round().astype(np.uint8).reshape(gh, gw, 3)


def _reduce_blocks_masked(crop, amask, s, mode):
    """Alpha-aware variant: each block's color comes from its OPAQUE pixels
    only, so a keyed-out backdrop can never bleed into edge pixels (green
    halo at the silhouette, muddy outlines). Blocks with no opaque pixel
    fall back to the plain reduce (their alpha is 0; color is irrelevant).
    'nearest' degrades to masked median when a mask is present: sampling the
    block center would re-introduce keyed backdrop color exactly where the
    subject covers most of the block.

    Fast path: the plain vectorized reduce is correct for fully-opaque and
    fully-transparent blocks; only MIXED blocks (the silhouette edge) get
    the per-block masked trim."""
    out = _reduce_blocks(crop, s, mode)
    gh, gw = crop.shape[0] // s, crop.shape[1] // s
    ss = s * s
    am = amask.reshape(gh, s, gw, s).transpose(0, 2, 1, 3).reshape(gh, gw, ss) > 0.5
    cnt = am.sum(-1)
    mixed = (cnt > 0) & (cnt < ss)
    if not mixed.any():
        return out
    blocks = crop.reshape(gh, s, gw, s, 3)
    px = blocks.transpose(0, 2, 1, 3, 4).reshape(gh, gw, ss, 3).astype(np.float32)
    widths = (8.0,) if mode in ("median", "nearest") else (12.0, 8.0)
    ys, xs = np.nonzero(mixed)
    for y, x in zip(ys, xs):
        block = px[y, x][am[y, x]]
        out[y, x] = _trimmed_mean(block[None, :, :], widths)[0].round()
    return out




def _reduce_blocks_frac(frame, amask, px, py, ox, oy, mode="median"):
    """Reduce (H,W,3) uint8 onto a FRACTIONAL lattice -- the integer
    masked path's semantics generalized to fractional cell windows.
    Every source pixel is assigned to exactly ONE cell by pixel-center
    (cell k covers [o+k*p, o+(k+1)*p) in edge coords; pixel x covers
    [x, x+1)); cell color = median-anchored trimmed mean of its OPAQUE
    pixels (median-anchored windows cut SYMMETRIC noise slices and drop
    the boundary-straddler columns/rows; an area-weighted MEAN instead
    mixes 6-12% of each neighbor's color into every cell -- measured on
    a ground-truth p=8.585 lattice: median cell err 9 even on a PERFECT
    blur-free frame, 14 with blur+noise; center-assigned: 0 and ~1).
    Cells with no opaque pixel fall back to the plain reduce (their
    alpha is 0, color irrelevant). Cell alpha = opaque majority of the
    assigned pixels, same rule as the integer path. Complete cells only
    (the ragged margin is dropped, same as the integer crop). Returns
    (rgb uint8 (gh,gw,3), alpha float32 (gh,gw))."""
    h, w = frame.shape[:2]
    nx = int((w - ox) // px)
    ny = int((h - oy) // py)
    if nx < 4 or ny < 4:
        raise ValueError("fractional lattice too fine for the frame")
    kx = np.floor((np.arange(w) + 0.5 - ox) / px).astype(np.int64)
    ky = np.floor((np.arange(h) + 0.5 - oy) / py).astype(np.int64)
    x0 = int(np.searchsorted(kx, 0))
    x1 = int(np.searchsorted(kx, nx))
    y0 = int(np.searchsorted(ky, 0))
    y1 = int(np.searchsorted(ky, ny))
    k = (ky[y0:y1, None] * nx + kx[None, x0:x1]).ravel()
    n = ny * nx
    cnt = np.bincount(k, minlength=n)
    maxc = int(cnt.max())
    order = np.argsort(k, kind="stable")
    starts = np.zeros(n, np.int64)
    np.cumsum(cnt[:-1], out=starts[1:])
    ks = k[order]
    pos = np.arange(ks.shape[0]) - starts[ks]
    f = frame[y0:y1, x0:x1].reshape(-1, 3).astype(np.float32)[order]
    buf = np.full((n, maxc, 3), np.nan, np.float32)
    buf[ks, pos] = f
    if amask is None:
        a = np.ones((h, w), np.float32)
    else:
        a = amask.astype(np.float32)
    amap = np.zeros((n, maxc), np.float32)
    amap[ks, pos] = a[y0:y1, x0:x1].reshape(-1)[order]
    opaque = amap > 0.5
    widths = (8.0,) if mode in ("median", "nearest") else (12.0, 8.0)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        mean = _trimmed_mean(np.where(opaque[..., None], buf, np.nan),
                             widths)
        plain = _trimmed_mean(buf, widths)
    cnt_op = opaque.sum(1)
    none = cnt_op == 0
    if none.any():
        mean[none] = plain[none]
    cell_a = cnt_op / np.maximum(cnt, 1)
    rgb = np.clip(np.round(mean), 0, 255).astype(np.uint8)
    return (rgb.reshape(ny, nx, 3),
            (cell_a > 0.5).astype(np.float32).reshape(ny, nx))


class PixelForgeGridRecover:
    """Recover the TRUE pixel grid H3 rendered, before pixelizing.

    auto mode sniffs the apparent block size + phase (autocorrelation of the
    edge profile + variance-scored phase search, shared with True Pixel
    Finalize), crops to the grid, then block-reduces every frame so each
    output pixel is one real art pixel. Wire grid_width/grid_height into the
    Quantize/Finalize node's pixel_width/height (widget -> input) for a 1:1
    mapping, or set any smaller target and use downsample_filter=nearest —
    either way no block averaging, no mush."""

    CATEGORY = "PixelForge/pixel"
    FUNCTION = "run"
    RETURN_TYPES = ("IMAGE", "MASK", "INT", "INT", "STRING")
    RETURN_NAMES = ("images", "alpha", "grid_width", "grid_height", "grid_info")
    DESCRIPTION = ("Detect the pixel-block grid H3 already drew (block size + phase) and "
                   "block-reduce frames back to the true art grid: majority/median/nearest "
                   "per block. Chain BEFORE Sprite Chroma Key / Pixel Art Quantize and set "
                   "the quantize downsample filter to 'nearest' (or wire grid_width into "
                   "pixel_width). Fixes '64x64 target reads like 16x16'.")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "mode": (["auto", "manual"],
                         {"tooltip": "auto = detect block size + phase from the frames. "
                                     "manual = use manual_block with zero offset."}),
                "manual_block": ("INT", {"default": 4, "min": 1, "max": 32,
                                         "tooltip": "Block size for manual mode, and the fallback when auto "
                                                    "finds no convincing grid. 1 = passthrough."}),
                "max_block": ("INT", {"default": 12, "min": 2, "max": 32,
                                      "tooltip": "Largest block size auto detection considers."}),
                "reduce": (["median", "majority", "nearest"],
                           {"tooltip": "How each block becomes one pixel. median = robust average "
                                       "(best default for noisy H3 blocks), majority = modal color bin "
                                       "(best for flat art with stray outlier pixels), "
                                       "nearest = block center sample (sharpest, noisiest)."}),
                "restore_size": ("BOOLEAN", {"default": False,
                                             "tooltip": "Nearest-upscale the recovered grid back to the grid-snapped "
                                                        "source size. Off = emit the small true-grid frames "
                                                        "(recommended; pixelize from there)."}),
            },
            "optional": {
                "alpha": ("MASK", {"tooltip": "Optional matte to crop/reduce alongside the frames."}),
            },
        }

    def run(self, images, mode, manual_block, max_block, reduce, restore_size,
            alpha=None):
        arr = _to_np(images)
        n, h, w, _ = arr.shape
        info = {"source_size": [w, h], "reduce": reduce, "mode": mode}

        am = None
        if alpha is not None:
            m = alpha.cpu().numpy()
            am = [np.clip(m[min(i, m.shape[0] - 1)], 0, 1) for i in range(n)]

        s, ox, oy = 1, 0, 0
        auto_detected = False
        frac = None
        if mode == "auto":
            probe = np.median(arr[:min(8, n)].astype(np.float32),
                              axis=0).astype(np.uint8)
            det = _detect_pixel_grid(probe, s_max=max_block)
            if det is not None:
                s, ox, oy = det
                auto_detected = True
                # v3.10.8-fracgrid: H3 can render its drawn pixel grid at a
                # NON-integer pitch (live run 4788d88fa5: 704px gen
                # imitating an 82-cell ref -> true pitch 8.585; the integer
                # s=9 grid drifted ~0.46px/cell off the drawn boundaries =
                # art pixels one cell off near the edges). Refine to the
                # fractional lattice when edge recall proves it on BOTH
                # axes; otherwise keep the integer grid unchanged.
                _a_probe = None
                if am is not None:
                    _a_probe = np.median(
                        np.stack(am[:min(8, n)]).astype(np.float32), axis=0)
                _det_f = _detect_pixel_grid_frac(probe, s, alpha=_a_probe)
                if _det_f is not None:
                    _gwf = int((w - _det_f[2]) // _det_f[0])
                    _ghf = int((h - _det_f[3]) // _det_f[1])
                    if _gwf >= 8 and _ghf >= 8:
                        frac = _det_f
        if not auto_detected:
            s = manual_block
            if mode == "auto":
                print("[PixelForgeGridRecover] auto: no confident grid, "
                      "falling back to manual_block=%d" % manual_block)
        info["auto_detected"] = bool(auto_detected)
        info["block"] = int(s)
        info["offset"] = [int(ox), int(oy)]
        if frac is not None:
            info["fractional"] = True
            info["pitch"] = [round(float(frac[0]), 4),
                             round(float(frac[1]), 4)]
            info["frac_offset"] = [round(float(frac[2]), 3),
                                   round(float(frac[3]), 3)]
            info["edge_recall"] = [round(float(frac[4]), 3),
                                   round(float(frac[5]), 3)]
            info["edge_excess"] = round(float(frac[6]), 3)
            info["block"] = int(round((frac[0] + frac[1]) / 2.0))

        if s <= 1:
            gw, gh = w, h
            out_rgb = arr
            out_a = (np.stack(am) if am is not None
                     else np.ones((n, h, w), dtype=np.float32)).astype(np.float32)
            info.update({"grid_size": [gw, gh], "note": "passthrough (block=1)"})
            return (_to_tensor(out_rgb), torch.from_numpy(out_a), gw, gh,
                    json.dumps(info))

        if frac is not None:
            _fpx, _fpy, _fox, _foy = frac[0], frac[1], frac[2], frac[3]
            gw = int((w - _fox) // _fpx)
            gh = int((h - _foy) // _fpy)
            small = np.empty((n, gh, gw, 3), dtype=np.uint8)
            small_a = np.empty((n, gh, gw), dtype=np.float32)
            for i in range(n):
                _ai = None
                if am is not None:
                    _ai = am[i]
                    if _ai.shape != (h, w):
                        from PIL import Image
                        _ai = np.asarray(
                            Image.fromarray((_ai * 255).astype(np.uint8))
                            .resize((w, h), Image.Resampling.NEAREST),
                            dtype=np.float32) / 255.0
                small[i], small_a[i] = _reduce_blocks_frac(
                    arr[i], _ai, _fpx, _fpy, _fox, _foy, mode=reduce)
            out_rgb, out_a = small, small_a
            if restore_size:
                _si = int(round((_fpx + _fpy) / 2.0))
                out_rgb = np.repeat(np.repeat(small, _si, axis=1),
                                    _si, axis=2)
                out_a = np.repeat(np.repeat(small_a, _si, axis=1),
                                  _si, axis=2)
            info.update({"grid_size": [gw, gh],
                         "output_size": [int(out_rgb.shape[2]),
                                         int(out_rgb.shape[1])],
                         "restore_size": bool(restore_size)})
            print("[PixelForgeGridRecover] auto: FRAC lattice "
                  "%.3fx%.3f px/cell @ (%.2f,%.2f) -> %dx%d true grid "
                  "(edge recall %.2f vs int %.2f, excess %.2f)"
                  % (_fpx, _fpy, _fox, _foy, gw, gh,
                     frac[4], frac[5], frac[6]))
            return (_to_tensor(out_rgb),
                    torch.from_numpy(out_a.astype(np.float32)),
                    gw, gh, json.dumps(info))

        new_w = s * ((w - ox) // s)
        new_h = s * ((h - oy) // s)
        if new_w < 8 or new_h < 8:
            gw, gh = w, h
            out_rgb = arr
            out_a = (np.stack(am) if am is not None
                     else np.ones((n, h, w), dtype=np.float32)).astype(np.float32)
            info.update({"grid_size": [gw, gh],
                         "note": "passthrough (grid too small)"})
            return (_to_tensor(out_rgb), torch.from_numpy(out_a), gw, gh,
                    json.dumps(info))

        gw, gh = new_w // s, new_h // s
        small = np.empty((n, gh, gw, 3), dtype=np.uint8)
        small_a = np.empty((n, gh, gw), dtype=np.float32)
        for i in range(n):
            crop = arr[i, oy:oy + new_h, ox:ox + new_w]
            if am is not None:
                a = am[i]
                if a.shape != (h, w):
                    from PIL import Image
                    a = np.asarray(Image.fromarray((a * 255).astype(np.uint8))
                                   .resize((w, h), Image.Resampling.NEAREST),
                                   dtype=np.float32) / 255.0
                acrop = a[oy:oy + new_h, ox:ox + new_w]
                small[i] = _reduce_blocks_masked(crop, acrop, s, reduce)
                small_a[i] = (acrop.reshape(gh, s, gw, s).mean((1, 3)) > 0.5)
            else:
                small[i] = _reduce_blocks(crop, s, reduce)
                small_a[i] = 1.0

        out_rgb, out_a = small, small_a
        if restore_size:
            out_rgb = np.repeat(np.repeat(small, s, axis=1), s, axis=2)
            out_a = np.repeat(np.repeat(small_a, s, axis=1), s, axis=2)

        info.update({"grid_size": [gw, gh],
                     "snapped_size": [new_w, new_h],
                     "output_size": [int(out_rgb.shape[2]), int(out_rgb.shape[1])],
                     "restore_size": bool(restore_size)})
        print("[PixelForgeGridRecover] %s grid: %dpx block @ (%d,%d) -> "
              "%dx%d true grid%s" % ("auto" if auto_detected else "manual",
                                     s, ox, oy, gw, gh,
                                     " (restored to %dx%d)" % (new_w, new_h)
                                     if restore_size else ""))
        return (_to_tensor(out_rgb), torch.from_numpy(out_a.astype(np.float32)),
                gw, gh, json.dumps(info))


NODE_CLASS_MAPPINGS = {"PixelForgeGridRecover": PixelForgeGridRecover}
NODE_DISPLAY_NAME_MAPPINGS = {
    "PixelForgeGridRecover": "Pixel Grid Recover (PixelForge)"}
