"""Pixel-art quantization node: downscale, palette-reduce, dither, nearest upscale.

v2 post-process engine:
  - k-means++ palette generation (sampled across the whole batch) instead of
    PIL median-cut -> palettes that actually match the artwork's color masses
  - perceptual (CIELAB) nearest-palette mapping -> hue-true color decisions
  - saturation/contrast/sharpness pre-boost -> survives the downscale wash-out
  - ordered Bayer dithering evaluated in perceptual space
  - despeckle pass (isolated-pixel majority filter on the index map) ->
    removes single-pixel noise so frames read as deliberate pixel art
  - style presets (modern hi-bit, retro 16-bit, hardcore 8-bit)
Everything is pure numpy/PIL/torch. Node class name and existing widgets are
unchanged, so saved workflows load untouched and simply render better.
"""

import json

import numpy as np
import torch
from PIL import Image, ImageEnhance, ImageFilter

from .pf_palettes import PALETTE_NAMES, palette_rgb

_RESAMPLE = {
    "nearest": Image.Resampling.NEAREST,
    "bilinear": Image.Resampling.BILINEAR,
    "bicubic": Image.Resampling.BICUBIC,
    "lanczos": Image.Resampling.LANCZOS,
    "area": Image.Resampling.BOX,
}

_BAYER = {
    "bayer2": np.array([[0, 2], [3, 1]], dtype=np.float32) / 4.0,
    "bayer4": np.array(
        [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]],
        dtype=np.float32) / 16.0,
    "bayer8": None,  # built lazily
}

# preset: colors, dither, dither_strength, saturation, contrast, sharpen, despeckle, flatten
_STYLE_PRESETS = {
    "modern_hibit": dict(colors=64, dither="bayer2", dither_strength=0.20,
                         saturation=1.25, contrast=1.10, sharpen=0.6, despeckle=1, flatten=3),
    "retro_16bit": dict(colors=32, dither="bayer4", dither_strength=0.30,
                        saturation=1.15, contrast=1.05, sharpen=0.4, despeckle=1, flatten=3),
    "hardcore_8bit": dict(colors=16, dither="bayer4", dither_strength=0.35,
                          saturation=1.05, contrast=1.05, sharpen=0.3, despeckle=1, flatten=3),
}

_RNG_SEED = 0xC0FFEE


# ---------------------------------------------------------------------------
# color space helpers (sRGB <-> CIELAB, D65)

def _rgb_to_lab(rgb):
    """rgb: (...,3) float32 in [0,255] -> Lab (...,3)."""
    x = rgb / 255.0
    lin = np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)
    r, g, b = lin[..., 0], lin[..., 1], lin[..., 2]
    X = r * 0.4124564 + g * 0.3575761 + b * 0.1804375
    Y = r * 0.2126729 + g * 0.7151522 + b * 0.0721750
    Z = r * 0.0193339 + g * 0.1191920 + b * 0.9503041
    X /= 0.95047
    Z /= 1.08883
    eps = 216.0 / 24389.0
    kap = 24389.0 / 27.0
    def f(t):
        return np.where(t > eps, np.cbrt(t), (kap * t + 16.0) / 116.0)
    fx, fy, fz = f(X), f(Y), f(Z)
    L = 116.0 * fy - 16.0
    a = 500.0 * (fx - fy)
    bb = 200.0 * (fy - fz)
    return np.stack([L, a, bb], axis=-1).astype(np.float32)


def _lab_to_rgb(lab):
    """lab: (...,3) -> rgb uint8-ish float (...,3) clipped to [0,255]."""
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    fy = (L + 16.0) / 116.0
    fx = fy + a / 500.0
    fz = fy - b / 200.0
    eps = 216.0 / 24389.0
    kap = 24389.0 / 27.0
    def inv(f):
        f3 = f ** 3
        return np.where(f3 > eps, f3, (116.0 * f - 16.0) / kap)
    X = inv(fx) * 0.95047
    Y = np.where(L > kap * eps, ((L + 16.0) / 116.0) ** 3, L / kap)
    Z = inv(fz) * 1.08883
    r = X * 3.2404542 + Y * -1.5371385 + Z * -0.4985314
    g = X * -0.9692660 + Y * 1.8760108 + Z * 0.0415560
    bb = X * 0.0556434 + Y * -0.2040259 + Z * 1.0572252
    lin = np.stack([r, g, bb], axis=-1)
    srgb = np.where(lin <= 0.0031308, 12.92 * lin,
                    1.055 * np.power(np.clip(lin, 0, None), 1 / 2.4) - 0.055)
    return (np.clip(srgb, 0.0, 1.0) * 255.0).astype(np.float32)


