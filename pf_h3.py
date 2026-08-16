"""Deep MiniMax H3 integration: sprite-tuned prompt builder, H3 frame-grid math,
and VIDEO -> frame-batch extraction with sprite-friendly decimation."""

import json

import numpy as np
import torch

FPS = 24  # H3 native frame rate


_STYLES = {
    "16-bit SNES": "16-bit SNES-era pixel art, rich 32-color palette, chunky readable sprites",
    "8-bit NES": "8-bit NES pixel art, harshly limited palette, single-pixel outlines",
    "GBA": "Game Boy Advance pixel art, bright saturated limited palette, soft sprite shading",
    "1-bit": "1-bit black and white pixel art, stark silhouette, dithered shading",
    "arcade CPS2": "1990s arcade CPS2 pixel art, bold outlines, dramatic shading with few tones",
    "modern hi-bit": "modern hi-bit pixel art, large clean uniform pixel clusters, visible crisp pixel grid, deliberate limited palette, hand-crafted look, no stray single pixels",
}

_VIEWS = {
    "side": "side-scrolling side view, character faces right",
    "3/4": "three-quarter top-down RPG view",
    "front": "flat front view",
    "top-down": "direct top-down view",
}

_BACKGROUNDS = {
    "chroma green": ("The background is a flat solid chroma green screen, pure #00FF00: "
                     "an empty featureless green void filling everything behind the "
                     "character. No ground, no floor, no horizon, no scenery, no props, "
                     "no shadows, no gradient, no environment details — nothing but "
                     "uniform flat green behind the sprite"),
    "chroma magenta": ("The background is a flat solid chroma magenta screen, pure #FF00FF: "
                       "an empty featureless magenta void filling everything behind the "
                       "character. No ground, no floor, no horizon, no scenery, no props, "
                       "no shadows, no gradient, no environment details — nothing but "
                       "uniform flat magenta behind the sprite"),
    "solid black": "perfectly flat uniform solid black background, no shadow, no scenery",
    "simple scene": ("very simple flat-color pixel background that stays static, "
                     "in one solid color that strongly contrasts with the character "
                     "(never white, never any of the character's own colors)"),
    # v3.6.0: white/blue variants so the One Forge can prompt for ANY backdrop
    # the forge keyer targets (the backdrop-sync fix needs the full vocab).
    "chroma blue": ("The background is a flat solid chroma blue screen, pure #0000FF: "
                    "an empty featureless blue void filling everything behind the "
                    "character. No ground, no floor, no horizon, no scenery, no props, "
                    "no shadows, no gradient, no environment details — nothing but "
                    "uniform flat blue behind the sprite"),
    "solid white": ("The background is a flat solid pure white screen, pure #FFFFFF: "
                    "an empty featureless white void filling everything behind the "
                    "character. No ground, no floor, no horizon, no scenery, no props, "
                    "no shadows, no gradient, no environment details — nothing but "
                    "uniform flat white behind the sprite"),
}


def clause_for_hex(hex_str):
    """Backdrop prompt clause for an arbitrary forge key hex.

    The gen prompt, the suite ref flatten, and the forge keyer must ALL target
    the same color — v3.6.0 backdrop sync. (Before it, the One Forge prompt
    hardcoded 'chroma green': any non-green Backdrop choice left the green
    backdrop surviving the keyer while sprite pixels matching the WRONG target
    keyed out as holes — measured on forge run d85671cd2d, 2026-08-16.)
    Exact vocab text for the known chroma colors; a templated flat-void clause
    for anything else (custom hex).
    """
    h = str(hex_str or "").strip().upper()
    if not h.startswith("#"):
        h = "#" + h
    known = {
        "#00FF00": _BACKGROUNDS["chroma green"],
        "#FF00FF": _BACKGROUNDS["chroma magenta"],
        "#0000FF": _BACKGROUNDS["chroma blue"],
        "#000000": _BACKGROUNDS["solid black"],
        "#FFFFFF": _BACKGROUNDS["solid white"],
    }
    if h in known:
        return known[h]
    return ("The background is a flat solid uniform {0} screen: an empty "
            "featureless void in exactly {0} filling everything behind the "
            "character. No ground, no floor, no horizon, no scenery, no props, "
            "no shadows, no gradient, no environment details — nothing but "
            "uniform flat {0} behind the sprite").format(h)


