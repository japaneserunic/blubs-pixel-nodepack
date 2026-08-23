# ᛒᛚᚢᛒ Super Pixel Forge — build checklist

**Goal:** one epic all-in-one ComfyUI node — a full pixel-art *workspace suite*
living inside a single node. Canvas, timeline, transport controls, stage
inspector, every parameter reachable, main ones obvious. Takes its cues from
the MiniMax Chain Studio (`minimax_director.js`, 540 KB of DOM-over-node UI)
and goes further: this one is a *post-processing workbench*, not a prompt
timeline.

**Non-destructive rule:** nothing existing changes behavior. The suite is a
new file (`pf_studio.py`) + new frontend (`web/js/pf_studio.js`) that *wrap*
the battle-tested engines in `pf_pixelize / pf_sprite / pf_grid / pf_temporal /
pf_finalize`. Old nodes, old workflows, and the Easy v2 nodes keep working
bit-identically. De-rope work stays parked until the suite lands.

## Design

```
┌─ ᛒᛚᚢᛒ SUPER PIXEL FORGE ────────────────────────────────────────┐
│ toolbar: stage tabs | play/pause/loop | fps | zoom/fit | onion  │
├──────────────────────────────────────┬──────────────────────────┤
│                                      │  QUICK FORGE (main knobs)│
│   CANVAS  (checkerboard, pixel-      │  size / look / palette   │
│   perfect nearest zoom, pan, onion   │  bg+key / motion / loop  │
│   skin, grid overlay)                ├──────────────────────────┤
│                                      │  STAGE INSPECTOR         │
│                                      │  key→grid→look→motion→   │
│                                      │  crop→loop→dedup toggles │
│                                      │  + per-stage advanced    │
├──────────────────────────────────────┴──────────────────────────┤
│ TIMELINE: frame thumbnails · scrubber · durations · loop marker │
└─────────────────────────────────────────────────────────────────┘
```

### Backend — `pf_studio.py` (`PixelForgeSuperForge`, category `PixelForge/Suite`)
- [x] Full parameter surface: every Easy v2 knob **plus** the advanced engine
      params Easy hides (keyer despill/erode/shadow, grid min/max block +
      reduce mode, quantize mapping/method/sat/contrast/sharpen/flatten/
      temporal_lock, truepixel bands/hue_shift/outline, temporal
      threshold/commit/max_hold, crop padding/snap, loop similarity, dedup
      threshold) — grouped so the *main* knobs sit on top. (70 widgets;
      adv_* use -1/"preset" sentinel = inherit from the main knobs.)
- [x] Stage capture: after each pipeline stage, stash the frame batch
      (`source → keyed → grid → look → motion → final`) and emit all of them
      as temp previews in the `ui` result under a custom `pf_stages` key.
      This is the killer feature: you *see* exactly where quality is lost
      (direct answer to the "processed output worse than raw H3" problem).
- [x] Outputs: `images, alpha, durations_json, palette_json, forge_report`
      (same contract as Sprite Studio Easy v2 — drop-in wire-compatible).
- [x] Preview thinning: cap stage previews at N frames (even stride) so a
      100-frame run doesn't ship 600 PNGs to the browser.
      (`preview_max_frames`, default 64.)
- [x] `WEB_DIRECTORY = "./web"` registered in `__init__.py`.

### Frontend — `web/js/pf_studio.js`
- [x] Extension registered for node `PixelForgeSuperForge`; DOM widget host
      built in `onNodeCreated` (Director pattern: hidden state widget +
      injected stylesheet, one root container).
- [x] **Canvas**: checkerboard alpha backdrop, nearest-neighbor zoom (1×–32×),
      fit-to-view, drag-pan, onion-skin (prev/next ghost), optional pixel-grid
      overlay at high zoom.
- [x] **Transport**: play/pause/loop, fps control (honors dedup durations),
      frame counter, click/drag scrub.
- [x] **Timeline**: thumbnail strip, current-frame highlight, click to seek, drag to scrub. (Loop-point marker: pending - loop cut info needs to reach the ui payload first.)
- [x] **Stage tabs**: source / keyed / grid / look / motion / final — instant
      switching between the captured stage previews; A/B split view (final
      vs source side-by-side) for the 1:1 fidelity check.
- [x] **Quick Forge strip**: DOM controls two-way-mirrored to the node's main widgets (size, look, palette, colors, background, key strength, grid, motion fix, loop mode) — the "super obvious" knobs live in the suite UI *and* stay
      real widgets so workflows/API still work.
- [x] **Resize**: UI tracks node resize (`onResize` + `ResizeObserver`),
      sensible min size, canvas redraws on any geometry change.
- [x] **Serialization**: UI state persisted via node.properties.pfs_ui (NOT a widget - never dirties the prompt hash). Restores on workflow load.

### Wiring & integration
- [x] Register node in `__init__.py` (additive; no existing mappings touched).
- [x] Smoke test: pack import + full pipeline run on synthetic batch
      (both quantize and hi-bit look paths, adv overrides, stage capture to
      temp, zero missing preview files) — `_smoke_studio.py`,
      `_smoke_studio2.py`. JS passes `node --check`.
- [x] Live test in ComfyUI (browser-driven, 2026-08-15): stage previews land
      inside the suite canvas (5-stage replay, 12/12 frames loaded), timeline +
      palette populate, ui.images leak defense holds (node.imgs stays 0), zero
      stray widgets, save/reload restores full-frame layout. Resize stress
      (7 rapid size changes incl. below-min): wrapper tracks every step after
      the authoritative-geometry watchdog fix. **Real-generation run (prompt →
      frames → export GIF as in-suite Export stage) still owner's hands-on.**
- [x] Example workflow `example_workflows/pixelforge_h3_super_forge.json` (generated from easy v2 by `_gen_superforge_wf.py`; wires preserved, 69 widget values validated, main knobs carried over).
- [x] README section (suite section covers Super Forge + One Forge; screenshot still nice-to-have).
- [ ] Commit + push (non-destructive, single feature commit) — after owner live test.

### Held / out of scope (per owner)
- [ ] ~~De-rope integration~~ — parked until suite + other updates land.
- [ ] Chain-style multi-shot timeline (that's the Director's job; forge is
      post-processing).
- [ ] In-canvas pixel *editing* (drawing) — future milestone; Aseprite bridge
      covers hand-editing for now.
