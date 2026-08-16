# ᛒᛚᚢᛒ Super Pixel Forge v3 — Aseprite-Like Layer System

## Vision

Transform the Super Pixel Forge from a "pipeline stage viewer" into a **real sprite animation workspace** — Aseprite-style layers, keyframes, compositing, canvas tools, and surgical regeneration. The canvas becomes a live compositing workspace where sprites are generated, placed, edited, and animated across multiple independent layers.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│  LAYER MODEL (frontend state, persisted in node.properties)     │
│  ┌─────┐ ┌─────┐ ┌─────┐                                       │
│  │ L3  │ │ L2  │ │ L1  │  ← each layer has frames[], opacity,  │
│  │back │ │char │ │fx   │    visibility, blend, transform       │
│  └─────┘ └─────┘ └─────┘                                       │
├─────────────────────────────────────────────────────────────────┤
│  COMPOSITING ENGINE (per-frame, bottom-to-top)                  │
│  For each frame: blend all visible layers → final composite     │
├─────────────────────────────────────────────────────────────────┤
│  CANVAS (interactive, multi-tool)                               │
│  Pointer | Move | Marquee | Placement Dot | Draw               │
├─────────────────────────────────────────────────────────────────┤
│  TIMELINE (Aseprite-style)                                      │
│  Layer rows with visibility/opacity/lock + keyframe diamonds    │
│  Frame cels show composited thumbnails                          │
├─────────────────────────────────────────────────────────────────┤
│  GENERATION (H3 → target layer)                                 │
│  New layer | Current layer | Fit to selection | Placement dot   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Data Model

### Layer
```javascript
{
  id: "layer_abc123",
  name: "Character",
  visible: true,
  opacity: 1.0,           // 0.0 – 1.0
  blend: "normal",        // normal | multiply | screen | overlay
  locked: false,
  frames: [               // sparse array — undefined = empty cel
    { img: <Image>, source: "generated"|"imported"|"drawn" },
    undefined,            // empty frame
    { img: <Image>, source: "generated" },
    ...
  ],
  transform: {            // per-layer default transform
    x: 0, y: 0,          // position offset (pixels)
    scale: 1.0,
    anchorX: 0.5,         // 0–1, relative to sprite width
    anchorY: 1.0,         // 0–1, bottom center by default
  },
  keyframes: {            // keyed transforms (frame → transform delta)
    0: { x: 0, y: 0, scale: 1.0 },
    12: { x: 0, y: -4, scale: 1.0 },
  },
  // Pipeline debug data (hidden by default, toggle via "Debug stages" button)
  _debugStages: null,     // populated when pipeline stages are captured
}
```

### Forge State (extends current `st`)
```javascript
{
  // ... existing state (fps, playing, zoom, pan, etc.) ...

  // NEW: layer system
  layers: [],             // ordered bottom-to-top
  activeLayer: 0,         // index of selected layer
  activeFrame: 0,         // current frame for editing
  totalFrames: 0,         // max frames across all layers

  // NEW: canvas tools
  tool: "pointer",        // pointer | move | marquee | place | draw
  marquee: null,          // { x, y, w, h } or null
  placementDot: null,     // { x, y } or null (null = canvas center)
  showPlacementDot: true,

  // NEW: generation target
  genTarget: "new",       // "new" | "current" | <layerId>
  genFrameStart: 0,       // first frame to fill
  genFrameEnd: -1,        // -1 = all frames

  // Pipeline stages moved to debug mode
  debugStages: {},        // keyed by stage name (source, keyed, etc.)
  showDebugStages: false,
}
```

### Backend UI payload (pf_studio.py changes)
```python
# Current: flat pf_frames list
# New: pf_layers list + per-layer frames
{
    "pf_layers": [
        {
            "id": "gen_abc123",
            "name": "Generated",
            "frames": [  # flat list, index = frame number
                {"filename": "pf_L_abc123_f000.png", "subfolder": "", "type": "temp"},
                {"filename": "pf_L_abc123_f001.png", ...},
            ],
            "meta": {"w": 64, "h": 64, "frameCount": 53},
            "source": "forge",  # "forge" | "imported" | "drawn"
        }
    ],
    "pf_frame_count": 53,
    "pf_report": "OK: 53 frames @ 64×64 | ...",
    # Debug stages (hidden by default, toggled via UI)
    "pf_debug_stages": [
        {"stage": "source", "frames": [...]},
        {"stage": "keyed", "frames": [...]},
        ...
    ],
    "pf_palette": [...],
}
```

---

## Checklist

