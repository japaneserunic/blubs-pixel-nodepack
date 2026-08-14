"""PixelForge Easy v2 — a condensed 3-node suite for non-technical users.

Wraps the battle-tested engines in pf_pixelize / pf_sprite / pf_temporal /
pf_grid / pf_finalize / pf_aseprite with plain-language presets. Nothing here
duplicates engine code; every knob maps onto the original nodes' parameters.

Nodes (category PixelForge/Easy):
  - Sprite Studio (Easy v2)   : frames -> game-ready sprite run, ONE node
  - Sprite Export (Easy v2)   : GIF + sheet + optional Aseprite in one place
  - H3 Sprite Prompt (Easy v2): minimal prompt builder (subject/action/style/seconds)
"""

import numpy as np
import torch

from .pf_palettes import PALETTE_NAMES
from .pf_pixelize import PixelForgeQuantize, _STYLE_PRESETS
from .pf_sprite import (PixelForgeAutoCrop, PixelForgeChromaKey,
                        PixelForgeFrameDedup, PixelForgeLoopTrim,
                        PixelForgeSheetPack)
from .pf_grid import PixelForgeGridRecover
from .pf_temporal import PixelForgeTemporalStabilize
from .pf_finalize import PixelForgeTruePixel
from .pf_aseprite import PixelForgeAsepriteExport, PixelForgeSaveGIF
from .pf_h3 import PixelForgeH3Prompt

_SIZE_PRESETS = {
    "Source (H3's own grid)": -1,
    "Tiny (16 px)": 16,
    "Small (32 px)": 32,
    "Medium (64 px)": 64,
    "Large (128 px)": 128,
    "Huge (256 px)": 256,
    "Custom size": 0,
}

_LOOKS = [
    "Modern (smooth color)",
    "Retro 16-bit",
    "Hardcore 8-bit",
    "Hi-bit cel shading",
    "Hi-bit clean",
]

_DITHER = {
    "Off": ("none", 0.0),
    "Light": ("bayer2", 0.15),
    "Medium": ("bayer4", 0.30),
    "Strong": ("bayer8", 0.45),
}

_KEY_STRENGTH = {           # (tolerance, shadow_tolerance)
    "Gentle": (0.18, 0.8),
    "Normal": (0.25, 1.2),
    "Aggressive": (0.35, 2.0),
}

_BACKGROUNDS = {
    "auto (detect)": "auto",
    "green screen": "#00FF00",
    "blue screen": "#0000FF",
    "magenta screen": "#FF00FF",
    "black": "#000000",
    "white": "#FFFFFF",
    "custom hex": "custom",
}

_MOTION = {                 # (mode, threshold, commit_frames, max_hold)
    "Off": None,
    "Light": ("despike", 4.0, 1, 1),
    "Strong": ("despike_matte", 4.0, 1, 1),
    "Extra strong": ("movelock", 20.0, 1, 1),
    "Smooth shading": ("median3_inner", 10.0, 2, 3),
}

_PLACEMENTS = ["center", "top_center", "bottom_center",
               "left_center", "right_center",
               "top_left", "top_right", "bottom_left", "bottom_right"]

_CANVAS = ["Tight (crop to sprite)", "Fixed square", "Fixed custom"]

_LOOPS = {
    "Auto seamless": "auto",
    "Ping-pong": "pingpong",
    "Keep all frames": "off",
}

_ANCHORS = ["bottom_center", "center"]


