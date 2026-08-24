# VERSION: v3.10.8-fracgrid (2026-08-19) -- pixel PLACEMENT fix: H3 renders the drawn pixel grid at a FRACTIONAL pitch when imitating a ref's cell count (live run 4788d88fa5: 704px gen, ref 820x721 @ 10px blocks = 82 cells -> true pitch 704/82 = 8.585; integer s=9 detection drifted ~0.46px/cell = art pixels one cell off near the edges; within-cell std 3.81 vs 0.74, edge recall 0.51 vs 0.995). GridRecover auto now refines to the fractional lattice (energy-weighted edge recall, both-axes gate >= 0.60 and >= 1.35x the integer recall; per-frame phase measured as noise -> global lattice) and reduces with area-weighted masked trimmed means on the true cell windows. Integer path untouched when no fractional lattice is proven (control run 7acc0e3dc1: gate 1.22x < 1.35x). v3.10.8b: the never-live v3.10.8 raw-recall scan crowned a degenerate p=3.0 comb on live run 10fb29c43f (recall 1.000 on a gen with NO global lattice = 234x234 grid); candidates now score by EXCESS over chance coverage 2*tol/p (true lattice +0.67..+0.72, false fine combs +0.04..+0.40, no-lattice gen +0.34; gate >= 0.45 both axes) + the pf_grid frac sanity gate read the X offset from the Y tuple slot (fixed). v3.10.8c: the recall tol plateau placed cells with median err 11/13.8% off on ground-truth synthetic (detector is not a fitter) -- after the excess gates pass, pitch+phase are now FIT by minimizing alpha-weighted within-cell variance (Gauss-Seidel, bincount stats, cheap-gates-first so integer/no-lattice gens never pay). FINAL: the reduce is pixel-CENTER assigned with the integer path's median-anchored trimmed mean per cell -- the area-weighted mean from the never-live a-c iterations mixed 6-12% neighbor color into every cell (measured median err 9 on a perfect ground-truth frame; center-assigned: 0).
# VERSION: v3.10.7-snapalways (2026-08-19) -- owner 21:18: 'why is there still a million gradients in the output' on live run 29f130e30a (v23, no LoRA, fresh seed): the gen drifted far off-palette (0%% exact-ref px, median redmean 61-125 across frames) -> the v3.8.8 guard tripped -> look == grid passthrough (3,580 unique colors at f0, ZERO color consolidation). Preset now snaps ALWAYS when a ref is armed (guard trip downgraded to a loud WARN line); explicit adv_gn_ref_snap=on keeps the legacy guard-gated mode, off = never. Color mapping is deterministic per color, so always-snap stays temporally consistent across frames.
# PREV: v3.10.6-snapall (2026-08-19) -- measured on live run 01c8045328 (sasuke ref, 56f): v3.10.5's cap-45 kept 39%% of px as gen gradient mush (f0 379 unique colors / 60.7%% exact-ref; f30 1450 colors / 32.9%%) and the 25%%/min-4 rescue gate never fired on the eye glints (measured 11-17%% support = 4-6px in a 36px full-res window). (1) SNAP-ALL: when the run-level dual-read guard passes (gen matches the ref), EVERY opaque block snaps to the nearest ref color -- cap preset 45 -> 1e9 (adv_gn_snap_cap still takes an explicit cap for foreign-prop content). True 1:1 colors with the input. (2) RESCUE GATE: light-extreme support threshold 25%%/min-4 -> 10%%/min-3 -- recovers the eye glints and de-tints cyan-shaded white shirt cells (measured 8-39%% support on mush cells). Green sweep unchanged (0 green-dominant opaque px on all 56 keyed frames of 01c8045328).
# PREV: v3.10.5-refsnap (2026-08-19) -- gen-native default-settings 1:1 push, measured on live run 2293e1bd04 (sasuke ref). (1) REF SNAP: with a ref armed (wired custom_palette_image or OneForge's auto-fed drawn_ref_image), the flattened native blocks snap onto the ref's EXACT modal palette (redmean argmin, cap 45 so foreign props keep gen colors; the v3.8.8 dual-read guard skips the snap on a foreign gen) -- kills the block-median gradient mush (f0: 704 unique colors in 927 opaque px, 4.6% on a ref color, median dist 19.3 -> 13 exact ref colors). (2) EXTREME RESCUE: the block median eats 2-3px light details (the eye glint: 1574 near-white px at keyed res -> 32 at grid res); a light-extreme ref color with >=25% support in a block's full-res window now wins the block. (3) GREEN SWEEP: post-keying, strongly green-dominant opaque px (G>R+25 & G>B+25) are keyed out when the ref palette carries no green (or refless when the screen itself was green) -- kills the detached/shadow-drifted green residue the border flood + temporal vote miss (f28-32: 400-1200 px/frame). New tail widgets adv_gn_green_sweep / adv_gn_ref_snap / adv_gn_snap_cap (preset = on; pf_oneforge passes no new keys -> presets apply, old workflows unaffected).
# VERSION: v3.10.2-genartdensity (2026-08-19) -- gen-native mode now reduces the guard-kept Source grid to the ref ruler's pixel-art density (the v3.8.2 refdensity block geometry: block = char height px / ref char cells; masked majority-reduce straight from the full-res keyed frames) -- DENSITY ONLY: palette still quantized from the gen itself (Hi-bit), RefMatch still skipped. Owner verdict on live f4c6a9c0cf (gen-native kept the 176x176 native grid, char 63x137 cells): 'not 1:1 as its pixel art representation'. No ref wired -> keeps the guard-kept grid (unchanged). Legacy ref snap byte-path untouched (harness D: max|diff| 0 vs .bak_v3102). v3.10.1b-limbgate (limb rescue now gated to comps adjacent to the main subject -- painted ground shadows on keyed light fields were color-'rescued' = full-frame crops) + v3.10.1-autokey2 (2026-08-19) -- 'auto' chroma key samples the FULL BORDER RING and keys every dominant border color (was: corner median only -- run 20818cd458 white studio field 69% + green letterbox bars: corners landed in the bars, only green keyed, white field stayed opaque as 'content' = whole-frame crop, palette eaten by whites, limb-rescue kept 75,615 detached white px = 72.2s keying > 67.9s generate). One shared Lab per frame per pass; despill per key; report self-reports detected keys. v3.10.0 note: (2026-08-19) -- new tail widget adv_ref_look_mode (after adv_ref_backdrop): "Gen-native (1:1 with the H3 gen)" (DEFAULT) keeps the guard-kept Source grid and quantizes the palette from the gen itself via the Hi-bit/TruePixel engine -- refdensity's 1:1-with-ref halving (live 1bac01576b: size guard kept 176, refdensity forced 88, 99-100% ref palette, -67% edges vs the H3 source = "detailing way off from the H3 output") and RefMatch's ref-palette snap are SKIPPED. "Reference look (legacy ref snap)" = byte-identical pre-v3.10.0 behavior. pf_oneforge tail re-order (adv_ref_backdrop, adv_ref_look_mode) keeps v21 119-value workflows aligned (missing trailing value = default = Gen-native).
# VERSION: v3.9.0-guardquorum (2026-08-19) -- the pooled dual-read ref guard false-tripped on live 6b7e1105f3 (Sasuke + a giant lavender sleeping bag: pooled core 27.2% / median 95.7 > 75 -> silent Hi-bit fallback at the guard-kept 176x176 Source grid = "density way too high, colors in wrong areas"). Now ALSO a per-frame quorum: pass when the pooled read passes OR >= 1/3 of frames individually pass (measured on all 9 preserved runs: matching quorum 46-100%, foreign f62d944eee/0e9d79c09e 0%). Also (pf_oneforge): v3.9.0-turbosteps clamps steps >8 -> 4 when a turbo LoRA is armed (288.8s -> ~100s generate).
# VERSION: v3.8.8-guardcore+phases (2026-08-18) -- (1) the v3.8.7 median-only ref guard false-tripped on MATCHING gens with a big foreign prop (live e49f434bfa/0d79b30fd6: Sasuke + giant cake = median 62-63 > 60 -> silent Hi-bit fallback). Now dual-read: core-within-30 >= 27% AND median <= 75 (measured on all 7 preserved runs: matching core 32-43% / median 39-63, foreign core 1-23% / median 86-130). (2) phase self-report: every pipeline section emits pf_studio_phase + a console line, the node shows a live phase strip at its top, and section durations land in the forge report.
# VERSION: v3.7.9-truecolors (2026-08-18) — the "inner" outline was the black-crush/eaten-sprite bug: on a small art grid (78x77) the inner silhouette ring is ~9%% of the sprite; repainting it near-black ate thin limbs + read as holes (measured on real v9 run uid b77f508dce: outline ON mean|d| 58 vs grid, ~700 near-black px; OFF 25.8 / ~200, colors match the gen). Default outline now OFF (H3 already draws its own outline; adv_tp_outline can force it). Subject palette share 0.75 -> 1.0 (wired alpha = invisible backdrop; the 4 bg clusters were pure transparent-black bases that black-holed dark shading px).
# VERSION: v3.7.8-regionvote (2026-08-17) — TruePixel classifies base+band from a 3x3-median signal (per-px argmin on 95%-speckle grid-res input = deepfry), 2x 3x3 majority region vote on the final class map, thin dark lines + inner ring snapped to ONE global outline color (unbroken black outline, no navy patchwork), grid report prints block/offset, full-res source frame dump for forensics
# VERSION: v3.7.7-pixelpure (2026-08-17) — Hi-bit cel flatten 5.0->0.0 (bilateral at art-grid res blurred clean pixels into mixel mush, the non-Hi-bit looks already knew: "flatten at art-res eats outlines"), TruePixel inner outline preserves existing near-black px (was repainting hand-drawn black outlines with base-color shadow shades = navy outlines on blue hair)
# VERSION: v3.8.9-detailvote (2026-08-19) -- RefMatch region_vote OFF at ref density: the 3x3 majority vote was tuned for the 2x-density grid (v3.8.2 speckle problem); at the 1:1 ref-density grid it eats real features (measured on d9952bcdfd: -18.7% of the reduce's surviving edge px batch-wide, 31.5 -> 36.2 edges/100cells vs ref 59.1, +0.9% speckle cost). despeckle stays on. Also (pf_studio.js): the A/B button now splits H3-source vs forge composite in the layers path (st.imgs.source built from pf_debug_stages.source) and the STAGE panel shows final-stage meta instead of "no stage data".
# VERSION: v3.8.7-refguard (2026-08-18) -- (1) gen<->ref compatibility guard on the Reference look: median redmean distance of opaque grid px to the ref palette > 60 falls back to Hi-bit cel instead of force-snapping a foreign gen onto the ref palette (live f62d944eee: H3 drifted to a dark ninja on the Sasuke seed; olive->black, navy->royal blue, red armband->magenta; measured med 124 vs 23 for a matching gen). (2) refdensity block from the pose-STABLE axis (character height) - the mean of w/h ratios let backflip action frames inflate the block (live 8b3edef07b: width term 14.9 vs height 8.3 -> block 12 -> 58px grid -> character 45 cells vs the ref's 64 = the 'details lost / shading not 1:1' verdict).
# VERSION: v3.8.6-bandmatch (2026-08-18) -- RefMatch band boundaries from the ref's own band-usage proportions (pf_finalize); fixes the output landing systematically darker/dirtier than the ref (light skin 0.7% vs ref 2.3%, tan 4.9% vs 3.0% on live aaf19735ff). Batch-pooled quantiles = no flicker. Achromatic path untouched.
# VERSION: v3.8.5-shadeboundary (2026-08-18) -- adv_ref_backdrop preset flips ON -> TRANSPARENT (owner v14 verdict: 'its not keying the bg'; pre-refmatch sprites 00085-00095 were transparent, refmatch-era baked #F6F6F6 opaque). The flat ref-color bake stays available via adv_ref_backdrop=on. Also see pf_finalize v3.8.5: boundary-vs-interior near-black rule (v3.8.4's component-thickness rescue navy'd whole outline stroke networks).
# VERSION: v3.8.2-refdensity (2026-08-18) -- the Reference look now matches the ref sprite's character-relative block size: measured on run cc3e40f8d9 the default output was 4.06x the ref's cell count (62x137 vs 30x65 character cells), so per-cell palette classification of the soft gen speckled every shading gradient and doubled every line. The forge grid is now derived from the ref's own integer-grid geometry (block 6 -> 85x85 for the 512px Sasuke run = 1:1 chunk) via a masked majority-reduce straight from the full-res keyed frames. Source-anchored size presets only; fixed/custom sizes untouched.
# VERSION: v3.8.1 (2026-08-18) -- TWO root causes of the "wrong colors / lost detail / blobby" v11 verdict, both measured on live run 1123616ebe: (1) fringefix: the v3.7.6 fringe snap capped the green channel of the WHOLE batch (missing mask), darkening every bright saturated px one shade band before the look stage (proven pixel-exact: bug repro == live look temps, 0 diff, 56/56 frames); now masked to the dark-green px only. (2) blackguard (pf_finalize PixelForgeRefMatch): chromatic dark-navy shadow px redmean-argmin'd to pure black = shade regions voided into black blobs; black is now reserved for near-neutral/near-black px (max>=32 & chroma>=25 reassigned to nearest non-black ref color; black 22414 -> 15079 px/56f).
# VERSION: v3.8.0-refmatch (2026-08-18) -- new suite look "Reference (match ref sprite)": snaps the forged frames onto the armed ref sprite's EXACT palette (integer-grid modal reduce, no kmeans, no shade ramps) + optional flat ref-color backdrop (adv_ref_backdrop). Measured on run 429e8cc342: kmeans+ramp dropped the ref's rare colors (magenta d=164 off) and Dulled everything through derived ramps; direct snapping restores exact colors + the flat chunky read. OneForge auto-feeds the armed ref slot (drawn_ref_image) when the look is selected.
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

