# VERSION: v3.0.0-layers (2026-08-15) — force cache bust
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
from .pf_grid import PixelForgeGridRecover
from .pf_temporal import PixelForgeTemporalStabilize
from .pf_finalize import PixelForgeTruePixel

# --- shared vocabularies (kept identical to pf_easy so muscle memory transfers)
from .pf_easy import (_ANCHORS, _BACKGROUNDS, _CANVAS, _DITHER, _KEY_STRENGTH,
                      _LOOPS, _LOOKS, _MOTION, _PLACEMENTS, _SIZE_PRESETS)

_TRI = ["preset", "on", "off"]          # 3-state override for engine booleans
_STAGE_ORDER = ["source", "keyed", "grid", "look", "motion", "final"]


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
                "size_preset": (list(_SIZE_PRESETS.keys()), {"default": "Source (H3's own grid)",
                                "tooltip": "Final sprite resolution in art pixels. Source = keep the exact grid H3 rendered (crispest, 1:1, recommended)."}),
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
                                 "tooltip": "Subject palette share. -1 = preset (0.75)."}),
                # ============ ADVANCED: motion fix ============
                "adv_motion_mode": (["preset", "despike", "despike_matte", "movelock",
                                     "minrun", "median3_inner", "lockdown",
                                     "hysteresis", "median3", "off"], {"default": "preset"}),
                "adv_motion_threshold": ("FLOAT", {"default": -1.0, "min": -1.0, "max": 128.0, "step": 1.0}),
                "adv_motion_commit": ("INT", {"default": -1, "min": -1, "max": 5}),
                "adv_motion_hold": ("INT", {"default": -1, "min": -1, "max": 8}),
                # ============ ADVANCED: crop / loop / dedup ============
                "adv_crop_padding": ("INT", {"default": -1, "min": -1, "max": 256}),
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
        else:
            report.append("key: skipped (alpha wired in)")
        capture("keyed", images, alpha, pixel_exact=False)

        # ---------------- stage: grid recover ----------------
        src_grid = None
        grid_frames = images
        if sharpen_grid:
            images, alpha, gw, gh, ginfo = PixelForgeGridRecover().run(
                images, adv_grid_mode, adv_grid_block, adv_grid_max_block,
                adv_grid_reduce, False, alpha=alpha)
            src_grid = (gw, gh)
            report.append(f"grid: {gw}x{gh}")
        else:
            report.append("grid: off")
        grid_frames = images
        if sharpen_grid:
            capture("grid", images, alpha, pixel_exact=True)
        else:
            meta["grid"] = {"skipped": True, "frames": 0, "shown": 0, "w": 0, "h": 0}

        # ---------------- resolve target size ----------------
        if size_preset == "Custom size":
            tw, th = custom_width, custom_height
        elif _SIZE_PRESETS[size_preset] < 0:
            if src_grid is not None:
                tw, th = src_grid
            else:
                tw, th = images.shape[2], images.shape[1]
        else:
            tw, th = _SIZE_PRESETS[size_preset], _SIZE_PRESETS[size_preset]
        report.append(f"size: {tw}x{th if th else 'auto'}")

        # ---------------- stage: look (quantize / truepixel) ----------------
        dmode, dstrength = _DITHER[dither]
        palette_json = "{}"
        if look.startswith("Hi-bit"):
            cel = look == "Hi-bit cel shading"
            images, alpha, _smask, palette_json = PixelForgeTruePixel().run(
                images, tw, th, "area", colors,
                _pick(adv_tp_share, 0.75),
                _pick(adv_tp_flatten, 5.0), 2,
                _pick(adv_tp_bands, 3 if cel else 1),
                _pick(adv_tp_ambient, 0.35),
                _pick(adv_tp_shadow_thr, 0.55),
                _pick(adv_tp_highlight_thr, 0.85),
                _pick(adv_tp_cel_contrast, 1.25),
                _pick(adv_tp_hue_shift, 0.30 if cel else 0.0),
                _pick(adv_tp_vibrancy, 1.15),
                _tri(adv_tp_outline, cel),
                dmode, dstrength, cleanup,
                _pick(adv_tp_saturation, 1.25),
                _pick(adv_tp_contrast, 1.10),
                _pick(adv_tp_sharpen, 0.6),
                True, 28.0, 1, "manual", 10, 0.06, True, alpha=alpha)
            report.append(f"look: {look.lower()}")
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
            report.append(f"look: {look.lower()}, palette: {palette}")
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
        pad = _pick(adv_crop_padding, 2)
        snap = _pick(adv_crop_snap, 8)
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