class PixelForgeSpriteStudio:
    """One node, whole pipeline: background removal (at full video res, where
    the keyer can actually see) -> alpha-aware grid recover -> pixel-art look
    -> despike motion fix -> crop/anchor -> loop trim -> dedup."""

    CATEGORY = "PixelForge/Easy"
    FUNCTION = "run"
    RETURN_TYPES = ("IMAGE", "MASK", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("images", "alpha", "durations_json", "palette_json", "studio_report")
    DESCRIPTION = ("All-in-one sprite maker: pick a size, a look, and a "
                   "background color — done. Advanced users can still reach "
                   "every knob via the individual PixelForge nodes.")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                # ---- sprite size ----
                "size_preset": (list(_SIZE_PRESETS.keys()), {"default": "Source (H3's own grid)",
                                "tooltip": "Final sprite resolution in art pixels. Source = keep the exact grid H3 rendered (crispest, 1:1, recommended). Pick a fixed size only for game-ready dimensions."}),
                "custom_width": ("INT", {"default": 64, "min": 8, "max": 2048, "step": 8,
                                 "tooltip": "Only used when size_preset = Custom size."}),
                "custom_height": ("INT", {"default": 0, "min": 0, "max": 2048, "step": 8,
                                  "tooltip": "0 = match the source aspect ratio. Only for Custom size."}),
                # ---- look ----
                "look": (_LOOKS, {"default": "Modern (smooth color)",
                         "tooltip": "The art style engine. Classic pixel looks or hi-bit cel shading."}),
                "palette": (["auto (from sprite)"] + PALETTE_NAMES + ["use custom image"],
                            {"default": "auto (from sprite)",
                             "tooltip": "Fixed retro palette, or let the node pick colors from your sprite."}),
                "colors": ("INT", {"default": 32, "min": 2, "max": 256,
                           "tooltip": "How many colors 'auto' may use. Fewer = more retro."}),
                "dither": (list(_DITHER.keys()), {"default": "Off",
                           "tooltip": "Dithering = fake shading with pixel patterns. Off is cleanest (recommended at Source size)."}),
                "cleanup": ("INT", {"default": 1, "min": 0, "max": 3,
                            "tooltip": "Removes lonely stray pixels. Higher = more aggressive."}),
                # ---- background removal ----
                "background": (list(_BACKGROUNDS.keys()), {"default": "auto (detect)",
                               "tooltip": "The backdrop color to remove. 'auto' reads it from the frame corners."}),
                "custom_bg_hex": ("STRING", {"default": "#00FF00",
                                  "tooltip": "Only used when background = custom hex."}),
                "key_strength": (list(_KEY_STRENGTH.keys()), {"default": "Normal",
                                 "tooltip": "How hard to cut the background. Aggressive eats shadows too — and can bite the sprite."}),
                # ---- motion & grid ----
                "sharpen_grid": ("BOOLEAN", {"default": True,
                                 "tooltip": "Recovers the TRUE pixel grid the model rendered. Recommended on."}),
                "motion_fix": (list(_MOTION.keys()), {"default": "Strong",
                               "tooltip": "Stops pixels crawling/flickering between frames. Strong (recommended): "
                                          "despike + a minimum-hold rule on the silhouette — 1-2 frame edge "
                                          "wobble dies and re-pinned pixels keep their real color (never flash "
                                          "black), with zero lag and no risk to real motion. Extra strong = "
                                          "also locks pixels the source says are static to their dominant "
                                          "color (kills interior shimmer too). Light = only lone 1-frame "
                                          "blips. Smooth shading = temporal median on interior pixels."}),
                # ---- loop & timing ----
                "loop_mode": (list(_LOOPS.keys()), {"default": "Auto seamless",
                              "tooltip": "Auto finds the best loop point; Ping-pong plays forward then backward."}),
                "remove_duplicate_frames": ("BOOLEAN", {"default": True,
                                            "tooltip": "Merges held frames and records real frame durations (game engines love this)."}),
                "anchor": (_ANCHORS, {"default": "bottom_center",
                           "tooltip": "Tight canvas only: where the sprite stands in its frame. bottom_center = feet planted, no jitter."}),
                # ---- canvas (v3 widgets appended; old workflows unaffected) ----
                "canvas": (_CANVAS, {"default": "Tight (crop to sprite)",
                            "tooltip": "Tight = canvas hugs the sprite. Fixed = exact artist canvas (e.g. 200x200) "
                                       "with the sprite placed inside — how real sprite assets ship."}),
                "canvas_size": ("INT", {"default": 200, "min": 16, "max": 2048, "step": 8,
                                "tooltip": "Fixed square: canvas is canvas_size x canvas_size art pixels."}),
                "canvas_width": ("INT", {"default": 200, "min": 8, "max": 2048, "step": 8,
                                 "tooltip": "Fixed custom: exact canvas width."}),
                "canvas_height": ("INT", {"default": 200, "min": 8, "max": 2048, "step": 8,
                                  "tooltip": "Fixed custom: exact canvas height."}),
                "placement": (_PLACEMENTS, {"default": "center",
                              "tooltip": "Fixed canvas: where the sprite sits. If it overflows, it crops "
                                         "symmetrically from this anchor."}),
                "offset_x": ("INT", {"default": 0, "min": -1024, "max": 1024,
                             "tooltip": "Fixed canvas: nudge sprite right (+) / left (-) in art pixels."}),
                "offset_y": ("INT", {"default": 0, "min": -1024, "max": 1024,
                             "tooltip": "Fixed canvas: nudge sprite down (+) / up (-) in art pixels."}),
            },
            "optional": {
                "alpha": ("MASK",),
                "custom_palette_image": ("IMAGE",),
            },
        }

    def run(self, images, size_preset, custom_width, custom_height, look, palette,
            colors, dither, cleanup, background, custom_bg_hex, key_strength,
            sharpen_grid, motion_fix, loop_mode, remove_duplicate_frames, anchor,
            canvas="Tight (crop to sprite)", canvas_size=200, canvas_width=200,
            canvas_height=200, placement="center", offset_x=0, offset_y=0,
            alpha=None, custom_palette_image=None):
        report = []

        # ---- 1. background removal FIRST, at full video res ----
        # The flood key needs real per-pixel color to tell backdrop gradient
        # from sprite outline; after a block reduce that information is gone
        # (measured 2026-08-13: grid-res key keeps either 556 px = eats the
        # sprite, or 30k px = keys nothing; video-res key keeps the clean
        # ~10k). Keyed backdrop can not bleed into edge pixels later because
        # GridRecover's reduce is alpha-aware when the matte is wired.
        if alpha is None:
            key_color = custom_bg_hex if background == "custom hex" else _BACKGROUNDS[background]
            tol, shadow = _KEY_STRENGTH[key_strength]
            images, alpha = PixelForgeChromaKey().run(
                images, key_color, tol, 0.0, True, "flood", shadow, True, 0.5, 1,
                True, 2.0, True, 5.0)
            report.append(f"key: {key_color} ({key_strength.lower()})")
        else:
            report.append("key: skipped (alpha wired in)")

        # ---- 2. grid recover (alpha-aware: edge blocks take subject color
        #         only, so no backdrop halo survives the reduce) ----
        src_grid = None
        grid_frames = None
        if sharpen_grid:
            images, alpha, gw, gh, ginfo = PixelForgeGridRecover().run(
                images, "auto", 4, 12, "median", False, alpha=alpha)
            report.append(f"grid: {gw}x{gh}")
            src_grid = (gw, gh)
        # pre-quantize frames = motion reference for the movelock motion fix
        # (measuring motion AFTER quantize would read palette snapping as
        # movement and nothing would count as static)
        grid_frames = images

        # ---- resolve size (after grid recover: Source uses the true grid) ----
        if size_preset == "Custom size":
            tw, th = custom_width, custom_height
        elif _SIZE_PRESETS[size_preset] < 0:
            if src_grid is not None:
                tw, th = src_grid  # 1:1 with the grid H3 actually rendered
            else:
                tw, th = images.shape[2], images.shape[1]  # no grid: snap at native res
        else:
            tw, th = _SIZE_PRESETS[size_preset], _SIZE_PRESETS[size_preset]
        report.append(f"size: {tw}x{th if th else 'auto'}")

        # ---- 3. pixel-art look ----
        dmode, dstrength = _DITHER[dither]
        palette_json = "{}"
        if look.startswith("Hi-bit"):
            cel = look == "Hi-bit cel shading"
            images, alpha, _smask, palette_json = PixelForgeTruePixel().run(
                images, tw, th, "area", colors, 0.75, 5.0, 2,
                3 if cel else 1, 0.35, 0.55, 0.85, 1.25,
                0.30 if cel else 0.0, 1.15, cel, dmode, dstrength,
                cleanup, 1.25, 1.10, 0.6, True, 28.0, 1,
                "manual", 10, 0.06, True, alpha=alpha)
            report.append(f"look: {look.lower()}")
        else:
            preset_name = {"Modern (smooth color)": "modern_hibit",
                           "Retro 16-bit": "retro_16bit",
                           "Hardcore 8-bit": "hardcore_8bit"}[look]
            p = dict(_STYLE_PRESETS[preset_name])
            # This node always quantizes at the recovered art grid (1:1), so
            # the preset flatten median prefilter runs at ART-PIXEL res where
            # it eats 1px outlines and — worse — it filters RGB across the
            # matte boundary, dragging keyed-out backdrop green INTO opaque
            # edge pixels (the green-speck failure). The grid recover's
            # trimmed-mean block reduce already killed the VAE grain flatten
            # was designed for. Force it off here; the standalone Quantize
            # node keeps it for video-res use.
            p.update(flatten=0)
            if look == "Modern (smooth color)":
                # fidelity mode: H3's own shading is already good pixel art -
                # don't re-grade it (boosts shift hues), just snap to palette
                p.update(saturation=1.0, contrast=1.0, sharpen=0.0)
            if palette == "auto (from sprite)":
                palette_mode, fixed_palette = "adaptive", PALETTE_NAMES[0]
            elif palette == "use custom image":
                palette_mode, fixed_palette = "custom_image", PALETTE_NAMES[0]
            else:
                palette_mode, fixed_palette = "fixed", palette
            use_colors = colors if palette_mode != "fixed" else p["colors"]
            images, palette_json, alpha = PixelForgeQuantize().run(
                images, tw, th, "nearest", "custom", palette_mode, "kmeans",
                fixed_palette, use_colors, "lab", dmode, dstrength, True,
                cleanup, p["saturation"], p["contrast"], p["sharpen"], 1,
                p["flatten"], temporal_lock=0.0,
                custom_palette_image=custom_palette_image,
                alpha=alpha)
            report.append(f"look: {look.lower()}, palette: {palette}")

        # ---- 4. motion fix (post-look, on the final palette + matte).
        #         despike: zero-lag blip removal that cannot eat the sprite.
        #         movelock: static-source pixels collapse to their mode color
        #         (motion measured on the pre-quantize grid frames). ----
        if _MOTION[motion_fix] is not None:
            mode, thr, commit, hold = _MOTION[motion_fix]
            images, alpha = PixelForgeTemporalStabilize().run(
                images, mode, thr, commit, hold, alpha=alpha,
                motion_ref=grid_frames if mode == "movelock" else None)
            report.append(f"motion_fix: {motion_fix.lower()}")

        # ---- 5. crop & anchor (tight) or place on a fixed artist canvas ----
        if canvas == "Tight (crop to sprite)":
            images, alpha, crop_info = PixelForgeAutoCrop().run(
                images, "union", anchor, 2, 8, 0, alpha=alpha)
        else:
            cwid = canvas_size if canvas == "Fixed square" else canvas_width
            chei = canvas_size if canvas == "Fixed square" else canvas_height
            images, alpha, crop_info = PixelForgeAutoCrop().run(
                images, "union", anchor, 2, 8, 0, "fixed", cwid, chei,
                placement, offset_x, offset_y, alpha=alpha)
        report.append(f"crop: {crop_info}")

        # ---- 6. loop trim ----
        images, alpha, loop_info = PixelForgeLoopTrim().run(
            images, _LOOPS[loop_mode], 0.06, 0.5, alpha=alpha)
        report.append(f"loop: {loop_info}")

        # ---- 7. dedup ----
        durations_json = ""
        if remove_duplicate_frames:
            images, alpha, durations_json = PixelForgeFrameDedup().run(
                images, 0.01, alpha=alpha)

        n = images.shape[0]
        h, w = images.shape[1], images.shape[2]
        report.insert(0, f"OK: {n} frames @ {w}x{h}")
        return (images, alpha, durations_json, palette_json, " | ".join(report))


