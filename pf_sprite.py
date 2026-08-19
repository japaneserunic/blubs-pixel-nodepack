"""Sprite surgery nodes: chroma key, auto-crop/anchor, loop trim, frame dedup, sheet packing."""

import json
import math

import numpy as np
import torch
from PIL import Image
from scipy import ndimage

from .pf_palettes import hex_to_rgb
from .pf_pixelize import _rgb_to_lab


def _to_np(images):
    return (images.clamp(0, 1) * 255).round().to(torch.uint8).cpu().numpy()


def _to_tensor(arr_uint8):
    return torch.from_numpy(arr_uint8.astype(np.float32) / 255.0)


def _masks_to_np(masks, n, h, w):
    if masks is None:
        return None
    m = masks.cpu().numpy()
    out = []
    for i in range(n):
        f = m[min(i, m.shape[0] - 1)]
        if f.shape != (h, w):
            f = np.asarray(Image.fromarray((f * 255).astype(np.uint8)).resize((w, h),
                           Image.Resampling.NEAREST), dtype=np.float32) / 255.0
        out.append(f)
    return np.stack(out)


_STRUCT8 = np.ones((3, 3), dtype=np.int32)


def _corner_key(arr):
    """Median corner color across the batch. arr: (n,h,w,3) float32."""
    n, h, w, _ = arr.shape
    p = max(2, min(h, w) // 16)
    corners = np.concatenate([
        arr[:, :p, :p].reshape(-1, 3), arr[:, :p, -p:].reshape(-1, 3),
        arr[:, -p:, :p].reshape(-1, 3), arr[:, -p:, -p:].reshape(-1, 3)])
    return np.median(corners, axis=0)


def _border_keys(arr, max_keys=3, min_share=0.08, merge_dist=32.0):
    """Dominant border-ring colors across the batch (multi-color backdrops).

    'auto' used to sample the CORNERS only -- a backdrop that never reaches
    the corners was never keyed (run 20818cd458: white studio field = 69%
    of the frame + green letterbox bars; corners land in the bars, only
    the 11% green got keyed, the white field stayed opaque as 'content').
    Sample the full border ring, quantize to 16-step buckets, and return
    every color covering >= min_share of ring px (most frequent first,
    near-duplicate buckets merged). Single-color screens return one key
    ~= the old corner median."""
    n, h, w, _ = arr.shape
    p = max(2, min(h, w) // 16)
    ring = np.concatenate([
        arr[:, :p, :].reshape(-1, 3), arr[:, -p:, :].reshape(-1, 3),
        arr[:, :, :p].reshape(-1, 3), arr[:, :, -p:].reshape(-1, 3)])
    q = (ring.astype(np.int32) // 16) * 16 + 8
    buckets, counts = np.unique(q, axis=0, return_counts=True)
    out = []
    for idx in np.argsort(-counts):
        if counts[idx] < min_share * counts.sum():
            break
        sel = np.all(q == buckets[idx], axis=1)
        med = np.median(ring[sel], axis=0).astype(np.float32)
        if any(float(np.sqrt(((med - k) ** 2).sum())) < merge_dist
               for k in out):
            continue
        out.append(med)
        if len(out) >= max_keys:
            break
    return out


def _key_candidates(frame_rgb, key_rgb, tolerance, shadow_tolerance,
                    lab=None):
    """Lab-space backdrop candidate mask.

    A pixel is a background candidate when its chroma (a,b) is close to the
    key color and its luminance isn't far ABOVE the key — but it may be much
    DARKER (shadow_tolerance): shadows a video model paints on a green screen
    keep the screen's hue and only drop L."""
    if lab is None:
        lab = _rgb_to_lab(frame_rgb.reshape(-1, 3)).reshape(frame_rgb.shape)
    key_lab = _rgb_to_lab(key_rgb.reshape(1, 3))[0]

    dL = lab[..., 0] - key_lab[0]
    l_up = 25.0 + tolerance * 40.0      # backdrop may be brighter (gradients)
    l_down = (10.0 + tolerance * 160.0) * shadow_tolerance  # and much darker (shadows)
    key_chroma = float(np.sqrt((key_lab[1:] ** 2).sum()))
    if key_chroma >= 25.0:
        # saturated key (green/blue screen): hue angle is the shadow-invariant
        cand_hue = np.degrees(np.arctan2(lab[..., 2], lab[..., 1]))
        key_hue = float(np.degrees(np.arctan2(key_lab[2], key_lab[1])))
        dhue = np.abs((cand_hue - key_hue + 180.0) % 360.0 - 180.0)
        hue_tol = 12.0 + tolerance * 48.0
        # SHADOW HUE DRIFT: deep shadow on a chroma screen drifts in hue as it
        # darkens (measured on H3 green-screen foot shadows: dhue 22 at dL -36,
        # while the flat backdrop holds dhue < 10). Widen the hue gate with
        # darkness so shadowed backdrop stays a candidate; the chroma floor
        # below still protects near-gray costume pieces.
        dark = np.clip(-dL / 40.0, 0.0, 1.0)
        hue_tol = hue_tol * (1.0 + dark)
        # CHROMA FLOOR: near-gray pixels (white/gray suit, skin highlights)
        # have an UNSTABLE hue angle that can land on the key's hue by
        # accident — without a floor they get keyed and the subject 'eats
        # itself'. Real backdrop (even shadowed) keeps real chroma.
        cand_chroma = np.sqrt((lab[..., 1:] ** 2).sum(-1))
        chroma_floor = max(12.0, 0.2 * key_chroma)
        cand = (dhue < hue_tol) & (dL < l_up) & (dL > -l_down) & \
               (cand_chroma >= chroma_floor)
    else:
        # near-gray key: hue is unstable, fall back to chromatic distance
        dab2 = (lab[..., 1] - key_lab[1]) ** 2 + (lab[..., 2] - key_lab[2]) ** 2
        chroma_tol2 = (12.0 + tolerance * 120.0) ** 2
        cand = (dab2 < chroma_tol2) & (dL < l_up) & (dL > -l_down)
    return cand


def _candidates_multi(frame_rgb, keys, tolerance, shadow_tolerance,
                      lab=None):
    """Union of backdrop candidates over several key colors (one shared
    Lab conversion per frame)."""
    if lab is None:
        lab = _rgb_to_lab(frame_rgb.reshape(-1, 3)).reshape(frame_rgb.shape)
    cand = np.zeros(frame_rgb.shape[:2], dtype=bool)
    for k in keys:
        cand |= _key_candidates(frame_rgb, k, tolerance, shadow_tolerance,
                                lab=lab)
    return cand


def _border_connected(cand):
    """Keep only candidate components touching the frame border."""
    lbl, _n = ndimage.label(cand, structure=_STRUCT8)
    border = np.unique(np.concatenate([lbl[0, :], lbl[-1, :], lbl[:, 0], lbl[:, -1]]))
    border = border[border != 0]
    if border.size == 0:
        return np.zeros(lbl.shape, dtype=bool)
    return np.isin(lbl, border)


def _flood_bg(frame_rgb, key_rgb, tolerance, shadow_tolerance):
    """Border-connected background removal in Lab space. Candidates are kept
    only if their connected component touches the frame border, so a
    character wearing green is safe unless it merges with the backdrop."""
    return _border_connected(_key_candidates(frame_rgb, key_rgb, tolerance,
                                             shadow_tolerance))


def _rescue_subject(frame_rgb, bg, key_rgb, tolerance, shadow_tolerance,
                    eat_fraction=0.85, min_subject_fraction=0.02,
                    interior_tolerance=0.5, interior_max_area=0,
                    lab=None):
    """Undo catastrophic subject-eating floods (white-suit-on-white-backdrop).

    Trigger: the flood keyed nearly the WHOLE frame AND almost no subject
    survived. The subject-fraction gate matters: a small sprite on a big
    clean backdrop legitimately keys 90%+ of the frame, and firing the
    rescue then RE-ADDS real background trapped inside the subject hull
    (green between the legs/arms). Only when the surviving subject is
    implausibly small (< min_subject_fraction) is the flood catastrophic.

    Color tightening can't help (the pixels are genuinely the same color),
    but the subject's dark OUTLINE survives even strict matching. Rebuild
    from it: strict candidates -> largest interior non-candidate component ->
    close small outline gaps -> fill enclosed holes -> un-key everything
    inside that hull — then re-run the enclosed-gap pass on the rescued
    region so backdrop holes inside the hull stay keyed."""
    if bg.mean() < eat_fraction:
        return bg
    if (1.0 - bg.mean()) >= min_subject_fraction:
        # a real subject survived the flood; nothing catastrophic happened
        return bg
    strict = _key_candidates(frame_rgb, key_rgb, tolerance * 0.4,
                             shadow_tolerance, lab=lab)
    interior = ~_border_connected(strict)
    lbl, nl = ndimage.label(interior, structure=_STRUCT8)
    if nl <= 0:
        return bg
    sizes = ndimage.sum_labels(interior, lbl, range(1, nl + 1))
    biggest = lbl == (1 + int(np.argmax(sizes)))
    hull = ndimage.binary_fill_holes(
        ndimage.binary_closing(biggest, structure=_STRUCT8, iterations=2))
    rescued = int((bg & hull).sum())
    if rescued == 0:
        return bg
    print("[PixelForgeChromaKey] subject rescue: flood left only %.1f%% "
          "subject — restored %d px inside the subject outline"
          % (100.0 * (1.0 - bg.mean()), rescued))
    out = bg & ~hull
    # the hull blindly covers enclosed backdrop gaps (between limbs) — re-key
    # them with the interior-gap pass so a rescued subject keeps its holes
    return _interior_gaps(frame_rgb, key_rgb, out, tolerance,
                          shadow_tolerance, interior_tolerance,
                          interior_max_area, lab=lab)


def _interior_gaps(frame_rgb, key_rgb, bg, tolerance, shadow_tolerance,
                   interior_tolerance=0.5, interior_max_area=0, lab=None):
    """Enclosed interior regions tightly matching the backdrop -> add to bg.

    Fixes backdrop residue trapped INSIDE the silhouette (arm/pole/leg gaps)
    that a pure border flood can never reach. Safety: an enclosed candidate
    component is only keyed when >=60% of its pixels also match at the
    TIGHTER interior_tolerance, so a same-hue costume piece rendered in a
    different shade than the flat backdrop survives.

    interior_max_area (px, 0 = unlimited): only key enclosed components up
    to this size. Real gaps between limbs are SMALL; a same-colored costume
    region (white chest plate on a white backdrop) is LARGE.
    """
    cand = _key_candidates(frame_rgb, key_rgb, tolerance, shadow_tolerance,
                           lab=lab)
    tight = _key_candidates(frame_rgb, key_rgb,
                            tolerance * interior_tolerance, shadow_tolerance,
                            lab=lab)
    lbl, nl = ndimage.label(cand, structure=_STRUCT8)
    if nl <= 0:
        return bg
    keyed_ids = set(np.unique(lbl[bg]))
    keyed_ids.discard(0)
    add = np.zeros_like(bg)
    for cid in range(1, nl + 1):
        if cid in keyed_ids:
            continue
        comp = lbl == cid
        size = int(comp.sum())
        # no minimum size: 1-3px specks are exactly the visible green
        # residue; the tight-match rule below is the real safety
        if interior_max_area > 0 and size > interior_max_area:
            continue
        if float((tight & comp).sum()) / size >= 0.6:
            add |= comp
    return bg | add


def _key_bg(frame_rgb, key_rgb, tolerance, shadow_tolerance,
            key_interior=True, interior_tolerance=0.5, interior_max_area=0,
            keys=None, lab=None):
    """Full background mask: border-connected flood PLUS enclosed interior
    regions (see _interior_gaps). keys: optional list of backdrop colors
    (multi-color auto backdrop) -- the flood unions their candidates;
    interior gaps still reference the dominant key_rgb."""
    if keys is not None:
        cand = _candidates_multi(frame_rgb, keys, tolerance,
                                 shadow_tolerance, lab=lab)
    else:
        cand = _key_candidates(frame_rgb, key_rgb, tolerance,
                               shadow_tolerance, lab=lab)
    bg = _border_connected(cand)
    if not key_interior:
        return bg
    return _interior_gaps(frame_rgb, key_rgb, bg, tolerance, shadow_tolerance,
                          interior_tolerance, interior_max_area, lab=lab)


class PixelForgeChromaKey:
    """Remove the background of sprite frames -> alpha MASK.
    method=flood: border-connected removal in Lab space, tolerant of the
    shadows/gradients H3 paints on the backdrop. method=key: legacy global
    color distance."""

    CATEGORY = "PixelForge/sprite"
    FUNCTION = "run"
    RETURN_TYPES = ("IMAGE", "MASK")
    RETURN_NAMES = ("images", "alpha")
    DESCRIPTION = "Flood-key the background of pixel frames from the borders in (shadow-tolerant Lab space) plus enclosed interior gaps (arm/pole holes). 'auto' samples the full border ring and keys every dominant border color (multi-color backdrops). Hard 1-bit alpha (correct for pixel art); matte_erode strips the blended halo ring, despill decontaminates the edge color."
    LAST_AUTO_KEYS = None  # self-report: detected auto border keys

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "key_color": ("STRING", {"default": "auto",
                                         "tooltip": "Hex like #00FF00, or 'auto' to sample frame corners."}),
                "tolerance": ("FLOAT", {"default": 0.25, "min": 0.0, "max": 1.0, "step": 0.01}),
                "softness": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 0.5, "step": 0.01,
                                       "tooltip": "Edge feather. 0 = hard 1-bit alpha (correct for pixel art)."}),
                "despill": ("BOOLEAN", {"default": True}),
                # --- v2 widgets appended (positional compat) ---
                "method": (["flood", "key"],
                           {"tooltip": "flood = border-connected Lab removal, shadow-tolerant (best for H3). "
                                       "key = legacy global color distance."}),
                "shadow_tolerance": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 3.0, "step": 0.1,
                                               "tooltip": "flood only: how much darker than the key color the backdrop may be "
                                                          "(painted shadows on the green screen). 1 = normal."}),
                # --- v3 widgets appended (positional compat) ---
                "key_interior": ("BOOLEAN", {"default": True,
                                             "tooltip": "Also key ENCLOSED regions trapped inside the silhouette "
                                                        "(arm/pole gaps) when their pixels tightly match the backdrop. "
                                                        "Turn off if a same-colored part of the character gets keyed out."}),
                "interior_tolerance": ("FLOAT", {"default": 0.5, "min": 0.05, "max": 1.0, "step": 0.05,
                                                 "tooltip": "Interior regions must match the backdrop at this fraction of the "
                                                            "main tolerance (tighter = safer for same-hue clothing)."}),
                "matte_erode": ("INT", {"default": 1, "min": 0, "max": 8,
                                        "tooltip": "Erode the matte inward by N px to strip the blended halo ring. "
                                                   "0 = off. 1 is right for most H3 output."}),
                # --- v4 widget appended (positional compat) ---
                "subject_rescue": ("BOOLEAN", {"default": True,
                                               "tooltip": "If the flood keys nearly the whole frame (subject matches "
                                                          "the backdrop, e.g. white suit on white bg), rebuild the "
                                                          "subject from its surviving outline and un-key its interior."}),
                # --- v5 widget appended (positional compat) ---
                "interior_max_area": ("FLOAT", {"default": 2.0, "min": 0.0, "max": 25.0, "step": 0.1,
                                                "tooltip": "Max size of an ENCLOSED region the interior pass may key, "
                                                           "as % of frame area. 2% covers leg/arm gaps; a same-colored "
                                                           "costume region is bigger and survives. 0 = unlimited (old behavior)."}),
                # --- v6 widget appended (positional compat) ---
                "temporal_alpha": ("BOOLEAN", {"default": True,
                                               "tooltip": "Median-of-3 (previous/current/next) vote on the matte per "
                                                          "pixel. Pins the silhouette edge so it can't crawl frame to "
                                                          "frame; preserves consistently-moving edges. Anti-flicker."}),
                # --- v7 widget appended (positional compat) ---
                "drop_detached": ("FLOAT", {"default": 5.0, "min": 0.0, "max": 100.0, "step": 0.5,
                                            "tooltip": "Drop opaque components DETACHED from the main subject when "
                                                       "smaller than this % of the largest component (painted ground "
                                                       "shadows, floating debris the key can't match). 0 = off. "
                                                       "The largest component is always kept. Limb rescue: a small "
                                                       "detached component whose color is well-represented in the "
                                                       "main subject (an amputated boot/hand) is kept, not dropped."}),
            },
        }

    def run(self, images, key_color, tolerance, softness, despill,
            method="flood", shadow_tolerance=1.0, key_interior=True,
            interior_tolerance=0.5, matte_erode=1, subject_rescue=True,
            interior_max_area=2.0, temporal_alpha=True, drop_detached=5.0):
        arr = _to_np(images).astype(np.float32)
        n, h, w, _ = arr.shape

        if key_color.strip().lower() == "auto":
            keys = _border_keys(arr)
            if not keys:
                keys = [_corner_key(arr)]
            PixelForgeChromaKey.LAST_AUTO_KEYS = [
                "#%02X%02X%02X" % tuple(int(round(float(c))) for c in k)
                for k in keys]
            if len(keys) > 1:
                print("[PixelForgeChromaKey] auto backdrop: %d border "
                      "colors keyed (%s)"
                      % (len(keys), ", ".join(
                          PixelForgeChromaKey.LAST_AUTO_KEYS)))
        else:
            keys = [np.array(hex_to_rgb(key_color.strip()),
                             dtype=np.float32)]
            PixelForgeChromaKey.LAST_AUTO_KEYS = None
        key = keys[0]  # dominant key: interior-gap/rescue reference

        max_area_px = (interior_max_area / 100.0) * h * w
        if method == "flood":
            # 1) full per-frame keying (flood + interior gaps + rescue)
            fulls = []
            for i in range(n):
                lab_i = _rgb_to_lab(
                    arr[i].reshape(-1, 3)).reshape(arr[i].shape)
                bg = _key_bg(arr[i], key, tolerance, shadow_tolerance,
                             key_interior, interior_tolerance, max_area_px,
                             keys=keys, lab=lab_i)
                if subject_rescue:
                    bg = _rescue_subject(arr[i], bg, key, tolerance,
                                         shadow_tolerance,
                                         interior_tolerance=interior_tolerance,
                                         interior_max_area=max_area_px,
                                         lab=lab_i)
                fulls.append(bg)
            # 2) temporal majority — but only WEAK keyed pixels follow the
            #    vote (blended silhouette edge = the crawl). Anything this
            #    frame keys with TIGHT color evidence stays keyed no matter
            #    what the neighbors say, so real gaps can't be resurrected.
            if temporal_alpha and n >= 3:
                sm = np.stack(fulls).astype(np.uint8)
                acc = np.zeros_like(sm)
                acc[1:-1] = sm[:-2] + sm[1:-1] + sm[2:]
                acc[0] = sm[0] + sm[1]
                acc[-1] = sm[-2] + sm[-1]
                voted = acc >= 2
                for i in range(n):
                    lab_i = _rgb_to_lab(
                        arr[i].reshape(-1, 3)).reshape(arr[i].shape)
                    tight = _candidates_multi(arr[i], keys,
                                              tolerance * interior_tolerance,
                                              shadow_tolerance, lab=lab_i)
                    # SYMMETRIC GUARD: the vote may only govern WEAK px
                    # (the blended silhouette edge = the crawl). A px that
                    # is strongly NOT backdrop this frame — fails the
                    # candidate test even at 2x tolerance (navy boots, white
                    # suit) — can not be voted transparent. H3 paints green
                    # spill onto boots/gloves in some frames; without this
                    # guard the vote spreads that keying into the clean
                    # frames (the 'occlusion chunk' eater, measured 2026-08-14:
                    # 193k subject-colored px keyed with the unguarded vote
                    # vs 59k with the vote off, Gentle key, H3_00600).
                    strong_fg = ~_candidates_multi(
                        arr[i], keys, min(1.0, tolerance * 2.0),
                        shadow_tolerance, lab=lab_i)
                    fulls[i] = (voted[i] & ~strong_fg) | \
                               (fulls[i] & (tight | strong_fg))
            alpha = np.empty((n, h, w), dtype=np.float32)
            dropped_total = 0
            rescued_total = 0
            for i in range(n):
                a = ~fulls[i]
                if matte_erode > 0 and a.any():
                    a = ndimage.binary_erosion(a, iterations=matte_erode)
                if drop_detached > 0.0 and a.any():
                    lbl, nl = ndimage.label(a, structure=_STRUCT8)
                    if nl > 1:
                        sizes = np.asarray(ndimage.sum_labels(
                            a, lbl, range(1, nl + 1)))
                        main_id = 1 + int(np.argmax(sizes))
                        largest = float(sizes[main_id - 1])
                        main_lab = _rgb_to_lab(arr[i][lbl == main_id])
                        near_main = ndimage.binary_dilation(
                            lbl == main_id, structure=_STRUCT8, iterations=2)
                        keep = np.zeros(nl + 1, dtype=bool)
                        keep[0] = False
                        rescued = 0
                        for k in range(nl):
                            if sizes[k] >= largest * drop_detached / 100.0:
                                keep[k + 1] = True
                                continue
                            # LIMB RESCUE: an amputated extremity (a boot
                            # severed by a 1-2px keyed ankle bridge) shares
                            # its color with the rest of the subject (same
                            # navy as the gloves/helmet); painted ground
                            # shadows and debris do not. Rescue a detached
                            # comp whose median color is well-represented
                            # inside the main component.
                            comp = lbl == (k + 1)
                            # ADJACENCY GATE: rescue only comps still
                            # touching the subject (a boot severed by a
                            # 1-2px keyed ankle bridge). An island split
                            # off by keyed backdrop -- the painted ground
                            # shadow on a light field, motion smear -- is
                            # debris, not a limb (run 20818cd458: 94k
                            # black shadow px 'rescued' batch-wide =
                            # full-frame crop boxes).
                            if not (comp & near_main).any():
                                continue
                            med = np.median(arr[i][comp], axis=0)
                            med_lab = _rgb_to_lab(med.reshape(1, 3))[0]
                            d = np.sqrt(((main_lab - med_lab) ** 2).sum(-1))
                            if int((d < 18.0).sum()) >= max(
                                    20, int(0.001 * main_lab.shape[0])):
                                keep[k + 1] = True
                                rescued += int(sizes[k])
                        drop = (lbl > 0) & ~keep[lbl]
                        if drop.any():
                            dropped_total += int(drop.sum())
                            a = a & ~drop
                        rescued_total += rescued
                af = a.astype(np.float32)
                if softness > 0.0:
                    af = np.clip(ndimage.gaussian_filter(af, sigma=softness * 8.0), 0, 1)
                alpha[i] = af
            if dropped_total:
                print("[PixelForgeChromaKey] drop_detached: removed %d "
                      "detached px across %d frames (min %.1f%% of main "
                      "subject)" % (dropped_total, n, drop_detached))
            if rescued_total:
                print("[PixelForgeChromaKey] limb rescue: kept %d detached "
                      "px whose color matches the main subject (amputated "
                      "extremities, not debris)" % rescued_total)
        else:
            dist = np.sqrt(((arr - key.reshape(1, 1, 1, 3)) ** 2).sum(-1)) / 255.0
            tol = tolerance
            soft = max(1e-4, softness)
            alpha = np.clip((dist - tol) / soft, 0.0, 1.0)

        if despill:
            for dkey in keys:
                dom = int(np.argmax(dkey))
                other = [c for c in range(3) if c != dom]
                edge = (alpha > 0.0) & (alpha < 1.0)
                key_chroma = float(dkey.max() - dkey.min())
                if key_chroma >= 60.0:
                    # saturated backdrop: also despill the HARD edge ring --
                    # with a 1-bit alpha the blended halo pixels are fully
                    # opaque, so the soft-edge-only despill never touched
                    # them (the green fringe).
                    fg = alpha > 0.5
                    ring = fg & ~ndimage.binary_erosion(fg)
                    edge = edge | ring
                lim = arr[..., other].max(-1)
                spill = edge & (arr[..., dom] > lim)
                arr[..., dom] = np.where(spill, lim, arr[..., dom])

        rgb = torch.from_numpy(arr.astype(np.float32) / 255.0)
        return (rgb, torch.from_numpy(alpha.astype(np.float32)))


