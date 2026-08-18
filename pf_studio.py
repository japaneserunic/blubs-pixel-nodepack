# VERSION: v3.7.9-truecolors (2026-08-18) — the "inner" outline was the black-crush/eaten-sprite bug: on a small art grid (78x77) the inner silhouette ring is ~9%% of the sprite; repainting it near-black ate thin limbs + read as holes (measured on real v9 run uid b77f508dce: outline ON mean|d| 58 vs grid, ~700 near-black px; OFF 25.8 / ~200, colors match the gen). Default outline now OFF (H3 already draws its own outline; adv_tp_outline can force it). Subject palette share 0.75 -> 1.0 (wired alpha = invisible backdrop; the 4 bg clusters were pure transparent-black bases that black-holed dark shading px).
# VERSION: v3.7.8-regionvote (2026-08-17) — TruePixel classifies base+band from a 3x3-median signal (per-px argmin on 95%-speckle grid-res input = deepfry), 2x 3x3 majority region vote on the final class map, thin dark lines + inner ring snapped to ONE global outline color (unbroken black outline, no navy patchwork), grid report prints block/offset, full-res source frame dump for forensics
# VERSION: v3.7.7-pixelpure (2026-08-17) — Hi-bit cel flatten 5.0->0.0 (bilateral at art-grid res blurred clean pixels into mixel mush, the non-Hi-bit looks already knew: "flatten at art-res eats outlines"), TruePixel inner outline preserves existing near-black px (was repainting hand-drawn black outlines with base-color shadow shades = navy outlines on blue hair)
"""PixelForge Super Forge — the all-in-one workspace suite node.

One node, whole pipeline, with a full in-node studio UI (canvas, timeline,
transport, stage inspector — see web/js/pf_studio.js). Wraps the exact same
battle-tested engines the Easy v2 suite uses (pf_sprite / pf_grid /
pf_pixelize / pf_finalize / pf_temporal); nothing here duplicates engine code
and nothing existing is modified — this file is purely additive.

What sets it apart from Sprite Studio (Easy v2):
  - FULL parameter surface: every Easy knob plus the advanced engine params
    Easy hides, as adv_* overrides with a "preset" sentinel (-1 / "preset"
    means: use the value the main knobs would pick).
  - Stage capture: after every pipeline stage the frames are written to the
    temp preview dir and shipped in the ui result as `pf_frames`/`pf_meta`
    (flat lists — dict-valued ui keys do NOT survive the server's ui merge,
    see the SERVER FLATTEN note near the return), so the frontend can show
    source -> keyed -> grid -> look -> motion -> final side by side. This is
    the direct answer to "the processed output looks worse than H3's raw
    video" — you can see exactly which stage loses it.
"""

import json
import os
import uuid

import numpy as np
import torch
from PIL import Image

import folder_paths

from .pf_palettes import PALETTE_NAMES
from .pf_pixelize import PixelForgeQuantize, _STYLE_PRESETS
from .pf_sprite import (PixelForgeAutoCrop, PixelForgeChromaKey,
                        PixelForgeFrameDedup, PixelForgeLoopTrim)
from .pf_grid import (PixelForgeGridRecover, _reduce_blocks,
                      _reduce_blocks_masked)
from .pf_temporal import PixelForgeTemporalStabilize
from .pf_finalize import PixelForgeTruePixel

# --- shared vocabularies (kept identical to pf_easy so muscle memory transfers)
from .pf_easy import (_ANCHORS, _BACKGROUNDS, _CANVAS, _DITHER, _KEY_STRENGTH,
                      _LOOPS, _LOOKS, _MOTION, _PLACEMENTS, _SIZE_PRESETS)

_TRI = ["preset", "on", "off"]          # 3-state override for engine booleans
_STAGE_ORDER = ["source", "keyed", "grid", "look", "motion", "final"]

# Suite-only size vocab (v3.7.0): the shared Easy dict can't carry this —
# Easy's resolver treats ANY negative sentinel as full Source. "Source / 2"
# halves H3's true grid: an exact 2x block-reduce (crisp, no fractional
# downsample mush) that lands in the pixel-art sweet spot (~68px for the
# default 544 gen vs 136 at full Source).
_SUITE_SIZES = (["Source (H3's own grid)", "Source / 2 (balanced)"] +
                [k for k in _SIZE_PRESETS if k != "Source (H3's own grid)"])


def _pick(v, default):
    """-1 sentinel = keep the value the main knobs selected."""
    return default if v == -1 else v


def _tri(v, default):
    return default if v == "preset" else (v == "on")


def _thin_indices(n, cap):
    if n <= cap:
        return list(range(n))
    return sorted(set(int(round(x)) for x in
                      np.linspace(0, n - 1, cap).tolist()))


def _save_stage(tag, uid, images, alpha, cap, max_edge=512, pixel_exact=False):
    """Write a thinned RGBA preview set to ComfyUI's temp dir.

    Returns (refs, meta). pixel_exact stages (anything at art-grid res) are
    never rescaled — the whole point is judging true pixels; smooth stages
    (source/keyed at video res) are capped for bandwidth.
    """
    refs = []
    n = images.shape[0]
    idxs = _thin_indices(n, cap)
    tmp = folder_paths.get_temp_directory()
    w = h = 0
    for out_i, i in enumerate(idxs):
        rgb = (images[i].clamp(0, 1) * 255).round().to(torch.uint8).cpu().numpy()
        h, w = rgb.shape[:2]
        if alpha is not None:
            a = alpha[min(i, alpha.shape[0] - 1)].cpu().numpy()
            a8 = (np.clip(a, 0, 1) * 255).round().astype(np.uint8)
            img = Image.fromarray(np.dstack([rgb, a8]), "RGBA")
        else:
            img = Image.fromarray(rgb, "RGB")
        if not pixel_exact and max(img.width, img.height) > max_edge:
            s = max_edge / float(max(img.width, img.height))
            img = img.resize((max(1, int(round(img.width * s))),
                              max(1, int(round(img.height * s)))),
                             Image.LANCZOS)
        fname = f"pfs_{uid}_{tag}_{out_i:03d}.png"
        img.save(os.path.join(tmp, fname))
        refs.append({"filename": fname, "subfolder": "", "type": "temp"})
    meta = {"frames": int(n), "shown": len(refs), "w": int(w), "h": int(h),
            "skipped": False}
    return refs, meta