class PixelForgeEasyExport:
    """GIF + sprite sheet + optional Aseprite hand-off in one node."""

    CATEGORY = "PixelForge/Easy"
    FUNCTION = "run"
    RETURN_TYPES = ("IMAGE", "IMAGE", "STRING")
    RETURN_NAMES = ("frames", "sheet", "report")
    OUTPUT_NODE = True
    DESCRIPTION = ("One-stop export: animated GIF preview, packed sprite sheet "
                   "with JSON, and optional Aseprite file. Defaults are "
                   "sensible — just set a name and run.")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "filename_prefix": ("STRING", {"default": "pixelforge/sprite",
                                    "tooltip": "Output file name (folders allowed). Saved under ComfyUI's output dir."}),
                "fps": ("FLOAT", {"default": 12.0, "min": 1.0, "max": 60.0,
                        "tooltip": "Playback speed. 8-12 reads most 'sprite'."}),
                "make_gif": ("BOOLEAN", {"default": True}),
                "gif_size": (["tiny (1x)", "small (2x)", "big (4x)", "huge (8x)"],
                             {"default": "big (4x)",
                              "tooltip": "GIF preview size. The saved frames stay true pixel size; this only scales the GIF."}),
                "make_sheet": ("BOOLEAN", {"default": True}),
                "sheet_columns": ("INT", {"default": 0, "min": 0, "max": 64,
                                  "tooltip": "0 = automatic square-ish layout."}),
                "sheet_bg": ("STRING", {"default": "#202040",
                             "tooltip": "Sheet background color (only visible where the sprite is transparent)."}),
                "build_aseprite": ("BOOLEAN", {"default": False,
                                   "tooltip": "Also build a .aseprite file (needs Aseprite installed). WIP."}),
                "aseprite_path": ("STRING", {"default": "",
                                  "tooltip": "Path to aseprite.exe. Leave empty to auto-detect."}),
            },
            "optional": {
                "alpha": ("MASK",),
                "durations_json": ("STRING", {"forceInput": True}),
            },
        }

    def run(self, images, filename_prefix, fps, make_gif, gif_size, make_sheet,
            sheet_columns, sheet_bg, build_aseprite, aseprite_path,
            alpha=None, durations_json=None):
        report = []
        ui_images = []
        ui_animated = None

        def _collect(r):
            # SaveGIF/AsepriteExport return {"ui": ..., "result": (report,)} —
            # propagate the ANIMATED preview so it shows ON this node. Only
            # the animated (webp) entry is surfaced: AsepriteExport's ui dumps
            # every PNG frame, and if those land first the frontend's animated
            # preview widget shows imgs[0] = a static frame — the "GIF doesn't
            # display" bug. The PNG sequence is still on disk (see report).
            nonlocal ui_animated
            if isinstance(r, dict):
                rep = r.get("result", ("",))
                report.append(rep[0] if isinstance(rep, (tuple, list))
                              else str(rep))
                ui = r.get("ui") or {}
                if ui.get("animated"):
                    ui_animated = ui["animated"]
                    ui_images[:] = ui.get("images", []) + ui_images
            else:
                report.append(r[0] if isinstance(r, (tuple, list)) else str(r))

        sheet = images  # passthrough if sheet disabled
        if make_sheet:
            sheet, _sa, sheet_json = PixelForgeSheetPack().run(
                images, sheet_columns, 0, sheet_bg, fps,
                alpha=alpha, durations_json=durations_json)
            report.append("sheet: packed")

        if make_gif:
            scale = {"tiny (1x)": 1, "small (2x)": 2, "big (4x)": 4, "huge (8x)": 8}[gif_size]
            r = PixelForgeSaveGIF().run(
                images, filename_prefix, fps, True, scale, True,
                alpha=alpha, durations_json=durations_json)
            _collect(r)

        if build_aseprite:
            r = PixelForgeAsepriteExport().run(
                images, filename_prefix, "run", fps, True, aseprite_path,
                alpha=alpha, durations_json=durations_json)
            _collect(r)

        result = (images, sheet, " | ".join(report))
        ui = {"images": ui_images}
        if ui_animated:
            ui["animated"] = ui_animated
        return {"ui": ui, "result": result}