class PixelForgeH3Prompt:
    """Build a sprite-animation prompt tuned for MiniMax H3's Qwen3-VL encoder,
    plus the grid-snapped frame count to feed EmptyMiniMaxH3LatentAV /
    MiniMaxH3ImageToVideo 'length'."""

    CATEGORY = "PixelForge/H3"
    FUNCTION = "run"
    RETURN_TYPES = ("STRING", "INT", "INT")
    RETURN_NAMES = ("h3_prompt", "length_frames", "fps")
    DESCRIPTION = "Sprite-animation prompt for MiniMax H3 (static camera, flat keyable background, loop hint) + H3 grid-snapped frame count."

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "subject": ("STRING", {"multiline": True, "default":
                                       "a small knight in blue armor with a red cape"}),
                "action": ("STRING", {"multiline": True, "default":
                                      "walks in place with a steady gait"}),
                "style": (list(_STYLES.keys()),),
                "view": (list(_VIEWS.keys()),),
                "background": (list(_BACKGROUNDS.keys()),),
                "seamless_loop": ("BOOLEAN", {"default": True}),
                "seconds": ("FLOAT", {"default": 2.0, "min": 0.5, "max": 15.0, "step": 0.25,
                                      "tooltip": "Clip length. H3 snaps this to its 17k+5 frame grid @24fps."}),
                "extra_notes": ("STRING", {"multiline": True, "default": ""}),
            },
        }

    @staticmethod
    def snap_frames(seconds):
        n = max(5, int(round(seconds * FPS)))
        while n % 17 != 5:
            n += 1
        return n

    @staticmethod
    def _build(subject, action, style, view, bg_clause, seamless_loop,
               extra_notes):
        """Prompt text from parts. bg_clause is the full backdrop sentence
        (vocab entry or clause_for_hex output), period appended by callers."""
        parts = [
            "Retro video game sprite animation, %s." % _STYLES[style],
            "%s, %s." % (subject.strip().rstrip("."), _VIEWS[view]),
            "The character %s." % action.strip().rstrip("."),
            "Full body visible, the character is large in frame (roughly two-thirds "
            "of the frame height) and stays fully inside the frame for the entire clip.",
            "Completely static orthographic camera, no pan, no zoom, no parallax.",
            bg_clause,
            "Crisp square pixels, limited color palette, clean silhouette, "
            "no anti-aliasing, no blur, no gradients, no glow, no dithering, "
            "no stippling, no noise or grain texture, no text, no watermark.",
        ]
        if seamless_loop:
            parts.append("The motion is a perfect seamless loop: the animation ends "
                         "exactly in the pose it started in.")
        if extra_notes.strip():
            parts.append(extra_notes.strip())
        return " ".join(parts)

    def run(self, subject, action, style, view, background, seamless_loop, seconds, extra_notes):
        prompt = self._build(subject, action, style, view,
                             _BACKGROUNDS[background] + ".",
                             seamless_loop, extra_notes)
        return (prompt, self.snap_frames(seconds), FPS)


class PixelForgeH3FrameGrid:
    """seconds <-> H3's 17k+5 frame grid @24fps."""

    CATEGORY = "PixelForge/H3"
    FUNCTION = "run"
    RETURN_TYPES = ("INT", "INT", "STRING")
    RETURN_NAMES = ("length_frames", "fps", "info")
    DESCRIPTION = "Snap a duration to MiniMax H3's 17k+5 latent frame grid (24 fps)."

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "seconds": ("FLOAT", {"default": 5.0, "min": 0.2, "max": 150.0, "step": 0.1}),
            "rounding": (["up", "down", "nearest"],),
        }}

    def run(self, seconds, rounding):
        n = max(5, int(round(seconds * FPS)))
        rem = (n - 5) % 17
        if rem:
            if rounding == "up":
                n += 17 - rem
            elif rounding == "down" and n - rem >= 5:
                n -= rem
            else:
                n += (17 - rem) if rem > 8 else -rem
        info = json.dumps({"frames": n, "fps": FPS, "seconds": round(n / FPS, 3)})
        return (n, FPS, info)