class PixelForgeSuperForge:
    """The suite. Same pipeline contract as Sprite Studio (Easy v2) — wire it
    anywhere the Easy node sits — plus full adv_* access and stage previews."""

    CATEGORY = "PixelForge/Suite"
    FUNCTION = "run"
    # NOTE: OUTPUT_NODE intentionally omitted. The suite renders its own
    # sprite frames inside the node canvas via pf_frames in the UI dict.
    # Setting OUTPUT_NODE = True causes ComfyUI's frontend to bolt a native
    # image-preview overlay onto the node — that widget appears OUTSIDE the
    # suite canvas (the "sprite outside the interface" bug) and steals
    # layout space from the suite.  The IMAGE output is still available for
    # downstream wiring (Preview Image, Save, etc.) regardless of this flag.
    RETURN_TYPES = ("IMAGE", "MASK", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("images", "alpha", "durations_json", "palette_json", "forge_report")
    DESCRIPTION = ("All-in-one pixel forge workspace: canvas + timeline + stage "
                   "inspector in the node UI. Main knobs up top; every advanced "
                   "engine parameter available as adv_* overrides (right-click "
                   "or the suite's Advanced toggle).")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                # ================= MAIN FORGE (obvious knobs) =================
                "size_preset": (list(_SUITE_SIZES), {"default": "Source (H3's own grid)",
                                "tooltip": "Final sprite resolution in art pixels. Source = the exact grid H3 rendered (crispest, very fine). Source / 2 = half that grid when the detected grid is just H3's ~4px render texture; if the gen already drew real pixel blocks (>=6px, e.g. imitating a hi-bit ref) the Source grid is kept — halving would erase the art. Pick a fixed size only for game-ready dimensions."}),
                "custom_width": ("INT", {"default": 64, "min": 8, "max": 2048, "step": 8}),
                "custom_height": ("INT", {"default": 0, "min": 0, "max": 2048, "step": 8,
                                  "tooltip": "0 = match source aspect. Custom size only."}),
                "look": (_LOOKS, {"default": "Modern (smooth color)"}),
                "palette": (["auto (from sprite)"] + PALETTE_NAMES + ["use custom image"],
                            {"default": "auto (from sprite)"}),
                "colors": ("INT", {"default": 32, "min": 2, "max": 256}),
                "dither": (list(_DITHER.keys()), {"default": "Off"}),
                "cleanup": ("INT", {"default": 1, "min": 0, "max": 3,
                            "tooltip": "Despeckle passes — removes lonely stray pixels."}),
                "background": (list(_BACKGROUNDS.keys()), {"default": "auto (detect)"}),
                "custom_bg_hex": ("STRING", {"default": "#00FF00"}),
                "key_strength": (list(_KEY_STRENGTH.keys()), {"default": "Normal"}),
                "sharpen_grid": ("BOOLEAN", {"default": True,
                                 "tooltip": "Recover the TRUE pixel grid H3 rendered. Recommended on."}),
                "motion_fix": (list(_MOTION.keys()), {"default": "Extra strong"}),
                "loop_mode": (list(_LOOPS.keys()), {"default": "Auto seamless"}),
                "remove_duplicate_frames": ("BOOLEAN", {"default": True}),
                "anchor": (_ANCHORS, {"default": "bottom_center"}),
                "canvas": (_CANVAS, {"default": "Tight (crop to sprite)"}),
                "canvas_size": ("INT", {"default": 200, "min": 16, "max": 2048, "step": 8}),
                "canvas_width": ("INT", {"default": 200, "min": 8, "max": 2048, "step": 8}),
                "canvas_height": ("INT", {"default": 200, "min": 8, "max": 2048, "step": 8}),
                "placement": (_PLACEMENTS, {"default": "center"}),
                "offset_x": ("INT", {"default": 0, "min": -1024, "max": 1024}),
                "offset_y": ("INT", {"default": 0, "min": -1024, "max": 1024}),
                "preview_max_frames": ("INT", {"default": 64, "min": 4, "max": 512, "step": 4,
                                       "tooltip": "Cap on frames shipped to the in-node preview per stage (even stride). Output frames are never dropped."}),
                # ============ GENERATION TARGETING ============
                "target_layer": (["new layer", "current layer"], {"default": "new layer",
                                   "tooltip": "Where generated frames go: 'new layer' creates a fresh layer, 'current layer' fills the active layer."}),
                "layer_name": ("STRING", {"default": "",
                               "tooltip": "Name for the new layer. Blank = auto-named 'Generated N'."}),
                "placement_x": ("INT", {"default": 0, "min": -2048, "max": 2048,
                                "tooltip": "X offset for placement dot (pixels from center). 0 = centered."}),
                "placement_y": ("INT", {"default": 0, "min": -2048, "max": 2048,
                                "tooltip": "Y offset for placement dot (pixels from center). 0 = centered."}),
                "selection_w": ("INT", {"default": 0, "min": 0, "max": 2048,
                                "tooltip": "Marquee selection width. 0 = no selection constraint."}),
                "selection_h": ("INT", {"default": 0, "min": 0, "max": 2048,
                                "tooltip": "Marquee selection height. 0 = no selection constraint."}),
                "selection_x": ("INT", {"default": 0, "min": -2048, "max": 2048,
                                "tooltip": "Marquee selection X origin."}),
                "selection_y": ("INT", {"default": 0, "min": -2048, "max": 2048,
                                "tooltip": "Marquee selection Y origin."}),
                # ============ ADVANCED: keyer (adv_key_*) ============
                "adv_key_method": (["preset", "flood", "key"], {"default": "preset"}),
                "adv_key_tolerance": ("FLOAT", {"default": -1.0, "min": -1.0, "max": 1.0, "step": 0.01,
                                      "tooltip": "-1 = use key_strength preset."}),
                "adv_key_shadow": ("FLOAT", {"default": -1.0, "min": -1.0, "max": 3.0, "step": 0.1,
                                   "tooltip": "Shadow tolerance. -1 = preset."}),
                "adv_key_softness": ("FLOAT", {"default": -1.0, "min": -1.0, "max": 0.5, "step": 0.01,
                                     "tooltip": "Edge feather. -1 = hard 1-bit alpha (pixel-art correct)."}),
                "adv_key_erode": ("INT", {"default": -1, "min": -1, "max": 8,
                                  "tooltip": "Matte erode px (strips halo ring). -1 = preset (1)."}),
                "adv_key_despill": (_TRI, {"default": "preset"}),
                "adv_key_interior": (_TRI, {"default": "preset",
                                    "tooltip": "Key enclosed gaps inside the silhouette."}),
                "adv_key_interior_tol": ("FLOAT", {"default": -1.0, "min": -1.0, "max": 1.0, "step": 0.05}),
                "adv_key_interior_max_area": ("FLOAT", {"default": -1.0, "min": -1.0, "max": 25.0, "step": 0.1}),
                "adv_key_rescue": (_TRI, {"default": "preset"}),
                "adv_key_temporal_alpha": (_TRI, {"default": "preset",
                                           "tooltip": "Median-of-3 matte vote; pins the silhouette edge."}),
                "adv_key_drop_detached": ("FLOAT", {"default": -1.0, "min": -1.0, "max": 100.0, "step": 0.5,
                                          "tooltip": "Drop detached specks (% of main subject). -1 = preset (5)."}),
                # ============ ADVANCED: grid recover ============
                "adv_grid_mode": (["auto", "manual"], {"default": "auto"}),
                "adv_grid_block": ("INT", {"default": 4, "min": 1, "max": 32}),
                "adv_grid_max_block": ("INT", {"default": 12, "min": 2, "max": 32}),
                "adv_grid_reduce": (["median", "majority", "nearest"], {"default": "median"}),
                # ============ ADVANCED: quantize look ============
                "adv_q_method": (["preset", "kmeans", "median_cut"], {"default": "preset"}),
                "adv_q_mapping": (["preset", "lab", "rgb"], {"default": "preset"}),
                "adv_q_saturation": ("FLOAT", {"default": -1.0, "min": -1.0, "max": 3.0, "step": 0.05}),
                "adv_q_contrast": ("FLOAT", {"default": -1.0, "min": -1.0, "max": 3.0, "step": 0.05}),
                "adv_q_sharpen": ("FLOAT", {"default": -1.0, "min": -1.0, "max": 2.0, "step": 0.1}),
                "adv_q_flatten": ("INT", {"default": -1, "min": -1, "max": 7, "step": 2,
                                  "tooltip": "Source-res median prefilter. -1 = preset (0 in-suite: grid reduce already kills grain)."}),
                "adv_q_temporal_lock": ("FLOAT", {"default": -1.0, "min": -1.0, "max": 0.9, "step": 0.05}),
                # ============ ADVANCED: hi-bit truepixel ============
                "adv_tp_bands": ("INT", {"default": -1, "min": -1, "max": 4}),
                "adv_tp_hue_shift": ("FLOAT", {"default": -1.0, "min": -1.0, "max": 1.0, "step": 0.05}),
                "adv_tp_vibrancy": ("FLOAT", {"default": -1.0, "min": -1.0, "max": 2.5, "step": 0.05}),
                "adv_tp_cel_contrast": ("FLOAT", {"default": -1.0, "min": -1.0, "max": 2.5, "step": 0.05}),
                "adv_tp_outline": (_TRI, {"default": "preset"}),
                "adv_tp_ambient": ("FLOAT", {"default": -1.0, "min": -1.0, "max": 0.9, "step": 0.05}),
                "adv_tp_shadow_thr": ("FLOAT", {"default": -1.0, "min": -1.0, "max": 0.95, "step": 0.05}),
                "adv_tp_highlight_thr": ("FLOAT", {"default": -1.0, "min": -1.0, "max": 1.5, "step": 0.05}),
                "adv_tp_flatten": ("FLOAT", {"default": -1.0, "min": -1.0, "max": 10.0, "step": 0.5}),
                "adv_tp_saturation": ("FLOAT", {"default": -1.0, "min": -1.0, "max": 3.0, "step": 0.05}),
                "adv_tp_contrast": ("FLOAT", {"default": -1.0, "min": -1.0, "max": 3.0, "step": 0.05}),
                "adv_tp_sharpen": ("FLOAT", {"default": -1.0, "min": -1.0, "max": 2.0, "step": 0.1}),
                "adv_tp_share": ("FLOAT", {"default": -1.0, "min": -1.0, "max": 1.0, "step": 0.05,
                                 "tooltip": "Subject palette share. -1 = preset (1.0 — wired alpha means the invisible backdrop gets no budget; standalone TruePixel default stays 0.75)."}),
                # ============ ADVANCED: motion fix ============
                "adv_motion_mode": (["preset", "despike", "despike_matte", "movelock",
                                     "minrun", "median3_inner", "lockdown",
                                     "hysteresis", "median3", "off"], {"default": "preset"}),
                "adv_motion_threshold": ("FLOAT", {"default": -1.0, "min": -1.0, "max": 128.0, "step": 1.0}),
                "adv_motion_commit": ("INT", {"default": -1, "min": -1, "max": 5}),
                "adv_motion_hold": ("INT", {"default": -1, "min": -1, "max": 8}),
                # ============ ADVANCED: crop / loop / dedup ============
                "adv_crop_padding": ("INT", {"default": -1, "min": -1, "max": 256,
                                     "tooltip": "Margin around the sprite on the Tight canvas. -1 = auto (~10% of the sprite — large but never frame-filling)."}),
                "adv_crop_snap": ("INT", {"default": -1, "min": -1, "max": 128,
                                  "tooltip": "Size multiple snap. -1 = preset (8)."}),
                "adv_loop_max_error": ("FLOAT", {"default": -1.0, "min": -1.0, "max": 1.0, "step": 0.01}),
                "adv_loop_tail": ("FLOAT", {"default": -1.0, "min": -1.0, "max": 0.9, "step": 0.05}),
                "adv_dedup_threshold": ("FLOAT", {"default": -1.0, "min": -1.0, "max": 1.0, "step": 0.005}),
            },
            "optional": {
                "alpha": ("MASK",),
                "custom_palette_image": ("IMAGE",),
            },
        }

    # ------------------------------------------------------------------ run
    def run(self, images, size_preset, custom_width, custom_height, look, palette,
            colors, dither, cleanup, background, custom_bg_hex, key_strength,
            sharpen_grid, motion_fix, loop_mode, remove_duplicate_frames, anchor,
            canvas, canvas_size, canvas_width, canvas_height, placement,
            offset_x, offset_y, preview_max_frames,
            adv_key_method, adv_key_tolerance, adv_key_shadow, adv_key_softness,
            adv_key_erode, adv_key_despill, adv_key_interior,
            adv_key_interior_tol, adv_key_interior_max_area, adv_key_rescue,
            adv_key_temporal_alpha, adv_key_drop_detached,
            adv_grid_mode, adv_grid_block, adv_grid_max_block, adv_grid_reduce,
            adv_q_method, adv_q_mapping, adv_q_saturation, adv_q_contrast,
            adv_q_sharpen, adv_q_flatten, adv_q_temporal_lock,
            adv_tp_bands, adv_tp_hue_shift, adv_tp_vibrancy, adv_tp_cel_contrast,
            adv_tp_outline, adv_tp_ambient, adv_tp_shadow_thr,
            adv_tp_highlight_thr, adv_tp_flatten, adv_tp_saturation,
            adv_tp_contrast, adv_tp_sharpen, adv_tp_share,
            adv_motion_mode, adv_motion_threshold, adv_motion_commit,
            adv_motion_hold,
            adv_crop_padding, adv_crop_snap, adv_loop_max_error, adv_loop_tail,
            adv_dedup_threshold,
            alpha=None, custom_palette_image=None,
            target_layer="new layer", layer_name="",
            placement_x=0, placement_y=0,
            selection_w=0, selection_h=0, selection_x=0, selection_y=0):

        report = []
        uid = uuid.uuid4().hex[:10]
        stages, meta = {}, {}

        def capture(tag, imgs, a, pixel_exact):
            refs, m = _save_stage(tag, uid, imgs, a, preview_max_frames,
                                  pixel_exact=pixel_exact)
            stages[tag] = refs
            meta[tag] = m

        # ---------------- stage: source ----------------
        capture("source", images, alpha, pixel_exact=False)
        try:
            _f0 = (images[0].clamp(0, 1) * 255).round().to(
                torch.uint8).cpu().numpy()
            if alpha is not None:
                _a0 = (alpha[0].clamp(0, 1).cpu().numpy() * 255).round(
                    ).astype(np.uint8)
                _f0 = np.dstack([_f0, _a0])
            Image.fromarray(_f0).save(os.path.join(
                folder_paths.get_temp_directory(),
                f"pfs_{uid}_srcfull_000.png"))
        except Exception:
            pass
        report.append(f"source: {images.shape[0]}f {images.shape[2]}x{images.shape[1]}")

        # ---------------- stage: keyed (full video res) ----------------
        if alpha is None:
            key_color = custom_bg_hex if background == "custom hex" else _BACKGROUNDS[background]
            tol_p, shadow_p = _KEY_STRENGTH[key_strength]
            images, alpha = PixelForgeChromaKey().run(
                images, key_color,
                _pick(adv_key_tolerance, tol_p),
                _pick(adv_key_softness, 0.0),
                _tri(adv_key_despill, True),
                "flood" if adv_key_method == "preset" else adv_key_method,
                _pick(adv_key_shadow, shadow_p),
                _tri(adv_key_interior, True),
                _pick(adv_key_interior_tol, 0.5),
                _pick(adv_key_erode, 1),
                _tri(adv_key_rescue, True),
                _pick(adv_key_interior_max_area, 2.0),
                _tri(adv_key_temporal_alpha, True),
                _pick(adv_key_drop_detached, 5.0))
            report.append(f"key: {key_color} ({key_strength.lower()})")
            _keyed_here = True
            # v3.7.2-sandblast: letterbox / backdrop-variant rescue. H3
            # sometimes delivers a NON-uniform backdrop (measured on run
            # ea62126afc: green bars + white band; single-color key left the
            # band opaque — early frames 86.8% opaque vs ~16% median). Frames
            # whose opaque fraction dwarfs the batch median get a second
            # flood-key pass targeting the SURVIVING border color (the band).
            # Prototype on the real frame: 87.0% -> 12.2% opaque, enclosed
            # white shirt untouched (flood only takes border-connected px).
            _op = (alpha > 0.5).float().mean(dim=(1, 2)).cpu().numpy()
            _med = float(np.median(_op))
            if _med < 0.45:
                _bad = [i for i in range(len(_op))
                        if _op[i] > 0.45
                        and _op[i] > max(2.0 * _med, _med + 0.30)]
                _rescued = 0
                for i in _bad:
                    _a = alpha[i].cpu().numpy()
                    _rgb = images[i].cpu().numpy()
                    _sa = np.concatenate([_a[:, :4].ravel(),
                                          _a[:, -4:].ravel()])
                    _sr = np.concatenate([_rgb[:, :4, :].reshape(-1, 3),
                                          _rgb[:, -4:, :].reshape(-1, 3)])
                    _eop = _sa > 0.5  # 4px strips: the keyer's matte erode
                    if _eop.sum() < 8:  # leaves the exact border col empty
                        continue
                    _band = np.median(_sr[_eop], axis=0)
                    _hex = "#%02X%02X%02X" % tuple(
                        int(round(v * 255)) for v in np.clip(_band, 0, 1))
                    # v3.7.3-tightband: the v3.7.2 re-key ran at FULL key
                    # tolerance with interior gaps ON. On a near-gray band
                    # (white scene) the Lab candidacy window admits every
                    # mid-gray, so the flood breaches the outline through
                    # the anti-aliased edge and eats white/skin costume
                    # pieces (measured on run aded984c73 f0-5: bright
                    # subject px 2.5-6.3k eaten vs 9.3-15.4k kept at tight
                    # tol; opaque-vs-tol plateaus up to ~0.16 then falls
                    # off a cliff at 0.25). The band itself is FLAT — it
                    # keys at a much tighter tolerance. Interior gaps are
                    # OFF here: the rescue's job is the border-connected
                    # band only (an enclosed white shirt tightly matches a
                    # white band; the interior pass can't tell them apart).
                    # Try tight first, loosen only if the band survives.
                    _a2 = None
                    for _ts in (0.4, 0.7, 1.0):
                        _, _try_a = PixelForgeChromaKey().run(
                            images[i:i + 1], _hex,
                            _pick(adv_key_tolerance, tol_p) * _ts,
                            _pick(adv_key_softness, 0.0),
                            _tri(adv_key_despill, True),
                            "flood",
                            _pick(adv_key_shadow, shadow_p),
                            False,
                            _pick(adv_key_interior_tol, 0.5),
                            _pick(adv_key_erode, 1),
                            _tri(adv_key_rescue, True),
                            _pick(adv_key_interior_max_area, 2.0),
                            _tri(adv_key_temporal_alpha, True),
                            _pick(adv_key_drop_detached, 5.0))
                        _a2 = torch.minimum(alpha[i],
                                            _try_a[0].to(alpha.device))
                        if float((_a2 > 0.5).float().mean()) <= \
                                max(1.6 * _med, _med + 0.20):
                            break
                    alpha[i] = _a2
                    _rescued += 1
                if _rescued:
                    report.append(
                        f"key rescue: re-keyed {_rescued} frame(s) onto a "
                        "surviving border backdrop variant")
        else:
            report.append("key: skipped (alpha wired in)")
            _keyed_here = False
        capture("keyed", images, alpha, pixel_exact=False)

        # ---------------- stage: grid recover ----------------
        src_grid = None
        grid_frames = images
        if sharpen_grid:
            images, alpha, gw, gh, ginfo = PixelForgeGridRecover().run(
                images, adv_grid_mode, adv_grid_block, adv_grid_max_block,
                adv_grid_reduce, False, alpha=alpha)
            src_grid = (gw, gh)
            try:
                _gi = json.loads(ginfo)
                report.append(
                    f"grid: {gw}x{gh} (block {_gi.get('block')} @ "
                    f"{tuple(_gi.get('offset', [0, 0]))}"
                    f"{'' if _gi.get('auto_detected') else ', manual'})")
            except Exception:
                report.append(f"grid: {gw}x{gh}")
        else:
            report.append("grid: off")
        grid_frames = images
        if sharpen_grid:
            capture("grid", images, alpha, pixel_exact=True)
        else:
            meta["grid"] = {"skipped": True, "frames": 0, "shown": 0, "w": 0, "h": 0}

        # ---------------- resolve target size ----------------
        _guard_kept = False
        if size_preset == "Custom size":
            tw, th = custom_width, custom_height
        elif size_preset == "Source / 2 (balanced)":
            if src_grid is not None:
                # v3.7.1-blockguard: halve ONLY H3's incidental VAE pseudo-
                # grid (~4px blocks). When the gen carries INTENTIONAL pixel
                # structure (>=6px blocks — e.g. imitating a hi-bit ref), the
                # detected grid IS the art grid; halving halves the artwork.
                # Measured on the Sasuke run (uid b7c4b8b23b): 78x77 grid from
                # ~9px blocks, within-2x2 MAD 25.9/255 -> Source/2 = 39x38
                # destroyed the hi-bit detail.
                try:
                    _blk = int(json.loads(ginfo).get("block", 0))
                except Exception:
                    _blk = 0
                # v3.7.2-sandblast: keep Source iff block >= 8 (deliberate
                # pixel art — the VAE pseudo-grid never exceeds ~7) OR the
                # within-2x2 MAD of grid-res opaque px > 11 (real pixel
                # structure 14.6-25.9 vs smooth texture 2.5-6.0, measured).
                # Block 6-7 alone is NOT proof: spurious detections happen on
                # perfectly smooth content (verify smooth control: block 7,
                # MAD 2.5).
                _mad = 0.0
                try:
                    _mads = []
                    for _i in _thin_indices(images.shape[0], 8):
                        _f = (images[_i].clamp(0, 1) * 255).cpu().numpy()
                        _h2, _w2 = (_f.shape[0] // 2 * 2,
                                    _f.shape[1] // 2 * 2)
                        _g = _f[:_h2, :_w2].reshape(
                            _h2 // 2, 2, _w2 // 2, 2, 3)
                        _m = np.abs(_g - _g.mean(axis=(1, 3),
                                    keepdims=True)).mean(axis=(1, 3, 4))
                        if alpha is not None:
                            _am = (alpha[_i].cpu().numpy()[:_h2, :_w2]
                                   .reshape(_h2 // 2, 2, _w2 // 2, 2)
                                   .all(axis=(1, 3)))
                            _mads.append(float(_m[_am].mean())
                                         if _am.any() else 0.0)
                        else:
                            _mads.append(float(_m.mean()))
                    _mad = float(np.median(_mads)) if _mads else 0.0
                except Exception:
                    _mad = 0.0
                if _blk >= 8 or _mad > 11.0:
                    _guard_kept = True
                    tw, th = src_grid
                    report.append(
                        f"size guard: gen carries real pixel structure "
                        f"(block {_blk}px, detail {_mad:.1f}) — keeping the "
                        "Source grid (halving would erase detail)")
                else:
                    tw, th = max(8, src_grid[0] // 2), max(8, src_grid[1] // 2)
            else:
                tw, th = max(8, images.shape[2] // 2), max(8, images.shape[1] // 2)
        elif _SIZE_PRESETS[size_preset] < 0:
            if src_grid is not None:
                tw, th = src_grid
            else:
                tw, th = images.shape[2], images.shape[1]
        else:
            tw, th = _SIZE_PRESETS[size_preset], _SIZE_PRESETS[size_preset]
        report.append(f"size: {tw}x{th if th else 'auto'}")
        # Art-grid sanity guardrail (v3.7.0): past ~128px on the long side the
        # pixel structure is invisible and the output reads as a downscaled
        # image, not pixel art — the owner's "blown-up 200x200" failure mode.
        _long_side = max(tw, th if th else tw)
        if _long_side > 128 and not _guard_kept:
            report.append(
                f"WARN size: {tw}x{th if th else 'auto'} art grid is very fine — "
                "pixel structure won't read (blown-up-image look). "
                "<=128 recommended; 'Source / 2' or Medium 64 for real pixels")
        elif _long_side < 16:
            report.append(
                f"WARN size: {tw}x{th if th else 'auto'} art grid is extremely "
                "coarse — sprite may be unreadable")

        # v3.7.6-fringesnap: despill residue at the silhouette survives
        # keying + the grid reduce as DARK OLIVE px (measured on run
        # 711da45a5a: [0,16,0]-[0,29,4], 0.3-0.8% of opaque). A majority
        # block-reduce lets them WIN edge blocks and kmeans then grows a
        # green base -> dark-GREEN edges (2030 green-dominant px measured
        # vs 0 with neutralization). Snap dark green-dominant opaque px to
        # a neutral dark; safe on green-screen keyed runs (a genuinely
        # dark-green subject would key out with the backdrop).
        if _keyed_here and alpha is not None:
            _fs = (images.clamp(0, 1) * 255).round().to(
                torch.uint8).cpu().numpy().astype(np.int16)
            _fm = (alpha.cpu().numpy() > 0.5)
            _fr, _fg, _fb = _fs[..., 0], _fs[..., 1], _fs[..., 2]
            _fm = _fm & (_fs.max(-1) < 90) & (_fg > _fr + 12) & (_fg > _fb + 12)
            if _fm.any():
                _fs[..., 1] = np.minimum(_fg, (_fr + _fb) // 2 + 6)
                images = torch.from_numpy(
                    _fs.clip(0, 255).astype(np.uint8).astype(np.float32)
                    / 255.0)
                grid_frames = images
                report.append(
                    f"fringe snap: neutralized {int(_fm.sum())} dark green "
                    "edge px")

        # v3.7.6-cleanhalf: "Source / 2 (balanced)" promises an exact 2x
        # block-reduce (size_preset tooltip) but actually let the look
        # stage PIL-area-average the grid 2:1 — on a noisy fine grid that
        # invents intermediate colors in EVERY mixed block (measured: 0.0%
        # of look px equal any of their 2x2 block members; mean block span
        # ~70/255) = the mixel/mush, and it smears the 1px black outline.
        # Do the halve with the GridRecover engine's masked majority
        # reduce; the look stage then runs 1:1 (no resample at all).
        if (size_preset == "Source / 2 (balanced)" and not _guard_kept
                and abs(images.shape[2] - tw * 2) <= 1
                and abs(images.shape[1] - th * 2) <= 1):
            _ha = (images.clamp(0, 1) * 255).round().to(
                torch.uint8).cpu().numpy()
            _hm = alpha.cpu().numpy() if alpha is not None else None
            _hn, _hh, _hw = _ha.shape[:3]
            _he, _hw2 = _hh // 2 * 2, _hw // 2 * 2
            _so = np.empty((_hn, _he // 2, _hw2 // 2, 3), dtype=np.uint8)
            _sm_a = np.empty((_hn, _he // 2, _hw2 // 2), dtype=np.float32)
            for _i in range(_hn):
                if _hm is not None:
                    _so[_i] = _reduce_blocks_masked(
                        _ha[_i, :_he, :_hw2], _hm[_i, :_he, :_hw2],
                        2, "majority")
                    _sm_a[_i] = (_hm[_i, :_he, :_hw2].reshape(
                        _he // 2, 2, _hw2 // 2, 2).mean((1, 3)) > 0.5)
                else:
                    _so[_i] = _reduce_blocks(_ha[_i, :_he, :_hw2],
                                             2, "majority")
                    _sm_a[_i] = 1.0
            images = torch.from_numpy(_so.astype(np.float32) / 255.0)
            alpha = torch.from_numpy(_sm_a.astype(np.float32))
            grid_frames = images
            tw, th = _hw2 // 2, _he // 2
            report.append(
                "halve: exact 2x2 majority block-reduce (no resample mush)")

        # ---------------- stage: look (quantize / truepixel) ----------------
        dmode, dstrength = _DITHER[dither]
        palette_json = "{}"
        if look.startswith("Hi-bit"):
            cel = look == "Hi-bit cel shading"
            # v3.7.4-looktune: retuned on the REAL 56-frame Sasuke run (uid
            # f208a47162 grid temps, measured not guessed). Old chain — sat
            # 1.25 x contrast 1.10 x vibrancy 1.15 x hue 0.30, plus sharpen
            # 0.6 as a 1px unsharp at ART res (params were designed for
            # video-res input) — posterized to neon and sprayed band-edge
            # speckle (2.40%). New: keep the sprite's own colors, no art-res
            # sharpen halos, cel_contrast 1.0 so borderline px stop flipping
            # bands per pixel. Measured: speckle 1.41%, ~29 ramp colors,
            # gradient retention 0.82, coherent shade shapes on all frames.
            tp_sat = _pick(adv_tp_saturation, 1.05)
            tp_con = _pick(adv_tp_contrast, 1.0)
            tp_shp = _pick(adv_tp_sharpen, 0.0)
            tp_vib = _pick(adv_tp_vibrancy, 1.0)
            tp_hue = _pick(adv_tp_hue_shift, 0.0)
            tp_cel = _pick(adv_tp_cel_contrast, 1.0)
            tp_bands = _pick(adv_tp_bands, 3 if cel else 1)
            images, alpha, _smask, palette_json = PixelForgeTruePixel().run(
                images, tw, th, "area", colors,
                _pick(adv_tp_share, 1.0),
                _pick(adv_tp_flatten, 0.0), 2,
                tp_bands,
                _pick(adv_tp_ambient, 0.35),
                _pick(adv_tp_shadow_thr, 0.55),
                _pick(adv_tp_highlight_thr, 0.85),
                tp_cel,
                tp_hue,
                tp_vib,
                # v3.7.6: TruePixel outline is a STRING combo
                # (off/outer/inner/both) — a bool activated NEITHER ring
                # (the cel preset outline never ran).
                # v3.7.9-truecolors: default OFF. "inner" repaints the whole
                # silhouette inner ring near-black — on a small art grid that
                # ring is ~9% of the sprite (thin limbs become mostly black,
                # reads as eaten outline + holes; measured on the real v9
                # run: 700 near-black px vs 200 with it off, mean|d| vs grid
                # 58 -> 25.8). H3 already draws its own outline at gen time;
                # adv_tp_outline = "on" forces the ring back if wanted.
                "inner" if _tri(adv_tp_outline, False) else "off",
                dmode, dstrength, cleanup,
                tp_sat,
                tp_con,
                tp_shp,
                True, 28.0, 1, "manual", 10, 0.06, True, alpha=alpha)
            # effective-config line (v3.7.4): what ACTUALLY ran is visible in
            # the report — stale saved widget values can't hide behind the
            # word "preset" (his saved v6 node ran Modern @ 8 colors while he
            # thought he was testing Hi-bit cel @ 16).
            report.append(
                f"look: {look.lower()} @ {colors} colors "
                f"(bands {tp_bands}, sat {tp_sat}, con {tp_con}, "
                f"sharpen {tp_shp}, vib {tp_vib}, hue {tp_hue}, "
                f"cel {tp_cel}, outline {"inner" if _tri(adv_tp_outline, False) else "off"}, regionvote)")
        else:
            preset_name = {"Modern (smooth color)": "modern_hibit",
                           "Retro 16-bit": "retro_16bit",
                           "Hardcore 8-bit": "hardcore_8bit"}[look]
            p = dict(_STYLE_PRESETS[preset_name])
            # suite quantizes at the recovered art grid: flatten at art-res
            # eats outlines and bleeds backdrop across the matte (see pf_easy)
            p.update(flatten=0)
            if look == "Modern (smooth color)":
                p.update(saturation=1.0, contrast=1.0, sharpen=0.0)
            if palette == "auto (from sprite)":
                palette_mode, fixed_palette = "adaptive", PALETTE_NAMES[0]
            elif palette == "use custom image":
                palette_mode, fixed_palette = "custom_image", PALETTE_NAMES[0]
            else:
                palette_mode, fixed_palette = "fixed", palette
            use_colors = colors if palette_mode != "fixed" else p["colors"]
            images, palette_json, alpha = PixelForgeQuantize().run(
                images, tw, th, "nearest", "custom", palette_mode,
                "kmeans" if adv_q_method == "preset" else adv_q_method,
                fixed_palette, use_colors,
                "lab" if adv_q_mapping == "preset" else adv_q_mapping,
                dmode, dstrength, True, cleanup,
                _pick(adv_q_saturation, p["saturation"]),
                _pick(adv_q_contrast, p["contrast"]),
                _pick(adv_q_sharpen, p["sharpen"]),
                1,
                _pick(adv_q_flatten, p["flatten"]),
                temporal_lock=_pick(adv_q_temporal_lock, 0.0),
                custom_palette_image=custom_palette_image,
                alpha=alpha)
            report.append(f"look: {look.lower()} @ {use_colors} colors, palette: {palette}")
        capture("look", images, alpha, pixel_exact=True)

        # ---------------- stage: motion fix ----------------
        m_mode, m_thr, m_commit, m_hold = None, None, None, None
        if _MOTION[motion_fix] is not None:
            m_mode, m_thr, m_commit, m_hold = _MOTION[motion_fix]
        if adv_motion_mode != "preset":
            m_mode = None if adv_motion_mode == "off" else adv_motion_mode
        if m_mode is not None:
            m_thr = _pick(adv_motion_threshold, m_thr if m_thr is not None else 10.0)
            m_commit = _pick(adv_motion_commit, m_commit if m_commit is not None else 2)
            m_hold = _pick(adv_motion_hold, m_hold if m_hold is not None else 3)
            images, alpha = PixelForgeTemporalStabilize().run(
                images, m_mode, m_thr, m_commit, m_hold, alpha=alpha,
                motion_ref=grid_frames if m_mode == "movelock" else None)
            report.append(f"motion: {m_mode}")
            capture("motion", images, alpha, pixel_exact=True)
        else:
            report.append("motion: off")
            meta["motion"] = {"skipped": True, "frames": 0, "shown": 0, "w": 0, "h": 0}

        # ---------------- crop & anchor ----------------
        # Suite placement dot: nudges the sprite inside a fixed canvas
        # (frontend writes placement_x/y from the dot, center-relative).
        snap = _pick(adv_crop_snap, 8)
        if adv_crop_padding == -1:
            # Proportional margin (v3.7.0): flat pad 2 made the Tight canvas
            # frame-filling BY CONSTRUCTION — 2px of margin on any sprite =
            # the character touches the frame = "blown-up image, not pixel
            # art". ~10% of the sprite's long side keeps the character large
            # but never frame-filling (pixels stay visible around it).
            pad = 2
            try:
                if alpha is not None:
                    _u = (alpha.cpu().numpy().max(axis=0) > 0.5)
                    if _u.any():
                        _ys, _xs = np.where(_u)
                        pad = int(min(32, max(3, round(
                            max(int(_xs.max()) - int(_xs.min()) + 1,
                                int(_ys.max()) - int(_ys.min()) + 1) * 0.10))))
            except Exception:
                pad = 2
        else:
            pad = adv_crop_padding
        if canvas == "Tight (crop to sprite)":
            images, alpha, crop_info = PixelForgeAutoCrop().run(
                images, "union", anchor, pad, snap, 0, alpha=alpha)
        else:
            cwid = canvas_size if canvas == "Fixed square" else canvas_width
            chei = canvas_size if canvas == "Fixed square" else canvas_height
            images, alpha, crop_info = PixelForgeAutoCrop().run(
                images, "union", anchor, pad, snap, 0, "fixed", cwid, chei,
                placement, offset_x + placement_x, offset_y + placement_y,
                alpha=alpha)
        report.append(f"crop: {crop_info}")

        # ---------------- loop trim ----------------
        images, alpha, loop_info = PixelForgeLoopTrim().run(
            images, _LOOPS[loop_mode],
            _pick(adv_loop_max_error, 0.06),
            _pick(adv_loop_tail, 0.5), alpha=alpha)
        report.append(f"loop: {loop_info}")

        # ---------------- dedup -> final ----------------
        durations_json = ""
        durations_frames = None
        if remove_duplicate_frames:
            images, alpha, durations_json = PixelForgeFrameDedup().run(
                images, _pick(adv_dedup_threshold, 0.01), alpha=alpha)
            try:
                durations_frames = json.loads(durations_json).get("durations_frames")
            except Exception:
                durations_frames = None
        # ---------------- suite marquee selection ----------------
        # The in-node workspace writes selection_x/y/w/h from the marquee
        # tool: crop the forged frames to the selected rect (sprite pixels).
        if selection_w > 0 and selection_h > 0:
            h0, w0 = images.shape[1], images.shape[2]
            sx0 = min(max(0, selection_x), max(0, w0 - 1))
            sy0 = min(max(0, selection_y), max(0, h0 - 1))
            sx1 = min(w0, sx0 + selection_w)
            sy1 = min(h0, sy0 + selection_h)
            if sx1 > sx0 and sy1 > sy0 and (sx0 or sy0 or sx1 < w0 or sy1 < h0):
                images = images[:, sy0:sy1, sx0:sx1, :]
                if alpha is not None:
                    alpha = alpha[:, sy0:sy1, sx0:sx1]
                report.append(f"selection: {sx1 - sx0}x{sy1 - sy0} @ {sx0},{sy0}")

        # Framing audit (v3.7.0): measure FINAL sprite occupancy of the
        # canvas. The two reads that kill pixel art: frame-filling (>92% =
        # blown-up image) and postage-stamp (<40% = sprite drowned in canvas,
        # e.g. a fixed 200x100 canvas around a 13px character).
        try:
            if alpha is not None:
                _fa = alpha.cpu().numpy()
                _u = (_fa.max(axis=0) > 0.5)
                if _u.any():
                    _ys, _xs = np.where(_u)
                    _bw = (int(_xs.max()) - int(_xs.min()) + 1) / _fa.shape[2]
                    _bh = (int(_ys.max()) - int(_ys.min()) + 1) / _fa.shape[1]
                    report.append(
                        f"framing: sprite {_bw * 100:.0f}%x{_bh * 100:.0f}% of canvas")
                    if _bw > 0.92 or _bh > 0.92:
                        report.append(
                            "WARN framing: sprite fills the frame — reads as a "
                            "blown-up image, not pixel art. Raise the margin "
                            "(adv_crop_padding) or use a smaller canvas")
                    elif _bw < 0.40 and _bh < 0.40:
                        report.append(
                            "WARN framing: sprite is tiny inside its canvas — "
                            "shrink the canvas or raise the art size")
        except Exception:
            pass

        capture("final", images, alpha, pixel_exact=True)

        n = images.shape[0]
        h, w = images.shape[1], images.shape[2]
        report.insert(0, f"OK: {n} frames @ {w}x{h}")
        report_str = " | ".join(report)

        # ---- Build layer-aware payload ----
        # The "final" stage becomes the default generated layer.
        # Pipeline debug stages (source/keyed/grid/look/motion) go into
        # pf_debug_stages for the optional debug view.
        final_refs = stages.get("final", [])
        layer_frames = [{"filename": r["filename"], "subfolder": r.get("subfolder", ""),
                         "type": r.get("type", "temp")} for r in final_refs]

        # Debug stages: flat list of {stage, frames} for the debug toggle
        debug_stages = []
        for tag in ["source", "keyed", "grid", "look", "motion"]:
            tag_refs = stages.get(tag, [])
            if tag_refs:
                debug_stages.append({
                    "stage": tag,
                    "frames": [{"filename": r["filename"], "subfolder": r.get("subfolder", ""),
                                "type": r.get("type", "temp")} for r in tag_refs],
                })

        # SERVER FLATTEN: pf_layers is a flat list of layer-dicts. Each
        # layer's "frames" is itself a flat list of file refs. The frontend
        # regroups them. pf_debug_stages follows the same flat pattern.
        layer_payload = [{
            "id": "gen_default",
            "name": "Generated",
            "frames": layer_frames,
            "source": "forge",
            "meta": {"w": w, "h": h, "frameCount": n},
        }]

        return {
            "ui": {
                "pf_layers": layer_payload,
                "pf_frame_count": [n],
                "pf_debug_stages": debug_stages,
                "pf_report": [report_str],
                "pf_durations_frames": [durations_frames] if durations_frames else [],
                # Legacy fallback (frontend uses pf_layers when present)
                "pf_frames": [{"stage": "final", **r} for r in final_refs],
            },
            "result": (images, alpha, durations_json, palette_json, report_str),
        }


NODE_CLASS_MAPPINGS = {"PixelForgeSuperForge": PixelForgeSuperForge}
NODE_DISPLAY_NAME_MAPPINGS = {"PixelForgeSuperForge": "ᛒᛚᚢᛒ Super Pixel Forge"}
