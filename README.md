# ComfyUI-PixelForge-H3

Turn **MiniMax H3** video output into real, game-ready **pixel-art sprite animations** —
palette-locked frames, keyed alpha, anchored crops, loop trimming, sprite sheets,
GIFs, and a headless **Aseprite bridge**. Fully self-contained: adds one folder under
`custom_nodes/`, modifies nothing else, and depends only on `torch`/`numpy`/`PIL`
(already in the ComfyUI venv).

## The pipeline

```
H3 (MiniMaxH3ImageToVideo / Director chain)
  -> KSampler -> VAEDecode (video VAE)          [IMAGE batch @24fps]
  -> H3 Frame Decimate        (24 -> 12 fps, sprite timing; every_nth=1 keeps all)
  -> Sprite Chroma Key        (flood: border-connected Lab removal, shadow-proof)
  -> Pixel Art Quantize       (wire images AND alpha: premultiplied downscale =
                               zero backdrop bleed; k-means palette from sprite
                               pixels only; flatten kills VAE grain)
  -> Sprite Auto-Crop & Anchor(union bbox, bottom-center anchor, no jitter)
  -> Sprite Loop Trim         (auto loop-point search / ping-pong / off)
  -> Sprite Frame Dedup       (drop duplicate holds -> durations_json)
  -> Sprite Sheet Pack        (grid sheet + Aseprite JSON-hash)
  -> Aseprite Export          (PNG seq + frames.json + .aseprite + sheet)
  -> Save Sprite GIF          (shared exact palette, transparency, in-app preview)
```

**Order matters: key BEFORE quantize.** Keying at full res gives a clean silhouette;
the quantize node's premultiplied downscale then keeps backdrop color out of the
sprite's edge pixels entirely. (Old workflows had key-after-quantize or the quantize
on a preview side-branch — the shipped examples are fixed.)

## The suite — ᛒᛚᚢᛒ Super Pixel Forge & One Forge

Two flagship nodes that wrap the stack in a full workspace UI: canvas with
pixel-perfect zoom/pan/onion-skin, **stage tabs that preview the frames after every
pipeline stage** (source → keyed → grid → look → motion → final), transport with fps
playback, and a frame timeline with thumbnails and scrubbing.

- **ᛒᛚᚢᛒ PIXEL FORGE** (`PixelForgeSuperForge`) — wire any decoded H3 batch in and
  forge it. Every Easy knob plus all advanced engine params, grouped so the main
  knobs stay obvious. The stage previews are the direct answer to "why does the
  processed sprite look worse than the raw H3 video?" — you see exactly which stage
  loses the quality. Example: `example_workflows/pixelforge_h3_super_forge.json`.
- **ᛒᛚᚢᛒ ONE FORGE** (`PixelForgeOneForge`) — the entire workflow collapsed into ONE
  node: model loaders, attention/FFN patches, turbo LoRA, prompt builder, **ref2va
  conditioning**, sampling, VAE decode, the full forge pipeline, and
  GIF/sheet/aseprite export. Suite UI is tabbed: ⚡ Generate (prompt / references /
  resolution / models / sampling / speed) · 🎨 Forge · 📦 Export. Optional sockets
  are the only pins: `images` (bypass generation, forge an existing batch),
  `first_frame` + `ref_image_2` (reference pictures — become `<Picture 1>` /
  `<Picture 2>`, tags auto-appended to the prompt), `alpha`,
  `custom_palette_image`.
  Example: `example_workflows/pixelforge_h3_one_forge.json` — one node, zero wires.

  Reference notes: conditioning runs through `MiniMaxH3ReferenceToVideo` — nothing
  wired = plain t2v; refs wired = reference-anchored gen. `ref_image_size`:
  `match` scales refs to the gen size (fast); `max` keeps refs at 2048px for best
  identity fidelity (several times slower). Reference anchoring needs a
  ref2va-capable checkpoint (e.g. a hybrid fl2va+ref2va build) — plain t2v works
  on any H3 checkpoint. On cores that predate the ref2va node, One Forge falls
  back to `MiniMaxH3ImageToVideo` automatically. Audio refs are intentionally not
  exposed — the sprite pipeline is silent and never needs the audio VAE.

## Nodes (category `PixelForge/*`)

### H3 integration
- **H3 Sprite Prompt** — sprite-tuned prompt for H3's Qwen3-VL encoder: style presets
  (SNES/NES/GBA/1-bit/CPS2/hi-bit), view, flat keyable background, static-camera and
  seamless-loop hints. Also outputs `length_frames` snapped to H3's **17k+5 grid @24fps**
  — wire it straight into `EmptyMiniMaxH3LatentAV` / `MiniMaxH3ImageToVideo.length`.