class PixelForgeVideoToFrames:
    """Extract frames from a ComfyUI VIDEO (e.g. LoadVideo / H3 chain output)
    with sprite-friendly decimation to 12/8 fps."""

    CATEGORY = "PixelForge/H3"
    FUNCTION = "run"
    RETURN_TYPES = ("IMAGE", "FLOAT", "STRING")
    RETURN_NAMES = ("images", "fps_effective", "info")
    DESCRIPTION = "VIDEO -> IMAGE batch with frame decimation (24fps H3 -> 12/8fps sprite timing)."

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "video": ("VIDEO",),
            "every_nth": ("INT", {"default": 2, "min": 1, "max": 24,
                                  "tooltip": "Keep every Nth frame. 2 turns 24fps H3 output into 12fps sprite timing."}),
            "start_offset": ("INT", {"default": 0, "min": 0, "max": 10000}),
            "max_frames": ("INT", {"default": 0, "min": 0, "max": 100000,
                                   "tooltip": "0 = no cap."}),
        }}

    def run(self, video, every_nth, start_offset, max_frames):
        components = video.get_components()
        frames = components.images  # [F,H,W,C] float
        src_fps = float(components.frame_rate)
        total = frames.shape[0]
        sel = frames[start_offset::every_nth]
        if max_frames > 0:
            sel = sel[:max_frames]
        if sel.shape[0] == 0:
            raise ValueError("PixelForgeVideoToFrames: no frames selected (offset too large?).")
        eff_fps = src_fps / every_nth
        info = json.dumps({"source_frames": int(total), "source_fps": src_fps,
                           "kept_frames": int(sel.shape[0]), "fps_effective": eff_fps})
        return (sel.contiguous(), eff_fps, info)


class PixelForgeH3StillPrompt:
    """Prompt builder for SINGLE-FRAME sprite generation with H3:
    a 5-frame (minimal grid) static hold, then grab frame 0 downstream."""

    CATEGORY = "PixelForge/H3"
    FUNCTION = "run"
    RETURN_TYPES = ("STRING", "INT", "INT")
    RETURN_NAMES = ("h3_prompt", "length_frames", "fps")
    DESCRIPTION = "Single-sprite prompt for MiniMax H3: 5-frame static hold (H3's minimum), pair with PixelForgeFirstFrame to extract the still."

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "subject": ("STRING", {"multiline": True, "default":
                                       "a small knight in blue armor with a red cape"}),
                "pose": ("STRING", {"multiline": True, "default":
                                    "standing in a confident idle stance, weapon resting"}),
                "style": (list(_STYLES.keys()),),
                "view": (list(_VIEWS.keys()),),
                "background": (list(_BACKGROUNDS.keys()),),
                "extra_notes": ("STRING", {"multiline": True, "default": ""}),
            },
        }

    def run(self, subject, pose, style, view, background, extra_notes):
        parts = [
            "Single static video game character sprite, %s." % _STYLES[style],
            "%s, %s, %s." % (subject.strip().rstrip("."), _VIEWS[view],
                             pose.strip().rstrip(".")),
            "Full body visible and fully inside the frame.",
            "The character holds completely still: no motion, no animation, no breathing, "
            "no camera movement, nothing changes between frames.",
            _BACKGROUNDS[background] + ".",
            "Crisp square pixels, limited color palette, clean silhouette, "
            "no anti-aliasing, no blur, no gradients, no glow, no text, no watermark.",
        ]
        if extra_notes.strip():
            parts.append(extra_notes.strip())
        return (" ".join(parts), 5, FPS)  # 5 = H3's minimal 17k+5 grid point


class PixelForgeH3EditPrompt:
    """Prompt builder for single-sprite EDITING via H3 ref2va:
    feed the source sprite into MiniMaxH3ReferenceToVideo ref_image_0,
    this prompt in, take frame 0 out."""

    CATEGORY = "PixelForge/H3"
    FUNCTION = "run"
    RETURN_TYPES = ("STRING", "INT", "INT")
    RETURN_NAMES = ("h3_prompt", "length_frames", "fps")
    DESCRIPTION = "Sprite-edit prompt for MiniMaxH3ReferenceToVideo: edit <Picture 1> while locking style, pose and palette. Pair with PixelForgePrepForH3 + PixelForgeFirstFrame."

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "edit_instruction": ("STRING", {"multiline": True, "default":
                                                "change the armor to gold and add a horned helmet"}),
                "background": (list(_BACKGROUNDS.keys()),),
                "keep_palette": ("BOOLEAN", {"default": True}),
                "extra_notes": ("STRING", {"multiline": True, "default": ""}),
            },
        }

    def run(self, edit_instruction, background, keep_palette, extra_notes):
        parts = [
            "Edit the pixel art game sprite in <Picture 1>: %s."
            % edit_instruction.strip().rstrip("."),
            "Keep the exact same character, pose, proportions, framing and pixel-art "
            "style as <Picture 1>; change only what was asked.",
        ]
        if keep_palette:
            parts.append("Preserve the original limited color palette of <Picture 1>; "
                         "introduce as few new colors as possible.")
        parts += [
            "The character holds completely still: no motion, no animation, "
            "no camera movement.",
            _BACKGROUNDS[background] + ".",
            "Crisp square pixels, clean silhouette, no anti-aliasing, no blur, "
            "no gradients, no dithering, no stippling, no noise or grain texture, "
            "no text, no watermark.",
        ]
        if extra_notes.strip():
            parts.append(extra_notes.strip())
        return (" ".join(parts), 5, FPS)


