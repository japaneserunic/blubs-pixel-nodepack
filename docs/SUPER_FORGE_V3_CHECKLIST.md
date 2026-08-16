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

### Phase 1: Data Model + Layer State (frontend only)
- [ ] Define Layer data structure in JS
- [ ] Add `layers[]`, `activeLayer`, `activeFrame` to `st`
- [ ] Add layer management functions: addLayer, removeLayer, duplicateLayer, reorderLayer
- [ ] Add layer visibility/opacity/lock toggle functions
- [ ] Add keyframe management: addKeyframe, removeKeyframe, interpolateTransforms
- [ ] Persist layer state in `node.properties.pfs_layers`
- [ ] Add canvas tool state: tool, marquee, placementDot
- [ ] Add generation target state: genTarget, genFrameStart, genFrameEnd

### Phase 2: Backend Layer Support (pf_studio.py)
- [ ] Change `pf_frames` output to `pf_layers` format (list of layer objects with frames)
- [ ] Add `pf_frame_count` to UI payload
- [ ] Move pipeline stage frames to `pf_debug_stages` (hidden by default)
- [ ] Add layer-aware compositing: save each layer's frames as separate files
- [ ] Add `target_layer` input parameter (optional, for generation targeting)
- [ ] Add `placement_x`, `placement_y` input parameters (for centering dot)
- [ ] Add `selection_box` input parameter (for marquee fit-to-selection)

### Phase 3: Timeline Rewrite (frontend)
- [ ] Redesign timeline HTML: real layer rows instead of stage rows
- [ ] Layer row controls: eye icon (visibility), opacity slider, lock icon, name label
- [ ] Keyframe diamonds on timeline (click to add/remove, drag to move)
- [ ] Frame cels show composited sprite thumbnails (not individual stage frames)
- [ ] Drag to select multiple frames, right-click context menu
- [ ] Layer reorder via drag (up/down)
- [ ] Add/remove/duplicate layer buttons at bottom of timeline
- [ ] Scrub indicator (vertical line following playhead)

### Phase 4: Canvas Compositing (frontend)
- [ ] Per-frame compositing: iterate layers bottom→top, apply opacity/blend
- [ ] Draw composited result to canvas (replaces current single-layer draw)
- [ ] Onion skin works on composited result
- [ ] Grid overlay works on composited result
- [ ] A/B split works on composited result vs source

### Phase 5: Canvas Tools (frontend)
- [ ] Tool palette (toolbar buttons): Pointer, Move, Marquee, Place, Draw
- [ ] **Pointer tool**: pan canvas (current behavior), click to deselect
- [ ] **Move tool**: click-drag to move active layer's content; cursor changes to 4-way arrow
- [ ] **Marquee tool**: click-drag to draw selection rectangle; marching ants border
  - Selection constrains next generation to fit within the marquee box
  - Clear selection with Escape or clicking outside
- [ ] **Placement dot**: draggable orange dot on canvas
  - Shows where next generation will be centered
  - Toggleable visibility (button in toolbar)
  - Snaps to pixel grid at high zoom
  - Double-click to reset to canvas center
- [ ] **Draw tool**: basic pixel painting on active layer
  - Left-click to paint with foreground color (from palette)
  - Right-click to erase (set alpha to 0)
  - Brush size: 1px (pixel-art correct)
  - Paints into the active layer's current frame

### Phase 6: Layer Compositing + Rendering
- [ ] `compositeFrame(frameIndex)` function: iterate layers, blend onto offscreen canvas
- [ ] Cache composited frames to avoid re-compositing every draw
- [ ] Invalidate cache when layer visibility/opacity/content changes
- [ ] Export composited frames (for GIF/sheet generation)

### Phase 7: Generation Integration
- [ ] When generation completes, auto-create layer or fill target layer
- [ ] "New layer" mode: create fresh layer with generated frames
- [ ] "Current layer" mode: fill selected layer's frames (overwrite)
- [ ] Placement dot offset applied during generation (backend reads placement_x/y)
- [ ] Marquee selection constrains generation output (backend reads selection_box)
- [ ] Generation targeting UI: dropdown in toolbar ("New Layer" / layer names)
- [ ] Layer-aware preview: show composited result, not just one layer

### Phase 8: Ref Input Support (mentioned by user)
- [ ] Wire ref_image_2 input to layer system
- [ ] Reference images can be placed as dedicated reference layers
- [ ] Reference layers are locked + semi-transparent by default
- [ ] Ref2va conditioning respects placement dot position

### Phase 9: Advanced Features
- [ ] Chain Studio-style surgical regeneration:
  - Select specific frames on a layer → re-generate only those frames
  - "Regen selected" button in timeline context menu
  - Partial frame ranges for targeted regeneration
- [ ] Layer blending modes (multiply, screen, overlay) for effects
- [ ] Frame timing overrides (per-frame duration for non-uniform animation)
- [ ] Layer group/folder support (group background layers, etc.)
- [ ] Undo/redo for canvas edits and layer operations
- [ ] Keyboard shortcuts (V=pointer, M=move, S=marquee, P=place, B=draw)

### Phase 10: Export + Aseprite Bridge
- [ ] Export composited animation as GIF (replaces current export stage)
- [ ] Export individual layers as separate GIFs
- [ ] Export layer stack as .aseprite file (with layers preserved)
- [ ] Sprite sheet export from composited frames
- [ ] Aseprite bridge: import .aseprite files as layer stacks

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