class PixelForgeEasyPrompt:
    """Minimal H3 sprite prompt: who, what they're doing, style, length."""

    CATEGORY = "PixelForge/Easy"
    FUNCTION = "run"
    RETURN_TYPES = ("STRING", "INT", "INT")
    RETURN_NAMES = ("h3_prompt", "length_frames", "fps")
    DESCRIPTION = ("Sprite prompt for MiniMax H3 in 4 fields. Wire h3_prompt "
                   "and length_frames straight into MiniMaxH3ImageToVideo.")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "character": ("STRING", {"multiline": True, "default":
                              "a small knight in blue armor with a red cape",
                              "tooltip": "Who/what the sprite is."}),
                "action": ("STRING", {"multiline": True, "default":
                           "walks in place with a steady gait",
                           "tooltip": "What they do. Keep it one simple motion for clean loops."}),
                "style": (["16-bit SNES", "8-bit NES", "GBA", "1-bit",
                           "arcade CPS2", "modern hi-bit"],),
                "seconds": ("FLOAT", {"default": 2.0, "min": 0.5, "max": 15.0, "step": 0.25,
                            "tooltip": "2-4 s is the sweet spot. Snapped to H3's frame grid automatically."}),
                "seamless_loop": ("BOOLEAN", {"default": True}),
            },
        }

    def run(self, character, action, style, seconds, seamless_loop):
        return PixelForgeH3Prompt().run(character, action, style, "side",
                                        "chroma green", seamless_loop, seconds, "")


NODE_CLASS_MAPPINGS = {
    "PixelForgeSpriteStudio": PixelForgeSpriteStudio,
    "PixelForgeEasyExport": PixelForgeEasyExport,
    "PixelForgeEasyPrompt": PixelForgeEasyPrompt,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "PixelForgeSpriteStudio": "\u2728 Sprite Studio (Easy v2)",
    "PixelForgeEasyExport": "\U0001F4E6 Sprite Export (Easy v2)",
    "PixelForgeEasyPrompt": "\U0001F4AC H3 Sprite Prompt (Easy v2)",
}

