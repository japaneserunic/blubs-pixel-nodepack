"""PixelForge One Forge — the entire H3 -> sprite stack in ONE node.

Absorbs the whole super-forge workflow (see docs/ONEFORGE.md): model loaders,
attention/FFN patches, turbo LoRA, prompt builder, H3 sampling, VAE decode,
the full Super Forge pipeline, and Easy Export. Purely additive — nothing
existing is touched; SuperForge and every standalone node keep working.

In-process delegation, no reimplementation:
  - core loaders (UNET/CLIP/VAE) come from ComfyUI's own nodes.py classes
  - comfy_extras nodes (guiders, noise, sampler) are reached through the same
    sys.modules trick the MiniMax Director uses, so we run the *identical*
    code the menu nodes run
  - conditioning comes from MiniMaxH3ReferenceToVideo (ref2va): plain t2v when
    no refs are wired, image-anchored when they are — one code path for both.
    Falls back to MiniMaxH3ImageToVideo on cores that predate ref2va.
  - KJNodes' MiniMaxChunkFeedForward, the turbo pack's LoRA, and core's
    ModelAttentionBackend are found through nodes.NODE_CLASS_MAPPINGS
  - forge + export call PixelForgeSuperForge / PixelForgeEasyExport directly

Optional sockets: `images` (skip generation, forge an existing batch),
`alpha`, `first_frame` (character reference, becomes <Picture 1>),
`ref_image_2` (extra reference, <Picture 2>), `custom_palette_image`.
Audio refs are deliberately not exposed — the sprite pipeline is silent, so
audio_vae is never needed in-process.
"""

import importlib.util
import json
import logging
import os
import sys

import folder_paths
import nodes as _core_nodes

import numpy as np
import torch
from PIL import Image

from .pf_easy import PixelForgeEasyExport, PixelForgeEasyPrompt, _BACKGROUNDS
from .pf_sampler import PixelForgeH3FlatSigmas, PixelForgeH3PixelSampler
from .pf_studio import PixelForgeSuperForge, _save_stage
# v3.6.0-bgsync uses these for the backdrop-synced gen prompt (the edit that
# introduced the call sites forgot this import — NameError on first Forge).
from .pf_h3 import FPS as _H3_FPS, PixelForgeH3Prompt, clause_for_hex

log = logging.getLogger(__name__)

# --------------------------------------------------------------------- access
_EXTRA_CACHE = {}


def _extra(module_name, probe_attr=None):
    """comfy_extras module by name, reusing the already-loaded instance.

    ComfyUI loads comfy_extras files via spec_from_file_location, so they sit
    in sys.modules under their full path — look them up by suffix first
    (bit-for-bit the same module the menu nodes use), load from file only as
    a fallback. Same approach as ComfyUI-MiniMaxH3-Director/minimax_core.py.
    """
    if module_name in _EXTRA_CACHE:
        return _EXTRA_CACHE[module_name]
    suffix = "comfy_extras/" + module_name
    mod = None
    for name, m in list(sys.modules.items()):
        if m is None:
            continue
        if str(name).replace("\\", "/").endswith(suffix):
            if probe_attr is None or hasattr(m, probe_attr):
                mod = m
                break
    if mod is None:
        path = os.path.join(os.path.dirname(os.path.realpath(_core_nodes.__file__)),
                            "comfy_extras", module_name + ".py")
        if not os.path.exists(path):
            raise ImportError(f"OneForge: comfy_extras/{module_name}.py not found at {path}")
        spec = importlib.util.spec_from_file_location("_pfoneforge_" + module_name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        log.info("[OneForge] loaded comfy_extras/%s from file", module_name)
    _EXTRA_CACHE[module_name] = mod
    return mod


def _unpack(out):
    """New-style io.NodeOutput -> plain tuple; old-style passthrough."""
    r = getattr(out, "result", None)
    return tuple(r) if r is not None else tuple(out)


def _node_class(name):
    cls = _core_nodes.NODE_CLASS_MAPPINGS.get(name)
    if cls is None:
        raise RuntimeError(f"OneForge: node '{name}' is not registered — "
                           "is its custom node pack installed and loaded?")
    return cls


# ------------------------------------------------------------------- vocab
_SIZE_PRESETS = {
    "custom": None,
    "16:9 · 0.2MP (608x352)": (608, 352),
    "16:9 · 0.3MP (736x416)": (736, 416),
    "16:9 · 0.5MP (960x544)": (960, 544),
    "1:1 · 0.2MP (448x448)": (448, 448),
    "1:1 · 0.3MP (544x544)": (544, 544),
    "1:1 · 0.5MP (704x704)": (704, 704),
    "9:16 · 0.3MP (416x736)": (416, 736),
}

_ATTENTION_CHOICES = ["comfy kitchen attention", "pytorch attention", "off (stock)"]


def _unet_list():
    try:
        return folder_paths.get_filename_list("diffusion_models")
    except Exception:
        return []


def _clip_list():
    try:
        return folder_paths.get_filename_list("text_encoders")
    except Exception:
        return []


def _vae_list():
    try:
        return folder_paths.get_filename_list("vae")
    except Exception:
        return []


def _lora_list():
    try:
        return ["none"] + folder_paths.get_filename_list("loras")
    except Exception:
        return ["none"]



# ---------------------------------------------------------------- drawn ref
def _hex_rgba(h, fallback=(0, 255, 0, 255)):
    try:
        h = str(h).strip().lstrip("#")
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)
    except Exception:
        return fallback