class PixelForgePrepForH3:
    """Prepare a small sprite for H3 ref2va editing: nearest-upscale to a valid
    H3 canvas (multiple of 32), pad with a keyable flat color."""

    CATEGORY = "PixelForge/H3"
    FUNCTION = "run"
    RETURN_TYPES = ("IMAGE", "INT", "INT")
    RETURN_NAMES = ("image", "width", "height")
    DESCRIPTION = "Upscale/pad a tiny sprite to H3 canvas size for ref2va edits. Nearest keeps the pixel structure; pad color should match the sprite background so keying still works."

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "image": ("IMAGE",),
            "target_long_edge": ("INT", {"default": 768, "min": 64, "max": 2048, "step": 32}),
            "upscale_filter": (["nearest", "bilinear"],),
            "pad_color": ("STRING", {"default": "#00FF00"}),
        }}

    def run(self, image, target_long_edge, upscale_filter, pad_color):
        from .pf_palettes import hex_to_rgb
        from PIL import Image as _Image
        arr = (image[0].clamp(0, 1) * 255).round().to(torch.uint8).cpu().numpy()
        h, w = arr.shape[:2]
        scale = target_long_edge / max(h, w)
        nw, nh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
        resample = _Image.Resampling.NEAREST if upscale_filter == "nearest" else _Image.Resampling.BILINEAR
        img = _Image.fromarray(arr, "RGB").resize((nw, nh), resample)
        cw = ((nw + 31) // 32) * 32
        ch = ((nh + 31) // 32) * 32
        canvas = _Image.new("RGB", (cw, ch), hex_to_rgb(pad_color.strip() or "#00FF00"))
        canvas.paste(img, ((cw - nw) // 2, (ch - nh) // 2))
        out = torch.from_numpy(np.asarray(canvas, dtype=np.float32) / 255.0).unsqueeze(0)
        return (out, cw, ch)


class PixelForgeFirstFrame:
    """Grab one frame (default: the first) from a batch — the still from a
    5-frame single-sprite H3 gen or edit."""

    CATEGORY = "PixelForge/H3"
    FUNCTION = "run"
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    DESCRIPTION = "Extract frame N (default 0) from an IMAGE batch. Use after a 5-frame H3 still/edit gen."

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "images": ("IMAGE",),
            "index": ("INT", {"default": 0, "min": 0, "max": 100000}),
        }}

    def run(self, images, index):
        idx = min(index, images.shape[0] - 1)
        return (images[idx:idx + 1].contiguous(),)


class PixelForgeFrameStep:
    """Same decimation for IMAGE batches coming straight off VAEDecode."""

    CATEGORY = "PixelForge/H3"
    FUNCTION = "run"
    RETURN_TYPES = ("IMAGE", "MASK", "STRING")
    RETURN_NAMES = ("images", "alpha", "info")
    DESCRIPTION = "Decimate an IMAGE batch (e.g. H3 VAEDecode output) from 24fps to sprite timing."

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "images": ("IMAGE",),
            "every_nth": ("INT", {"default": 2, "min": 1, "max": 24}),
            "start_offset": ("INT", {"default": 0, "min": 0, "max": 10000}),
            "source_fps": ("FLOAT", {"default": 24.0, "min": 1.0, "max": 120.0}),
        }, "optional": {"alpha": ("MASK",)}}

    def run(self, images, every_nth, start_offset, source_fps, alpha=None):
        sel = images[start_offset::every_nth]
        if sel.shape[0] == 0:
            raise ValueError("PixelForgeFrameStep: no frames selected.")
        out_a = alpha[start_offset::every_nth] if alpha is not None else \
            torch.ones(sel.shape[0], sel.shape[1], sel.shape[2])
        info = json.dumps({"kept_frames": int(sel.shape[0]),
                           "fps_effective": source_fps / every_nth})
        return (sel.contiguous(), out_a, info)