- **H3 Single Sprite Prompt** — still-sprite variant: a 5-frame (minimal grid) static
  hold. Pair with **Extract Single Frame** to pull the still.
- **H3 Sprite Edit Prompt** — ref2va edit mode: "edit `<Picture 1>`" instructions that
  lock character/pose/style/palette and change only what you ask. Feed the source
  sprite through **H3 Prep Sprite For Edit** into `MiniMaxH3ReferenceToVideo.ref_image_0`.
- **H3 Prep Sprite For Edit** — nearest-upscales a tiny sprite to a valid H3 canvas
  (multiple of 32) and pads with a keyable flat color; outputs matching width/height.
- **Extract Single Frame** — grab frame N (default 0) from a decoded batch.
- **H3 Frame Grid Snap** — seconds ↔ H3 frame-grid math utility.
- **H3 Video To Sprite Frames** — `VIDEO` → IMAGE batch with decimation
  (for LoadVideo or Director/chain VIDEO outputs).
- **H3 Frame Decimate** — same for IMAGE batches straight off `VAEDecode`.

### Pixel art core
- **Pixel Art Quantize** (v2 engine) — pre-boost (saturation/contrast/unsharp) so color
  survives the downscale, downscale to true pixel resolution, then a **k-means++ palette
  sampled across the whole batch** (or built-in PICO-8/NES/GAMEBOY/ENDESGA-32/SWEETIE-16/
  CGA/1-bit or custom-image palettes), **perceptual CIELAB color mapping**, Bayer 2/4/8 or
  Floyd–Steinberg dithering, **despeckle** (orphan-pixel majority cleanup — the pass that
  makes output read as hand-placed pixel art), nearest-neighbor upscale back to display
  size. Style presets: `modern_hibit` (clean contemporary, 64 colors, light dither),
  `retro_16bit`, `hardcore_8bit`, or `custom`. Batch-shared palette keeps animation
  colors temporally stable. Legacy `median_cut` + `rgb` mapping remain selectable.
- **Sprite Chroma Key** — `flood` method: border-connected background removal in
  Lab space keyed on **hue angle** (shadow-invariant), so the shadows/gradients H3
  paints on the green screen go away with it; `shadow_tolerance` controls how dark
  the backdrop may get. Hard 1-bit alpha by default (correct for pixel art); `key`
  method keeps the legacy global-distance behavior. Despill tames color bleed.
- **Sprite Auto-Crop & Anchor** — union or per-frame bbox, bottom-center/center anchor,
  padding, size snapping, nearest resize → jitter-free uniform frames.
- **Sprite Loop Trim** — auto: scans the tail for the frame closest to frame 0 and cuts
  the loop; ping-pong: appends reversed frames for a guaranteed seamless loop.
- **Sprite Frame Dedup** — merges consecutive look-alikes and emits `durations_json`.
- **Sprite Sheet Pack** — uniform grid packing + **Aseprite JSON-hash** metadata
  (with real per-frame durations when dedup is wired in).

### Export
- **Aseprite Export** — writes RGBA PNG sequence + `frames.json` manifest, then (if
  Aseprite is installed) drives `aseprite.exe -b` headless to build a tagged
  `.aseprite` and export a packed sheet + JSON. Aseprite path auto-detects from the
  node input, `ASEPRITE_EXE` env, common install locations, or `aseprite_path.txt`
  next to this pack. No Aseprite → PNGs + JSON only, nothing breaks.
- **Save Sprite GIF** — animated GIF with transparency + loop, previews in-app.

### Sampling (pixel-art tuned, for the turbo path)
- **H3 Flat Sigmas** — custom sigma schedule for the distilled 4-step turbo LoRA.
  `tail_compress` warps the schedule to front-load composition and skip the
  ultra-low-sigma tail (gradients/grain the quantize pass deletes anyway), so the
  VAE hands the quantizer flatter color fields for free. `0` = identical to
  `BasicScheduler`; try `0.3–0.5`. Plug into `SamplerCustomAdvanced.sigmas`.
- **H3 Pixel Sampler** — wraps any SAMPLER (e.g. `MiniMaxH3TurboSampler` or
  `KSamplerSelect`) between it and `SamplerCustomAdvanced`. Three knobs, all
  default `0` (off = bit-identical passthrough):
  - `temporal_blend` — correlates init noise across frames (variance-preserving),
    killing pixel shimmer / palette flicker at the source. Try `0.3–0.6`.
  - `loop_noise` — bends late-frame noise back toward frame 0 (quadratic ramp) so
    cycles actually loop. Try `0.2–0.5`.
  - `edge_commit` — final-latent grain damping (3×3 binomial mix, video half only),
    softening the ringing that becomes keying halo. Try `0.2–0.4`.