# ---------------------------------------------------------------------------
# small utils

def _bayer8():
    global _BAYER
    if _BAYER["bayer8"] is None:
        b4 = _BAYER["bayer4"]
        b8 = np.zeros((8, 8), dtype=np.float32)
        b8[0::2, 0::2] = 4 * b4
        b8[0::2, 1::2] = 4 * b4 + 2
        b8[1::2, 0::2] = 4 * b4 + 3
        b8[1::2, 1::2] = 4 * b4 + 1
        _BAYER["bayer8"] = b8 / 64.0
    return _BAYER["bayer8"]


def _tensor_to_pil_list(images):
    arr = (images.clamp(0, 1) * 255).round().to(torch.uint8).cpu().numpy()
    return [Image.fromarray(arr[i], "RGB") for i in range(arr.shape[0])]


def _pil_list_to_tensor(frames):
    arr = np.stack([np.asarray(f, dtype=np.float32) / 255.0 for f in frames])
    return torch.from_numpy(arr)


def _palette_from_quantized(q, colors):
    pal = q.getpalette() or []
    n = min(colors, len(pal) // 3)
    return [tuple(pal[i * 3:i * 3 + 3]) for i in range(n)]


def _build_fixed_pal_image(rgb_list):
    pal = Image.new("P", (1, 1))
    flat = []
    for r, g, b in rgb_list:
        flat += [r, g, b]
    flat += [0] * (768 - len(flat))
    pal.putpalette(flat)
    return pal


def _preprocess(frames, saturation, contrast, sharpen):
    out = []
    for f in frames:
        if saturation != 1.0:
            f = ImageEnhance.Color(f).enhance(saturation)
        if contrast != 1.0:
            f = ImageEnhance.Contrast(f).enhance(contrast)
        if sharpen > 0.0:
            f = f.filter(ImageFilter.UnsharpMask(radius=2, percent=int(sharpen * 150),
                                                 threshold=2))
        out.append(f)
    return out


# ---------------------------------------------------------------------------
# k-means++ palette

def _sample_pixels(frames, max_samples=65536, masks=None):
    """Gather a representative pixel sample from a list of PIL frames.
    masks: optional list of (H,W) bool arrays (small frame size) — only
    valid (True) pixels are sampled, so transparent background never
    contaminates the palette."""
    rng = np.random.default_rng(_RNG_SEED)
    per = max(1, max_samples // max(1, len(frames)))
    chunks = []
    for i, f in enumerate(frames):
        px = np.asarray(f, dtype=np.float32).reshape(-1, 3)
        if masks is not None:
            px = px[masks[i].reshape(-1)]
        if px.shape[0] == 0:
            continue
        if px.shape[0] > per:
            px = px[rng.choice(px.shape[0], per, replace=False)]
        chunks.append(px)
    if not chunks:  # everything masked out; fall back to full frames
        return _sample_pixels(frames, max_samples, None)
    return np.concatenate(chunks, axis=0)


def _kmeans_palette(frames, k, space="lab", iters=24, masks=None):
    """k-means++ over batch-sampled pixels. Returns [(r,g,b), ...] length k."""
    pts = _sample_pixels(frames, masks=masks)
    work = _rgb_to_lab(pts) if space == "lab" else pts
    rng = np.random.default_rng(_RNG_SEED + 1)
    n = work.shape[0]
    k = max(2, min(k, n))
    # k-means++ seeding
    cent = [work[rng.integers(n)]]
    d2 = ((work - cent[0]) ** 2).sum(-1)
    for _ in range(1, k):
        s = float(d2.sum())
        if s <= 1e-9:
            cent.append(work[rng.integers(n)])  # remaining points are duplicates
        else:
            cent.append(work[rng.choice(n, p=d2 / s)])
        d2 = np.minimum(d2, ((work - cent[-1]) ** 2).sum(-1))
    C = np.stack(cent).astype(np.float32)
    # lloyd iterations, chunked
    for _ in range(iters):
        idx = np.empty(n, dtype=np.int32)
        chunk = 16384
        for s in range(0, n, chunk):
            d = ((work[s:s + chunk, None, :] - C[None, :, :]) ** 2).sum(-1)
            idx[s:s + chunk] = d.argmin(-1)
        newC = C.copy()
        for ci in range(k):
            mask = idx == ci
            if mask.any():
                newC[ci] = work[mask].mean(0)
        if np.allclose(newC, C, atol=1e-3):
            C = newC
            break
        C = newC
    if space == "lab":
        rgb = _lab_to_rgb(C)
    else:
        rgb = C
    return [tuple(int(round(v)) for v in c) for c in np.clip(rgb, 0, 255)]


# ---------------------------------------------------------------------------
# perceptual nearest-palette mapping (+ dither + despeckle)

def _nearest_palette_map(px, palette, space="rgb"):
    """px: (H,W,3) float32 0-255; palette: (N,3) float32 0-255 -> (H,W) uint8."""
    if space == "lab":
        px = _rgb_to_lab(px)
        palette = _rgb_to_lab(palette)
    h, w, _ = px.shape
    flat = px.reshape(-1, 3)
    idx = np.empty(flat.shape[0], dtype=np.uint8)
    chunk = 65536
    for s in range(0, flat.shape[0], chunk):
        d = ((flat[s:s + chunk, None, :] - palette[None, :, :]) ** 2).sum(-1)
        idx[s:s + chunk] = d.argmin(-1).astype(np.uint8)
    return idx.reshape(h, w)


def _map_frames(frames, pal_rgb, space, dither, dither_strength):
    """Map PIL frames onto pal_rgb. Returns (frames_rgb, index_maps)."""
    pal = np.array(pal_rgb, dtype=np.float32)
    out, maps = [], []
    fs = (dither == "floyd_steinberg")
    pal_img = _build_fixed_pal_image(pal_rgb) if fs else None
    for f in frames:
        if fs:
            # error diffusion stays on PIL's fast C path (RGB space);
            # palette itself was still k-means/lab chosen.
            q = f.quantize(palette=pal_img, dither=Image.Dither.FLOYDSTEINBERG)
            maps.append(np.asarray(q, dtype=np.uint8))
            out.append(q.convert("RGB"))
            continue
        px = np.asarray(f, dtype=np.float32)
        if dither.startswith("bayer") and dither_strength > 0:
            matrix = _bayer8() if dither == "bayer8" else _BAYER[dither]
            kk = matrix.shape[0]
            h, w, _ = px.shape
            tiled = np.tile(matrix, (h // kk + 1, w // kk + 1))[:h, :w]
            px = np.clip(px + (tiled - 0.5)[:, :, None] * 96.0 * dither_strength,
                         0, 255)
        idx = _nearest_palette_map(px, pal, space)
        maps.append(idx)
        out.append(Image.fromarray(pal[idx].astype(np.uint8), "RGB"))
    return out, maps


def _despeckle(idx, passes):
    """Majority filter: replace pixels that share a color with NONE of their
    8 neighbors with the dominant neighbor color. The classic 'orphan pixel'
    cleanup that makes AI output read as hand-placed pixel art."""
    if passes <= 0:
        return idx
    idx = idx.astype(np.int32)
    for _ in range(passes):
        h, w = idx.shape
        padded = np.pad(idx, 1, mode="edge")
        counts = np.zeros((h, w), dtype=np.int32)       # same-color neighbors
        best_val = np.zeros((h, w), dtype=np.int32)     # running modal neighbor
        best_cnt = np.zeros((h, w), dtype=np.int32)
        neigh_cnt = {}
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dy == 0 and dx == 0:
                    continue
                nb = padded[1 + dy:1 + dy + h, 1 + dx:1 + dx + w]
                counts += (nb == idx)
                key = (dy, dx)
                neigh_cnt[key] = nb
        # modal neighbor via per-shift vote accumulation
        vote = np.zeros((h, w), dtype=np.int32)
        best_val.fill(-1)
        for key, nb in neigh_cnt.items():
            c = np.zeros((h, w), dtype=np.int32)
            for k2, nb2 in neigh_cnt.items():
                c += (nb2 == nb)
            take = c > vote
            vote = np.where(take, c, vote)
            best_val = np.where(take, nb, best_val)
        isolated = (counts == 0) & (vote > 0)
        if not isolated.any():
            break
        idx = np.where(isolated, best_val, idx)
    return idx


# ---------------------------------------------------------------------------
# palette acquisition

def _merge_palette(pal_rgb, threshold=7.0):
    """Drop near-duplicate palette entries (Lab distance < threshold).
    k-means loves parking many centroids on one dominant color mass; those
    duplicate slots wash out the rest of the palette and make despeckle blind
    (neighbors hold different-but-identical-looking indices)."""
    if len(pal_rgb) <= 2:
        return list(pal_rgb)
    lab = _rgb_to_lab(np.array(pal_rgb, dtype=np.float32).reshape(-1, 3))
    kept = [tuple(pal_rgb[0])]
    kept_lab = [lab[0]]
    for i in range(1, len(pal_rgb)):
        d = np.sqrt(((np.stack(kept_lab) - lab[i]) ** 2).sum(-1))
        if d.min() >= threshold:
            kept.append(tuple(pal_rgb[i]))
            kept_lab.append(lab[i])
    return kept


def _get_palette(frames, palette_mode, fixed_palette, colors, custom_pal_rgb,
                 palette_method, mapping_space, shared_palette, masks=None):
    """Returns pal_rgb list. frames are the downscaled PIL frames."""
    if palette_mode == "fixed":
        return palette_rgb(fixed_palette)
    if palette_mode == "custom_image" and custom_pal_rgb is not None:
        return custom_pal_rgb
    # adaptive
    if palette_method == "kmeans":
        src = frames if shared_palette else frames[:1]
        mk = masks if shared_palette else (masks[:1] if masks else None)
        return _kmeans_palette(src, colors, space=mapping_space, masks=mk)
    # median cut (PIL classic)
    if shared_palette and len(frames) > 1:
        widths = max(f.width for f in frames)
        total_h = sum(f.height for f in frames)
        stacked = Image.new("RGB", (widths, total_h))
        y = 0
        for f in frames:
            stacked.paste(f, (0, y))
            y += f.height
        q = stacked.quantize(colors=colors, method=Image.Quantize.MEDIANCUT,
                             dither=Image.Dither.NONE)
        return _palette_from_quantized(q, colors)
    q = frames[0].quantize(colors=colors, method=Image.Quantize.MEDIANCUT,
                           dither=Image.Dither.NONE)
    return _palette_from_quantized(q, colors)


class PixelForgeQuantize:
    """Downscale to true pixel resolution, build a k-means palette shared
    across the batch (temporal color stability), map colors perceptually
    (CIELAB) with optional ordered/FS dithering, despeckle orphan pixels,
    then nearest-neighbor upscale back to display size."""

    CATEGORY = "PixelForge/pixel"
    FUNCTION = "run"
    RETURN_TYPES = ("IMAGE", "STRING", "MASK")
    RETURN_NAMES = ("images", "palette_json", "alpha")
    DESCRIPTION = ("Turn H3 (or any) frames into real pixel art: boost, downscale "
                   "(premultiplied when alpha is wired in, so backdrop color never "
                   "bleeds into sprite edges), k-means palette (shared across the "
                   "batch), perceptual color mapping, dither, despeckle, "
                   "nearest-upscale.")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "pixel_width": ("INT", {"default": 256, "min": 8, "max": 2048, "step": 8,
                                        "tooltip": "Target pixel-art width. Height keeps aspect unless pixel_height is set."}),
                "pixel_height": ("INT", {"default": 0, "min": 0, "max": 2048, "step": 8,
                                         "tooltip": "0 = derive from aspect ratio."}),
                "downsample_filter": (["area", "bilinear", "bicubic", "lanczos", "nearest"],),
                "palette_mode": (["adaptive", "fixed", "custom_image"],),
                "fixed_palette": (PALETTE_NAMES,),
                "colors": ("INT", {"default": 48, "min": 2, "max": 256}),
                "dither": (["none", "bayer2", "bayer4", "bayer8", "floyd_steinberg"],),
                "dither_strength": ("FLOAT", {"default": 0.2, "min": 0.0, "max": 1.0, "step": 0.05}),
                "shared_palette": ("BOOLEAN", {"default": True,
                                               "tooltip": "One palette for the whole batch. Strongly recommended for animation."}),
                "upscale_factor": ("INT", {"default": 2, "min": 0, "max": 16,
                                           "tooltip": "Nearest-neighbor upscale after quantization. 0 = back to input size."}),
                # --- v2 widgets: appended last so OLD workflows' positional
                # widgets_values still land on the right widgets ---
                "style_preset": (["custom", "modern_hibit", "retro_16bit", "hardcore_8bit"],
                                 {"tooltip": "modern_hibit = clean contemporary look (64 colors, light dither). "
                                             "'custom' = use the sliders above. Presets override colors/dither/boost sliders."}),
                "palette_method": (["kmeans", "median_cut"],
                                   {"tooltip": "kmeans = batch-sampled k-means++ palette (best). median_cut = legacy PIL behavior."}),
                "mapping_space": (["lab", "rgb"],
                                  {"tooltip": "lab = perceptual color decisions (hue-true). rgb = legacy behavior. "
                                              "floyd_steinberg dither always maps in RGB (PIL fast path)."}),
                "despeckle": ("INT", {"default": 1, "min": 0, "max": 3,
                                      "tooltip": "Orphan-pixel cleanup passes. 1 is usually perfect; 0 = off."}),
                "saturation": ("FLOAT", {"default": 1.2, "min": 0.0, "max": 3.0, "step": 0.05,
                                         "tooltip": "Pre-boost before downscale so color survives palette reduction."}),
                "contrast": ("FLOAT", {"default": 1.1, "min": 0.0, "max": 3.0, "step": 0.05}),
                "sharpen": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 2.0, "step": 0.1,
                                      "tooltip": "Unsharp mask before downscale; keeps edges crisp at tiny pixel sizes."}),
                "flatten": ("INT", {"default": 3, "min": 0, "max": 7, "step": 2,
                                    "tooltip": "Median denoise at SOURCE resolution, before downscale. "
                                               "Kills VAE grain -> flat color regions -> much less mud. 0 = off."}),
            },
            "optional": {
                "custom_palette_image": ("IMAGE", {"tooltip": "Palette source image when palette_mode=custom_image."}),
                "alpha": ("MASK", {"tooltip": "Wire Sprite Chroma Key's alpha here (key BEFORE quantize). "
                                              "Downscale becomes premultiplied: no backdrop bleed on sprite edges, "
                                              "and the palette is built from sprite pixels only."}),
            },
        }

    def run(self, images, pixel_width, pixel_height, downsample_filter, style_preset,
            palette_mode, palette_method, fixed_palette, colors, mapping_space,
            dither, dither_strength, shared_palette, despeckle, saturation,
            contrast, sharpen, upscale_factor, flatten=3, custom_palette_image=None,
            alpha=None):
        frames = _tensor_to_pil_list(images)
        src_w, src_h = frames[0].size
        n = len(frames)

        if style_preset != "custom":
            p = _STYLE_PRESETS[style_preset]
            colors = p["colors"]
            dither = p["dither"]
            dither_strength = p["dither_strength"]
            saturation = p["saturation"]
            contrast = p["contrast"]
            sharpen = p["sharpen"]
            despeckle = p["despeckle"]
            flatten = p["flatten"]

        tw = pixel_width
        th = pixel_height if pixel_height > 0 else max(8, round(src_h * tw / src_w))
        fk = flatten if flatten >= 3 else 0
        if fk and fk % 2 == 0:
            fk += 1

        # alpha masks per frame, at source res
        am = None
        if alpha is not None:
            m = alpha.cpu().numpy()
            am = [np.asarray(
                Image.fromarray((np.clip(m[min(i, m.shape[0] - 1)], 0, 1) * 255)
                                .astype(np.uint8)).resize((src_w, src_h),
                                Image.Resampling.BILINEAR),
                dtype=np.float32) / 255.0 for i in range(n)]

        custom_pal_rgb = None
        if palette_mode == "custom_image":
            if custom_palette_image is None:
                raise ValueError("PixelForgeQuantize: palette_mode=custom_image needs custom_palette_image.")
            pal_frames = _tensor_to_pil_list(custom_palette_image)
            if palette_method == "kmeans":
                custom_pal_rgb = _kmeans_palette(pal_frames[:1], colors,
                                                 space=mapping_space)
            else:
                q = pal_frames[0].quantize(colors=colors, method=Image.Quantize.MEDIANCUT)
                custom_pal_rgb = _palette_from_quantized(q, colors)

        frames = _preprocess(frames, saturation, contrast, sharpen)

        # flatten (median denoise) at SOURCE res: kills VAE grain without
        # carving the pixel-res art into ragged patches
        if fk:
            frames = [f.filter(ImageFilter.MedianFilter(fk)) for f in frames]

        # downscale (premultiplied when alpha present -> zero backdrop bleed)
        small = []
        small_masks = None
        if am is not None:
            small_masks = []
        for i, f in enumerate(frames):
            if am is not None:
                rgb = np.asarray(f, dtype=np.float32)
                a = am[i]
                prem = Image.fromarray(np.clip(rgb * a[..., None], 0, 255).astype(np.uint8))
                prem_s = np.asarray(prem.resize((tw, th), _RESAMPLE[downsample_filter]),
                                    dtype=np.float32)
                a_s = np.asarray(Image.fromarray((a * 255).astype(np.uint8)).resize(
                    (tw, th), _RESAMPLE[downsample_filter]), dtype=np.float32) / 255.0
                small_masks.append(a_s > 0.5)
                safe = np.maximum(a_s, 1e-3)
                unprem = np.clip(prem_s / safe[..., None], 0, 255)
                unprem[a_s <= 0.5] = 0  # transparent pixels: color irrelevant
                sf = Image.fromarray(unprem.astype(np.uint8))
            else:
                sf = f.resize((tw, th), _RESAMPLE[downsample_filter])
            small.append(sf)

        pal_rgb = _get_palette(small, palette_mode, fixed_palette, colors,
                               custom_pal_rgb, palette_method, mapping_space,
                               shared_palette, masks=small_masks)
        if palette_mode == "adaptive":
            pal_rgb = _merge_palette(pal_rgb)

        quant, idx_maps = _map_frames(small, pal_rgb, mapping_space, dither,
                                      dither_strength)

        if despeckle > 0:
            pal = np.array(pal_rgb, dtype=np.uint8)
            quant = []
            for idx in idx_maps:
                idx = _despeckle(idx, despeckle)
                quant.append(Image.fromarray(pal[idx.clip(0, len(pal) - 1)], "RGB"))

        if upscale_factor == 0:
            fw, fh = src_w, src_h
        elif upscale_factor > 1:
            fw, fh = tw * upscale_factor, th * upscale_factor
        else:
            fw, fh = tw, th
        if (fw, fh) != (tw, th):
            quant = [f.resize((fw, fh), Image.Resampling.NEAREST) for f in quant]

        # alpha out, matching final size
        if am is not None:
            out_a = np.zeros((n, fh, fw), dtype=np.float32)
            for i in range(n):
                a_img = Image.fromarray((small_masks[i].astype(np.uint8)) * 255)
                if (fw, fh) != (tw, th):
                    a_img = a_img.resize((fw, fh), Image.Resampling.NEAREST)
                out_a[i] = np.asarray(a_img, dtype=np.float32) / 255.0
        else:
            out_a = np.ones((n, fh, fw), dtype=np.float32)

        pal_hex = ["#%02X%02X%02X" % tuple(c) for c in pal_rgb]
        info = json.dumps({"palette": pal_hex, "pixel_size": [tw, th],
                           "output_size": [fw, fh], "frames": len(quant),
                           "palette_method": palette_method,
                           "mapping_space": mapping_space,
                           "style_preset": style_preset})
        return (_pil_list_to_tensor(quant), info, torch.from_numpy(out_a))


NODE_CLASS_MAPPINGS = {"PixelForgeQuantize": PixelForgeQuantize}
NODE_DISPLAY_NAME_MAPPINGS = {"PixelForgeQuantize": "Pixel Art Quantize (PixelForge)"}