### Phase 1: Data Model + Layer State (frontend only) — ✅ DONE
- [x] Define Layer data structure in JS
- [x] Add `layers[]`, `activeLayer`, `activeFrame` to `st`
- [x] Add layer management functions: addLayer, removeLayer, duplicateLayer, reorderLayer
- [x] Add layer visibility/opacity/lock toggle functions
- [x] Add keyframe management: addKeyframe, removeKeyframe, interpolateTransforms
- [x] Persist layer state in `node.properties.pfs_layers`
- [x] Add canvas tool state: tool, marquee, placementDot
- [x] Add generation target state: genTarget ✅ + genFrameStart/End via the
  surgical-regen window (regenWindow state + gen_win_start widget, Phase 9)

### Phase 2: Backend Layer Support (pf_studio.py) — mostly done
- [x] Change `pf_frames` output to `pf_layers` format (list of layer objects with frames)
- [x] Add `pf_frame_count` to UI payload
- [x] Move pipeline stage frames to `pf_debug_stages` (hidden by default)
- [x] Add layer-aware compositing: save each layer's frames as separate files
- [x] Add `target_layer` input parameter (optional, for generation targeting)
- [x] Add `placement_x`, `placement_y` input parameters (for centering dot)
- [ ] Add `selection_box` input parameter (for marquee fit-to-selection)