try:
    from server import PromptServer
except Exception:  # offline verify harness: no ComfyUI server module
    PromptServer = None

from .pf_palettes import PALETTE_NAMES
from .pf_pixelize import PixelForgeQuantize, _STYLE_PRESETS
from .pf_sprite import (PixelForgeAutoCrop, PixelForgeChromaKey,
                        PixelForgeFrameDedup, PixelForgeLoopTrim)
from .pf_grid import (PixelForgeGridRecover, _reduce_blocks,
                      _reduce_blocks_masked)
from .pf_temporal import PixelForgeTemporalStabilize
from .pf_finalize import PixelForgeTruePixel, PixelForgeRefMatch, _ref_palette

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

# Suite-only look (v3.8.0-refmatch): match the armed ref sprite's own palette
# + backdrop at forge time (see pf_finalize.PixelForgeRefMatch).
_REF_LOOK = "Reference (match ref sprite)"
# v3.10.0-gennative: adv_ref_look_mode choices (see VERSION note).
# v3.10.3-genraw: gen-native is a pure passthrough -- the keyed H3 gen
# 1:1 (native grid, gen colors, no quantize / re-grid / RefMatch).
_GEN_RAW = "Gen-native passthrough (1:1 keyed gen)"  # v3.10.4: now
# reached AFTER the native-grid flatten -- see the grid stage.
_REF_LOOK_MODE_GEN = "Gen-native (1:1 with the H3 gen)"
_REF_LOOK_MODE_LEGACY = "Reference look (legacy ref snap)"
_REF_LOOK_MODES = [_REF_LOOK_MODE_GEN, _REF_LOOK_MODE_LEGACY]
# v3.8.2: ref-density auto-sizing only for Source-anchored presets;
# an explicit fixed/custom size always wins.
_SRC_SIZE_MODES = ("Source (H3's own grid)", "Source / 2 (balanced)")
_SUITE_LOOKS = list(_LOOKS) + [_REF_LOOK]


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
                "look": (list(_SUITE_LOOKS), {"default": "Modern (smooth color)"}),
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
                "adv_ref_backdrop": (_TRI, {"default": "preset",
                                     "tooltip": "Reference look: fill the keyed backdrop with the ref's own dominant color (the source's simple flat backdrop) instead of leaving it transparent. preset = transparent (keyed bg, the pre-refmatch behavior); set on to bake the flat ref-color backdrop."}),
                "adv_ref_look_mode": (list(_REF_LOOK_MODES), {"default": _REF_LOOK_MODE_GEN,
                                     "tooltip": "Reference look mode. Gen-native (default): the keyed H3 gen as true pixel art at its own native block grid -- GridRecover detects the gen's native blocks, every block becomes one flat median color (kills the anti-alias mush = hard pixels), colors + content 1:1 the gen's, no palette quantize / density ruler / RefMatch; border-only keying (no interior hole punches). Reference look (legacy): the pre-v3.10.0 ref snap (refdensity grid + RefMatch palette snap)."}),
                "adv_gn_green_sweep": (_TRI, {"default": "preset",
                                     "tooltip": "Gen-native: after keying, key out leftover green-dominant px (bg residue the border flood misses on some frames). Safe: only runs when the ref palette has no green, or refless when the screen itself was green. preset = on."}),
                "adv_gn_ref_snap": (_TRI, {"default": "preset",
                                     "tooltip": "Gen-native: snap every block to the armed ref's EXACT palette (kills the block-median gradient mush = true 1:1 colors with the input) + rescue tiny light details the median eats (eye glints). preset = ALWAYS snap when a ref is armed (even on a drifted gen; guard trip = WARN only); on = guarded (a foreign gen keeps its own colors); off = never."}),
                "adv_gn_snap_cap": ("FLOAT", {"default": -1.0, "min": -1.0, "max": 200.0, "step": 1.0,
                                     "tooltip": "Gen-native ref snap: max redmean distance a px may travel to a ref color; farther px keep the gen color. -1 = preset (snap ALL, always, even on a drifted gen; type e.g. 45 to let foreign props keep gen colors). Rescued extreme details always snap."}),
            },
            "optional": {
                "alpha": ("MASK",),
                "custom_palette_image": ("IMAGE",),
            },
            "hidden": {"unique_id": "UNIQUE_ID"},
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
            adv_dedup_threshold, adv_ref_backdrop="preset",
            adv_ref_look_mode=_REF_LOOK_MODE_GEN,
            adv_gn_green_sweep="preset", adv_gn_ref_snap="preset",
            adv_gn_snap_cap=-1.0,
            alpha=None, custom_palette_image=None,
            target_layer="new layer", layer_name="",
            placement_x=0, placement_y=0,
            selection_w=0, selection_h=0, selection_x=0, selection_y=0,
            unique_id=None, phase_prefix=None):

        report = []
        uid = uuid.uuid4().hex[:10]
        stages, meta = {}, {}
        # v3.10.3-genraw: gen-native decided up front -- it changes the
        # keying profile, skips grid/size/look processing entirely.
        _gennative = (look == _REF_LOOK
                      and adv_ref_look_mode == _REF_LOOK_MODE_GEN)

        # v3.8.8: phase self-report -- every pipeline section announces
        # itself (console + pf_studio_phase event for the in-node top strip)
        # and section durations land in the forge report, so a slow phase is
        # visible live instead of after the fact.
        import time as _time
        _ph = {"cur": "", "t": _time.perf_counter()}
        _phase_log = list(phase_prefix) if phase_prefix else []

        def _mark(label):
            _now = _time.perf_counter()
            if _ph["cur"]:
                _phase_log.append(f"{_ph['cur']} {_now - _ph['t']:.1f}s")
            _ph["cur"], _ph["t"] = label, _now
            print(f"[PixelForge {uid}] phase: {label}"
                  + (f" (prev {_phase_log[-1]})" if _phase_log else ""))
            try:
                if PromptServer is not None and unique_id is not None:
                    PromptServer.instance.send_sync("pf_studio_phase", {
                        "node": str(unique_id), "phase": label,
                        "trail": list(_phase_log),
                        "reset": label == "source" and not phase_prefix})
            except Exception:
                pass

        def capture(tag, imgs, a, pixel_exact):
            refs, m = _save_stage(tag, uid, imgs, a, preview_max_frames,
                                  pixel_exact=pixel_exact)
            stages[tag] = refs
            meta[tag] = m

        # ---------------- stage: source ----------------
        _mark("source")
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
        _mark("keying")
        if alpha is None:
            key_color = custom_bg_hex if background == "custom hex" else _BACKGROUNDS[background]
            tol_p, shadow_p = _KEY_STRENGTH[key_strength]
            # v3.10.3-genraw: content-preserving keying. The interior-gap
            # pass + matte erode punched 1.3k hole px into the f12d26cffb
            # sprite (measured); gen-native keys the border-connected
            # backdrop ONLY (rescue/temporal/drop_detached stay).
            _ki = _tri(adv_key_interior, True) and not _gennative
            _ke = _pick(adv_key_erode, 1) if not _gennative else 0
            images, alpha = PixelForgeChromaKey().run(
                images, key_color,
                _pick(adv_key_tolerance, tol_p),
                _pick(adv_key_softness, 0.0),
                _tri(adv_key_despill, True),
                "flood" if adv_key_method == "preset" else adv_key_method,
                _pick(adv_key_shadow, shadow_p),
                _ki,
                _pick(adv_key_interior_tol, 0.5),
                _ke,
                _tri(adv_key_rescue, True),
                _pick(adv_key_interior_max_area, 2.0),
                _tri(adv_key_temporal_alpha, True),
                # v3.11.17: flying content IS the content in T2V -- the 5%-of-main rule + the 2px adjacency gate ate every far droplet (live 3a5b3d6e81: far-arc drops 0px in keyed); residue cleanup is the key sweep's job now
                (_pick(adv_key_drop_detached, 5.0) if not _gennative else 0.0),
                neutral_key_tight=_gennative)
            _ak = getattr(PixelForgeChromaKey, "LAST_AUTO_KEYS", None)
            report.append(f"key: {key_color} ({key_strength.lower()})" +
                          (f" [{', '.join(_ak)}]" if _ak else "") +
                          (" | gen-native key profile: border-only "
                           "(no interior-gap pass, no matte erode, "
                           "tight neutral keys)"
                           if _gennative else ""))
            _keyed_here = True
            # v3.11.19: border-support filter on the auto keys. A splash
            # touching the frame edge registers as a "backdrop" color
            # (live 89ce8bad: coffee red #8F0200 joined green #05EE00 ->
            # every near-key pass then ate the coffee as "residue"). Real
            # chroma DOMINATES the border ring; content at the border is a
            # sliver. Keys with < 1% border support (or < 24 px) are dropped
            # once, here, so the sweep / gap key / de-fringe / re-seat all
            # stop treating that content color as backdrop.
            _ak1 = getattr(PixelForgeChromaKey, "LAST_AUTO_KEYS", None)
            if _ak1 and len(_ak1) > 1 and images.ndim == 4:
                try:
                    _f0 = (images[0].clamp(0, 1) * 255).cpu().numpy()
                    _bh, _bw = _f0.shape[:2]
                    _t = 4
                    _ring = np.concatenate([
                        _f0[:_t].reshape(-1, 3), _f0[-_t:].reshape(-1, 3),
                        _f0[:, :_t].reshape(-1, 3),
                        _f0[:, -_t:].reshape(-1, 3)]).astype(np.float32)
                    _sup = []
                    for _hx5 in _ak1:
                        _c5 = np.array([int(_hx5[_j5:_j5 + 2], 16)
                                        for _j5 in (1, 3, 5)],
                                       dtype=np.float32)
                        _sup.append(int((np.sqrt(((_ring - _c5) ** 2)
                                                 .sum(-1)) < 55.0).sum()))
                    _keep5 = [k for k, s in zip(_ak1, _sup)
                              if s >= max(24, 0.01 * _ring.shape[0])]
                    if _keep5 and len(_keep5) < len(_ak1):
                        PixelForgeChromaKey.LAST_AUTO_KEYS = _keep5
                        report.append(
                            "key filter: dropped " +
                            ", ".join(k for k in _ak1 if k not in _keep5)
                            + f" (border support {_sup}); kept " +
                            ", ".join(_keep5))
                except Exception as _e5:
                    report.append(f"key filter: skipped ({_e5})")
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
                            # v3.11.17: flying content IS the content in T2V -- the 5%-of-main rule + the 2px adjacency gate ate every far droplet (live 3a5b3d6e81: far-arc drops 0px in keyed); residue cleanup is the key sweep's job now
                            (_pick(adv_key_drop_detached, 5.0) if not _gennative else 0.0))
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
                # v3.11.9-smartbg (gen-native): residue sweep keyed to the DETECTED
        # screen color(s), not a hue formula. The old green-dominance rule
        # (G>R+25 & G>B+25) missed cyan screens by construction (#54A3A4:
        # B~=G fails the G>B gate -> teal fringe survived on live 054b1ae2).
        # Now: opaque px within euclidean 55 of ANY auto-keyed screen color
        # are residue, provided the ref palette carries no such color.
        if (_gennative and alpha is not None
                and _tri(adv_gn_green_sweep, True)):
            try:
                import scipy.ndimage as _ndi
                _kb = []
                for _hx0 in (getattr(PixelForgeChromaKey,
                                     "LAST_AUTO_KEYS", None) or []):
                    _kb.append([int(_hx0[_j:_j + 2], 16)
                                for _j in (1, 3, 5)])
                if _kb:
                    _KS = np.array(_kb, dtype=np.float32)
                    _gs_ok = True
                    _gs_why = "screen color(s) " + " ".join(
                        str(_h) for _h in (
                            getattr(PixelForgeChromaKey,
                                    "LAST_AUTO_KEYS", None) or []))
                    if custom_palette_image is not None:
                        _rg0 = (custom_palette_image[0].clamp(0, 1) * 255
                                ).round().to(torch.uint8).cpu(
                                    ).numpy()[..., :3]
                        _p0, _b0, _k0, _a0 = _ref_palette(_rg0, colors)
                        _all0 = np.array(
                            [list(map(float, c)) for c in _p0]
                            + [list(map(float, _b0))], dtype=np.float32)
                        _dd0 = np.sqrt(((_all0[:, None, :] - _KS[None, :, :])
                                        ** 2).sum(-1))
                        _gs_ok = not bool((_dd0 < 55.0).any())
                    if _gs_ok:
                        _fa0 = (images.clamp(0, 1) * 255).cpu().numpy()
                        _aa0 = alpha.cpu().numpy()
                        _dm0 = np.sqrt(((
                            _fa0[..., None, :] - _KS[None, None, :, :]
                        ) ** 2).sum(-1)).min(-1)
                        _gm0 = (_aa0 > 0.5) & (_dm0 < 55.0)
                        # v3.11.18: sweep DETACHED components only. Live
                        # 89ce8bad: auto-keys picked up dark red (#8F0200)
                        # from the coffee splash touching the border, and
                        # the sweep then keyed the coffee itself (it is
                        # main-connected content). Residue is by definition
                        # detached fragments; the main component is spared.
                        _lbl0, _nl0 = _ndi.label(_aa0 > 0.5)
                        if _nl0 > 1:
                            _sz0 = _ndi.sum(_aa0 > 0.5, _lbl0,
                                            range(1, _nl0 + 1))
                            _main0 = int(np.argmax(_sz0)) + 1
                            _gm0 &= (_lbl0 != _main0)
                        _ng0 = int(_gm0.sum())
                        if _ng0:
                            alpha = torch.from_numpy(np.where(
                                _gm0, 0.0, _aa0).astype(np.float32)).to(
                                    alpha.device)
                            report.append(
                                f"key sweep: keyed {_ng0} residue px "
                                f"batch-wide ({_gs_why})")
                    else:
                        report.append(
                            "key sweep: skipped (ref palette sits on the "
                            "screen color)")
                else:
                    report.append("key sweep: skipped (no auto keys)")
            except Exception as _e:
                report.append(f"key sweep: skipped ({_e})")
        # v3.11.11-gapkey rev2: enclosed screen pockets by HUE. Border-only
        # keying never reaches backdrop fully enclosed by the body
        # (arm/torso holes); the v3.10.3 interior pass was disabled for
        # punching holes into character-internal regions. Measured on live
        # e1464e15a0: pockets survive as DESATURATED shadow green ([88,126,
        # 55], hue ~84) that fails both redmean distance (110) and strict
        # dominance tests. Rule: inside ENCLOSED opaque components, key px
        # whose hue sits within 50 deg of a detected screen-key hue with
        # sat > 0.25; stand down when the character itself wears that hue
        # (interior green-ish share > 2%).
        if (_gennative and alpha is not None
                and _tri(adv_key_interior, True)):
            try:
                import scipy.ndimage as _ndi
                _gk = [[int(_hx3[_j3:_j3 + 2], 16) for _j3 in (1, 3, 5)]
                       for _hx3 in (getattr(PixelForgeChromaKey,
                                            "LAST_AUTO_KEYS", None) or [])]
                if _gk:
                    _KS3 = np.array(_gk, dtype=np.float32) / 255.0
                    _kmx = _KS3.max(-1)
                    _kmn = _KS3.min(-1)
                    _kd = np.maximum(_kmx - _kmn, 1e-6)
                    _kr, _kg, _kb = _KS3[..., 0], _KS3[..., 1], _KS3[..., 2]
                    _kh = np.where(_kmx == _kr, (60 * ((_kg - _kb) / _kd))
                                   % 360,
                                   np.where(_kmx == _kg,
                                            60 * ((_kb - _kr) / _kd) + 120,
                                            60 * ((_kr - _kg) / _kd) + 240))
                    _fa3 = (images.clamp(0, 1) * 255).cpu().numpy()
                    _aa3 = alpha.cpu().numpy()
                    _n3, _h3, _w3 = _fa3.shape[:3]
                    _fr = _fa3[..., 0] / 255.0
                    _fg = _fa3[..., 1] / 255.0
                    _fb = _fa3[..., 2] / 255.0
                    _fmx = np.max((_fr, _fg, _fb), axis=0)
                    _fmn = np.min((_fr, _fg, _fb), axis=0)
                    _fd = np.maximum(_fmx - _fmn, 1e-6)
                    _fsat = np.where(_fmx > 0, _fd / np.maximum(_fmx, 1e-6),
                                     0.0)
                    _fhue = np.zeros_like(_fmx)
                    _m = (_fmx == _fr) & (_fd > 0)
                    _fhue[_m] = (60 * ((_fg - _fb)[_m] / _fd[_m])) % 360
                    _m = (_fmx == _fg) & (_fd > 0)
                    _fhue[_m] = 60 * ((_fb - _fr)[_m] / _fd[_m]) + 120
                    _m = (_fmx == _fb) & (_fd > 0)
                    _fhue[_m] = 60 * ((_fr - _fg)[_m] / _fd[_m]) + 240
                    # v3.11.18: PER-KEY worn check. Live 89ce8bad: the auto
                    # keys were [#8F0200 red, #05EE00 green]; the coffee
                    # plume is red-hue, so the old any-key guard saw
                    # "character wears the screen hue" and skipped ALL
                    # pocket keying. Now each key stands down individually:
                    # a key whose hue the interior wears (>2%) is excluded
                    # from pocket keying; the others still run.
                    _perkey = (((_fhue[..., None] - _kh[None, None, :]
                                 + 180) % 360) - 180)
                    _sklist = [((np.abs(_perkey[..., _kx]) < 50.0)
                                & (_fsat > 0.25)
                                & (_fa3.max(-1) > 40.0))
                               for _kx in range(_kh.shape[0])]
                    _gp = _gq = 0
                    for _i3 in range(_n3):
                        _op3 = _aa3[_i3] > 0.5
                        if not _op3.any():
                            continue
                        _lbl, _nl = _ndi.label(_op3)
                        if not _nl:
                            continue
                        _edge = set(_lbl[0, :]) | set(_lbl[-1, :]) \
                            | set(_lbl[:, 0]) | set(_lbl[:, -1])
                        _enc = np.zeros_like(_op3)
                        for _L in range(1, _nl + 1):
                            if _L in _edge:
                                continue
                            _enc |= (_lbl == _L)
                        if not _enc.any():
                            continue
                        _body = _op3 & ~_enc
                        _m3 = np.zeros_like(_op3)
                        _nworn = 0
                        for _sk in _sklist:
                            if _body.any() and (_sk[_i3][_body]).mean() > 0.02:
                                _nworn += 1
                                continue
                            _m3 |= (_sk[_i3] & _enc)
                        _m3 &= _op3
                        if _nworn == len(_sklist):
                            _gp = -1
                            break
                        _npx = int(_m3.sum())
                        if _npx:
                            _aa3[_i3][_m3] = 0.0
                            _gp += _npx
                            _gq += 1
                    if _gp == -1:
                        report.append(
                            "gap key: skipped (character wears every "
                            "screen hue)")
                    elif _gp:
                        alpha = torch.from_numpy(
                            _aa3.astype(np.float32)).to(alpha.device)
                        report.append(
                            f"gap key: keyed {_gp} px in {_gq} enclosed "
                            f"screen pocket(s)")
            except Exception as _e3:
                report.append(f"gap key: skipped ({_e3})")
        capture("keyed", images, alpha, pixel_exact=False)
        # v3.8.2-refdensity: full-res keyed stash for the ref-density
        # reduce (the look branch reduces straight from here).
        _keyed_full = (images, alpha)

        # ---------------- stage: grid recover ----------------
        _mark("grid")
        src_grid = None
        grid_frames = images
        # v3.10.4-genflatten: gen-native RUNS GridRecover -- the gen's own
        # native block grid IS the art grid; every block becomes one flat
        # (median) color + block-majority alpha = true hard pixels, the
        # gen's own colors/content 1:1, no quantize. Stray faint edge px
        # die at the majority-alpha rule (they stretched df1deac457's crop
        # bbox to the full 704 frame).
        if sharpen_grid or _gennative:
            images, alpha, gw, gh, ginfo = PixelForgeGridRecover().run(
                images, adv_grid_mode, adv_grid_block, adv_grid_max_block,
                adv_grid_reduce, False, alpha=alpha,
                nominal_on_empty=(None if custom_palette_image is not None
                                  else 4),
                # v3.11.13: keep silhouette boundary blocks at 35%% coverage
                # (majority 0.5 ate the outer art-pixel ring, live 5fb8bff4cc)
                alpha_keep=(0.35 if _gennative else 0.5))
            src_grid = (gw, gh)
            # v3.11.9-smartbg rev2: silhouette de-fringe. Flatten bakes
            # CHAR/SCREEN mixtures into boundary blocks (teal fringe on live
            # 054b1ae2/e4bd9decc6: 931 ring px batch-wide at d<90 of the key).
            # Mixing-line fitting under-fits real blocks (multi-color + AA);
            # measured simpler rule: any SILHOUETTE-ring block near the key
            # is fringe -> fill with the local interior median. Guarded: if
            # the character itself sits near the screen color (interior
            # share > 5%), the pass stands down -- never eat legit art.
            if _gennative and _tri(adv_gn_green_sweep, True):
                try:
                    _uk = [[int(_hx1[_j1:_j1 + 2], 16) for _j1 in (1, 3, 5)]
                           for _hx1 in (getattr(PixelForgeChromaKey,
                                                "LAST_AUTO_KEYS", None)
                                        or [])]
                    if _uk:
                        _KSu = np.array(_uk, dtype=np.float32)
                        _ga1 = (images.clamp(0, 1) * 255).round(
                            ).cpu().numpy().astype(np.float32)
                        _aa1 = alpha.cpu().numpy()
                        _nN, _nH, _nW = _ga1.shape[:3]

                        def _sil(opm):
                            _Tp = np.pad(~opm, 1)
                            _nb = np.zeros_like(opm)
                            for _dy in (-1, 0, 1):
                                for _dx in (-1, 0, 1):
                                    if _dy == 0 and _dx == 0:
                                        continue
                                    _nb |= _Tp[1 + _dy:_nH + 1 + _dy,
                                               1 + _dx:_nW + 1 + _dx]
                            return opm & _nb

                        _R = 6
                        _TOTF = _TOTK = 0
                        _skip = False
                        for _i1 in range(_nN):
                            _op = _aa1[_i1] > 0.5
                            if not _op.any():
                                continue
                            _rgb = _ga1[_i1]
                            _dk1 = np.sqrt(((_rgb - _KSu[0][None, None, :])
                                            ** 2).sum(-1))
                            for _k2 in _KSu[1:]:
                                _dk1 = np.minimum(_dk1, np.sqrt(
                                    ((_rgb - _k2[None, None, :]) ** 2).sum(-1)))
                            _sl = _sil(_op)
                            _it = _op & ~_sl
                            if not _sl.any():
                                continue
                            if (_dk1[_it] < 90.0).mean() > 0.05:
                                _skip = True
                                break
                            _ys, _xs = np.nonzero(_sl & (_dk1 < 90.0))
                            for _y, _x in zip(_ys, _xs):
                                _y0, _y1 = max(0, _y - _R), min(_nH,
                                                                _y + _R + 1)
                                _x0, _x1 = max(0, _x - _R), min(_nW,
                                                                _x + _R + 1)
                                _sub = _op[_y0:_y1, _x0:_x1].copy()
                                _sub[_y - _y0, _x - _x0] = False
                                _cy, _cx = np.nonzero(_sub)
                                if len(_cy) == 0:
                                    _aa1[_i1, _y, _x] = 0.0
                                    _TOTK += 1
                                    continue
                                _C = _rgb[_y0:_y1, _x0:_x1][_cy, _cx]
                                _rgb[_y, _x] = np.median(_C, axis=0)
                                _TOTF += 1
                        if _skip:
                            report.append(
                                "smart bg: skipped (character sits near "
                                "the screen color)")
                        elif _TOTF or _TOTK:
                            images = torch.from_numpy(
                                (_ga1 / 255.0).astype(np.float32)).to(
                                    images.device)
                            alpha = torch.from_numpy(
                                _aa1.astype(np.float32)).to(alpha.device)
                            report.append(
                                f"smart bg: de-fringed {_TOTF} ring blocks"
                                f", keyed {_TOTK} orphans vs {len(_uk)} "
                                f"screen color(s)")
                except Exception as _e2:
                    report.append(f"smart bg: skipped ({_e2})")

            try:
                _gi = json.loads(ginfo)
                if _gi.get("fractional"):
                    _pit = _gi.get("pitch", [0.0, 0.0])
                    _fo = _gi.get("frac_offset", [0.0, 0.0])
                    _er = _gi.get("edge_recall", [0.0, 0.0])
                    _ex = _gi.get("edge_excess", 0.0)
                    report.append(
                        ("grid: native " if _gennative else "grid: ")
                        + f"{gw}x{gh} (FRAC pitch {_pit[0]:.2f}x"
                        f"{_pit[1]:.2f} @ ({_fo[0]:.1f},{_fo[1]:.1f}), "
                        f"edge recall {_er[0]:.2f} vs int {_er[1]:.2f}, "
                        f"excess {_ex:.2f}"
                        + (", gen-native flatten: every native block -> one "
                           "flat median color, the gen's own colors 1:1)"
                           if _gennative else ")"))
                else:
                    report.append(
                        ("grid: native " if _gennative else "grid: ")
                        + f"{gw}x{gh} (block {_gi.get('block')} @ "
                        f"{tuple(_gi.get('offset', [0, 0]))}"
                        f"{'' if _gi.get('auto_detected') else ', manual'}"
                        + (", gen-native flatten: every native block -> one "
                           "flat median color, the gen's own colors 1:1)"
                           if _gennative else ")"))
            except Exception:
                report.append(f"grid: {gw}x{gh}")
        else:
            report.append("grid: off")
        # v3.11.14: detached-content re-seat. Flying islands (coffee drops,
        # sparks, debris) are sub-cell at block scale and die in the
        # block-alpha rule (live 5fb8bff4cc: 6761 -> 601 brown px across the
        # keyed->grid boundary while the keyer itself loses none). Every
        # DETACHED keyed component re-claims the cells it covers with >= 2
        # opaque px, colored by its own pixels -- the main subject is left
        # to alpha_keep alone.
        if _gennative and alpha is not None and _keyed_full is not None:
            try:
                import scipy.ndimage as _ndi
                _gi4 = json.loads(ginfo) if ginfo else {}
                _s4 = int(_gi4.get("block", 0) or 0)
                if _s4 >= 2:
                    # v3.11.18: residue islands (near a screen key) are NOT
                    # content -- re-seat skips them (live 89ce8bad: green
                    # speckle re-seated batch-wide = bg bleed).
                    _gk4 = [[int(_hx4[_j4:_j4 + 2], 16)
                             for _j4 in (1, 3, 5)]
                            for _hx4 in (getattr(PixelForgeChromaKey,
                                                 "LAST_AUTO_KEYS", None)
                                         or [])]
                    _KS4 = (np.array(_gk4, dtype=np.float32) if _gk4
                            else np.zeros((1, 3), np.float32))
                    _off4 = _gi4.get("offset", [0, 0]) or [0, 0]
                    _ka4 = _keyed_full[1].cpu().numpy()
                    _kr4 = _keyed_full[0].cpu().numpy()
                    _ga4 = alpha.cpu().numpy()
                    _gr4 = images.cpu().numpy()
                    _n4, _h4, _w4 = _ka4.shape
                    _oy4, _ox4 = int(_off4[1]), int(_off4[0])
                    _seatc = 0
                    for _i4 in range(_n4):
                        _op4 = _ka4[_i4] > 0.5
                        if not _op4.any():
                            continue
                        _lbl4, _nl4 = _ndi.label(_op4)
                        if _nl4 < 2:
                            continue
                        _sz4 = _ndi.sum(_op4, _lbl4, range(1, _nl4 + 1))
                        _main = int(np.argmax(_sz4)) + 1
                        _gaB = _ga4[_i4] > 0.5
                        # v3.11.16 REVERTED to islands-only: the
                        # main-adjacency variant re-seated ~7.4k cells on
                        # live 3a5b3d6e81 = a 1px fuzz ring around the whole
                        # silhouette (every low-coverage edge cell is
                        # adjacent to a kept cell). Stream-connected
                        # sub-cell bulges are inherent AA, not content.
                        for _L in range(1, _nl4 + 1):
                            if _L == _main:
                                continue
                            _m4 = _lbl4 == _L
                            if _m4.sum() < 2:
                                continue
                            _med4 = np.median(_kr4[_i4][_m4], axis=0)
                            # 55 not 90: live 89ce8bad's red "key" IS the
                            # coffee's color family (#8F0200 vs brown ~75
                            # apart) -- at 90 the filter ate the coffee
                            # drops as "residue". 55 matches the sweep.
                            if float(np.min(np.sqrt(
                                    ((_med4 - _KS4) ** 2).sum(-1)))) < 55.0:
                                continue
                            _ys, _xs = np.nonzero(_m4)
                            _cy = ((_ys - _oy4) // _s4).astype(np.int64)
                            _cx = ((_xs - _ox4) // _s4).astype(np.int64)
                            _ok = ((_cy >= 0) & (_cy < _ga4.shape[1])
                                   & (_cx >= 0) & (_cx < _ga4.shape[2]))
                            _cy, _cx = _cy[_ok], _cx[_ok]
                            _ys, _xs = _ys[_ok], _xs[_ok]
                            if len(_cy) == 0:
                                continue
                            _cid = _cy * _ga4.shape[2] + _cx
                            # v3.11.15b: >= 1 px -- a far-shrunk drop is a
                            # single source pixel by the time it detaches
                            # fully; >= 2 still ate it (owner report).
                            for _cell in np.unique(_cid):
                                _by, _bx = divmod(int(_cell),
                                                  _ga4.shape[2])
                                if _gaB[_by, _bx]:
                                    continue
                                _sel = _cid == _cell
                                _gaB[_by, _bx] = True
                                _gr4[_i4, _by, _bx] = np.median(
                                    _kr4[_i4][_ys[_sel], _xs[_sel]],
                                    axis=0)
                                _seatc += 1
                        _ga4[_i4] = _gaB.astype(np.float32)
                    if _seatc:
                        alpha = torch.from_numpy(
                            _ga4.astype(np.float32)).to(alpha.device)
                        # v3.11.14b HOTFIX: _gr4 and _kr4 are both 0-1
                        # tensors -- the /255 here blacked out the whole
                        # frame (owner: "just a black silhouette").
                        images = torch.from_numpy(
                            _gr4.astype(np.float32)).to(images.device)
                        grid_frames = images
                        report.append(
                            f"detached re-seat: recovered {_seatc} cells "
                            f"of flying content")
            except Exception as _e4:
                report.append(f"detached re-seat: skipped ({_e4})")
        grid_frames = images
        if sharpen_grid or _gennative:
            capture("grid", images, alpha, pixel_exact=True)
        else:
            meta["grid"] = {"skipped": True, "frames": 0, "shown": 0, "w": 0, "h": 0}

        # ---------------- resolve target size ----------------
        _mark("size")
        _guard_kept = False
        if _gennative:
            tw, th = images.shape[2], images.shape[1]
            report.append(f"size: native {tw}x{th} (gen 1:1 art grid, "
                          "no resize)")
        elif size_preset == "Custom size":
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
        if not _gennative:
            report.append(f"size: {tw}x{th if th else 'auto'}")
        # Art-grid sanity guardrail (v3.7.0): past ~128px on the long side the
        # pixel structure is invisible and the output reads as a downscaled
        # image, not pixel art — the owner's "blown-up 200x200" failure mode.
        _long_side = max(tw, th if th else tw)
        if _long_side > 128 and not _guard_kept and not _gennative:
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
                # v3.8.1-fringefix: cap G ONLY on the masked dark-green px.
                # The unmasked assignment slashed the green channel of every
                # bright saturated px in the batch (cyan/skin/highlight ->
                # one shade band darker; measured on live run 1123616ebe:
                # 194 px reported, 13,501 actually mutated, 6.1% of opaque).
                _fs[..., 1] = np.where(
                    _fm, np.minimum(_fg, (_fr + _fb) // 2 + 6), _fg)
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
                and not _gennative
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
        _mark("look:gen-native" if (look == _REF_LOOK
                                    and adv_ref_look_mode == _REF_LOOK_MODE_GEN)
              else "look")
        dmode, dstrength = _DITHER[dither]
        palette_json = "{}"
        _gennative_density = False  # v3.10.2: gen-native + ref wired
        if (look == _REF_LOOK and custom_palette_image is None
                and adv_ref_look_mode != _REF_LOOK_MODE_GEN):
            report.append(
                "ref look: no ref image (arm a ref slot or wire "
                "custom_palette_image) -- falling back to Hi-bit cel")
            look = "Hi-bit cel shading"
        # v3.10.0-gennative: default mode keeps the gen 1:1 -- the
        # guard-kept Source grid stands (no refdensity halving) and
        # the palette comes from the gen itself via the Hi-bit
        # engine (no RefMatch snap). Measured on live 1bac01576b:
        # guard kept 176, refdensity forced 88, 99-100% ref palette,
        # -67% edges vs the H3 source = "detailing way off from the
        # H3 output". Legacy mode = the pre-v3.10.0 ref snap.
        if look == _REF_LOOK and adv_ref_look_mode == _REF_LOOK_MODE_GEN:
            report.append(
                "ref look mode: gen-native (keyed H3 gen flattened to its "
                "native block grid -- every block one flat median color, "
                "the gen's own colors/content 1:1; no density ruler, no "
                "quantize, no RefMatch; adv_ref_look_mode = legacy "
                "restores the ref snap pipeline)")
            look = _GEN_RAW
        if look == _REF_LOOK and custom_palette_image is not None:
            # v3.8.7-refguard: gen<->ref compatibility gate. RefMatch assumes
            # the gen IS the ref's character (hue-window + bandmatch snapping
            # is only meaningful then). H3 seed drift or a swapped ref slot
            # breaks that assumption and produced silent garbage (live
            # f62d944eee: a dark-ninja gen force-snapped into the Sasuke
            # palette -- olive->black, navy->royal blue, red armband->
            # magenta). Measured on the real runs: median redmean distance
            # of opaque grid px to the ref palette = 23 for a matching gen
            # (8b3edef07b) vs 124 for the foreign one. Gate at 60: on clear
            # mismatch use the gen's own colors (Hi-bit cel) instead of
            # snapping onto a foreign palette.
            try:
                _rg = (custom_palette_image[0].clamp(0, 1) * 255).round(
                ).to(torch.uint8).cpu().numpy()[..., :3]
                _pal_g, _bg_g, _k_g, _art_g = _ref_palette(_rg, colors)
                _pg = np.array(_pal_g, np.float32)
                _gs = []
                _fstats = []
                for _i in range(images.shape[0]):
                    _fr = (images[_i].clamp(0, 1) * 255).round().to(
                        torch.uint8).cpu().numpy()
                    if alpha is not None:
                        _am = alpha[min(_i, alpha.shape[0] - 1)].cpu().numpy()
                        if _am.shape != _fr.shape[:2]:
                            _am = np.asarray(Image.fromarray(
                                (_am * 255).astype(np.uint8)).resize(
                                (_fr.shape[1], _fr.shape[0]),
                                Image.Resampling.NEAREST),
                                dtype=np.float32) / 255.0
                        _fr = _fr[_am > 0.5]
                    else:
                        _fr = _fr.reshape(-1, 3)
                    if len(_fr):
                        _fr = _fr.astype(np.float32)
                        _gs.append(_fr)
                        # v3.9.0-guardquorum: per-frame read (see verdict)
                        _frm = (_fr[:, :1] + _pg[None, :, 0]) / 2.0
                        _fd2 = ((2.0 + _frm / 256.0)
                                * (_fr[:, :1] - _pg[None, :, 0]) ** 2
                                + 4.0 * (_fr[:, 1:2] - _pg[None, :, 1]) ** 2
                                + (2.0 + (255.0 - _frm) / 256.0)
                                * (_fr[:, 2:3] - _pg[None, :, 2]) ** 2)
                        _fdm = np.sqrt(_fd2.min(1))
                        _fstats.append(
                            (float((_fdm < 30.0).mean() * 100.0),
                             float(np.median(_fdm))))
                if _gs:
                    _gp = np.concatenate(_gs)
                    if len(_gp) > 200000:
                        _gp = _gp[::len(_gp) // 200000 + 1]
                    _rm = (_gp[:, :1] + _pg[None, :, 0]) / 2.0
                    _d2 = ((2.0 + _rm / 256.0)
                           * (_gp[:, :1] - _pg[None, :, 0]) ** 2
                           + 4.0 * (_gp[:, 1:2] - _pg[None, :, 1]) ** 2
                           + (2.0 + (255.0 - _rm) / 256.0)
                           * (_gp[:, 2:3] - _pg[None, :, 2]) ** 2)
                    _dmin = np.sqrt(_d2.min(1))
                    _gm = float(np.median(_dmin))
                    _f30 = float((_dmin < 30.0).mean() * 100.0)
                    # v3.8.8-guardcore: the median alone false-trips on a
                    # MATCHING gen carrying a big foreign prop (live
                    # e49f434bfa / 0d79b30fd6: Sasuke + a giant cake =
                    # median 62-63 > 60 -> silent Hi-bit fallback on a
                    # perfect gen). Measured on all 7 preserved runs:
                    # core-within-30 = 32-43% matching vs 1-23% foreign
                    # (gate 27); median = 39-63 matching vs 86-130 foreign
                    # (gate 75). Pass only when BOTH reads say matching --
                    # a white-heavy foreign character keeps a big core but
                    # a high median, a prop-heavy matching gen keeps a big
                    # core with a mid median.
                    # v3.9.0-guardquorum: a giant foreign PROP poisons the
                    # pooled read while the character stays on-palette in
                    # most frames (live 6b7e1105f3: sleeping bag = pooled
                    # median 95.7 > 75, frame quorum 46%). Pass when the
                    # pooled dual-read passes OR >= 1/3 of frames pass it.
                    _q = 0.0
                    if _fstats:
                        _q = float(np.mean(
                            [1.0 if (c >= 27.0 and m <= 75.0) else 0.0
                             for c, m in _fstats]))
                    if (_f30 < 27.0 or _gm > 75.0) and _q < 1.0 / 3.0:
                        report.append(
                            f"ref look: gen does not match the ref sprite "
                            f"(core {_f30:.0f}% of px near a ref color, "
                            f"median distance {_gm:.0f}, frame quorum "
                            f"{_q * 100:.0f}%) -- snapping would "
                            "mangle it; using the gen's own colors "
                            "(re-gen or swap the ref slot to match)")
                        look = "Hi-bit cel shading"
                    elif _f30 < 27.0 or _gm > 75.0:
                        report.append(
                            f"ref guard: gen matches the ref on "
                            f"{_q * 100:.0f}% of frames (prop-heavy batch; "
                            f"pooled core {_f30:.0f}%, median {_gm:.0f}) "
                            "-- snapping per the frame quorum")
                    else:
                        report.append(
                            f"ref guard: gen matches the ref (core "
                            f"{_f30:.0f}% of px near a ref color, median "
                            f"distance {_gm:.0f})")
                else:
                    report.append("ref guard: no opaque px -- skipped")
            except Exception as _e:
                report.append(f"ref guard: skipped ({_e})")
        if look == _REF_LOOK or _gennative_density:
            _rb = _tri(adv_ref_backdrop, False)
            # v3.8.2-refdensity: match the ref sprite's character-relative
            # block size. Measured on run cc3e40f8d9: ref character 30x65
            # blocks (1,130 cells) vs our 62x137 (4,591) = 4.06x cells /
            # 2.07x linear — per-cell classification of a soft gen at 2x the
            # ref's density speckles every shading gradient and doubles every
            # line. Derive the forge grid from the REF's own geometry and
            # masked-majority-reduce the full-res keyed frames straight to it.
            _rdm = None
            if (custom_palette_image is not None
                    and _keyed_full[0] is not None
                    and size_preset in _SRC_SIZE_MODES):
                try:
                    _ru = (custom_palette_image[0].clamp(0, 1) * 255).round(
                    ).to(torch.uint8).cpu().numpy()[..., :3]
                    _pal_r, _bg_r, _k_r, _art_r = _ref_palette(_ru, colors)
                    if _k_r is None or _k_r <= 1:
                        raise ValueError("ref has no integer grid")
                    _char = (np.abs(_art_r.astype(np.int16)
                                    - np.array(_bg_r, np.int16)).max(-1) > 24)
                    if _char.sum() < 25:
                        raise ValueError("ref character not found")
                    _cys, _cxs = np.where(_char)
                    _cbw = int(_cxs.max() - _cxs.min() + 1)
                    _cbh = int(_cys.max() - _cys.min() + 1)
                    _fi, _fa = _keyed_full
                    if _fa is None:
                        raise ValueError("no alpha for character bbox")
                    _fan = _fa.cpu().numpy()
                    _cands = []
                    for _i in range(_fan.shape[0]):
                        _ys, _xs = np.where(_fan[_i] > 0.5)
                        if len(_ys) < 100:
                            continue
                        # v3.8.7: match the ref's block size on the
                        # pose-STABLE axis (character height). The mean of
                        # the w/h ratios let wide ACTION frames inflate the
                        # block (live 8b3edef07b: width term 14.9 vs height
                        # 8.3 -> block 12 -> 58px grid -> character 45 cells
                        # vs the ref's 64 = "lost details / not 1:1").
                        _cands.append(
                            (_ys.max() - _ys.min() + 1) / _cbh)
                    if not _cands:
                        raise ValueError("no opaque frames")
                    _blk = max(3, min(24, int(round(float(np.median(_cands))))))
                    _tw2, _th2 = (_fi.shape[2] // _blk, _fi.shape[1] // _blk)
                    if not (16 <= _tw2 <= 256 and 16 <= _th2 <= 256):
                        raise ValueError(f"bad target {_tw2}x{_th2}")
                    _rdm = (_blk, _tw2, _th2, _cbw, _cbh)
                except Exception as _e:
                    report.append(f"ref density: skipped ({_e})")
            if _rdm is not None:
                _blk, tw, th, _cbw, _cbh = _rdm
                _fi, _fa = _keyed_full
                _ha = (_fi.clamp(0, 1) * 255).round().to(
                    torch.uint8).cpu().numpy()
                _hm = _fa.cpu().numpy()
                if _keyed_here:
                    # same dark-green fringe neutralization as the grid path
                    _fs2 = _ha.astype(np.int16)
                    _fm2 = ((_hm > 0.5) & (_fs2.max(-1) < 90)
                            & (_fs2[..., 1] > _fs2[..., 0] + 12)
                            & (_fs2[..., 1] > _fs2[..., 2] + 12))
                    if _fm2.any():
                        _fs2[..., 1] = np.where(
                            _fm2, np.minimum(
                                _fs2[..., 1],
                                (_fs2[..., 0] + _fs2[..., 2]) // 2 + 6),
                            _fs2[..., 1])
                        _ha = _fs2.clip(0, 255).astype(np.uint8)
                _he, _hw2 = th * _blk, tw * _blk
                _so = np.empty((_ha.shape[0], th, tw, 3), dtype=np.uint8)
                _sa = np.empty((_ha.shape[0], th, tw), dtype=np.float32)
                for _i in range(_ha.shape[0]):
                    _so[_i] = _reduce_blocks_masked(
                        _ha[_i, :_he, :_hw2], _hm[_i, :_he, :_hw2],
                        _blk, "majority")
                    _sa[_i] = (_hm[_i, :_he, :_hw2].reshape(
                        th, _blk, tw, _blk).mean((1, 3)) > 0.5)
                images = torch.from_numpy(_so.astype(np.float32) / 255.0)
                alpha = torch.from_numpy(_sa)
                grid_frames = images
                report.append(
                    ("gen-native density" if _gennative_density
                     else "ref density")
                    + f": block {_blk}px -> {tw}x{th} grid (ref character "
                    f"{_cbw}x{_cbh} blocks = 1:1 chunk)")
            elif (look == _REF_LOOK
                    and (tw, th) != (images.shape[2], images.shape[1])):
                _rr = []
                for _i in range(images.shape[0]):
                    _f = (images[_i].clamp(0, 1) * 255).round().to(
                        torch.uint8).cpu().numpy()
                    _rr.append(np.asarray(Image.fromarray(_f).resize(
                        (tw, th), Image.Resampling.NEAREST)))
                images = torch.from_numpy(
                    np.stack(_rr).astype(np.float32) / 255.0)
                if alpha is not None:
                    _ra = []
                    for _i in range(alpha.shape[0]):
                        _f = (alpha[_i].clamp(0, 1) * 255).round().to(
                            torch.uint8).cpu().numpy()
                        _ra.append(np.asarray(Image.fromarray(_f).resize(
                            (tw, th), Image.Resampling.NEAREST)))
                    alpha = torch.from_numpy(
                        np.stack(_ra).astype(np.float32) / 255.0)
                report.append(f"ref look: nearest-resized to target {tw}x{th}")
            if look == _REF_LOOK:
                # v3.8.9-detailvote: region_vote OFF at ref density (see
                # VERSION note). The vote consolidated 2x-density speckle;
                # at 1:1 it smooths real 1-cell features away.
                images, alpha, palette_json = PixelForgeRefMatch().run(
                    images, custom_palette_image, colors, cleanup, False,
                    "ref color" if _rb else "transparent", alpha=alpha)
                try:
                    _ri = json.loads(palette_json)
                    report.append(
                        f"look: reference match @ {_ri.get('palette_size')}"
                        f" ref colors (ref grid {_ri.get('ref_grid')}px, bg"
                        f" {_ri.get('backdrop')}, backdrop "
                        f"{_ri.get('backdrop_mode')}, bandmatch "
                        f"{_ri.get('bandmatch_families')} fam)")
                except Exception:
                    report.append("look: reference match")
        if look == _REF_LOOK:
            pass  # legacy ref look done above (density + RefMatch)
        elif look == _GEN_RAW:
            # v3.10.4-genflatten: the flattened native-grid frames ARE the
            # output art (flatten happened at the grid stage).
            report.append(
                "look: gen-native flatten (native block grid, the gen's "
                "own colors 1:1)")
            # v3.11.10-solidlook: collapse H3's shading ramps + soft line
            # art into flat pixel-art bands. Flatten kills block mush but
            # keeps per-block gradients (H3 paints smooth ramps); TruePixel
            # consolidates them onto a k-means palette FROM THE GEN ITSELF
            # + cel bands + region vote + despeckle (v3.7.x-hardened chain).
            # Owner verdict on live e4bd9decc6/c4433541: "too many
            # gradients, interior/exterior line art should be more solid".
            # adv_tp_* widgets now tune this pass (bands -1 -> preset 2).
            images, alpha, _tpm, _tpp = PixelForgeTruePixel().run(
                images, tw, th, "area", colors,
                _pick(adv_tp_share, 1.0),
                _pick(adv_tp_flatten, 0.0), 2,
                _pick(adv_tp_bands, 3),
                _pick(adv_tp_ambient, 0.35),
                _pick(adv_tp_shadow_thr, 0.55),
                _pick(adv_tp_highlight_thr, 0.85),
                _pick(adv_tp_cel_contrast, 1.0),
                _pick(adv_tp_hue_shift, 0.0),
                _pick(adv_tp_vibrancy, 1.0),
                "inner" if _tri(adv_tp_outline, False) else "off",
                dmode, dstrength,
                # v3.11.14: despeckle off -- it eats the re-seated 1-cell
                # droplets (and any legit single-cell detail)
                False,
                _pick(adv_tp_saturation, 1.05),
                _pick(adv_tp_contrast, 1.0),
                _pick(adv_tp_sharpen, 0.0),
                # auto_subject=False: measured on e4bd9decc6 -- with the
                # backdrop dominating the frame, subject detection built a
                # dark-only palette and shredded the sprite; full-frame
                # k-means + the alpha matte is the clean path (alpha hides
                # the backdrop clusters).
                # v3.11.12: shade_smooth=False + region_vote=False --
                # measured A/B on live e1464e15a0 f28 (owner verdict
                # "melting playdough" on the smooth+vote build): killing
                # the smoothers keeps hair strands + body definition
                # while bands=3 keeps the shading deliberate. The vote at
                # 1-cell scale is the v3.8.9 detail-eater all over again.
                False, 28.0, 1, "manual", 10, 0.06, False, False, 5,
                alpha=alpha)
            grid_frames = images
            report.append(
                f"look: gen-native solid @ {colors} colors (k-means 3-band"
                " cel, no vote/smooth; adv_tp_* widgets tune)")

            # v3.10.5-refsnap: snap the flattened blocks onto the ref's
            # EXACT palette (integer-grid modal reduce, no kmeans). The
            # block median keeps H3's per-pixel gradients (measured on run
            # 2293e1bd04 f0: 704 unique colors in 927 opaque px, 4.6% on a
            # ref color, median redmean 19.3 -- "bad color gradients that
            # didn't exist on the source inputs"); after the snap every
            # opaque block IS a ref color = true 1:1 with the input.
            # Guarded by the v3.8.8 dual-read so a foreign gen keeps its
            # own colors; px farther than the cap (foreign props) keep the
            # gen color. Extreme rescue: a light-extreme ref color with
            # >=25% support in a block's full-res window wins the block --
            # the block median eats 2-3px light details (the eye glint:
            # 1574 near-white px at keyed res -> 32 at grid res here).
            if (custom_palette_image is not None
                    and _tri(adv_gn_ref_snap, True)):
                try:
                    _ru = (custom_palette_image[0].clamp(0, 1) * 255
                           ).round().to(torch.uint8).cpu().numpy()[..., :3]
                    _pal_s, _bg_s, _k_s, _art_s = _ref_palette(_ru, colors)
                    _spl = [list(map(float, c)) for c in _pal_s]
                    _bgf = list(map(float, _bg_s))
                    if _bgf not in _spl:
                        _spl.append(_bgf)
                    _SP = np.array(_spl, dtype=np.float32)
                    _SPl = (_SP[:, 0] * 0.299 + _SP[:, 1] * 0.587
                            + _SP[:, 2] * 0.114)
                    _cap = _pick(adv_gn_snap_cap, 1.0e9)  # v3.10.6: preset = snap ALL (guard-gated)
                    _nc = len(_SP)

                    def _snap_idx(pxf):
                        _rm = (pxf[:, :1] + _SP[None, :, 0]) / 2.0
                        _d2 = ((2.0 + _rm / 256.0)
                               * (pxf[:, :1] - _SP[None, :, 0]) ** 2
                               + 4.0 * (pxf[:, 1:2] - _SP[None, :, 1]) ** 2
                               + (2.0 + (255.0 - _rm) / 256.0)
                               * (pxf[:, 2:3] - _SP[None, :, 2]) ** 2)
                        return _d2.argmin(1), np.sqrt(_d2.min(1))

                    _GA = (images.clamp(0, 1) * 255).cpu().numpy()
                    _AA = alpha.cpu().numpy() if alpha is not None else None
                    _gh2, _gw2 = _GA.shape[1], _GA.shape[2]
                    _opx = []
                    for _i in range(_GA.shape[0]):
                        _m = (_AA[_i] > 0.5) if _AA is not None \
                            else np.ones((_gh2, _gw2), bool)
                        if _m.any():
                            _opx.append(_GA[_i][_m])
                    if not _opx:
                        raise ValueError("no opaque px")
                    _op = np.concatenate(_opx).astype(np.float32)
                    if len(_op) > 200000:
                        _op = _op[::len(_op) // 200000 + 1]
                    _, _gd = _snap_idx(_op)
                    _core = float((_gd < 30.0).mean() * 100.0)
                    _gmed = float(np.median(_gd))
                    # v3.10.7: preset = ALWAYS snap (owner directive: 1:1
                    # with the input even when the gen drifts); explicit
                    # adv_gn_ref_snap=on keeps the guarded mode.
                    _gtrip = (_core < 27.0 or _gmed > 75.0)
                    # v3.11.8-t2vpitch: catastrophic trip stands preset
                    # down. A ref armed for one character (R2V) must not
                    # repaint an unrelated T2V gen (live c069502ba3: brown
                    # T-rex snapped onto a stale Sasuke palette, core 1-9%,
                    # median 132). Matching gens measure core 25-43%, so
                    # this never fires on legit R2V runs.
                    _gforeign = (_core < 10.0 and _gmed > 95.0)
                    if _gtrip and (adv_gn_ref_snap == "on"
                                   or (adv_gn_ref_snap == "preset"
                                       and _gforeign)):
                        report.append(
                            f"ref snap: {'FOREIGN GEN, always-snap stood down' if _gforeign else 'gen does not match the ref'} "
                            f"(core {_core:.0f}% of px near a ref color, "
                            f"median {_gmed:.0f}) -- keeping the gen's own "
                            f"colors")
                    else:
                        if _gtrip:
                            report.append(
                                f"ref snap: WARN gen far from the ref "
                                f"(core {_core:.0f}%, median {_gmed:.0f}) "
                                f"-- snapping anyway (preset = always; "
                                f"adv_gn_ref_snap=on restores the guard)")
                        _out = _GA.copy()
                        _moved = 0
                        _kept = 0
                        for _i in range(_GA.shape[0]):
                            _m = (_AA[_i] > 0.5) if _AA is not None \
                                else np.ones((_gh2, _gw2), bool)
                            if not _m.any():
                                continue
                            _cur = _GA[_i][_m].astype(np.float32)
                            _idx, _dist = _snap_idx(_cur)
                            _far = _dist > _cap
                            _new = np.where(_far[:, None], _cur, _SP[_idx])
                            _kept += int(_far.sum())
                            _moved += int((np.abs(_new - _cur).max(-1)
                                           > 0.5).sum())
                            _f = _out[_i]
                            _f[_m] = _new
                            _out[_i] = _f
                        # --- extreme-minority rescue (eye glints) ---
                        # Vote palette labels over each block's FULL-RES
                        # keyed window; a light-extreme ref color (palette
                        # max luminance family) with >=25% support wins the
                        # block even as a minority. Only fires into blocks
                        # that aren't already light (no highlight speckle).
                        _resc = 0
                        _fim, _fam = _keyed_full
                        _xL = float(_SPl.max())
                        _xidx = [int(_j) for _j in range(_nc)
                                 if _SPl[_j] >= _xL - 12.0]
                        if (_fim is not None and _fam is not None
                                and _xidx and _nc > 1):
                            _FI = (_fim.clamp(0, 1) * 255).cpu().numpy()
                            _FA = _fam.cpu().numpy()
                            _nf = min(_FI.shape[0], _GA.shape[0])
                            _hf, _wf = _FI.shape[1], _FI.shape[2]
                            _sy = _hf / float(_gh2)
                            _sx = _wf / float(_gw2)
                            _ys, _xs = np.mgrid[0:_hf, 0:_wf]
                            _cy = np.minimum(
                                (_ys / _sy).astype(np.int32), _gh2 - 1)
                            _cx = np.minimum(
                                (_xs / _sx).astype(np.int32), _gw2 - 1)
                            _cell = (_cy * _gw2 + _cx).ravel()
                            _xarr = np.array(_xidx, dtype=np.int64)
                            for _i in range(_nf):
                                _m = (_AA[_i] > 0.5) if _AA is not None \
                                    else np.ones((_gh2, _gw2), bool)
                                if not _m.any():
                                    continue
                                _lab, _ = _snap_idx(
                                    _FI[_i].reshape(-1, 3).astype(
                                        np.float32))
                                _opm = (_FA[_i] > 0.5).ravel()
                                _lin = _cell * _nc + _lab
                                _cnt = np.bincount(
                                    _lin[_opm], minlength=_gh2 * _gw2 * _nc)
                                _cnt = _cnt.reshape(_gh2, _gw2, _nc)
                                _tot = _cnt.sum(-1)
                                _xc = _cnt[..., _xidx]
                                _xsup = _xc.max(-1)
                                _xbest = _xarr[_xc.argmax(-1)]
                                _f = _out[_i]
                                _cl = (_f[..., 0] * 0.299
                                       + _f[..., 1] * 0.587
                                       + _f[..., 2] * 0.114)
                                _fire = (_m & (_tot > 0)
                                         & (_xsup >= np.maximum(
                                             3, 0.10 * _tot))  # v3.10.6
                                         & (_cl <= _xL - 40.0))
                                if _fire.any():
                                    _f[_fire] = _SP[_xbest[_fire]]
                                    _out[_i] = _f
                                    _resc += int(_fire.sum())
                        images = torch.from_numpy(
                            (_out / 255.0).astype(np.float32)).to(
                            images.device)
                        grid_frames = images
                        report.append(
                            f"ref snap: gen-native snapped to the ref's "
                            f"exact {_nc}-color palette ({_moved} px "
                            f"moved, {_kept} beyond cap {_cap:.0f} kept "
                            f"gen color; guard core {_core:.0f}% median "
                            f"{_gmed:.0f})"
                            + (f" | extreme rescue: {_resc} detail "
                               "blocks (eye glints / speculars)"
                               if _resc else ""))
                except Exception as _e:
                    report.append(f"ref snap: skipped ({_e})")
        elif look.startswith("Hi-bit"):
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
        _mark("motion")
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
        _mark("crop")
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
        # v3.8.0: the Reference look can fill the backdrop with the
        # ref's flat color (alpha fully opaque). Cropping/padding a
        # full-bleed frame would only add a TRANSPARENT margin around the
        # opaque backdrop -- keep the canvas exactly the frame (identity crop).
        if look == _REF_LOOK and _tri(adv_ref_backdrop, False):
            pad, snap = 0, 1
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
        _mark("loop")
        if _gennative:
            # v3.11.21: gen-native keeps ALL frames. The trim found a
            # "loop point" at 33 on live 85665631 and dropped frames 34-56
            # -- the pose cycles there but flying content (drops) does not,
            # and the owner wants the full clip. Legacy ref look trims as
            # before.
            images = images
            loop_info = json.dumps({"mode": "gen-native: trim skipped",
                                    "input_frames": images.shape[0],
                                    "note": "all frames kept"})
            report.append(f"loop: gen-native keeps all "
                          f"{images.shape[0]} frames")
        else:
            images, alpha, loop_info = PixelForgeLoopTrim().run(
                images, _LOOPS[loop_mode],
                _pick(adv_loop_max_error, 0.06),
                _pick(adv_loop_tail, 0.5), alpha=alpha)
            report.append(f"loop: {loop_info}")

        # ---------------- dedup -> final ----------------
        _mark("dedup")
        durations_json = ""
        durations_frames = None
        if remove_duplicate_frames:
            images, alpha, durations_json = PixelForgeFrameDedup().run(
                images, _pick(adv_dedup_threshold, 0.01), alpha=alpha,
                strong_keep=_gennative)
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
            if alpha is not None and not (
                    look == _REF_LOOK and _tri(adv_ref_backdrop, False)):
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

        _mark("finalize")
        capture("final", images, alpha, pixel_exact=True)

        n = images.shape[0]
        h, w = images.shape[1], images.shape[2]
        _mark("done")
        if _phase_log:
            report.append("phases: " + " | ".join(_phase_log))
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