def _ref_flat_hex(forge):
    """Color the suite ref is flattened onto before ref2va. The H3 gen
    continues the ref's background, so this MUST be the color the forge
    will key out — otherwise the backdrop survives the keyer (and the
    keyer eats sprite pixels that match the WRONG target color).
    auto = green screen (auto-detect keys whatever dominates, green is
    the safest); custom hex / explicit backdrops flatten onto themselves."""
    bg = forge.get("background", "auto (detect)")
    if bg in ("auto (detect)", "custom hex"):
        return forge.get("custom_bg_hex", "#00FF00")
    hexv = _BACKGROUNDS.get(bg)
    return hexv if isinstance(hexv, str) and hexv.startswith("#") \
        else forge.get("custom_bg_hex", "#00FF00")


def _load_drawn_ref(name, width, height, bg_hex, dx=0, dy=0):
    """Load a suite-drawn reference PNG from ComfyUI's temp dir and prepare it
    for ref2va: alpha-bbox auto-crop (detect the painted sprite), flatten onto
    the forge key color, integer NEAREST upscale to fit the gen frame
    (pixel-perfect — no resampling blur), centered on a gen-size canvas.
    dx/dy offset the paste position (in sprite pixels, scaled by the same
    integer factor) so the suite's placement dot steers where the ref sits.
    Returns an IMAGE tensor [1,H,W,3], or None on any problem."""
    try:
        base = os.path.basename(str(name or "").strip())
        if not base or not base.lower().endswith(".png"):
            return None
        path = os.path.join(folder_paths.get_temp_directory(), base)
        if not os.path.isfile(path):
            return None
        img = Image.open(path).convert("RGBA")
        bbox = img.getchannel("A").getbbox()
        if bbox:
            img = img.crop(bbox)
        bg = _hex_rgba(bg_hex)
        flat = Image.new("RGBA", img.size, bg)
        flat.alpha_composite(img)
        img = flat
        bw, bh = img.size
        k = min(width // bw, height // bh)
        if k >= 1:
            img = img.resize((bw * k, bh * k), Image.NEAREST)
            ox, oy = int(round(dx * k)), int(round(dy * k))
        else:  # drawn sprite bigger than the gen frame — contain, still NN
            s = min(width / bw, height / bh)
            img = img.resize((max(1, round(bw * s)), max(1, round(bh * s))),
                             Image.NEAREST)
            ox, oy = int(round(dx * s)), int(round(dy * s))
        canvas = Image.new("RGBA", (width, height), bg)
        canvas.alpha_composite(img, ((width - img.width) // 2 + ox,
                                     (height - img.height) // 2 + oy))
        arr = np.asarray(canvas.convert("RGB"), dtype=np.float32) / 255.0
        return torch.from_numpy(arr)[None,]
    except Exception as e:  # never let a ref helper kill the whole gen
        log.warning("[OneForge] drawn ref load failed for %r: %s", name, e)
        return None


# ---------------------------------------------------------------- video ref
def _load_ref_video(name, fps=24.0, max_seconds=15.0):
    """Load a suite video-reference clip (mp4/webm/...) for ref2va <Video k>.

    Decodes with PyAV (same decoder Chain Studio uses), resamples to 24 fps,
    caps at 15s (ref2va's trained range). Resolution is left to the core
    node (adapt_canvas); the n%17==5 frame-grid trim is core-side too.
    Sprite pipeline is silent — the soundtrack is dropped, never encoded.
    Returns an IMAGE tensor [N,H,W,3], or None on any problem."""
    try:
        base = str(name or "").strip()
        if not base:
            return None
        # resolve like Chain Studio: annotated input path, temp fallback
        path = None
        try:
            path = folder_paths.get_annotated_filepath(base)
        except Exception:
            path = None
        if not path or not os.path.isfile(path):
            tpath = os.path.join(folder_paths.get_temp_directory(),
                                 os.path.basename(base))
            path = tpath if os.path.isfile(tpath) else None
        if path is None:
            log.warning("[OneForge] video ref %r not found", base)
            return None
        import av
        container = av.open(path)
        stream = container.streams.video[0]
        tb = float(stream.time_base)
        raw = []
        for frame in container.decode(stream):
            t = float(frame.pts * tb) if frame.pts is not None \
                else len(raw) / fps
            raw.append((t, torch.from_numpy(
                frame.to_ndarray(format="rgb24")).float() / 255.0))
        container.close()
        if not raw:
            return None
        dur = raw[-1][0] - raw[0][0] if len(raw) > 1 else 1.0 / fps
        n = max(5, min(int(round(dur * fps)) + 1, int(max_seconds * fps)))
        times = [t for t, _ in raw]
        out = []
        for i in range(n):
            target = raw[0][0] + i / fps
            idx = 0
            while idx + 1 < len(times) and times[idx + 1] <= target:
                idx += 1
            out.append(raw[idx][1])
        frames = torch.stack(out)
        log.info("[OneForge] video ref %s: %df decoded -> %df @ 24fps",
                 base, len(raw), frames.shape[0])
        return frames
    except Exception as e:  # never let a ref helper kill the whole gen
        log.warning("[OneForge] video ref load failed for %r: %s", name, e)
        return None


# -------------------------------------------------------------- prompt lane
def _assemble_lane_prompts(base, segments_json, win_start, win_len):
    """Chain Studio prompt-lane parity: per-segment prompt clips on the
    suite's timeline lane that overlap the gen window append to the base
    prompt in timeline order. Window is [win_start, win_start + win_len)
    in timeline frames (win_start = 0 for a full gen; the surgical-regen
    offset otherwise). Empty/duplicate segments are skipped. <Picture i> /
    <Video k> tags in segment text pass straight through — the ref binder
    below only auto-binds tags the final prompt doesn't already name."""
    try:
        segs = json.loads(segments_json or "[]")
        if not isinstance(segs, list):
            return base, 0
    except Exception:
        return base, 0
    start = int(win_start or 0)
    end = start + max(1, int(win_len or 0))
    parts = []
    for s in sorted((x for x in segs if isinstance(x, dict)),
                    key=lambda x: x.get("start", 0)):
        p = str(s.get("prompt") or "").strip()
        if not p:
            continue
        try:
            ss, se = int(s.get("start") or 0), int(s.get("end") or 0)
        except Exception:
            continue
        if se <= ss or ss >= end or se <= start:
            continue  # degenerate or no overlap with the gen window
        if p not in parts:
            parts.append(p)
    out = base or ""
    for p in parts:
        out = p if not out else out.rstrip(".") + ". " + p
    return out, len(parts)

# ==================================================================== node
class PixelForgeOneForge:
    """Prompt in one end, game-ready sprite out the other. One node, no wires."""

    CATEGORY = "PixelForge/Suite"
    FUNCTION = "run"
    OUTPUT_NODE = True
    RETURN_TYPES = ("IMAGE", "MASK", "STRING", "STRING", "STRING",
                    "IMAGE", "IMAGE", "STRING")
    RETURN_NAMES = ("images", "alpha", "durations_json", "palette_json",
                    "forge_report", "frames", "sheet", "export_report")
    DESCRIPTION = ("The whole stack in one node: H3 loaders + turbo LoRA + "
                   "ref2va conditioning + sampler + forge pipeline + "
                   "GIF/sheet/aseprite export. All controls live in the suite "
                   "UI tabs (Generate / Forge / Export). Wire the optional "
                   "images socket to skip generation and forge an existing "
                   "batch; wire first_frame / ref_image_2 to anchor the gen "
                   "with reference pictures (<Picture 1> / <Picture 2>), or "
                   "arm the suite's V1 slot to anchor motion/style with a "
                   "reference clip (<Video 1>).")

    @classmethod
    def INPUT_TYPES(cls):
        sf = PixelForgeSuperForge.INPUT_TYPES()
        forge_required = {k: v for k, v in sf["required"].items() if k != "images"}
        forge_optional = sf.get("optional", {})
        gen = {
            # ---------------- Prompt ----------------
            "character": ("STRING", {"multiline": True, "default":
                          "a small knight in blue armor with a red cape",
                          "tooltip": "Who/what the sprite is."}),
            "action": ("STRING", {"multiline": True, "default":
                       "walks in place with a steady gait",
                       "tooltip": "What they do. One simple motion loops cleanest."}),
            "style": (["16-bit SNES", "8-bit NES", "GBA", "1-bit",
                       "arcade CPS2", "modern hi-bit"],),
            "seconds": ("FLOAT", {"default": 2.0, "min": 0.5, "max": 15.0, "step": 0.25,
                        "tooltip": "Clip length. 2-4s is the sweet spot; snapped to H3's frame grid."}),
            "seamless_loop": ("BOOLEAN", {"default": True}),
            "ref_image_size": (["match", "max"], {"default": "match",
                               "tooltip": "Reference fidelity when first_frame / ref_image_2 are wired. "
                                          "'match' scales refs to the gen size (fast); 'max' keeps refs at "
                                          "2048px for best identity fidelity but is several times slower."}),
            # ---------------- Resolution ----------------
            "gen_size": (list(_SIZE_PRESETS.keys()), {"default": "16:9 · 0.5MP (960x544)"}),
            "gen_width": ("INT", {"default": 960, "min": 32, "max": 8192, "step": 32,
                          "tooltip": "Only used when gen_size = custom."}),
            "gen_height": ("INT", {"default": 544, "min": 32, "max": 8192, "step": 32,
                           "tooltip": "Only used when gen_size = custom."}),
            # ---------------- Models ----------------
            "unet_name": (_unet_list(),),
            "clip_name": (_clip_list(),),
            "vae_name": (_vae_list(),),
            "turbo_lora": (_lora_list(), {"default": "none",
                           "tooltip": "MiniMax-H3 turbo LoRA (4-step distilled). 'none' = base model speed."}),
            "lora_strength": ("FLOAT", {"default": 1.0, "min": -10.0, "max": 10.0, "step": 0.01}),
            # ---------------- Sampling ----------------
            "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff,
                     "tooltip": "Noise seed. Same seed + same prompt = same clip."}),
            "steps": ("INT", {"default": 15, "min": 1, "max": 64,
                      "tooltip": "15 with er_sde is the battle-tested setting; 4 when the turbo LoRA is on."}),
            "sampler_name": (_comfy_samplers(), {"default": "er_sde"}),
            "scheduler": (_comfy_schedulers(), {"default": "simple"}),
            "tail_compress": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 0.9, "step": 0.05,
                              "tooltip": "Flat-sigmas warp: spend steps on composition, not fine grain. 0.3-0.5 for turbo pixel art."}),
            "temporal_blend": ("FLOAT", {"default": 0.3, "min": 0.0, "max": 1.0, "step": 0.05,
                               "tooltip": "Correlate noise across frames — kills pixel shimmer at the source. 0.3-0.6 sweet spot."}),
            "loop_noise": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 1.0, "step": 0.05,
                           "tooltip": "Bend late-frame noise toward frame 0 so cycles loop. 0.2-0.5."}),
            "edge_commit": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 1.0, "step": 0.05,
                            "tooltip": "Final-latent grain damping — softens keying halo. 0.2-0.4."}),
            # ---------------- Speed / VRAM ----------------
            "attention_backend": (_ATTENTION_CHOICES, {"default": "comfy kitchen attention"}),
            "ffn_chunks": ("INT", {"default": 33, "min": 1, "max": 64,
                           "tooltip": "Chunk the H3 feedforward to cut peak VRAM. 1 = off."}),
            "ffn_seq_threshold": ("INT", {"default": 4096, "min": 256, "max": 262144, "step": 256}),
        }
        export = {
            "filename_prefix": ("STRING", {"default": "pixelforge/sprite",
                                "tooltip": "Output name (folders allowed), under ComfyUI's output dir."}),
            "export_fps": ("FLOAT", {"default": 12.0, "min": 1.0, "max": 60.0,
                           "tooltip": "GIF/sheet playback speed. 8-12 reads most 'sprite'."}),
            "make_gif": ("BOOLEAN", {"default": True}),
            "gif_size": (["tiny (1x)", "small (2x)", "big (4x)", "huge (8x)"],
                         {"default": "big (4x)"}),
            "make_sheet": ("BOOLEAN", {"default": True}),
            "sheet_columns": ("INT", {"default": 0, "min": 0, "max": 64,
                              "tooltip": "0 = automatic square-ish sheet layout."}),
            "sheet_bg": ("STRING", {"default": "#202040"}),
            "build_aseprite": ("BOOLEAN", {"default": False,
                               "tooltip": "Also build a .aseprite file (needs Aseprite installed). WIP."}),
            "aseprite_path": ("STRING", {"default": "",
                              "tooltip": "Path to aseprite.exe. Empty = auto-detect."}),
            # Hidden suite widget — MUST stay the last required entry so
            # pre-drawn-ref workflows (112 values) still align (missing
            # trailing value = default).
            "drawn_ref_image": ("STRING", {"default": "",
                                "tooltip": "Suite-drawn reference (temp PNG filename). Set by the "
                                           "suite's drawn-ref toggle; becomes <Picture 1> when no "
                                           "first_frame is wired. Auto-cropped + nearest-upscaled."}),
            # Second suite ref slot (<Picture 2>). Also MUST stay last.
            "drawn_ref_image_2": ("STRING", {"default": "",
                                "tooltip": "Suite ref slot 2 (temp PNG filename). Set by the suite's "
                                           "ref-slot buttons; becomes <Picture 2> when no ref_image_2 "
                                           "is wired."}),
            # Video ref slot (<Video 1>) — suite-imported clip for
            # motion/style-anchored genning (Chain Studio vidref parity).
            # Also MUST stay last (widget-value alignment).
            "ref_video_1": ("STRING", {"default": "",
                            "tooltip": "Suite video reference (input-dir filename). Set by the "
                                       "suite's V1 button; becomes <Video 1> in the ref2va "
                                       "conditioning — anchors motion/style. 2-15s clips, silent."}),
            # Timeline prompt lane (Chain Studio parity): JSON list of
            # {start, end, prompt} segment clips. Segments overlapping the
            # gen window append to the base prompt in timeline order.
            # MUST stay after ref_video_1 (widget-value alignment).
            "prompt_segments": ("STRING", {"default": "[]",
                                "tooltip": "Suite prompt lane (JSON). Set by the suite timeline; "
                                           "overlapping segment prompts append to the base prompt "
                                           "in timeline order."}),
            # Gen window offset (timeline frames) — nonzero only for
            # surgical regen. MUST stay last.
            "gen_win_start": ("INT", {"default": 0, "min": 0, "max": 999999,
                              "tooltip": "Suite gen-window start frame (0 = full gen). Set by the "
                                         "suite's surgical regen; selects which prompt-lane "
                                         "segments overlap."}),
        }
        required = {}
        required.update(gen)
        required.update(forge_required)
        required.update(export)
        # One Forge out-of-box defaults = the battle-tested config (owner's
        # known-good, verified across the 2026-08-16 sessions): square 1:1
        # 0.3MP canvas (single character fills it; ~2.5x fewer pixels to gen
        # than 16:9 0.5MP), Hi-bit cel shading look, 16 colors.
        # v3.7.0 adds size_preset "Source / 2 (balanced)": full Source (~136px
        # grid on the 544 gen) is too fine to read as pixel art — half the
        # grid is an exact 2x block-reduce that keeps pixels VISIBLE.
        # SuperForge / Easy defs stay untouched — these overrides apply to
        # THIS node only.
        for _k, _dv in {"gen_size": "1:1 · 0.3MP (544x544)",
                        "gen_width": 544, "gen_height": 544,
                        "look": "Hi-bit cel shading",
                        "colors": 16,
                        "size_preset": "Source / 2 (balanced)"}.items():
            _t, _meta = required[_k]
            required[_k] = (_t, {**(_meta or {}), "default": _dv})
        optional = {
            "images": ("IMAGE",),
            "first_frame": ("IMAGE", {"tooltip": "Character/subject reference — becomes <Picture 1> "
                                      "in the ref2va conditioning. Wire a character sheet or pose."}),
            "ref_image_2": ("IMAGE", {"tooltip": "Optional second reference — becomes <Picture 2>."}),
        }
        optional.update(forge_optional)   # alpha, custom_palette_image
        return {"required": required, "optional": optional}

    # ------------------------------------------------------------------ run
    def run(self, character, action, style, seconds, seamless_loop,
            ref_image_size,
            gen_size, gen_width, gen_height,
            unet_name, clip_name, vae_name, turbo_lora, lora_strength,
            seed, steps, sampler_name, scheduler, tail_compress,
            temporal_blend, loop_noise, edge_commit,
            attention_backend, ffn_chunks, ffn_seq_threshold,
            filename_prefix, export_fps, make_gif, gif_size, make_sheet,
            sheet_columns, sheet_bg, build_aseprite, aseprite_path,
            drawn_ref_image="", drawn_ref_image_2="", ref_video_1="",
            prompt_segments="[]", gen_win_start=0,
            images=None, first_frame=None, ref_image_2=None,
            alpha=None, custom_palette_image=None,
            **forge):
        log_lines = []

        # ---------------- 1. generate (unless images wired in) ----------------
        if images is None:
            # Backdrop sync (v3.6.0): the gen prompt must request the SAME
            # color the forge will key — and the same color suite refs flatten
            # onto (_ref_flat_hex). Before this, EasyPrompt hardcoded
            # "chroma green": any non-green Backdrop choice produced a gen on
            # green that the keyer never touched (backdrop survives), while
            # sprite pixels matching the WRONG target keyed out (holes).
            # Measured on run d85671cd2d: 84.7% of the "sprite" was surviving
            # green, ~8.3k interior px eaten per frame with key #FFFFFF.
            _ref_bg = _ref_flat_hex(forge)
            prompt = PixelForgeH3Prompt._build(
                character, action, style, "side",
                clause_for_hex(_ref_bg) + ".", seamless_loop, "")
            length = PixelForgeH3Prompt.snap_frames(seconds)
            _pfps = _H3_FPS
            log_lines.append(f"backdrop: {_ref_bg} (prompt/ref/key synced)")
            # Prompt lane: overlapping timeline segments append in order
            # (Chain Studio parity). gen_win_start is the regen offset.
            prompt, _lane_n = _assemble_lane_prompts(
                prompt, prompt_segments, gen_win_start, length)
            if _lane_n:
                log_lines.append(f"prompt lane: +{_lane_n} segment(s)")
            wh = _SIZE_PRESETS.get(gen_size)
            width, height = wh if wh else (gen_width, gen_height)
            log_lines.append(f"prompt: {length}f @ {width}x{height}")

            print("[OneForge] loading models…", flush=True)
            model = _core_nodes.UNETLoader().load_unet(unet_name, "default")[0]
            if attention_backend != "off (stock)":
                model = _node_class("ModelAttentionBackend")().patch(
                    model, attention_backend)[0]
            if ffn_chunks > 1:
                model = _unpack(_node_class("MiniMaxChunkFeedForward").execute(
                    model=model, chunks=ffn_chunks,
                    seq_threshold=ffn_seq_threshold))[0]
            if turbo_lora != "none":
                model = _node_class("MiniMaxH3TurboLoRA")().apply_lora(
                    model, turbo_lora, lora_strength)[0]
            clip = _core_nodes.CLIPLoader().load_clip(clip_name, "minimax", "default")[0]
            vae = _core_nodes.VAELoader().load_vae(vae_name)[0]

            mm = _extra("nodes_minimax_h3")
            sm = _extra("nodes_custom_sampler", "SamplerCustomAdvanced")

            # Reference-to-Video (ref2va) is the single conditioning path:
            # no refs wired = plain t2v; refs wired = image-anchored gen.
            refs = {}
            # Suite placement dot steers where slot refs land on the gen frame.
            _pdx = int(forge.get("placement_x", 0) or 0)
            _pdy = int(forge.get("placement_y", 0) or 0)
            # Refs are flattened onto the color the forge will actually key
            # (green for auto/custom, the explicit backdrop otherwise) so the
            # gen's background keys out instead of surviving + eating holes.
            # _ref_bg was resolved at prompt build time (backdrop sync) —
            # prompt, ref flatten and keyer all target the same color.
            if first_frame is not None:
                refs["ref_image_1"] = first_frame
            elif drawn_ref_image:
                dref = _load_drawn_ref(drawn_ref_image, width, height,
                                       _ref_bg, dx=_pdx, dy=_pdy)
                if dref is not None:
                    refs["ref_image_1"] = dref
                    log_lines.append(
                        f"drawn ref: {os.path.basename(drawn_ref_image)} -> <Picture 1> "
                        f"(bbox-cropped, nearest-upscaled into {width}x{height})")
            if ref_image_2 is not None:
                refs["ref_image_2"] = ref_image_2
            elif drawn_ref_image_2:
                dref2 = _load_drawn_ref(drawn_ref_image_2, width, height,
                                        _ref_bg, dx=_pdx, dy=_pdy)
                if dref2 is not None:
                    refs["ref_image_2"] = dref2
                    log_lines.append(
                        f"ref slot 2: {os.path.basename(drawn_ref_image_2)} -> <Picture 2>")
            # Suite video ref slot (V1): motion/style anchor -> <Video 1>.
            vrefs = {}
            if ref_video_1:
                vframes = _load_ref_video(ref_video_1)
                if vframes is not None:
                    vrefs["ref_video_1"] = vframes
                    log_lines.append(
                        f"video ref: {os.path.basename(ref_video_1)} -> <Video 1> "
                        f"({vframes.shape[0]}f @ 24fps)")
            ref_prompt = prompt
            if refs or vrefs:
                # Tags must match the ACTUAL ref slots used (slot 2 alone is
                # still <Picture 2>), not a 1..N range. Only bind tags the
                # prompt doesn't already name (Chain Studio bind semantics).
                itags = [f"<Picture {k.rsplit('_', 1)[1]}>" for k in sorted(refs)]
                vtags = [f"<Video {k.rsplit('_', 1)[1]}>" for k in sorted(vrefs)]
                bits = []
                miss_i = [t for t in itags if t not in prompt]
                miss_v = [t for t in vtags if t not in prompt]
                if miss_i:
                    bits.append("The subject matches " + ", ".join(miss_i) + ".")
                if miss_v:
                    bits.append("The motion and style match "
                                + ", ".join(miss_v) + ".")
                if bits:
                    ref_prompt = f"{prompt.rstrip()} {' '.join(bits)}"

            print("[OneForge] encoding prompt…", flush=True)
            r2v = getattr(mm, "MiniMaxH3ReferenceToVideo", None)
            if r2v is not None:
                if refs:
                    log_lines.append(f"refs: {len(refs)} image(s) @ {ref_image_size} "
                                     f"(flattened onto {_ref_bg} = forge key target)")
                cond, latent = _unpack(r2v.execute(
                    clip=clip, vae=vae, audio_vae=None, prompt=ref_prompt,
                    width=width, height=height, length=length,
                    ref_image_size=ref_image_size,
                    ref_images=refs or None,
                    ref_videos=vrefs or None))[:2]
            else:
                # core predates ref2va — fall back to the i2v node
                log_lines.append("ref2va missing on this core, using i2v")
                if vrefs:
                    log_lines.append("video refs ignored (no ref2va on this core)")
                cond, latent = _unpack(mm.MiniMaxH3ImageToVideo.execute(
                    clip=clip, vae=vae, prompt=ref_prompt, width=width,
                    height=height, length=length, first_frame=first_frame))[:2]

            guider = _unpack(sm.BasicGuider.execute(
                model=model, conditioning=cond))[0]
            noise = sm.Noise_RandomNoise(int(seed))
            sampler = _unpack(sm.KSamplerSelect.execute(sampler_name=sampler_name))[0]
            sampler = PixelForgeH3PixelSampler().wrap(
                sampler, temporal_blend, loop_noise, edge_commit)[0]
            sigmas = PixelForgeH3FlatSigmas().get_sigmas(
                model, scheduler, steps, tail_compress)[0]

            print(f"[OneForge] sampling {steps} steps ({sampler_name}/{scheduler})…",
                  flush=True)
            sampled = _unpack(sm.SamplerCustomAdvanced.execute(
                noise=noise, guider=guider, sampler=sampler, sigmas=sigmas,
                latent_image=latent))[0]

            print("[OneForge] decoding…", flush=True)
            images = _core_nodes.VAEDecode().decode(vae, sampled)[0]
            log_lines.append(f"sampled: {images.shape[0]}f")
        else:
            log_lines.append(f"generate: skipped (images wired in, {images.shape[0]}f)")

        # ---------------- 2. forge (SuperForge engine, untouched) ----------------
        print("[OneForge] forging pixels…", flush=True)
        forge_out = PixelForgeSuperForge().run(
            images, alpha=alpha, custom_palette_image=custom_palette_image,
            **forge)
        f_images, f_alpha, durations_json, palette_json, forge_report = forge_out["result"]
        forge_ui = forge_out.get("ui", {})

        # ---------------- 3. export (EasyExport engine, untouched) ----------------
        print("[OneForge] exporting…", flush=True)
        exp = PixelForgeEasyExport().run(
            f_images, filename_prefix, export_fps, make_gif, gif_size,
            make_sheet, sheet_columns, sheet_bg, build_aseprite, aseprite_path,
            alpha=f_alpha, durations_json=durations_json or None)
        frames, sheet, export_report = exp["result"]
        exp_ui = exp.get("ui", {})

        ui = dict(forge_ui)
        # NEVER forward exp_ui["images"]/["animated"] to the node-level ui:
        # the frontend bolts its own native image-preview widget onto any node
        # that emits ui.images — that widget joins the layout's space
        # distribution and steals ~half the suite's height (the "half-size
        # lock" glitch) AND draws the sprite outside the suite canvas. The
        # export GIF goes out under our own key instead, and the suite shows
        # it as a live "Export" stage in its own canvas/timeline.
        gifs = exp_ui.get("images") or []
        if gifs:
            ui["pf_export_gif"] = gifs

        # Sheet preview: ship the packed sprite sheet as a temp image under
        # our own key so the suite shows it as a "Sheet" stage next to the
        # live Export GIF (flat list — survives the server ui flatten).
        try:
            if make_sheet and sheet is not None and hasattr(sheet, "shape") \
                    and sheet.shape[0] > 0:
                import uuid as _uuid
                srefs, _smeta = _save_stage("sheet", _uuid.uuid4().hex[:10],
                                            sheet, None, 1, max_edge=2048,
                                            pixel_exact=True)
                if srefs:
                    ui["pf_sheet"] = srefs
        except Exception as e:
            log.warning("[OneForge] sheet preview failed: %s", e)

        head = " | ".join(log_lines)
        full_forge_report = f"{head} | {forge_report}" if head else forge_report
        return {
            "ui": ui,
            "result": (f_images, f_alpha, durations_json, palette_json,
                       full_forge_report, frames, sheet, export_report),
        }


def _comfy_samplers():
    import comfy.samplers
    return list(comfy.samplers.KSAMPLER_NAMES)


def _comfy_schedulers():
    import comfy.samplers
    return list(comfy.samplers.SCHEDULER_NAMES)


NODE_CLASS_MAPPINGS = {"PixelForgeOneForge": PixelForgeOneForge}
NODE_DISPLAY_NAME_MAPPINGS = {"PixelForgeOneForge": "ᛒᛚᚢᛒ Pixel Forge (all-in-one)"}