class PixelForgeAutoCrop:
    """Crop frames to sprite content and anchor them on a uniform canvas."""

    CATEGORY = "PixelForge/sprite"
    FUNCTION = "run"
    RETURN_TYPES = ("IMAGE", "MASK", "STRING")
    RETURN_NAMES = ("images", "alpha", "crop_info")
    DESCRIPTION = "Bounding-box crop all frames (union or per-frame), re-anchor to a shared canvas so the sprite doesn't jitter."

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "bbox_mode": (["union", "per_frame"],),
                "anchor": (["bottom_center", "center", "top_left"],),
                "padding": ("INT", {"default": 2, "min": 0, "max": 256}),
                "size_multiple": ("INT", {"default": 8, "min": 1, "max": 128,
                                          "tooltip": "Round canvas size up to a multiple of this."}),
                "out_size": ("INT", {"default": 0, "min": 0, "max": 2048, "step": 8,
                                     "tooltip": "0 = keep cropped size. >0 = nearest-resize canvas to this square."}),
                # --- v2 widgets appended (positional compat) ---
                "canvas_mode": (["content", "fixed"],
                                {"tooltip": "content = canvas hugs the sprite (old behavior). fixed = exact "
                                            "canvas_width x canvas_height canvas with the sprite PLACED inside "
                                            "(how real sprite assets ship: 200x200 canvas, character centered)."}),
                "canvas_width": ("INT", {"default": 200, "min": 8, "max": 2048, "step": 8,
                                         "tooltip": "fixed mode: exact canvas width in art pixels."}),
                "canvas_height": ("INT", {"default": 200, "min": 8, "max": 2048, "step": 8,
                                          "tooltip": "fixed mode: exact canvas height in art pixels."}),
                "placement": (["center", "top_center", "bottom_center",
                               "left_center", "right_center",
                               "top_left", "top_right", "bottom_left", "bottom_right"],
                              {"tooltip": "fixed mode: where the sprite sits inside the canvas. "
                                          "If the sprite is bigger than the canvas it overflows "
                                          "symmetrically from this anchor."}),
                "offset_x": ("INT", {"default": 0, "min": -1024, "max": 1024,
                                     "tooltip": "fixed mode: nudge the sprite right (+) / left (-) in art pixels."}),
                "offset_y": ("INT", {"default": 0, "min": -1024, "max": 1024,
                                     "tooltip": "fixed mode: nudge the sprite down (+) / up (-) in art pixels."}),
            },
            "optional": {"alpha": ("MASK",)},
        }

    def _content_mask(self, rgb, alpha):
        if alpha is not None:
            return alpha > 0.5
        # fall back to difference from corner color
        p = max(2, min(rgb.shape[1], rgb.shape[2]) // 16)
        corners = np.concatenate([
            rgb[:, :p, :p].reshape(-1, 3), rgb[:, :p, -p:].reshape(-1, 3),
            rgb[:, -p:, :p].reshape(-1, 3), rgb[:, -p:, -p:].reshape(-1, 3)])
        bg = np.median(corners, axis=0)
        dist = np.abs(rgb.astype(np.float32) - bg.reshape(1, 1, 1, 3)).max(-1)
        return dist > 24

    def run(self, images, bbox_mode, anchor, padding, size_multiple, out_size,
            canvas_mode="content", canvas_width=200, canvas_height=200,
            placement="center", offset_x=0, offset_y=0, alpha=None):
        rgb = _to_np(images)
        n, h, w, _ = rgb.shape
        am = _masks_to_np(alpha, n, h, w)
        content = self._content_mask(rgb, am)

        def bbox_of(m):
            ys, xs = np.where(m)
            if len(xs) == 0:
                return (0, 0, w, h)
            return (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)

        if bbox_mode == "union":
            boxes = [bbox_of(content.max(0))]
        else:
            boxes = [bbox_of(content[i]) for i in range(n)]

        fixed = canvas_mode == "fixed" and canvas_width > 0 and canvas_height > 0
        if fixed:
            # exact artist canvas (e.g. 200x200) — no size_multiple rounding
            cw, ch = int(canvas_width), int(canvas_height)
        else:
            max_bw = max(b[2] - b[0] for b in boxes) + 2 * padding
            max_bh = max(b[3] - b[1] for b in boxes) + 2 * padding
            cw = int(math.ceil(max_bw / size_multiple) * size_multiple)
            ch = int(math.ceil(max_bh / size_multiple) * size_multiple)

        def _placed_origin(fw, fh):
            """fixed mode: 9-point placement + manual offset."""
            col = {"left": 0, "center": (cw - fw) // 2, "right": cw - fw}
            row = {"top": 0, "center": (ch - fh) // 2, "bottom": ch - fh}
            vert, _, horiz = placement.partition("_")
            if not horiz:          # bare "center"
                vert, horiz = "center", "center"
            elif vert in ("left", "right"):   # left_center / right_center
                vert, horiz = "center", vert
            return col[horiz] + offset_x, row[vert] + offset_y

        out_rgb = np.zeros((n, ch, cw, 3), dtype=np.uint8)
        out_a = np.zeros((n, ch, cw), dtype=np.float32)
        infos = []
        for i in range(n):
            x0, y0, x1, y1 = boxes[min(i, len(boxes) - 1)]
            x0 = max(0, x0 - padding); y0 = max(0, y0 - padding)
            x1 = min(w, x1 + padding); y1 = min(h, y1 + padding)
            crop = rgb[i, y0:y1, x0:x1]
            fh, fw = crop.shape[:2]
            if fixed:
                ox, oy = _placed_origin(fw, fh)
            elif anchor == "bottom_center":
                ox, oy = (cw - fw) // 2, ch - fh
            elif anchor == "center":
                ox, oy = (cw - fw) // 2, (ch - fh) // 2
            else:
                ox, oy = 0, 0
            # clip-aware paste: sprite may overflow the canvas in fixed mode
            sx0, sy0 = max(0, -ox), max(0, -oy)
            dx0, dy0 = max(0, ox), max(0, oy)
            pw = min(fw - sx0, cw - dx0)
            ph = min(fh - sy0, ch - dy0)
            if pw > 0 and ph > 0:
                out_rgb[i, dy0:dy0 + ph, dx0:dx0 + pw] = crop[sy0:sy0 + ph, sx0:sx0 + pw]
                if am is not None:
                    out_a[i, dy0:dy0 + ph, dx0:dx0 + pw] = am[i, y0 + sy0:y0 + sy0 + ph,
                                                              x0 + sx0:x0 + sx0 + pw]
                else:
                    out_a[i, dy0:dy0 + ph, dx0:dx0 + pw] = \
                        content[i, y0 + sy0:y0 + sy0 + ph,
                                x0 + sx0:x0 + sx0 + pw].astype(np.float32)
            infos.append([x0, y0, x1, y1, ox, oy])

        if out_size > 0:
            new_rgb = np.zeros((n, out_size, out_size, 3), dtype=np.uint8)
            new_a = np.zeros((n, out_size, out_size), dtype=np.float32)
            for i in range(n):
                new_rgb[i] = np.asarray(Image.fromarray(out_rgb[i]).resize(
                    (out_size, out_size), Image.Resampling.NEAREST))
                new_a[i] = np.asarray(Image.fromarray(
                    (out_a[i] * 255).astype(np.uint8)).resize(
                    (out_size, out_size), Image.Resampling.NEAREST), dtype=np.float32) / 255.0
            out_rgb, out_a = new_rgb, new_a
            ch = cw = out_size

        info = json.dumps({"canvas": [cw, ch], "canvas_mode": canvas_mode,
                           "placement": placement if fixed else anchor,
                           "boxes": infos, "frames": n})
        return (_to_tensor(out_rgb), torch.from_numpy(out_a), info)


class PixelForgeLoopTrim:
    """Make the animation loop: auto-find the best loop point or build a ping-pong loop."""

    CATEGORY = "PixelForge/sprite"
    FUNCTION = "run"
    RETURN_TYPES = ("IMAGE", "MASK", "STRING")
    RETURN_NAMES = ("images", "alpha", "report")
    DESCRIPTION = "auto: scan the tail for the frame closest to frame 0 and cut there. pingpong: append reversed frames for a seamless loop."

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "mode": (["auto", "pingpong", "off"],),
                "max_loop_error": ("FLOAT", {"default": 0.06, "min": 0.0, "max": 1.0, "step": 0.01,
                                             "tooltip": "Mean abs diff (0-1) allowed between last kept frame and frame 0 in auto mode."}),
                "search_tail_fraction": ("FLOAT", {"default": 0.5, "min": 0.1, "max": 0.9, "step": 0.05}),
            },
            "optional": {"alpha": ("MASK",)},
        }

    def run(self, images, mode, max_loop_error, search_tail_fraction, alpha=None):
        n = images.shape[0]
        report = {"mode": mode, "input_frames": int(n)}

        def _frame_err(a_img, b_img, a_m, b_m):
            """Visible-frame diff. With mattes wired, the mean is taken over
            the UNION of opaque px only (pre-multiplied RGB + matte term), so
            the measure is canvas-size invariant: a small sprite on a big
            fixed artist canvas no longer dilutes the error to ~0."""
            if a_m is None:
                return float((a_img.float() - b_img.float()).abs().mean())
            au = (a_m > 0.5) | (b_m > 0.5)
            if not bool(au.any()):
                return 0.0
            af = a_m.float()[..., None]
            bf = b_m.float()[..., None]
            d_rgb = (a_img.float() * af - b_img.float() * bf).abs().mean(-1)
            d_a = (a_m.float() - b_m.float()).abs()
            return float((d_rgb + d_a)[au].mean() * 0.5)

        if mode == "off" or n < 3:
            report["note"] = "untouched"
            return (images, alpha if alpha is not None else torch.ones(n, images.shape[1], images.shape[2]), json.dumps(report))

        if mode == "pingpong":
            mid = images[-2:0:-1]
            out = torch.cat([images, mid], 0)
            out_a = None
            if alpha is not None:
                out_a = torch.cat([alpha, alpha[-2:0:-1]], 0)
            report.update({"output_frames": int(out.shape[0]), "loop": "pingpong"})
            return (out, out_a if out_a is not None else torch.ones(out.shape[0], out.shape[1], out.shape[2]), json.dumps(report))

        ref = images[:1].float()
        ref_a = alpha[:1] if alpha is not None else None
        start = max(1, int(n * (1.0 - search_tail_fraction)))
        errs = [_frame_err(images[k:k + 1], ref,
                           alpha[k:k + 1] if alpha is not None else None,
                           ref_a) for k in range(start, n)]
        best_k = int(np.argmin(errs)) + start
        best_err = errs[best_k - start]
        if best_err <= max_loop_error:
            out = images[:best_k]
            out_a = alpha[:best_k] if alpha is not None else None
            report.update({"loop_frame": best_k, "loop_error": round(best_err, 4),
                           "output_frames": int(out.shape[0])})
        else:
            out, out_a = images, alpha
            report.update({"note": "no loop point under threshold; kept all frames",
                           "best_candidate": best_k, "best_error": round(best_err, 4)})
        if out_a is None:
            out_a = torch.ones(out.shape[0], out.shape[1], out.shape[2])
        return (out, out_a, json.dumps(report))


class PixelForgeFrameDedup:
    """Drop consecutive near-duplicate frames and emit per-frame durations."""

    CATEGORY = "PixelForge/sprite"
    FUNCTION = "run"
    RETURN_TYPES = ("IMAGE", "MASK", "STRING")
    RETURN_NAMES = ("images", "alpha", "durations_json")
    DESCRIPTION = "Merge consecutive look-alike frames; durations_json holds how many source frames each kept frame represents."

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "threshold": ("FLOAT", {"default": 0.01, "min": 0.0, "max": 1.0, "step": 0.005,
                                        "tooltip": "Mean abs diff (0-1) below which two consecutive frames count as identical."}),
            },
            "optional": {"alpha": ("MASK",)},
        }

    def run(self, images, threshold, alpha=None):
        n = images.shape[0]
        keep = [0]
        durations = []
        for i in range(1, n):
            j = keep[-1]
            if alpha is None:
                d = float((images[i:i + 1].float() - images[j:j + 1].float()).abs().mean())
            else:
                # canvas-size invariant: mean over the union of opaque px,
                # premultiplied RGB + matte term (same metric as LoopTrim)
                au = (alpha[i] > 0.5) | (alpha[j] > 0.5)
                if not bool(au.any()):
                    d = 0.0
                else:
                    ai = alpha[i].float()[..., None]
                    aj = alpha[j].float()[..., None]
                    d_rgb = (images[i].float() * ai - images[j].float() * aj).abs().mean(-1)
                    d_a = (alpha[i].float() - alpha[j].float()).abs()
                    d = float((d_rgb + d_a)[au].mean() * 0.5)
            if d > threshold:
                durations.append(i - keep[-1])
                keep.append(i)
        durations.append(n - keep[-1])
        idx = torch.tensor(keep, dtype=torch.long)
        out = images[idx]
        out_a = alpha[idx] if alpha is not None else torch.ones(out.shape[0], out.shape[1], out.shape[2])
        return (out, out_a, json.dumps({"durations_frames": durations,
                                        "kept": len(keep), "dropped": n - len(keep)}))