### Phase 3: Timeline Rewrite (frontend) — mostly done
- [x] Redesign timeline HTML: real layer rows instead of stage rows
- [x] Layer row controls: eye icon (visibility), opacity badge, lock icon, name label
- [x] Keyframe diamonds on timeline (rendered on keyed cels)
- [x] Frame cels show per-layer thumbnails (layer's own frame; composited-thumb option TODO)
- [ ] Drag to select multiple frames, right-click context menu
- [~] Layer reorder: up/down buttons done; drag-reorder TODO
- [x] Add/remove/duplicate layer buttons at bottom of timeline
- [x] Scrub indicator (vertical playhead line + click-to-scrub header)

### Phase 4: Canvas Compositing (frontend) — ✅ DONE
- [x] Per-frame compositing: iterate layers bottom→top, apply opacity/blend
- [x] Draw composited result to canvas (replaces current single-layer draw)
- [x] Onion skin works on composited result
- [x] Grid overlay works on composited result
- [x] A/B split works on composited result vs source

### Phase 5: Canvas Tools (frontend) — mostly done
- [x] Tool palette (toolbar buttons): Pointer, Move, Marquee, Place, Draw
- [x] **Pointer tool**: pan canvas (current behavior), click to deselect
- [x] **Move tool**: click-drag to move active layer's content; cursor changes to 4-way arrow
- [x] **Marquee tool**: click-drag selection rectangle + Escape/click-outside clear;
  constrains the forge to the marquee box (synced to `selection_*` widgets at
  queue time; final frames are cropped to the rect)
- [~] **Placement dot**: draggable + toggleable done; pixel-grid snap + double-click reset TODO
- [x] **Draw tool**: basic pixel painting on active layer
  - Left-click to paint with foreground color (brush color picker in toolbar)
  - Brush size: 1px (pixel-art correct); stroke = paintLine interpolation
  - Paints into the active layer's current frame (per-frame offscreen canvas)
  - Right-click erase TODO

### Phase 6: Layer Compositing + Rendering — mostly done
- [x] `compositeFrame(frameIndex)` function: iterate layers, blend onto offscreen canvas
- [x] Cache composited frames to avoid re-compositing every draw
- [x] Invalidate cache when layer visibility/opacity/content changes
- [ ] Export composited frames (for GIF/sheet generation)

### Phase 7: Generation Integration — mostly done
- [x] When generation completes, auto-create layer or fill target layer
- [x] "New layer" mode: create fresh layer with generated frames
- [x] "Current layer" mode: fill selected layer's frames (overwrite)
- [x] Placement dot offset applied during generation (backend reads placement_x/y)
- [ ] Marquee selection constrains generation output (backend reads selection_box)
- [x] Generation targeting UI: dropdown in toolbar ("Gen→" New Layer / Current / layer names)
- [x] Layer-aware preview: show composited result, not just one layer

### Phase 8: Ref Input Support (Chain Studio-style ref genning) — ✅ DONE
- [x] Reference images can be placed as dedicated reference layers (🔖 toggle
  on any layer, or 📥 import an image file straight into a ref layer)
- [x] Reference layers are locked + semi-transparent by default (40% opacity;
  single-frame refs show on every frame; never inflate the composite canvas;
  imported refs re-fetch from temp after reload via persisted `refFile`)
- [x] Ref2va conditioning respects placement dot position (suite syncs the
  dot → `placement_x/y` widgets at queue time; `_load_drawn_ref` offsets the
  ref by dot × integer upscale factor; also nudges fixed-canvas crops)
- [x] **Character-slot refs (Chain Studio parity)**: gen-ref slots P1/P2 in
  the layer bar — push the ACTIVE layer's current frame into `<Picture 1>` /
  `<Picture 2>` (new hidden `drawn_ref_image_2` widget for slot 2; prompt
  tags now follow the ACTUAL slots used, not a 1..N range). A wired socket
  still wins over each slot.
- [x] Drawn/painted layer content can be pushed straight into a ref slot
  (draw it → P1/P2 → gen from it; drawn-ref composite toggle still works)
- [x] **Reference video clips → `<Video k>` tags**: V1 slot in the layer bar
  (next to P1/P2) — import a 2-15s clip (≤50MB, goes to the input dir like
  Chain Studio panel media), the backend decodes + resamples it to 24fps and
  passes it to ref2va as `ref_videos` (`ref_video_1` hidden widget, kept last
  for workflow alignment). Silent pipeline: soundtracks dropped, audio_vae
  never touched. Prompt auto-binds "The motion and style match `<Video 1>`."
  (only tags the prompt doesn't already name, Chain Studio bind semantics)
- [x] Generation targeting actually honored on ingest: Gen→ New/Current/
  named layer fills in place (identity/transform/keyframes survive regen),
  and USER layers (refs/imports/painted) are never wiped by executions
- [x] Marquee → backend: suite syncs marquee → `selection_x/y/w/h` widgets
  at queue time; the forge crops final frames to the selection rect

### Phase 9: Advanced Features — partially done
- [x] Chain Studio-style surgical regeneration:
  - Drag across cels on a layer row = frame-range selection (orange highlight;
    plain click still just moves the cursor)
  - "Regen frames a–b" / "Regen this frame" in the timeline context menu
  - Partial frame ranges honored end-to-end: seconds snaps up to H3's 17k+5
    grid to cover the range (round-trip verified), a fresh seed busts the
    cache, gen targets the layer, and ingest SPLICES the new frames over
    [start, start+count) only — cels outside the range stay untouched
- [x] **Timeline right-click context menu (smooth, Chain Studio-style)**:
  regen this frame/range · copy/paste cel · duplicate cel · insert blank ·
  clear · delete (shift) · duplicate/delete layer. (Chain items — continue
  from here / use as context — land with Phase 11, when chains exist.)
- [x] **Prompt lane on the timeline (Chain Studio parity)**: dedicated PROMPT
  lane above the layer rows (One Forge only); right-click lane/header to add
  a segment clip, dbl-click to edit (floating editor — window.prompt is dead
  in Electron), drag body to move, drag edges to resize. Segments overlapping
  the gen window append to the base prompt in timeline order via hidden
  `prompt_segments` + `gen_win_start` widgets (synced at queue time);
  `<Picture i>` / `<Video k>` tags in segment text pass through and suppress
  auto-bind dupes. Persisted in node.properties.
- [x] Layer blending modes (multiply, screen, overlay) — applied in compositeFrame
- [ ] Frame timing overrides (per-frame duration for non-uniform animation)
- [ ] Layer group/folder support (group background layers, etc.)
- [ ] Undo/redo for canvas edits and layer operations
- [x] Keyboard shortcuts (V=pointer, M=move, S=marquee, P=place, B=draw, [/]=layer switch, Esc=clear marquee)

### Phase 10: Export + Aseprite Bridge — NOT STARTED
- [ ] Export composited animation as GIF (replaces current export stage)
- [ ] Export individual layers as separate GIFs
- [ ] Export layer stack as .aseprite file (with layers preserved)
- [ ] Sprite sheet export from composited frames
- [ ] Aseprite bridge: import .aseprite files as layer stacks

### Phase 11: H3 chain continuation + video-to-video (Chain Studio parity) — NOT STARTED
Build video continuation on the existing **ComfyUI-H3-Motion-Context** engine
(interior keyframe anchors carry motion AND audio across clip joins) so long
animations are chained clips instead of one drifting mega-gen:
- [ ] **Video continuation**: continue the chain from the last clip — next
  gen picks up exact motion/direction/speed where the previous clip ended
  (H3 Motion Context: `continue_from` auto / specific clip semantics)
- [ ] **Clip slots + fingerprint matching**: reuse the chain folder /
  `chain_index.json` format so the Super Forge and Chain Studio can share
  the same chains (match distance ≤ 0.20, re-roll vs advance behavior)
- [ ] **Regen-in-place**: regenerate one clip in the middle of a chain —
  context comes from its parent clip, save overwrites its slot
  (Chain Studio `regen_clip` semantics; root regen = plain redo)
- [ ] **Video-to-video**: load an external video/image as continuation
  context (`context_video`) — re-render existing footage through the forge,
  or use it as the chain seed (fingerprint matching still applies;
  `if_no_match` = start_fresh / refuse)
- [ ] **Gen window on the timeline**: the chain renders as clip segments on
  the timeline; picking a segment + continue/regen drives `continue_from` /
  `regen_clip` exactly like Chain Studio's panel buttons
- [ ] Trim/preview per clip (`trim_frames` carried across, Chain Output
  parity) so chained clips land on the sprite frame grid cleanly

---

## UI Layout (Target)

```
┌──────────────────────────────────────────────────────────────────┐
│ ᛒᛚᚢᛒ SUPER PIXEL FORGE  │ [A/B] [◐] [▦] [🎨] [▤] │ [-] 4.3x [+] [⤢] │
├──────┬───────────────────────────────────────┬──────────────────┤
│TOOLS │                                       │ FORGE PARAMETERS │
│      │                                       │                  │
│ [V]  │        CANVAS (composited view)       │ Quick Forge:     │
│ [M]  │                                       │ Size | Look | .. │
│ [⬚]  │   ● placement dot (draggable)        │                  │
│ [+]  │                                       │ ▸ Background     │
│ [✎]  │                                       │ ▸ Grid Recover   │
│      │                                       │ ▸ Look Engine    │
│──────│                                       │ ▸ Motion Fix     │
│PAL   │                                       │                  │
│32col │                                       │ Layer Controls:  │
│      │                                       │ [▼ bg] [🔒] [40%]│
│──────│                                       │ [▼ char] [👁]    │
│STAGE │                                       │ [▼ fx] [👁]      │
│Layer1│                                       │ Target: [v] New  │
│report│                                       └──────────────────┘
├──────┴───────────────────────────────────────────────────────────┤
│ ▶ ⏮ ◀ 12fps 🔁 │ 📐: 64×64 │ 🎯: Character │ Gen: [New Layer]  │
├─────────────────────────────────────────────────────────────────┤
│ LAYERS \ FRAMES │  1  2  3  4  5  6  7  8  9 10 11 12 13 ...  │
├─────────────────┼──────────────────────────────────────────────┤
│ ● Background    │  ◆ ── ◆ ── ◆ ── ◆ ── ◆ ── ◆ ── ◆ ── ◆     │
│ ● Character  👁 │  ◆ ── ◆ ── ◆ ── ◆ ── ◆ ── ◆ ── ◆ ── ◆     │
│ ● Effects    👁 │  ─ ─ ─ ─ ─ ─ ◆ ── ◆ ── ◆ ── ◆ ── ─ ─ ─     │
│ ● FX Glow    👁 │  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ◆ ── ◆ ── ◆ ── ◆     │
├─────────────────┴──────────────────────────────────────────────┤
│ FINAL Frame: 1/53  │  Sprite: 64×64  │  Zoom: 4.3×  │  24 colors │
└─────────────────────────────────────────────────────────────────┘
```

---

## Key Design Decisions

1. **Pipeline stages become debug-only**: Source/Keyed/Grid/Look/Motion/Final are debugging aids, not layers. Toggle with a "Debug stages" button. The main canvas always shows the composited result.

2. **Layers are compositable**: Each layer is an independent sprite element with its own frames, opacity, visibility, blend mode, and transform. The canvas composites all visible layers per-frame.

3. **Placement dot is the generation anchor**: When generating a new sprite, it appears centered on the placement dot (or constrained to the marquee selection). This lets you build complex multi-element sprites by placing each generation precisely.

4. **Keyframes store transform data**: Each keyframe records {x, y, scale} at a specific frame. Between keyframes, transforms are linearly interpolated. This enables smooth animation of layer positions without regenerating.

5. **Generation targets layers**: When you generate, you choose which layer receives the frames. "New Layer" creates a fresh layer. "Current Layer" fills the selected layer. This is how you build up complex sprites iteratively.

6. **Backward compatible**: The backend still returns frames — the frontend just interprets them as a single default layer. Existing workflows continue to work.

7. **Chain Studio parity for genning**: Refs, prompting, and continuation follow the ComfyUI-H3-Motion-Context Chain Studio model — panel-driven character slots (`<Picture i>`), reference video tracks (`<Video k>`), a global prompt + timeline prompt lane, and clip-chain continuation/regen via the H3 Motion Context engine (shared chain folder format, so chains made in either UI work in both). The Super Forge becomes the sprite-side editor on top of the same chain: gen/continue/regen in H3 land, then the forge pipeline pixelizes each clip onto its layer.
