# ᛒᛚᚢᛒ ONE FORGE — single-node workflow checklist

Goal: the entire super-forge workflow stack collapses into ONE node. No pin
links, no supporting cast — loaders, sampler, LoRA, prompt, forge pipeline,
and export all live under the suite UI, grouped into tabs.

Non-destructive: `PixelForgeSuperForge` and every existing node/workflow keep
working untouched. One Forge is a new additive node (`PixelForgeOneForge`).

## Stack being absorbed (from pixelforge_h3_super_forge.json)

- [x] UNETLoader (minimax_h3_fl2va pruned int8) → Models tab
- [x] CLIPLoader (qwen3vl minimax) → Models tab
- [x] VAELoader (video VAE) → Models tab
- [x] ModelAttentionBackend (comfy kitchen attention) → Speed tab
- [x] MiniMaxChunkFeedForward (chunks/threshold) → Speed tab
- [x] MiniMaxH3TurboLoRA (lightx2v 4-step + strength) → Models tab
- [x] PixelForgeEasyPrompt (character/action/style/seconds/loop) → Prompt tab
- [x] ResolutionSelector → Resolution tab (preset combo + custom w/h)
- [x] MiniMaxH3ReferenceToVideo (t2v + ref-anchored conditioning) → internal call
      (switched from ImageToVideo 2026-08-15; i2v fallback kept for old cores)
- [x] RandomNoise (seed) → Sampling tab
- [x] BasicGuider → internal call
- [x] KSamplerSelect (er_sde default) → Sampling tab
- [x] PixelForgeH3PixelSampler (temporal_blend/loop_noise/edge_commit) → Sampling tab
- [x] PixelForgeH3FlatSigmas (scheduler/steps/tail_compress) → Sampling tab
- [x] SamplerCustomAdvanced → internal call
- [x] VAEDecode → internal call
- [x] PixelForgeSuperForge (full forge pipeline + stage previews) → Forge tab (reused as-is)
- [x] PixelForgeEasyExport (GIF/sheet/aseprite) → Export tab (reused as-is)

## ref2va switch (2026-08-15)

- [x] Conditioning moved from `MiniMaxH3ImageToVideo` to
      `MiniMaxH3ReferenceToVideo` (owner request): one path does t2v (no refs)
      AND reference-anchored gen. `first_frame` socket is now reference
      `<Picture 1>`; new optional `ref_image_2` socket = `<Picture 2>`; tags are
      auto-appended to the built prompt when refs are wired. New
      `ref_image_size` widget (match/max) in the Generate → References tab.
      audio_vae passed None (sprite pipeline is silent; R2V only touches it for
      audio refs, which OneForge deliberately doesn't expose). Automatic
      fallback to `MiniMaxH3ImageToVideo` on cores without ref2va.
- [x] Bug found + fixed: `__init__.py` merged `**_OF_D` but not `**_OF_C` —
      One Forge never actually registered before this.
- [x] Smoke: `_smoke_oneforge.py` (pack load, 103 widgets, sockets) +
      `_smoke_oneforge2.py` (mocked H3: refs→R2V with tags, no-refs→clean t2v,
      R2V-missing→i2v fallback) ALL PASS.

## Deliberately NOT absorbed (and why)

- Audio VAE / VAEDecodeAudio / CreateVideo / SaveVideo — sprite work doesn't
  use H3's audio track; raw video save may come back later as an option.
- PreviewImage — the suite's stage timeline already shows every frame.
- LoadImage edit path — covered by the optional `images` socket: wire anything
  in and generation is skipped (node becomes forge+export only).

## UI

- Right panel gets tabs: **⚡ Generate** (Prompt / Resolution / Models /
  Sampling / Speed) · **🎨 Forge** (existing quick knobs + all adv sections)
  · **📦 Export** (filename, fps, gif/sheet/aseprite).
- Seed gets a 🎲 reroll button in the suite.
- character/action fields render as multiline text areas.

## Optional sockets (only pins left, all optional)

- `images` — bypass generation, forge an existing batch
- `alpha` — external matte
- `first_frame` — reference picture, becomes `<Picture 1>` (character anchor)
- `ref_image_2` — second reference, becomes `<Picture 2>`
- `custom_palette_image` — fixed palette source

## Status

- [x] Backend `pf_oneforge.py`
- [x] Suite UI tabs in `pf_studio.js`
- [x] ref2va switch + `ref_image_size` widget + `ref_image_2` socket (2026-08-15)
- [x] `__init__.py` class-mapping fix (`**_OF_C` was never merged) (2026-08-15)
- [x] Example workflow JSON `example_workflows/pixelforge_h3_one_forge.json`
      (one node, zero wires, 103 widgets validated against INPUT_TYPES)
- [x] README section (suite: Super Forge + One Forge)
- [ ] Live test: restart ComfyUI, open the one-forge workflow, queue a gen,
      confirm stage previews + export land (owner hands-on)
- [ ] Commit + push (after live test passes)