class PixelForgeSheetPack:
    """Pack frames into a uniform-grid sprite sheet + Aseprite-compatible JSON."""

    CATEGORY = "PixelForge/sprite"
    FUNCTION = "run"
    RETURN_TYPES = ("IMAGE", "MASK", "STRING")
    RETURN_NAMES = ("sheet", "sheet_alpha", "sheet_json")
    DESCRIPTION = "Lay frames out on a grid. sheet_json is Aseprite's JSON-Hash format (with durations when durations_json is wired in)."

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "columns": ("INT", {"default": 0, "min": 0, "max": 64,
                                    "tooltip": "0 = pick a near-square grid automatically."}),
                "padding": ("INT", {"default": 0, "min": 0, "max": 64}),
                "bg_color": ("STRING", {"default": "#000000",
                                        "tooltip": "RGB preview fill behind transparent areas."}),
                "fps_for_durations": ("FLOAT", {"default": 12.0, "min": 1.0, "max": 60.0}),
            },
            "optional": {
                "alpha": ("MASK",),
                "durations_json": ("STRING", {"forceInput": True}),
            },
        }

    def run(self, images, columns, padding, bg_color, fps_for_durations,
            alpha=None, durations_json=None):
        rgb = _to_np(images)
        n, h, w, _ = rgb.shape
        am = _masks_to_np(alpha, n, h, w)

        cols = columns if columns > 0 else int(math.ceil(math.sqrt(n)))
        rows = int(math.ceil(n / cols))
        cw, chh = w + padding, h + padding
        sw, sh = cols * cw + padding, rows * chh + padding

        bg = np.array(hex_to_rgb(bg_color.strip() or "#000000"), dtype=np.uint8)
        sheet = np.zeros((sh, sw, 3), dtype=np.uint8)
        sheet[:] = bg.reshape(1, 1, 3)
        sheet_a = np.zeros((sh, sw), dtype=np.float32)

        durations = None
        if durations_json:
            try:
                durations = json.loads(durations_json).get("durations_frames")
            except Exception:
                durations = None

        frames_meta = {}
        for i in range(n):
            r, c = divmod(i, cols)
            x = padding + c * cw
            y = padding + r * chh
            sheet[y:y + h, x:x + w] = rgb[i]
            if am is not None:
                sheet_a[y:y + h, x:x + w] = am[i]
            else:
                sheet_a[y:y + h, x:x + w] = 1.0
            entry = {"frame": {"x": x, "y": y, "w": w, "h": h},
                     "rotated": False, "trimmed": False,
                     "spriteSourceSize": {"x": 0, "y": 0, "w": w, "h": h},
                     "sourceSize": {"w": w, "h": h}}
            if durations:
                ms = int(round(1000.0 * durations[min(i, len(durations) - 1)] / fps_for_durations))
                entry["duration"] = max(1, ms)
            frames_meta["frame_%03d" % i] = entry

        # composite preview over bg
        comp = sheet.astype(np.float32) * sheet_a[..., None] + \
            bg.astype(np.float32).reshape(1, 1, 3) * (1.0 - sheet_a[..., None])
        sheet_t = torch.from_numpy((comp / 255.0).astype(np.float32)).unsqueeze(0)

        meta = {"frames": frames_meta,
                "meta": {"app": "ComfyUI-PixelForge-H3", "version": "1.0",
                         "image": "sheet.png", "format": "RGBA8888",
                         "size": {"w": sw, "h": sh},
                         "scale": "1",
                         "frameTags": [{"name": "all", "from": 0, "to": n - 1,
                                        "direction": "forward"}]}}
        return (sheet_t, torch.from_numpy(sheet_a).unsqueeze(0), json.dumps(meta))