### Grid recovery
- **Pixel Grid Recover** — detects the block grid H3 already rendered (block size +
  phase) and block-reduces frames back to the TRUE art grid (median / majority /
  nearest per block). Chain BEFORE Chroma Key / Quantize; fixes "64×64 target reads
  like 16×16" and gives the keyer hard pixel edges. `manual` + block `1` = passthrough.

### Temporal stabilization
- **Temporal Stabilize / Crawl Killer** — kills pixel creep/crawl (edges H3 redraws
  slightly differently every frame, so recovered pixels oscillate across frames).
  Place right AFTER Pixel Grid Recover (small true-grid frames = cheap, and each
  pixel is one real art pixel), BEFORE key/quantize. Modes:
  - `hysteresis` (default) — a pixel only commits a color change when the new color
    persists for `commit_frames` consecutive frames. One-frame blips never commit
    (crawl dies); persistent motion passes with ≤1 frame of delay.
    **Starvation escape (`max_hold`)**: a pixel that has NOT matched its committed
    color for `max_hold` consecutive frames force-commits to the current color.
    This matters: continuously-moving regions (legs mid-swing) change color every
    frame, so without the escape they never persist long enough to commit and
    freeze on a stale color — visible as "sandblasted" patches on moving parts.
    Oscillating crawl still dies, because it keeps returning to the committed
    color and resets the escape counter before it fires. Defaults
    (commit 2 / max_hold 3) are right for H3 run cycles; raise `max_hold` if fast
    motion looks one frame late, lower `threshold` if subtle shading flickers.
  - `median3` — 3-frame temporal median. Softer, cheaper, but also eats legitimate
    1-frame events (muzzle flashes, impacts).
  - `off` — bit-identical passthrough.

### True pixel finalize (optional style branch)
- **True Pixel Finalize** — the "modern hi-bit" engine: edge-preserving bilateral
  flatten, subject/background segmentation with separate palette budgets,
  de-muddied k-means palette (centroids pulled toward each cluster's most vibrant
  core pixel), cel-band shading with hue-shifted ramps (shadows→indigo,
  highlights→amber), silhouette outline, crisp 1-bit alpha. This is a **style
  change**, not a cleanup — for the clean v3 look keep it on a preview side-branch
  with `bands=1`, `hue_shift=0`, neutral saturation/contrast/sharpen (the v4
  workflow ships it exactly like that). Turn `bands`→3 and `hue_shift`→0.3 for the
  full cel look. Wire Grid Recover's `grid_width`/`grid_height` into
  `pixel_width`/`pixel_height` and keep `pixel_grid=manual` so it never re-scales
  the recovered grid.
- **Segment Color Mask** — standalone redmean color-key region extractor (any
  match / border-connected backdrop / largest island) with grow/erode and a
  tinted preview, for pulling subjects or regions out of H3 frames.

## Aseprite extension (the other direction)

`aseprite_extension/pixel-forge-bridge/` is a real Aseprite extension:
zip it, rename to `.aseprite-extension`, add via *Edit → Preferences → Extensions*
(or drop the folder in Aseprite's `extensions/` dir). It adds
**File → Import → Import PixelForge Run…**: pick any `frames.json` the export node
wrote and Aseprite rebuilds the document with frames, durations, and tag.

## Workflow tips for clean sprites from H3

- Ask for a **flat chroma background** (the prompt node does) — keying beats matting.
- Keep generations short: **2–4 s** (loop a walk cycle, don't render 15 s).
- Lower fps reads more "sprite": decimate 24 → **12 or 8 fps**.
- Quantize with **shared_palette = on** — per-frame palettes cause color flicker.
- If H3 drifts off-model, regenerate the first frame as an image (ref2va keyframe)
  instead of fighting the video prompt.

Example workflows (UI format — drag into ComfyUI):
- `example_workflows/pixelforge_h3_sprite.json` — full animated sprite run (t2v Turbo chain + pixel pipeline + sheet + Aseprite).
- `example_workflows/pixelforge_h3_sprite_v3.json` — v3: same run + **Grid Recover** before key/quantize, **Temporal Stabilize** (crawl killer) right after it, **H3 Pixel Sampler** (temporal_blend 0.3) and **H3 Flat Sigmas** (0 = stock, turn up to A/B) wired in.
- `example_workflows/pixelforge_h3_sprite_v4.json` — v4: v3 chain unchanged, plus **True Pixel Finalize** as a clean-mode preview side-branch (does not touch the v3 look; unbypass/restyle to taste).
- `example_workflows/pixelforge_h3_sprite_still.json` — single-sprite generation: 5-frame static hold → Extract Single Frame → pixelize → export.
- `example_workflows/pixelforge_h3_sprite_edit.json` — single-sprite editing: LoadImage → Prep For Edit → ref2va → frame 0 → quantize with the **original sprite's palette** → export.
