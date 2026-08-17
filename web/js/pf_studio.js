/* VERSION: v3.5.5-stepfix (2026-08-16) — ROOT CAUSE of the stuck-slider saga: frontend stores options.step x10 (raw in step2); sliders were 10x coarser, narrow ranges frozen solid
 * ᛒᛚᚢᛒ Pixel Forge suite — in-node workspace for PixelForgeSuperForge and
 * PixelForgeOneForge (all-in-one).
 *
 * Aseprite-style layout inside one ComfyUI node: big checkerboard canvas,
 * palette strip on the left, tabbed parameter panel on the right (Generate /
 * Forge / Export on One Forge), transport, and a layer-row x frame-column
 * timeline on the bottom where each pipeline stage (source/keyed/grid/look/
 * motion/final) is a "layer" and every cel is clickable. Every native widget
 * is hidden and mirrored into the panel (Director pattern), so widget values
 * stay the single source of truth (workflow save + API keep working); UI-only
 * state goes to node.properties and never enters the prompt hash.
 *
 * SIZING (do not regress): the suite declares a min-height floor through the
 * DOM-widget layout API (getMinHeight). Never derive the widget height from
 * node.size[1] (that ratchets — the "super tall" bug), and do NOT give the
 * widget a computeSize (that makes the frontend treat it as fixed height and
 * vertically locks the node). Floor, no ceiling; the layout engine hands the
 * suite whatever space the node has.
 *
 * LAYOUT WAR (the "half-size lock", do not reintroduce): the frontend's
 * _arrangeWidgets splits leftover node height between ALL non-hidden widgets
 * with a computeLayoutSize. If the node ever emits ui.images, the frontend
 * bolts a native image-preview widget (minHeight 220) onto it and the split
 * leaves the suite ~half the node — plus the sprite renders outside the
 * suite canvas. So: (1) backends must never emit node-level ui.images —
 * export previews ride the custom `pf_export_gif` key and are shown as the
 * "Export" stage INSIDE the suite; (2) node.hideOutputImages = true opts out
 * of the new frontend's node-level output-image overlay (the official flag
 * core's ImageCompositor/Painter set); (3) a watchdog below re-hides any
 * stray widget that appears after init and re-runs node.arrange() if the
 * suite's computedHeight ever drifts from the node's actual leftover space.
 * On Vue frontends the .dom-widget wrapper's geometry is owned reactively by
 * the frontend itself (position:fixed + transform, recomputed every draw) —
 * the watchdog must NOT write wrapper inline geometry there (that was the
 * "popping out of the node frame" glitch); it only fixes the layout DATA
 * (y / computedHeight / width) and lets the frontend position the wrapper; the
 * watchdog also pins widget.width to the live node width every tick, because
 * frontends >= ~1.48 compute the wrapper width as (widget.width ?? node.width)
 * - 2*margin on every draw - a stale widget.width is the horizontal half-size
 * lock. On legacy
 * frontends it still rewrites the wrapper geometry against its live values
 * every tick (the old frontend's own geometry sync read stale layout state
 * after a resize, then stopped when the canvas was no longer dirty).
 *
 * MASK REAPER (v3.4.3, hardened v3.4.4 with a stuck-spinner sweep): a global watchdog reaps orphaned PrimeVue
 * full-screen BlockUI masks (stuck spinner overlay from the App root) - the
 * stuck mask freezes the whole page (sliders/canvas/menus all dead) after a
 * workflow load. See the __pfsMaskReaper guard below.
 *
 * FULL-FRAME (do not regress): the native socket rows are hidden
 * (node.drawSlots no-op) and the widget area starts right under the title bar
 * (node.widgets_start_y = SUITE_TOP), so the suite occupies the ENTIRE node
 * body. The pins live on as the socket-strip chips inside the suite — they
 * show live link state and are fully wireable (left-drag to connect through
 * the canvas's own LinkConnector, right-click to disconnect). The strip is
 * HIDDEN BY DEFAULT (v3.4.2 — declutter); the ⇄ toolbar toggle brings it
 * back whenever wiring is needed. Slots are still
 * measured, so existing links keep their anchor positions; they are simply
 * not drawn and reserve no body space.
 */

// --- global guard: reap orphaned PrimeVue full-screen BlockUI masks --------
// frontend 1.48.x race: the App root mounts a full-screen BlockUI bound to the
// global "spinner" store (main-*.js: blocked: spinner, fullScreen). A fast
// block->unblock during workflow load leaves the mask with BOTH
// p-overlay-mask-enter and p-overlay-mask-leave classes: PrimeVue's unblock()
// waits for an animationend that never fires (the enter animation already
// finished), so the invisible full-screen mask (z 1801, pointer-events auto)
// plus the body scroll lock (p-overflow-hidden) stay forever and eat every
// pointer event on the page - sliders, canvas, menus, everything.
// A mask carrying -leave means the app already asked for it to go away, so
// reap it once it has lingered > 1s, and release the body scroll lock when no
// overlay masks remain. Legit masks are removed by PrimeVue within ~300ms, so
// the grace window never touches live UI.
console.info("[PixelForge] pf_studio v3.7.0-spriteguard — true-pixel-art defaults + sizing guardrails");
const PFS_VERSION = "v3.7.0-spriteguard";
// --- self-report probe (v3.5.3-probe): the suite phones pointer forensics home
// to OUR backend (POST /pixelforge/probe -> _probe_log.jsonl) so diagnosing the
// owner's live tab needs NOTHING from him but normal use. Batched + fire-and-
// forget; can never throw into the page.
const __pfsProbeQ = [];
let __pfsProbeTimer = null;
function __pfsProbe(kind, data) {
    try {
        __pfsProbeQ.push(Object.assign({ kind, t: Date.now(), v: PFS_VERSION }, data));
        if (!__pfsProbeTimer) {
            __pfsProbeTimer = setTimeout(() => {
                __pfsProbeTimer = null;
                const batch = __pfsProbeQ.splice(0, __pfsProbeQ.length);
                fetch("/pixelforge/probe", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ events: batch }),
                }).catch(() => {});
            }, 1500);
        }
    } catch (_) {}
}
const __pfsElTag = (e) => {
    if (!e) return "null";
    let pe = "?";
    try { pe = getComputedStyle(e).pointerEvents; } catch (_) {}
    return e.tagName + "." + String(e.className || "").slice(0, 60) + " pe=" + pe;
};
if (!window.__pfsClickProbe) {
    window.__pfsClickProbe = true;
    window.addEventListener("pointerdown", (ev) => {
        try {
            const x = ev.clientX, y = ev.clientY;
            const hit = document.elementFromPoint(x, y);
            // suite sliders under the pointer that did NOT receive the event
            const covered = [];
            for (const r of document.querySelectorAll(".pfs-root input[type=range]")) {
                const b = r.getBoundingClientRect();
                if (b.width > 0 && x >= b.left && x <= b.right && y >= b.top && y <= b.bottom && hit !== r) {
                    covered.push({ val: r.value, min: r.min, max: r.max });
                }
            }
            const masks = document.querySelectorAll(".p-blockui-mask").length;
            const locked = document.body.classList.contains("p-overflow-hidden");
            // log only anomaly-relevant clicks: slider-covered, or mask/lock present
            if (covered.length || masks || locked) {
                __pfsProbe("pdown", {
                    x: Math.round(x), y: Math.round(y),
                    inSuite: !!(hit && hit.closest && hit.closest(".pfs-root")),
                    hit: __pfsElTag(hit),
                    covered: covered.length ? covered : undefined,
                    masks, locked,
                    suites: document.querySelectorAll(".pfs-root").length,
                    stack: document.elementsFromPoint(x, y).slice(0, 4).map(__pfsElTag),
                });
            }
        } catch (_) {}
    }, true);
    __pfsProbe("probe-armed", { href: location.href });
}
if (!window.__pfsMaskReaper) {
    const born = new WeakMap();
    window.__pfsMaskReaper = setInterval(() => {
        const now = Date.now();
        let reaped = false;
        for (const m of document.querySelectorAll(".p-blockui-mask")) {
            if (!born.has(m)) born.set(m, now);
            const age = now - born.get(m);
            const leaving = m.classList.contains("p-overlay-mask-leave");
            // -leave = the app already asked for it to go: 1s grace. Otherwise a
            // full-screen mask older than 12s means the spinner never released
            // (stuck-blocked variant) — reap that too; a legit workflow-load
            // spinner lives for ~1-2s, so the window never touches live UI.
            if ((leaving && age > 1000) || age > 12000) {
                console.info("[PixelForge] reaped stuck full-screen BlockUI mask (" + (leaving ? "leave-orphan" : "stuck-spinner") + ", age " + Math.round(age / 1000) + "s)");
                m.remove();
                reaped = true;
            }
        }
        if (reaped && !document.querySelector(".p-overlay-mask")) {
            document.body.classList.remove("p-overflow-hidden");
        }
    }, 500);
}

const { app } = window.comfyAPI.app;

const MIN_SUITE_H = 460;
const NODE_MIN_W = 920;
const NODE_MIN_H = 560;
const NODE_MAX_RESTORE_H = 1100;   // saved sizes taller than this snap back
const NODE_DEFAULT_H = 680;
const SUITE_TOP = 34;              // title bar height: suite starts right under it
const PFS_DRAG_PX = 6;             // chip drag threshold before a wire drag starts
const PFS_NO_DRAW = () => {};      // drawSlots override — hides native socket rows

const STAGE_LABELS = {
    source: "Source", keyed: "Keyed", grid: "Grid",
    look: "Look", motion: "Motion", final: "Final",
    export: "Export", sheet: "Sheet",
};
const STAGE_ORDER_FALLBACK = ["source", "keyed", "grid", "look", "motion", "final"];

// Suite-internal sync widgets: written at queue time by the suite itself
// (gen targeting, placement dot, marquee, ref slots, prompt lane). They must
// stay on node.widgets (they go into the prompt) but NEVER get panel rows —
// raw JSON/filename rows confuse and editing them breaks sync.
const PFS_INTERNAL = new Set([
    "target_layer", "layer_name", "placement_x", "placement_y",
    "selection_x", "selection_y", "selection_w", "selection_h",
    "drawn_ref_image", "drawn_ref_image_2", "ref_video_1",
    "prompt_segments", "gen_win_start",
]);
// Prompt fields that deserve a multiline box even when the backend def
// does not mark them multiline.
const PFS_MULTILINE = new Set(["character", "action", "style"]);

// The 9 mains — always visible at the top of the Forge tab.
const QUICK = [
    "size_preset", "look", "palette", "colors", "background",
    "key_strength", "sharpen_grid", "motion_fix", "loop_mode",
];
// Everything else, grouped. Rendered as collapsible <details> sections.
// Any widget not listed here or in QUICK lands in an auto "More" section so
// no parameter can ever end up hidden with no way to reach it.
const SECTIONS = [
    ["Size & Canvas", ["custom_width", "custom_height", "canvas", "canvas_size",
        "canvas_width", "canvas_height", "placement", "anchor", "offset_x", "offset_y",
        "adv_crop_padding", "adv_crop_snap"]],
    ["Finish", ["dither", "cleanup", "remove_duplicate_frames"]],
    ["Background Keyer", ["custom_bg_hex", "adv_key_method", "adv_key_tolerance",
        "adv_key_shadow", "adv_key_softness", "adv_key_erode", "adv_key_despill",
        "adv_key_interior", "adv_key_interior_tol", "adv_key_interior_max_area",
        "adv_key_rescue", "adv_key_temporal_alpha", "adv_key_drop_detached"]],
    ["Grid Recover", ["adv_grid_mode", "adv_grid_block", "adv_grid_max_block",
        "adv_grid_reduce"]],
    ["Look Engine · Quantize", ["adv_q_method", "adv_q_mapping", "adv_q_saturation",
        "adv_q_contrast", "adv_q_sharpen", "adv_q_flatten", "adv_q_temporal_lock"]],
    ["Look Engine · Hi-bit", ["adv_tp_bands", "adv_tp_hue_shift", "adv_tp_vibrancy",
        "adv_tp_cel_contrast", "adv_tp_outline", "adv_tp_ambient",
        "adv_tp_shadow_thr", "adv_tp_highlight_thr", "adv_tp_flatten",
        "adv_tp_saturation", "adv_tp_contrast", "adv_tp_sharpen", "adv_tp_share"]],
    ["Motion Fix", ["adv_motion_mode", "adv_motion_threshold", "adv_motion_commit",
        "adv_motion_hold"]],
    ["Loop & Dedup", ["adv_loop_max_error", "adv_loop_tail", "adv_dedup_threshold"]],
    ["Suite", ["preview_max_frames"]],
];

const PRETTY = {
    size_preset: "Size", look: "Look", palette: "Palette", colors: "Colors",
    background: "Backdrop", key_strength: "Key", sharpen_grid: "Grid",
    motion_fix: "Motion", loop_mode: "Loop", dither: "Dither",
    cleanup: "Cleanup", remove_duplicate_frames: "Dedup frames",
    character: "Character", action: "Action", style: "Style", seconds: "Seconds",
    seamless_loop: "Seamless loop", gen_size: "Preset", gen_width: "Width",
    gen_height: "Height", unet_name: "UNET (diffusion)", clip_name: "CLIP (text enc)",
    vae_name: "VAE", turbo_lora: "Turbo LoRA", lora_strength: "LoRA strength",
    seed: "Seed", steps: "Steps", sampler_name: "Sampler", scheduler: "Scheduler",
    tail_compress: "Tail compress", temporal_blend: "Temporal blend",
    loop_noise: "Loop noise", edge_commit: "Edge commit",
    attention_backend: "Attention", ffn_chunks: "FFN chunks",
    ffn_seq_threshold: "FFN threshold", filename_prefix: "Save as",
    export_fps: "FPS", make_gif: "GIF", gif_size: "GIF size",
    make_sheet: "Sprite sheet", sheet_columns: "Sheet columns",
    sheet_bg: "Sheet BG", build_aseprite: "Aseprite file",
    aseprite_path: "Aseprite.exe",
};

function prettyName(n) {
    if (PRETTY[n]) return PRETTY[n];
    return n.replace(/^adv_(key|grid|q|tp|motion|loop|crop|dedup)_/, "")
        .replace(/^adv_/, "").replace(/_/g, " ");
}

// One Forge tab layout: Generate (prompt/models/sampling) | Forge | Export.
// "forge" sentinel = the shared quick knobs + engine sections above.
const OF_TABS = [
    ["⚡ Generate", [
        ["Prompt", ["character", "action", "style", "seconds", "seamless_loop"]],
        ["References", ["ref_image_size"]],
        ["Resolution", ["gen_size", "gen_width", "gen_height"]],
        ["Models", ["unet_name", "clip_name", "vae_name", "turbo_lora", "lora_strength"]],
        ["Sampling", ["seed", "control_after_generate", "steps", "sampler_name", "scheduler", "tail_compress",
            "temporal_blend", "loop_noise", "edge_commit"]],
        ["Speed & VRAM", ["attention_backend", "ffn_chunks", "ffn_seq_threshold"]],
    ]],
    ["🎨 Forge", "forge"],
    ["📦 Export", [
        ["Export", ["filename_prefix", "export_fps", "make_gif", "gif_size",
            "make_sheet", "sheet_columns", "sheet_bg", "build_aseprite", "aseprite_path"]],
    ]],
];

const NODE_CONFIGS = {
    PixelForgeSuperForge: { title: "ᛒᛚᚢᛒ PIXEL FORGE", tabs: null },
    PixelForgeOneForge: { title: "ᛒᛚᚢᛒ PIXEL FORGE", tabs: OF_TABS },
};

const STYLES = `
.pfs-root { display:flex; flex-direction:column; width:100%; height:100%;
    background:#0e0e14; color:#d8d8e2; outline:none;
    font:11px/1.4 "Segoe UI","Segoe UI Symbol",system-ui,sans-serif;
    border-radius:6px; overflow:hidden; user-select:none; }

/* ---- toolbar ---- */
.pfs-bar { display:flex; align-items:center; gap:5px; padding:5px 8px;
    background:linear-gradient(#1a1a23,#15151d); border-bottom:1px solid #26262f;
    flex:0 0 auto; flex-wrap:wrap; }
.pfs-title { font-weight:700; color:#ff9d45; letter-spacing:1.5px; margin-right:8px;
    white-space:nowrap; font-size:11px;
    font-family:"Segoe UI","Segoe UI Symbol",sans-serif;
    text-shadow:0 0 8px rgba(255,157,69,.25); }
.pfs-sep { width:1px; height:16px; background:#2c2c38; margin:0 2px; flex:0 0 auto; }
.pfs-spacer { flex:1; }
.pfs-cluster { display:inline-flex; align-items:center; gap:2px; background:#0b0b11;
    border:1px solid #2a2a35; border-radius:6px; padding:2px; }
.pfs-btn { background:transparent; border:1px solid transparent; color:#b9b9c8;
    border-radius:4px; padding:2px 7px; cursor:pointer; font-size:11px; line-height:1.3; }
.pfs-btn:hover { background:#22222c; color:#ffd9ae; }
.pfs-btn.on { background:#3a2c1a; border-color:#ff9d45; color:#ff9d45; }
.pfs-lbl { font-size:10px; color:#9a9aa8; font-variant-numeric:tabular-nums;
    padding:0 4px; white-space:nowrap; }
.pfs-color { width:20px; height:20px; padding:0; border:1px solid #2a2a35;
    border-radius:4px; background:#0b0b11; cursor:pointer; }
.pfs-runbtn { background:#3a2c1a; border:1px solid #ff9d45; color:#ff9d45;
    font-weight:700; letter-spacing:.4px; padding:3px 12px; }
.pfs-runbtn:hover { background:#ff9d45; color:#0e0e14; }
.pfs-ver { font-size:8.5px; color:#555566; padding:0 6px; user-select:none;
    font-variant-numeric:tabular-nums; }

/* ---- socket strip (top pins, integrated into the suite) ---- */
.pfs-sockbar { display:flex; align-items:center; gap:4px; padding:3px 8px;
    background:#101018; border-bottom:1px solid #20202a; flex:0 0 auto;
    overflow-x:auto; overflow-y:hidden; scrollbar-width:none; white-space:nowrap; }
.pfs-sockbar::-webkit-scrollbar { display:none; }
.pfs-sockbar.hide { display:none; }
.pfs-mode { font-size:8.5px; font-weight:700; letter-spacing:1.2px;
    color:#0e0e14; background:#ff9d45; border-radius:3px; padding:2px 6px;
    margin-right:4px; flex:0 0 auto; }
.pfs-chip { display:inline-flex; align-items:center; gap:4px; font-size:9px;
    color:#9a9aa8; background:#0b0b11; border:1px solid #26262f;
    border-radius:8px; padding:1px 7px 1px 5px; flex:0 0 auto; cursor:default; }
.pfs-chip i { width:7px; height:7px; border-radius:50%; background:#3f3f4c;
    flex:0 0 auto; }
.pfs-chip.in.wired i { background:#7fd67f; box-shadow:0 0 4px rgba(127,214,127,.6); }
.pfs-chip.out.wired i { background:#6fb7ff; box-shadow:0 0 4px rgba(111,183,255,.6); }
.pfs-chip.wired { color:#d8d8e2; border-color:#3a3a48; }
.pfs-socksep { width:1px; height:12px; background:#2c2c38; margin:0 3px;
    flex:0 0 auto; }
.pfs-socklbl { font-size:8px; letter-spacing:1.2px; color:#555566;
    text-transform:uppercase; flex:0 0 auto; }

/* ---- main split ---- */
.pfs-main { display:flex; flex:1 1 auto; min-height:0; }
.pfs-cwrap { flex:1 1 auto; position:relative; min-width:0; background:#0a0a0f; }
.pfs-canvas { position:absolute; inset:0; width:100%; height:100%; display:block;
    cursor:grab; image-rendering:pixelated; }
.pfs-canvas.panning { cursor:grabbing; }

/* ---- left: palette ---- */
.pfs-left { flex:0 0 auto; width:148px; background:#12121a;
    border-right:1px solid #26262f; display:flex; flex-direction:column;
    overflow-y:auto; overflow-x:hidden; scrollbar-width:thin; }
.pfs-left.hide { display:none; }
.pfs-palhead { padding:6px 10px 4px; font-size:9px; text-transform:uppercase;
    letter-spacing:1.4px; color:#ff9d45; font-weight:700; }
.pfs-palcount { color:#6f6f7e; font-weight:400; letter-spacing:.4px; }
.pfs-palgrid { display:grid; grid-template-columns:repeat(6,1fr); gap:3px;
    padding:2px 10px 8px; }
.pfs-swatch { aspect-ratio:1; border-radius:3px; border:1px solid #000;
    outline:1px solid #2c2c38; cursor:pointer; }
.pfs-swatch:hover { outline:1px solid #ff9d45; }
.pfs-palempty { padding:2px 10px; font-size:9.5px; color:#555566; }
.pfs-leftsec { padding:7px 10px 8px; border-top:1px solid #1e1e28; }
.pfs-leftsec h4 { margin:0 0 6px; font-size:9px; text-transform:uppercase;
    letter-spacing:1.4px; color:#6f6f7e; font-weight:700; }
.pfs-info { font-size:10px; color:#9a9aa8; white-space:pre-wrap; word-break:break-word; }
.pfs-report { font-size:9.5px; color:#7f8a7f; max-height:90px; overflow-y:auto;
    white-space:pre-wrap; word-break:break-word; scrollbar-width:thin; }

/* ---- right: parameters ---- */
.pfs-side { flex:0 0 auto; width:264px; background:#12121a;
    border-left:1px solid #26262f; display:flex; flex-direction:column;
    overflow-y:auto; overflow-x:hidden; scrollbar-width:thin; }
.pfs-sidehead { display:flex; align-items:center; padding:6px 10px 5px;
    border-bottom:1px solid #20202a; flex:0 0 auto; }
.pfs-sidehead h3 { margin:0; font-size:9px; text-transform:uppercase;
    letter-spacing:1.6px; color:#6f6f7e; font-weight:700; flex:1; }
.pfs-mini { background:transparent; border:1px solid #32323e; color:#8a8a99;
    border-radius:3px; font-size:8.5px; padding:1px 5px; cursor:pointer; margin-left:4px; }
.pfs-mini:hover { border-color:#ff9d45; color:#ffd9ae; }
.pfs-sec { padding:7px 10px 8px; border-bottom:1px solid #1e1e28; }
.pfs-sec h4 { margin:0 0 6px; font-size:9px; text-transform:uppercase;
    letter-spacing:1.4px; color:#ff9d45; font-weight:700; }
.pfs-details { border-bottom:1px solid #1e1e28; }
.pfs-details summary { cursor:pointer; padding:6px 10px; font-size:9.5px;
    text-transform:uppercase; letter-spacing:1.2px; color:#9a9aa8; font-weight:700;
    list-style:none; display:flex; align-items:center; }
.pfs-details summary::before { content:"▸"; color:#ff9d45; margin-right:6px;
    font-size:9px; transition:transform .12s; }
.pfs-details[open] summary::before { transform:rotate(90deg); }
.pfs-details summary:hover { color:#ffd9ae; background:#16161f; }
.pfs-details .pfs-body { padding:1px 10px 8px; }

/* ---- panel tabs (One Forge) ---- */
.pfs-tabstrip { display:flex; gap:3px; padding:6px 8px 5px; border-bottom:1px solid #20202a;
    flex:0 0 auto; }
.pfs-ptab { flex:1; background:#0b0b11; border:1px solid #2a2a35; color:#9a9aa8;
    border-radius:5px; padding:3px 4px; cursor:pointer; font-size:9.5px; white-space:nowrap; }
.pfs-ptab:hover { color:#ffd9ae; border-color:#3a3a48; }
.pfs-ptab.on { background:#3a2c1a; border-color:#ff9d45; color:#ff9d45; font-weight:700; }

/* ---- parameter rows ---- */
.pfs-qrow { display:flex; align-items:center; gap:6px; margin-bottom:5px; }
.pfs-qrow.wrap { flex-wrap:wrap; }
.pfs-qrow label { flex:0 0 82px; color:#9a9aa8; font-size:10px; overflow:hidden;
    text-overflow:ellipsis; white-space:nowrap; }
.pfs-qrow select, .pfs-qrow input[type=number], .pfs-qrow input[type=text] {
    flex:1; min-width:0; background:#0b0b11; border:1px solid #32323e; color:#e8e8f0;
    border-radius:4px; padding:2px 5px; font-size:10px; }
.pfs-qrow select:focus, .pfs-qrow input:focus { border-color:#ff9d45; outline:none; }
.pfs-qrow input[type=number] { flex:0 0 52px; text-align:right;
    font-variant-numeric:tabular-nums; }
.pfs-qrow input[type=range] { flex:1; min-width:0; appearance:none; height:14px;
    background:transparent; outline:none; cursor:pointer; margin:0; padding:0;
    pointer-events:auto; }
.pfs-qrow input[type=range]::-webkit-slider-runnable-track { height:3px;
    background:#2a2a36; border-radius:2px; }
.pfs-qrow input[type=range]::-webkit-slider-thumb { appearance:none; width:14px;
    height:14px; border-radius:50%; background:#ff9d45; border:2px solid #0e0e14;
    box-shadow:0 0 5px rgba(255,157,69,.5); margin-top:-5.5px; cursor:pointer;
    pointer-events:auto; }
.pfs-qrow input[type=range]::-moz-range-track { height:3px;
    background:#2a2a36; border-radius:2px; }
.pfs-qrow input[type=range]::-moz-range-thumb { width:12px; height:12px;
    border-radius:50%; background:#ff9d45; border:2px solid #0e0e14;
    cursor:pointer; pointer-events:auto; }
/* form controls inside the suite must be fully interactive */
.pfs-side input, .pfs-side select, .pfs-side textarea,
.pfs-side button { user-select:auto; pointer-events:auto; }

.pfs-qrow input[type=checkbox] { appearance:none; width:26px; height:14px;
    background:#2a2a36; border-radius:8px; position:relative; cursor:pointer;
    margin-left:2px; transition:background .15s; flex:0 0 auto; }
.pfs-qrow input[type=checkbox]::after { content:""; position:absolute; top:2px;
    left:2px; width:10px; height:10px; border-radius:50%; background:#8a8a99;
    transition:left .15s, background .15s; }
.pfs-qrow input[type=checkbox]:checked { background:#3a2c1a;
    box-shadow:inset 0 0 0 1px #ff9d45; }
.pfs-qrow input[type=checkbox]:checked::after { left:14px; background:#ff9d45; }
.pfs-ta { flex:1 1 100%; min-height:34px; resize:vertical; background:#0b0b11;
    border:1px solid #32323e; color:#e8e8f0; border-radius:4px; padding:3px 5px;
    font-size:10px; font-family:inherit; }
.pfs-ta:focus { border-color:#ff9d45; outline:none; }

/* ---- transport ---- */
.pfs-transport { display:flex; align-items:center; gap:3px; padding:4px 8px;
    background:linear-gradient(#15151d,#121219); border-top:1px solid #26262f;
    flex:0 0 auto; }
.pfs-tbtn { background:transparent; border:1px solid transparent; color:#b9b9c8;
    border-radius:4px; padding:2px 8px; cursor:pointer; font-size:11px; line-height:1.3; }
.pfs-tbtn:hover { background:#22222c; color:#ffd9ae; }
.pfs-tbtn.play { color:#ff9d45; font-size:12px; min-width:30px; }
.pfs-tbtn.on { background:#3a2c1a; border-color:#ff9d45; color:#ff9d45; }
.pfs-num { width:40px; background:#0b0b11; border:1px solid #32323e; color:#d8d8e2;
    border-radius:4px; padding:1px 4px; font-size:10px; text-align:right; }

/* ---- timeline (aseprite layer rows x frame columns) ---- */
.pfs-tlwrap { flex:0 0 auto; height:178px; background:#0d0d13;
    border-top:1px solid #26262f; position:relative; display:flex; flex-direction:column; }
.pfs-tlwrap.hide { display:none; }
.pfs-tl { position:relative; flex:1 1 auto; min-height:0; width:100%; display:block; cursor:pointer; }

/* ---- layer controls bar ---- */
.pfs-layerbar { display:flex; align-items:center; gap:4px; padding:3px 8px;
    background:linear-gradient(#13131b,#101018); border-top:1px solid #26262f;
    flex:0 0 auto; flex-wrap:wrap; }
.pfs-lyr-btn { background:#0b0b11; border:1px solid #2a2a35; color:#b9b9c8;
    border-radius:4px; padding:2px 7px; cursor:pointer; font-size:11px;
    line-height:1.3; }
.pfs-lyr-btn:hover { background:#22222c; color:#ffd9ae; border-color:#3a3a48; }
.pfs-lyr-opac { display:inline-flex; align-items:center; gap:3px; margin-left:8px;
    background:#0b0b11; border:1px solid #2a2a35; border-radius:6px; padding:2px 6px; }
.pfs-lyr-opac-lbl { font-size:9px; color:#6f6f7e; font-weight:700; }
.pfs-lyr-opac-slider { width:60px; appearance:none; height:14px;
    background:transparent; outline:none; cursor:pointer; margin:0; padding:0;
    pointer-events:auto; }
.pfs-lyr-opac-slider::-webkit-slider-runnable-track { height:3px;
    background:#2a2a36; border-radius:2px; }
.pfs-lyr-opac-slider::-webkit-slider-thumb { appearance:none; width:12px;
    height:12px; border-radius:50%; background:#ff9d45; border:2px solid #0e0e14;
    box-shadow:0 0 5px rgba(255,157,69,.5); margin-top:-4.5px; cursor:pointer;
    pointer-events:auto; }
.pfs-lyr-opac-slider::-moz-range-track { height:3px;
    background:#2a2a36; border-radius:2px; }
.pfs-lyr-opac-slider::-moz-range-thumb { width:10px; height:10px;
    border-radius:50%; background:#ff9d45; border:2px solid #0e0e14;
    cursor:pointer; pointer-events:auto; }
.pfs-lyr-opac-val { font-size:9px; color:#9a9aa8; min-width:28px; text-align:right;
    font-variant-numeric:tabular-nums; }
.pfs-lyr-gen { display:inline-flex; align-items:center; gap:3px; margin-left:8px;
    background:#0b0b11; border:1px solid #2a2a35; border-radius:6px; padding:2px 6px; }
.pfs-lyr-gen-lbl { font-size:9px; color:#ff9d45; font-weight:700; }
.pfs-lyr-gen-sel { background:#0b0b11; border:1px solid #32323e; color:#e8e8f0;
    border-radius:4px; padding:1px 4px; font-size:9.5px; }
.pfs-lyr-gen-sel:focus { border-color:#ff9d45; outline:none; }
.pfs-lyr-name { font-size:9.5px; color:#9a9aa8; margin-left:8px; font-style:italic; }

/* ---- status bar ---- */
.pfs-status { flex:0 0 auto; display:flex; align-items:center; gap:10px;
    padding:3px 10px; background:#101018; border-top:1px solid #26262f;
    font-size:9.5px; color:#9a9aa8; font-variant-numeric:tabular-nums;
    white-space:nowrap; overflow:hidden; }
.pfs-status b { color:#ff9d45; font-weight:700; }
`;

let styleEl = document.getElementById("pfs-styles");
if (!styleEl) {
    styleEl = document.createElement("style");
    styleEl.id = "pfs-styles";
    document.head.appendChild(styleEl);
}
styleEl.textContent = STYLES;

// ---------------------------------------------------------------- helpers
function viewURL(ref) {
    const q = new URLSearchParams({
        filename: ref.filename,
        subfolder: ref.subfolder || "",
        type: ref.type || "temp",
    });
    return `/view?${q.toString()}`;
}

function hideWidget(w) {
    if (!w || w._pfsHidden) return;
    w._pfsHidden = true;
    w._pfsOrigCompute = w.computeSize;
    w.hidden = true;
    if (!w.options) w.options = {};
    w.options.hidden = true;
    w.computeSize = () => [0, -4];
    if (w.element) w.element.style.display = "none";
}

function checkerTile() {
    const c = document.createElement("canvas");
    c.width = c.height = 16;
    const x = c.getContext("2d");
    x.fillStyle = "#3c3c46"; x.fillRect(0, 0, 16, 16);
    x.fillStyle = "#2a2a33"; x.fillRect(0, 0, 8, 8); x.fillRect(8, 8, 8, 8);
    return c;
}

// ---------------------------------------------------------------- forge
function createForge(node, config) {
    const st = {
        stages: {}, order: [], meta: {}, report: "", durations: null,
        imgs: {}, thumbs: {},
        stage: "final", frame: 0,
        playing: false, loop: true, fps: 12,
        zoom: 0, panX: 0, panY: 0,          // zoom 0 = fit
        onion: false, grid: false, ab: false, abSplit: 0.5,
        showPal: true, showTl: true, showSockets: false,
        pal: [], _palKey: "",
        tlScroll: 0,
        _acc: 0, _lastT: 0, _raf: 0, _gifRaf: 0, _gifLast: 0,

        // ==== Aseprite-like layer system ====
        layers: [],           // ordered bottom→top: [{id, name, visible, opacity,
                              //   blend, locked, frames: [{img, source}|null],
                              //   transform: {x,y,scale,anchorX,anchorY},
                              //   keyframes: {frameIdx: {x,y,scale}}}]
        activeLayer: 0,       // index into layers[]
        activeFrame: 0,       // current frame for editing
        totalFrames: 0,       // max frame count across all layers

        // Canvas tools
        tool: "pointer",      // pointer | move | marquee | place | draw
        marquee: null,        // {x,y,w,h} in sprite-pixel coords or null
        placementDot: null,   // {x,y} in sprite-pixel coords or null (null = center)
        brushColor: "#ffffff", // draw-tool brush color
        showPlacementDot: true,
        drawnRef: false,      // drawn-ref armed (One Forge): drawing -> <Picture 1>
        refSlots: { p1: "", p2: "" },  // armed gen-ref slots (temp PNG names)
        vidRef: "",           // armed video-ref slot V1 (input-dir clip name)

        // Generation target
        genTarget: "new",     // "new" | "current" | <layerId>
        genFrameStart: 0,
        genFrameEnd: -1,      // -1 = all frames

        // Phase 9: frame-range selection + surgical regen + prompt lane
        frameSel: null,       // {layer, start, end} inclusive cel range or null
        regenWindow: null,    // {start, count} pending surgical-regen splice
        celClipboard: null,   // copied cel (canvas) for copy/paste
        promptSegs: [],       // [{start, end, prompt}] timeline prompt lane
        activePromptSeg: -1,  // selected prompt segment index or -1

        // Pipeline debug stages (toggled, not shown by default)
        debugStages: {},      // {stageName: [{filename,...}]}
        showDebugStages: false,

        // Compositing cache: frameIdx → offscreen canvas
        _compositeCache: {},
    };

    // ---- FULL-FRAME: the suite fills the entire node body (header note).
    // Slots stay measured (link anchors keep working) but are never drawn and
    // reserve no vertical space; the chips below replace them as the pins. ----
    node.widgets_start_y = SUITE_TOP;
    node.drawSlots = PFS_NO_DRAW;
    // Frontend >=1.2x bolts a native output-image overlay onto any node whose
    // execution store entry gains .images (the "sprite outside the suite"
    // glitch). hideOutputImages is the official opt-out (same flag core's
    // ImageCompositor / Painter / ImageCropV2 set). Belt-and-braces: we never
    // emit ui.images anyway (see the LAYOUT WAR note).
    node.hideOutputImages = true;

    // ==== Layer management functions ====
    let _layerIdCounter = 0;
    function _makeLayerId() { return "L" + (++_layerIdCounter) + "_" + Date.now().toString(36); }

    function addLayer(name, opts) {
        opts = opts || {};
        const layer = {
            id: _makeLayerId(),
            name: name || ("Layer " + (st.layers.length + 1)),
            kind: opts.kind || "normal",   // "normal" | "ref" (reference guide)
            source: opts.source || "user", // "forge" | "user" | "imported" | "paint"
            refFile: opts.refFile || "",   // temp filename for imported refs (reload)
            visible: opts.visible !== false,
            opacity: opts.opacity != null ? opts.opacity : 1.0,
            blend: opts.blend || "normal",
            locked: opts.locked === true,
            frames: [],        // sparse: frames[i] = {img: Image, source: string} | null
            transform: { x: 0, y: 0, scale: 1.0, anchorX: 0.5, anchorY: 1.0 },
            keyframes: {},     // frameIdx → {x, y, scale}
            _dirty: true,      // needs composite recache
        };
        const pos = opts.at != null ? opts.at : st.layers.length;
        st.layers.splice(pos, 0, layer);
        st.activeLayer = pos;
        _recalcTotalFrames();
        _invalidateAllComposites();
        saveLayerProps();
        return layer;
    }

    function removeLayer(idx) {
        if (st.layers.length <= 1) return; // keep at least one layer
        st.layers.splice(idx, 1);
        if (st.activeLayer >= st.layers.length) st.activeLayer = st.layers.length - 1;
        _recalcTotalFrames();
        _invalidateAllComposites();
        saveLayerProps();
    }

    function duplicateLayer(idx) {
        const src = st.layers[idx];
        if (!src) return;
        const dup = {
            id: _makeLayerId(),
            name: src.name + " copy",
            kind: src.kind || "normal",
            source: src.source || "user",
            refFile: src.refFile || "",
            visible: src.visible,
            opacity: src.opacity,
            blend: src.blend,
            locked: false,
            frames: src.frames.map(f => f ? { img: f.img, source: f.source } : null),
            transform: { ...src.transform },
            keyframes: JSON.parse(JSON.stringify(src.keyframes)),
            _dirty: true,
        };
        st.layers.splice(idx + 1, 0, dup);
        st.activeLayer = idx + 1;
        _invalidateAllComposites();
        saveLayerProps();
    }

    function moveLayer(fromIdx, toIdx) {
        if (toIdx < 0 || toIdx >= st.layers.length) return;
        const [layer] = st.layers.splice(fromIdx, 1);
        st.layers.splice(toIdx, 0, layer);
        st.activeLayer = toIdx;
        _invalidateAllComposites();
        saveLayerProps();
    }

    function setActiveLayer(idx) {
        st.activeLayer = Math.max(0, Math.min(st.layers.length - 1, idx));
        refreshLayerBar();
    }

    function getActiveLayer() { return st.layers[st.activeLayer] || null; }

    function setLayerVisible(idx, v) { st.layers[idx].visible = v; _invalidateAllComposites(); saveLayerProps(); }
    function setLayerOpacity(idx, o) { st.layers[idx].opacity = Math.max(0, Math.min(1, o)); _invalidateAllComposites(); saveLayerProps(); }
    function setLayerLocked(idx, l) { st.layers[idx].locked = l; saveLayerProps(); }
    function renameLayer(idx, n) { st.layers[idx].name = n; saveLayerProps(); }

    // ---- keyframes ----
    function addKeyframe(layerIdx, frameIdx, tf) {
        st.layers[layerIdx].keyframes[frameIdx] = { x: tf.x || 0, y: tf.y || 0, scale: tf.scale || 1.0 };
        _invalidateAllComposites();
        saveLayerProps();
    }
    function removeKeyframe(layerIdx, frameIdx) {
        delete st.layers[layerIdx].keyframes[frameIdx];
        _invalidateAllComposites();
        saveLayerProps();
    }
    function getInterpolatedTransform(layer, frameIdx) {
        // Find surrounding keyframes
        const kf = layer.keyframes;
        const keys = Object.keys(kf).map(Number).sort((a, b) => a - b);
        if (!keys.length) return { ...layer.transform };
        if (keys.length === 1) return { ...layer.transform, ...kf[keys[0]] };
        if (frameIdx <= keys[0]) return { ...layer.transform, ...kf[keys[0]] };
        if (frameIdx >= keys[keys.length - 1]) return { ...layer.transform, ...kf[keys[keys.length - 1]] };
        // Linear interpolation between surrounding keys
        let prev = keys[0], next = keys[keys.length - 1];
        for (let i = 0; i < keys.length - 1; i++) {
            if (keys[i] <= frameIdx && keys[i + 1] >= frameIdx) {
                prev = keys[i]; next = keys[i + 1]; break;
            }
        }
        const t = next === prev ? 0 : (frameIdx - prev) / (next - prev);
        const a = kf[prev], b = kf[next];
        return {
            ...layer.transform,
            x: layer.transform.x + a.x + (b.x - a.x) * t,
            y: layer.transform.y + a.y + (b.y - a.y) * t,
            scale: (layer.transform.scale * a.scale) + ((layer.transform.scale * b.scale) - (layer.transform.scale * a.scale)) * t,
        };
    }

    // ---- frame count ----
    function _recalcTotalFrames() {
        let max = 0;
        for (const l of st.layers) max = Math.max(max, l.frames.length);
        st.totalFrames = max;
    }

    // ---- compositing ----
    function _invalidateAllComposites() {
        st._compositeCache = {};
        for (const l of st.layers) l._dirty = true;
    }

    // A frame's paint surface: an edited offscreen canvas (draw tool) wins
    // over the source image.
    function frameSurf(fr) { return fr ? (fr.canvas || fr.img) : null; }
    function surfW(s) { return s ? (s.naturalWidth || s.width) : 0; }
    function surfH(s) { return s ? (s.naturalHeight || s.height) : 0; }

    function compositeFrame(frameIdx) {
        if (st._compositeCache[frameIdx] && !st.layers.some(l => l._dirty)) {
            return st._compositeCache[frameIdx];
        }
        // Determine canvas size from the widest/tallest CONTENT layer frame.
        // Reference layers (kind "ref") are guides — they never inflate the
        // canvas (a big ref sheet would blow up the composite otherwise).
        let w = 64, h = 64;
        for (const l of st.layers) {
            if (!l.visible || l.kind === "ref") continue;
            const fr = l.frames[frameIdx];
            if (!fr) continue;
            const s = frameSurf(fr);
            if (surfW(s)) {
                w = Math.max(w, surfW(s));
                h = Math.max(h, surfH(s));
            }
        }
        const c = document.createElement("canvas");
        c.width = w; c.height = h;
        const ctx = c.getContext("2d");
        ctx.imageSmoothingEnabled = false;
        // Draw layers bottom→top
        for (const l of st.layers) {
            if (!l.visible) continue;
            // Ref layers with a single frame show it on EVERY frame (guide)
            const fr = l.frames[frameIdx] ||
                (l.kind === "ref" ? l.frames.find(f => f) : null);
            const surf = frameSurf(fr);
            if (!surf || !surfW(surf)) continue;
            const tf = getInterpolatedTransform(l, frameIdx);
            ctx.globalAlpha = l.opacity;
            ctx.globalCompositeOperation = l.blend === "normal" ? "source-over" : l.blend;
            const dx = tf.x + (w - surfW(surf) * tf.scale) * tf.anchorX;
            const dy = tf.y + (h - surfH(surf) * tf.scale) * tf.anchorY;
            ctx.drawImage(surf, dx, dy, surfW(surf) * tf.scale, surfH(surf) * tf.scale);
        }
        ctx.globalAlpha = 1;
        ctx.globalCompositeOperation = "source-over";
        st._compositeCache[frameIdx] = c;
        for (const l of st.layers) l._dirty = false;
        return c;
    }

    // ---- draw tool: pixel painting ----
    // Every stroke paints into a per-frame offscreen canvas (fr.canvas).
    // If the frame only has a source image, the image is copied into the
    // canvas first (non-destructive: the original ref stays in fr.img).
    // If the layer has no frame here at all, a blank "precanvas" is created
    // at the current composite size so you can draw from thin air.
    function ensureDrawableFrame(layer, frameIdx) {
        let fr = layer.frames[frameIdx];
        if (fr && fr.canvas) return fr;
        if (fr && fr.img && fr.img.naturalWidth) {
            const cv = document.createElement("canvas");
            cv.width = fr.img.naturalWidth; cv.height = fr.img.naturalHeight;
            const cx = cv.getContext("2d"); cx.imageSmoothingEnabled = false;
            cx.drawImage(fr.img, 0, 0);
            fr.canvas = cv;
            return fr;
        }
        const comp = compositeFrame(frameIdx);
        const cv = document.createElement("canvas");
        cv.width = comp ? comp.width : 64; cv.height = comp ? comp.height : 64;
        fr = { img: null, canvas: cv, source: "paint" };
        layer.frames[frameIdx] = fr;
        _recalcTotalFrames();
        return fr;
    }

    function paintDot(fr, sx, sy) {
        const cv = fr && fr.canvas; if (!cv) return;
        const x = Math.floor(sx), y = Math.floor(sy);
        if (x < 0 || y < 0 || x >= cv.width || y >= cv.height) return;
        const cx = cv.getContext("2d");
        cx.fillStyle = st.brushColor || "#ffffff";
        cx.fillRect(x, y, 1, 1);
    }

    function paintLine(fr, x0, y0, x1, y1) {
        const dx = x1 - x0, dy = y1 - y0;
        const steps = Math.max(Math.abs(dx), Math.abs(dy), 1);
        for (let i = 0; i <= steps; i++) paintDot(fr, x0 + dx * i / steps, y0 + dy * i / steps);
    }

    // ---- persistence ----
    function saveLayerProps() {
        node.properties = node.properties || {};
        node.properties.pfs_layers = st.layers.map(l => ({
            id: l.id, name: l.name, kind: l.kind || "normal",
            source: l.source || "user", refFile: l.refFile || "",
            visible: l.visible, opacity: l.opacity,
            blend: l.blend, locked: l.locked,
            transform: l.transform, keyframes: l.keyframes,
        }));
        node.properties.pfs_activeLayer = st.activeLayer;
        node.properties.pfs_genTarget = st.genTarget;
        node.properties.pfs_tool = st.tool;
        node.properties.pfs_showPlacementDot = st.showPlacementDot;
        node.properties.pfs_showDebugStages = st.showDebugStages;
        node.properties.pfs_drawnRef = st.drawnRef;
        node.properties.pfs_refSlots = { ...st.refSlots };
        node.properties.pfs_vidRef = st.vidRef || "";
        node.properties.pfs_promptSegs = st.promptSegs.map(s => ({ start: s.start, end: s.end, prompt: s.prompt }));
    }

    function restoreLayerProps() {
        const p = node.properties || {};
        // Restore layer metadata (frames are repopulated on execution)
        // NOTE: an EMPTY pfs_layers array means "no data" (saved before any
        // layer existed) — do NOT wipe the default layer with it.
        if (Array.isArray(p.pfs_layers) && p.pfs_layers.length) {
            st.layers = p.pfs_layers.map(l => {
                const layer = {
                    ...l, frames: [], _dirty: true,
                    kind: l.kind || "normal",
                    source: l.source || "user",
                    refFile: l.refFile || "",
                    transform: l.transform || { x: 0, y: 0, scale: 1.0, anchorX: 0.5, anchorY: 1.0 },
                    keyframes: l.keyframes || {},
                };
                // Imported reference layers re-fetch their image from temp
                // (best effort — temp may have been cleaned between sessions)
                if (layer.refFile) {
                    const im = new Image();
                    im.src = viewURL({ filename: layer.refFile, subfolder: "", type: "temp" });
                    im.onload = () => { layer._dirty = true; _invalidateAllComposites(); draw(); drawTl(); };
                    layer.frames[0] = { img: im, source: "imported" };
                }
                return layer;
            });
        }
        st.activeLayer = p.pfs_activeLayer || 0;
        st.genTarget = p.pfs_genTarget || "new";
        st.tool = p.pfs_tool || "pointer";
        st.showPlacementDot = p.pfs_showPlacementDot !== false;
        st.showDebugStages = p.pfs_showDebugStages || false;
        st.drawnRef = !!p.pfs_drawnRef;
        if (p.pfs_refSlots && typeof p.pfs_refSlots === "object") {
            st.refSlots = { p1: p.pfs_refSlots.p1 || "", p2: p.pfs_refSlots.p2 || "" };
        }
        st.vidRef = p.pfs_vidRef || "";
    }

    // ---- DOM skeleton ----
    const root = document.createElement("div"); root.className = "pfs-root";
    root.tabIndex = 0;                       // keyboard transport (guarded below)

    const bar = document.createElement("div"); bar.className = "pfs-bar";
    const title = document.createElement("span"); title.className = "pfs-title";
    title.textContent = config.title; bar.appendChild(title);

    const mkBtn = (txt, tip, onclick, toggle, cls) => {
        const b = document.createElement("button");
        b.className = cls || "pfs-btn"; b.textContent = txt; b.title = tip || "";
        b.addEventListener("click", (e) => {
            e.stopPropagation();
            if (toggle) b.classList.toggle("on");
            onclick(b);
        });
        return b;
    };
    const mkSep = () => { const s = document.createElement("span"); s.className = "pfs-sep"; return s; };
    const mkCluster = (...els) => {
        const c = document.createElement("span"); c.className = "pfs-cluster";
        els.forEach(e => c.appendChild(e)); return c;
    };

    const btnAB = mkBtn("A/B", "Split view: source vs current stage", () => { st.ab = !st.ab; draw(); saveProps(); }, true);
    const btnOnion = mkBtn("◐", "Onion skin (ghost previous frame)", () => { st.onion = !st.onion; draw(); saveProps(); }, true);
    const btnGrid = mkBtn("▦", "Pixel grid overlay (zoom >= 8x)", () => { st.grid = !st.grid; draw(); saveProps(); }, true);

    // ---- canvas tools (Aseprite-style) ----
    const TOOL_KEYS = { pointer: "V", move: "M", marquee: "S", place: "P", draw: "B" };
    const TOOL_BTN = {};
    const mkTool = (id, icon, tip) => {
        const b = mkBtn(icon, tip, () => {
            st.tool = id;
            for (const [k, v] of Object.entries(TOOL_BTN)) v.classList.toggle("on", k === id);
            canvas.style.cursor = id === "move" ? "move" : id === "marquee" ? "crosshair" :
                                 id === "place" ? "copy" : id === "draw" ? "crosshair" : "grab";
            saveLayerProps();
        }, true, "pfs-btn");
        if (id === st.tool) b.classList.add("on");
        TOOL_BTN[id] = b;
        return b;
    };
    const btnPointer = mkTool("pointer", "V", "Pointer — pan canvas, click to deselect (V)");
    const btnMove = mkTool("move", "↔", "Move — drag to reposition active layer (M)");
    const btnMarquee = mkTool("marquee", "⬚", "Marquee — draw selection box for fit-to-selection generation (S)");
    const btnPlace = mkTool("place", "◎", "Placement dot — drag to set where next generation centers (P)");
    const btnDraw = mkTool("draw", "✎", "Draw — paint pixels on active layer (B)");

    const btnPal = mkBtn("🎨", "Palette panel", () => { st.showPal = !st.showPal; left.classList.toggle("hide", !st.showPal); saveProps(); }, true);
    btnPal.classList.add("on");
    const btnTl = mkBtn("▤", "Timeline", () => { st.showTl = !st.showTl; tlWrap.classList.toggle("hide", !st.showTl); drawTl(); saveProps(); }, true);
    btnTl.classList.add("on");
    bar.appendChild(mkCluster(btnAB, btnOnion, btnGrid));
    bar.appendChild(mkSep());
    const brushCol = document.createElement("input");
    brushCol.type = "color"; brushCol.value = st.brushColor || "#ffffff";
    brushCol.className = "pfs-color"; brushCol.title = "Brush color (draw tool)";
    brushCol.addEventListener("input", () => { st.brushColor = brushCol.value; });
    brushCol.addEventListener("pointerdown", (e) => e.stopPropagation());
    bar.appendChild(mkCluster(btnPointer, btnMove, btnMarquee, btnPlace, btnDraw, brushCol));

    // ---- drawn-ref toggle (One Forge only): what you drew becomes the
    // ref2v <Picture 1> — composited, uploaded, auto-cropped + upscaled ----
    const btnDrawnRef = mkBtn("✎⤴", "Drawn ref: use what you drew as the generation reference "
        + "(ref2v <Picture 1>). The visible composite of the current frame is uploaded and the "
        + "backend auto-crops + nearest-upscales it. Strokes re-upload automatically while armed. "
        + "A wired first_frame socket wins over the drawn ref.", async () => {
        st.drawnRef = !st.drawnRef;
        saveLayerProps();
        if (st.drawnRef) await uploadDrawnRef();
        else { const w = widgetByName("drawn_ref_image"); if (w) setWidgetValue(w, ""); }
    }, true);
    if (st.drawnRef) btnDrawnRef.classList.add("on");
    if (config.tabs) bar.appendChild(mkCluster(btnDrawnRef));
    bar.appendChild(mkSep());
    bar.appendChild(mkCluster(btnPal, btnTl));
    bar.appendChild(mkSep());
    const btnZmOut = mkBtn("−", "Zoom out", () => zoomBy(1 / 1.25));
    const zoomLbl = document.createElement("span"); zoomLbl.className = "pfs-lbl"; zoomLbl.textContent = "fit";
    const btnZmIn = mkBtn("+", "Zoom in", () => zoomBy(1.25));
    const btnFit = mkBtn("⤢", "Fit to view", () => { st.zoom = 0; draw(); });
    bar.appendChild(mkCluster(btnZmOut, zoomLbl, btnZmIn, btnFit));
    const barSpacer = document.createElement("span"); barSpacer.className = "pfs-spacer"; bar.appendChild(barSpacer);

    // ---- main: left palette | canvas | right params ----
    const main = document.createElement("div"); main.className = "pfs-main";

    const left = document.createElement("div"); left.className = "pfs-left";
    const palHead = document.createElement("div"); palHead.className = "pfs-palhead";
    palHead.innerHTML = 'Palette <span class="pfs-palcount"></span>';
    const palGrid = document.createElement("div"); palGrid.className = "pfs-palgrid";
    const palEmpty = document.createElement("div"); palEmpty.className = "pfs-palempty";
    palEmpty.textContent = "forge frames to pull the palette";
    left.appendChild(palHead); left.appendChild(palGrid); left.appendChild(palEmpty);
    const secInfo = document.createElement("div"); secInfo.className = "pfs-leftsec";
    secInfo.innerHTML = "<h4>Stage</h4>";
    const infoEl = document.createElement("div"); infoEl.className = "pfs-info";
    infoEl.textContent = "run the graph to forge frames";
    secInfo.appendChild(infoEl);
    const secReport = document.createElement("div"); secReport.className = "pfs-leftsec";
    secReport.innerHTML = "<h4>Forge Report</h4>";
    const reportEl = document.createElement("div"); reportEl.className = "pfs-report";
    secReport.appendChild(reportEl);
    left.appendChild(secInfo); left.appendChild(secReport);

    const cwrap = document.createElement("div"); cwrap.className = "pfs-cwrap";
    const canvas = document.createElement("canvas"); canvas.className = "pfs-canvas";
    cwrap.appendChild(canvas);

    const side = document.createElement("div"); side.className = "pfs-side";
    const sideHead = document.createElement("div"); sideHead.className = "pfs-sidehead";
    sideHead.innerHTML = "<h3>Forge Parameters</h3>";
    const btnExpand = mkBtn("▾ all", "Expand all sections", () => setAllDetails(true), false, "pfs-mini");
    const btnCollapse = mkBtn("▸ all", "Collapse all sections", () => setAllDetails(false), false, "pfs-mini");
    sideHead.appendChild(btnExpand); sideHead.appendChild(btnCollapse);
    side.appendChild(sideHead);
    const secQuick = document.createElement("div"); secQuick.className = "pfs-sec";
    secQuick.innerHTML = "<h4>Quick Forge</h4>";

    main.appendChild(left); main.appendChild(cwrap); main.appendChild(side);

    // ---- transport ----
    const transport = document.createElement("div"); transport.className = "pfs-transport";
    const stepFrame = (d) => {
        const n = frameCount();
        if (!n) return;
        st.playing = false; btnPlay.textContent = "▶";
        st.frame = ((st.frame + d) % n + n) % n;
        draw(); drawTl();
    };
    const btnFirst = mkBtn("⏮", "First frame", () => { st.playing = false; btnPlay.textContent = "▶"; st.frame = 0; draw(); drawTl(); }, false, "pfs-tbtn");
    const btnPrev = mkBtn("◀", "Previous frame (left arrow)", () => stepFrame(-1), false, "pfs-tbtn");
    const btnPlay = mkBtn("▶", "Play / pause (space)", () => { st.playing = !st.playing; btnPlay.textContent = st.playing ? "⏸" : "▶"; st._lastT = 0; tick(); }, false, "pfs-tbtn play");
    const btnNext = mkBtn("▶", "Next frame (right arrow)", () => stepFrame(1), false, "pfs-tbtn");
    const btnLast = mkBtn("⏭", "Last frame", () => {
        st.playing = false; btnPlay.textContent = "▶";
        const n = frameCount(); if (n) st.frame = n - 1;
        draw(); drawTl();
    }, false, "pfs-tbtn");
    const btnLoop = mkBtn("🔁", "Loop playback", () => { st.loop = !st.loop; saveProps(); }, true, "pfs-tbtn");
    btnLoop.classList.add("on");
    const fpsLbl = document.createElement("span"); fpsLbl.className = "pfs-lbl"; fpsLbl.textContent = "fps";
    const fpsIn = document.createElement("input"); fpsIn.className = "pfs-num";
    fpsIn.type = "number"; fpsIn.min = 1; fpsIn.max = 60; fpsIn.value = st.fps;
    fpsIn.addEventListener("change", () => {
        st.fps = Math.max(1, Math.min(60, parseFloat(fpsIn.value) || 12));
        fpsIn.value = st.fps; saveProps();
    });
    fpsIn.addEventListener("pointerdown", (e) => e.stopPropagation());
    [btnFirst, btnPrev, btnPlay, btnNext, btnLast, btnLoop].forEach(e => transport.appendChild(e));
    transport.appendChild(mkSep());
    [fpsLbl, fpsIn].forEach(e => transport.appendChild(e));

    // ---- timeline (aseprite-style) ----
    const tlWrap = document.createElement("div"); tlWrap.className = "pfs-tlwrap";
    const tl = document.createElement("canvas"); tl.className = "pfs-tl";
    tlWrap.appendChild(tl);

    // ---- layer controls bar (below timeline) ----
    const layerBar = document.createElement("div"); layerBar.className = "pfs-layerbar";

    const mkLyrBtn = (txt, tip, onclick) => {
        const b = document.createElement("button");
        b.className = "pfs-lyr-btn"; b.textContent = txt; b.title = tip;
        b.addEventListener("click", (e) => { e.stopPropagation(); onclick(); });
        b.addEventListener("pointerdown", (e) => e.stopPropagation());
        return b;
    };

    const btnLyrAdd = mkLyrBtn("+", "Add new layer (Ctrl+N)", () => {
        addLayer(null, { at: st.activeLayer + 1 });
        draw(); drawTl();
    });
    const btnLyrDup = mkLyrBtn("⧉", "Duplicate active layer (Ctrl+D)", () => {
        duplicateLayer(st.activeLayer);
        draw(); drawTl();
    });
    const btnLyrDel = mkLyrBtn("🗑", "Delete active layer", () => {
        if (st.layers.length > 1) { removeLayer(st.activeLayer); draw(); drawTl(); }
    });
    const btnLyrUp = mkLyrBtn("▲", "Move layer up", () => {
        moveLayer(st.activeLayer, st.activeLayer + 1);
        draw(); drawTl();
    });
    const btnLyrDown = mkLyrBtn("▼", "Move layer down", () => {
        moveLayer(st.activeLayer, st.activeLayer - 1);
        draw(); drawTl();
    });
    const btnLyrMerge = mkLyrBtn("⊞", "Merge down (combine with layer below)", () => {
        // TODO: implement merge down
    });
    // Reference toggle: mark the active layer as a guide layer — locked,
    // 40% opacity, single frame shows on every frame, survives executions.
    const btnLyrRef = mkLyrBtn("🔖", "Mark active layer as a REFERENCE layer (locked, "
        + "40% opacity, shows on all frames, never wiped by generations). "
        + "A VISIBLE ref layer automatically feeds the generation as <Picture 1>/<Picture 2> "
        + "(watch the blue P1/P2 badge on its row) — hide it to take it out of the gen. "
        + "Click again to turn it back into a normal layer.", () => {
        const l = getActiveLayer(); if (!l) return;
        if (l.kind === "ref") {
            l.kind = "normal"; l.locked = false; l.opacity = 1.0;
        } else {
            l.kind = "ref"; l.locked = true; l.opacity = 0.4;
            if (!l.source || l.source === "forge") l.source = "user";
        }
        _invalidateAllComposites(); saveLayerProps(); refreshLayerBar(); refreshRefSlots(); draw(); drawTl();
    });
    // Import an image file as a reference layer (character sheets, pose refs)
    const fileIn = document.createElement("input");
    fileIn.type = "file"; fileIn.accept = "image/*"; fileIn.style.display = "none";
    fileIn.addEventListener("change", async () => {
        const f = fileIn.files && fileIn.files[0];
        fileIn.value = "";
        if (!f) return;
        try {
            const fd = new FormData();
            fd.append("image", f, f.name);
            fd.append("type", "temp");
            fd.append("overwrite", "true");
            const r = await fetch("/upload/image", { method: "POST", body: fd });
            const j = await r.json();
            if (!j || !j.name) return;
            const im = new Image();
            im.src = viewURL({ filename: j.name, subfolder: j.subfolder || "", type: "temp" });
            im.onload = () => {
                const layer = addLayer(f.name.replace(/\.[^.]+$/, ""),
                    { kind: "ref", source: "imported", refFile: j.name,
                      locked: true, opacity: 0.4 });
                layer.frames[0] = { img: im, source: "imported" };
                _recalcTotalFrames(); _invalidateAllComposites();
                saveLayerProps(); refreshLayerBar(); refreshRefSlots(); draw(); drawTl();
                console.info(`[PixelForge] ref imported: "${layer.name}" — visible ref layers `
                    + `auto-feed the gen as <Picture 1>/<Picture 2> (blue badge on the row)`);
            };
        } catch (e) { console.warn("[PixelForge] ref import failed:", e); }
    });
    const btnLyrImport = mkLyrBtn("📥", "Import an image as a reference layer "
        + "(character sheet, pose ref). It lands as a locked guide layer AND automatically "
        + "feeds the generation as <Picture 1>/<Picture 2> while visible — the row badge "
        + "shows which slot. Hide the layer to take it out of the gen.", () => fileIn.click());
    root.appendChild(fileIn);

    // Opacity slider for active layer
    const opacWrap = document.createElement("span"); opacWrap.className = "pfs-lyr-opac";
    const opacLbl = document.createElement("span"); opacLbl.className = "pfs-lyr-opac-lbl";
    opacLbl.textContent = "α";
    const opacSlider = document.createElement("input"); opacSlider.type = "range";
    opacSlider.min = "0"; opacSlider.max = "1"; opacSlider.step = "0.01"; opacSlider.value = "1";
    opacSlider.className = "pfs-lyr-opac-slider";
    const opacVal = document.createElement("span"); opacVal.className = "pfs-lyr-opac-val";
    opacVal.textContent = "100%";
    opacSlider.addEventListener("input", () => {
        const v = parseFloat(opacSlider.value);
        setLayerOpacity(st.activeLayer, v);
        opacVal.textContent = Math.round(v * 100) + "%";
        draw();
    });
    opacSlider.addEventListener("pointerdown", (e) => {
        e.stopPropagation();
        try { opacSlider.setPointerCapture(e.pointerId); } catch (_) {}
    });
    opacWrap.append(opacLbl, opacSlider, opacVal);

    // Generation target dropdown
    const genTargetWrap = document.createElement("span"); genTargetWrap.className = "pfs-lyr-gen";
    const genTargetLbl = document.createElement("span"); genTargetLbl.className = "pfs-lyr-gen-lbl";
    genTargetLbl.textContent = "Gen→";
    const genTargetSel = document.createElement("select"); genTargetSel.className = "pfs-lyr-gen-sel";
    function refreshGenTarget() {
        genTargetSel.innerHTML = "";
        const optNew = document.createElement("option"); optNew.value = "new"; optNew.textContent = "New Layer";
        genTargetSel.appendChild(optNew);
        const optCur = document.createElement("option"); optCur.value = "current"; optCur.textContent = "Current Layer";
        genTargetSel.appendChild(optCur);
        for (const l of st.layers) {
            const o = document.createElement("option"); o.value = l.id; o.textContent = l.name;
            genTargetSel.appendChild(o);
        }
        genTargetSel.value = st.genTarget || "new";
    }
    genTargetSel.addEventListener("change", () => {
        st.genTarget = genTargetSel.value;
        saveLayerProps();
    });
    genTargetSel.title = "Which layer receives newly forged frames (New Layer / Current / a named layer)";
    genTargetSel.addEventListener("pointerdown", (e) => e.stopPropagation());
    genTargetWrap.append(genTargetLbl, genTargetSel);

    // Layer name display
    const lyrNameEl = document.createElement("span"); lyrNameEl.className = "pfs-lyr-name";

    layerBar.append(btnLyrAdd, btnLyrDup, btnLyrDel, btnLyrUp, btnLyrDown, btnLyrMerge,
        btnLyrRef, btnLyrImport);
    layerBar.append(opacWrap, genTargetWrap, lyrNameEl);
    tlWrap.appendChild(layerBar);

    // ---- gen-ref slots (One Forge): push the active layer's frame into
    // ref2va <Picture 1> / <Picture 2>. Chain-Studio-style panel refs: pick
    // the layer, arm the slot, generate. A wired socket still wins. ----
    const refSlotWrap = document.createElement("span"); refSlotWrap.className = "pfs-lyr-gen";
    const refSlotLbl = document.createElement("span"); refSlotLbl.className = "pfs-lyr-gen-lbl";
    refSlotLbl.textContent = "Refs:";
    const refSlotBtns = {};
    for (const slot of ["p1", "p2"]) {
        const tag = slot === "p1" ? "<Picture 1>" : "<Picture 2>";
        const b = mkLyrBtn(slot.toUpperCase(), `Gen-ref slot ${tag}: push the ACTIVE layer's `
            + `current frame as the generation reference. Click to arm/re-push; `
            + `armed slot glows — click again to clear. A wired socket overrides the slot.`, async () => {
            if (st.refSlots[slot]) { clearRefSlot(slot); return; }
            await pushLayerToRefSlot(slot);
        });
        refSlotBtns[slot] = b;
        refSlotWrap.appendChild(b);
    }
    refSlotWrap.insertBefore(refSlotLbl, refSlotWrap.firstChild);
    // ---- video ref slot V1 (One Forge): import a clip as ref2va
    // <Video 1> — motion/style anchor. Chain Studio vidref parity: the
    // clip goes to the input dir via /upload/image, the backend decodes +
    // resamples it to 24fps. Sprite pipeline is silent (no soundtrack). ----
    const vidFileIn = document.createElement("input");
    vidFileIn.type = "file"; vidFileIn.accept = "video/*"; vidFileIn.style.display = "none";
    root.appendChild(vidFileIn);
    vidFileIn.addEventListener("change", async () => {
        const f = vidFileIn.files && vidFileIn.files[0];
        vidFileIn.value = "";
        if (f) await uploadVidRef(f);
    });
    const btnVidRef = mkLyrBtn("V1", "Gen-ref slot <Video 1>: import a video clip (2-15s) "
        + "as the motion/style reference for generation — walk cycles, attack swings, "
        + "camera moves. Armed slot glows; click again to clear.", () => {
        if (st.vidRef) { clearVidRef(); return; }
        vidFileIn.click();
    });
    refSlotWrap.appendChild(btnVidRef);
    function refreshRefSlots() {
        const binds = computeRefBinds();
        const autoFor = { p1: null, p2: null };
        for (const lid of Object.keys(binds)) autoFor[binds[lid]] = lid;
        for (const slot of ["p1", "p2"]) {
            const b = refSlotBtns[slot];
            const tag = slot === "p1" ? "<Picture 1>" : "<Picture 2>";
            const armed = !!st.refSlots[slot];
            const autoL = armed ? null
                : (st.layers.find(l => l.id === autoFor[slot]) || null);
            b.classList.toggle("on", armed);
            // orange glow = manual push, blue = auto-bound ref layer
            b.style.color = armed ? "#ff9d45" : (autoL ? "#6fb7ff" : "");
            b.title = armed
                ? `${slot.toUpperCase()} armed (manual): ${st.refSlots[slot]} — click to clear, or re-push after editing the layer`
                : autoL
                    ? `${slot.toUpperCase()} auto: ref layer "${autoL.name}" feeds ${tag} at queue time. Click to push the ACTIVE layer's frame instead (manual override).`
                    : `Gen-ref slot ${tag}: visible 🔖 ref layers fill free slots automatically — or click to push the ACTIVE layer's frame manually.`;
        }
        const varmed = !!st.vidRef;
        btnVidRef.classList.toggle("on", varmed);
        btnVidRef.style.color = varmed ? "#ff9d45" : "";
        btnVidRef.title = varmed
            ? `V1 armed: ${st.vidRef} — click to clear, or re-import to replace`
            : "Gen-ref slot: import a video clip (2-15s) as <Video 1> — the motion/style reference";
    }
    if (config.tabs) {
        layerBar.appendChild(refSlotWrap);
        refreshRefSlots();
    }

    function refreshLayerBar() {
        const layer = getActiveLayer();
        if (!layer) return;
        opacSlider.value = layer.opacity;
        opacVal.textContent = Math.round(layer.opacity * 100) + "%";
        lyrNameEl.textContent = layer.name + (layer.kind === "ref" ? " 🔖" : "");
        btnLyrRef.style.color = layer.kind === "ref" ? "#ff9d45" : "";
        refreshGenTarget();
    }

    // ---- status bar ----
    const status = document.createElement("div"); status.className = "pfs-status";
    status.textContent = "idle — queue a prompt to forge";

    // ---- socket strip: the node's top pins, integrated into the suite ----
    // Each chip mirrors a real input/output socket's live link state, so the
    // pins' features are visible from inside the interface (and the mode
    // badge tells you which pipeline the node will run).
    const sockBar = document.createElement("div"); sockBar.className = "pfs-sockbar";
    const modeBadge = document.createElement("span"); modeBadge.className = "pfs-mode";
    modeBadge.style.display = "none";   // label removed — the node speaks for itself
    sockBar.appendChild(modeBadge);
    const inLbl = document.createElement("span"); inLbl.className = "pfs-socklbl";
    inLbl.textContent = "in";
    sockBar.appendChild(inLbl);
    const inChips = [];
    // node.inputs also carries every widget's hidden input-slot — only the
    // real sockets (no .widget backlink) are actual pins on the node frame.
    (node.inputs || []).forEach((inp, idx) => {
        if (inp.widget) return;
        const chip = document.createElement("span");
        chip.className = "pfs-chip in";
        chip.innerHTML = "<i></i>";
        chip.appendChild(document.createTextNode(inp.name));
        chip.title = `${inp.name} : ${inp.type} — drag to wire · right-click to disconnect`;
        wireChip(chip, "in", inp, idx);
        sockBar.appendChild(chip);
        inChips.push({ inp, chip });
    });
    const sockSep = document.createElement("span"); sockSep.className = "pfs-socksep";
    sockBar.appendChild(sockSep);
    const outLbl = document.createElement("span"); outLbl.className = "pfs-socklbl";
    outLbl.textContent = "out";
    sockBar.appendChild(outLbl);
    const outChips = [];
    (node.outputs || []).forEach((outp, idx) => {
        const chip = document.createElement("span");
        chip.className = "pfs-chip out";
        chip.innerHTML = "<i></i>";
        chip.appendChild(document.createTextNode(outp.name));
        chip.title = `${outp.name} : ${outp.type} — drag to wire · right-click to disconnect`;
        wireChip(chip, "out", outp, idx);
        sockBar.appendChild(chip);
        outChips.push({ outp, chip });
    });

    // ---- socket strip visibility (v3.4.2): hidden by default — owner found
    // the chip row pure clutter. The pins still fully work when shown; the ⇄
    // toolbar toggle brings the strip back for wiring. Persisted in pfs_ui. ----
    const btnSocks = mkBtn("⇄", "Sockets — show/hide the node's input/output pins "
        + "(wire by dragging a chip, right-click to disconnect)", () => {
        st.showSockets = !st.showSockets;
        btnSocks.classList.toggle("on", st.showSockets);
        sockBar.classList.toggle("hide", !st.showSockets);
        saveProps();
    }, true);
    btnSocks.classList.toggle("on", !!st.showSockets);
    bar.appendChild(mkCluster(btnSocks));
    // Primary action: run the forge from inside the suite. Goes through
    // app.queuePrompt (wrapped below) so layers/refs/marquee/prompt-lane
    // all sync to widgets before the prompt is built.
    const btnRun = mkBtn("⚡ Forge", "Run the forge — same as ComfyUI Run, but syncs the\n" +
        "suite first (layers, refs, placement dot, marquee, prompt lane).", () => {
        app.queuePrompt();
    }, false, "pfs-btn pfs-runbtn");
    const verChip = document.createElement("span");
    verChip.className = "pfs-ver"; verChip.textContent = PFS_VERSION;
    verChip.title = "Suite build version — if support asks, read this";
    bar.appendChild(mkSep());
    bar.appendChild(btnRun);
    bar.appendChild(verChip);
    sockBar.classList.toggle("hide", !st.showSockets);

    let flipToForgeTab = null;   // assigned when the One Forge tab strip is built

    // ---- chip wiring: the native socket rows are hidden (FULL-FRAME note),
    // so the chips ARE the pins now. Left-drag a chip to start a link (a
    // wired input chip picks up its existing link, like native sockets);
    // right-click a wired chip to disconnect. Drags run through the canvas's
    // own LinkConnector, so drops, type checks and the empty-canvas search
    // box behave exactly like native wiring. Pointer events are mirrored onto
    // the canvas element because the suite DOM sits above it. ----
    const lcOf = () => (app.canvas && app.canvas.linkConnector) || null;
    const canvasEl = () => app.canvas && (app.canvas.canvas || app.canvasEl);

    function forwardToCanvas(ev) {
        const cv = canvasEl();
        if (!cv || ev.target === cv) return;    // canvas already got the real one
        if (root.contains(ev.target)) return;   // over the suite: caller decides
        cv.dispatchEvent(new PointerEvent(ev.type, {
            clientX: ev.clientX, clientY: ev.clientY,
            button: ev.button, buttons: ev.buttons,
            pointerId: ev.pointerId, bubbles: true, cancelable: true,
        }));
    }

    function chipWireStart(dir, slot) {
        const lc = lcOf();
        if (!lc || lc.isConnecting || !node.graph) return false;
        try {
            if (dir === "out") lc.dragNewFromOutput(node.graph, node, slot);
            else if (slot.link != null) lc.moveInputLink(node.graph, slot);
            else lc.dragNewFromInput(node.graph, node, slot);
            if (app.canvas) app.canvas.dirty_bgcanvas = true;
        } catch (e) {
            return false;   // older frontend without LinkConnector — display-only chips
        }
        return !!lc.isConnecting;
    }

    function wireChip(chip, dir, slot, idx) {
        chip.style.cursor = "crosshair";
        chip.addEventListener("pointerdown", (e) => {
            if (e.button !== 0) return;
            e.stopPropagation(); e.preventDefault();
            const sx = e.clientX, sy = e.clientY;
            let dragging = false;
            const cleanup = () => {
                window.removeEventListener("pointermove", move, true);
                window.removeEventListener("pointerup", up, true);
            };
            const move = (mev) => {
                if (!dragging) {
                    if (Math.hypot(mev.clientX - sx, mev.clientY - sy) < PFS_DRAG_PX) return;
                    dragging = chipWireStart(dir, slot);
                    if (!dragging) { cleanup(); return; }
                }
                forwardToCanvas(mev);
            };
            const up = (uev) => {
                cleanup();
                if (!dragging) return;
                if (root.contains(uev.target)) {
                    // released back over the suite — treat as "never mind"
                    const lc = lcOf();
                    if (lc && lc.isConnecting) lc.reset();
                    if (app.canvas) app.canvas.setDirtyCanvas(true, true);
                } else {
                    forwardToCanvas(uev);   // canvas drops (or opens the search box)
                    const lc = lcOf();
                    if (lc && lc.isConnecting) lc.reset();   // stale-drag safety net
                }
                setTimeout(refreshSockets, 60);
            };
            window.addEventListener("pointermove", move, true);
            window.addEventListener("pointerup", up, true);
        });
        chip.addEventListener("contextmenu", (e) => {
            e.preventDefault(); e.stopPropagation();
            try {
                if (dir === "in") { if (slot.link != null) node.disconnectInput(idx); }
                else if (slot.links && slot.links.length) node.disconnectOutput(idx);
            } catch (err) { /* older frontend */ }
            refreshSockets();
        });
    }

    function refreshSockets() {
        let imagesWired = false;
        for (const { inp, chip } of inChips) {
            const wired = inp.link != null;
            chip.classList.toggle("wired", wired);
            chip.title = `${inp.name} : ${inp.type} — ${wired ? "wired" : "open"}`;
            if (inp.name === "images" && wired) imagesWired = true;
        }
        for (const { outp, chip } of outChips) {
            const wired = !!(outp.links && outp.links.length);
            chip.classList.toggle("wired", wired);
            chip.title = `${outp.name} : ${outp.type} — ${wired ? "wired" : "open"}`;
        }
        // mode badge label removed per owner — node speaks for itself.
        if (0) modeBadge.textContent = config.tabs
        // One Forge: wiring external frames in flips the panel to the Forge tab
        if (config.tabs && imagesWired && !st._imagesWired && flipToForgeTab) flipToForgeTab();
        st._imagesWired = imagesWired;
    }

    [bar, sockBar, main, transport, tlWrap, status].forEach(e => root.appendChild(e));

    // ---- keyboard shortcuts: tools, transport, layer ops ----
    root.addEventListener("keydown", (e) => {
        const t = e.target;
        if (t && /^(INPUT|SELECT|TEXTAREA)$/.test(t.tagName)) return;
        if (e.code === "Space") { e.preventDefault(); btnPlay.click(); }
        else if (e.key === "ArrowLeft") { e.preventDefault(); stepFrame(-1); }
        else if (e.key === "ArrowRight") { e.preventDefault(); stepFrame(1); }
        else if (e.key === "v" || e.key === "V") { btnPointer.click(); }
        else if (e.key === "m" || e.key === "M") { btnMove.click(); }
        else if (e.key === "s" && !e.ctrlKey && !e.metaKey) { btnMarquee.click(); }
        else if (e.key === "p" || e.key === "P") { btnPlace.click(); }
        else if (e.key === "b" || e.key === "B") { btnDraw.click(); }
        else if (e.key === "Escape") { st.marquee = null; draw(); }
        else if (e.key === "Delete" || e.key === "Backspace") {
            // Delete selected layer's current frame content
            const layer = getActiveLayer();
            if (layer && !layer.locked && layer.frames[st.activeFrame]) {
                layer.frames[st.activeFrame] = null;
                layer._dirty = true;
                _invalidateAllComposites();
                draw(); drawTl();
            }
        }
        // Layer shortcuts with Ctrl/Cmd
        else if ((e.ctrlKey || e.metaKey) && e.key === "n") {
            e.preventDefault();
            addLayer(null, { at: st.activeLayer + 1 });
            draw(); drawTl();
        }
        else if ((e.ctrlKey || e.metaKey) && e.key === "d") {
            e.preventDefault();
            duplicateLayer(st.activeLayer);
            draw(); drawTl();
        }
        // Layer selection with [ and ]
        else if (e.key === "[") { setActiveLayer(st.activeLayer - 1); drawTl(); }
        else if (e.key === "]") { setActiveLayer(st.activeLayer + 1); drawTl(); }
    });

    // ---- parameter controls (every native widget, mirrored two-way) ----
    const widgetByName = (n) => (node.widgets || []).find(w => w.name === n);
    const ctrls = [];
    // ---- v3.6.1-presetview: "preset" shows what it RESOLVES to, live ----
    // Mirrors the _pick/_tri fallbacks in pf_studio.py PixelForgeSuperForge.run()
    // (the One Forge forges through that same code path). Resolved values track
    // the main knobs: look / key_strength / motion_fix. Keep in sync with python.
    const presetLabels = [];
    const PFS_KS = { "Gentle": [0.18, 0.8], "Normal": [0.25, 1.2], "Aggressive": [0.35, 2.0] };
    const PFS_MOTION = { "Off": null, "Light": ["despike", 4, 1, 1], "Strong": ["despike_matte", 4, 1, 1], "Extra strong": ["movelock", 20, 1, 1], "Smooth shading": ["median3_inner", 10, 2, 3] };
    const PFS_QLOOK = { "Modern (smooth color)": [1.0, 1.0, 0.0], "Retro 16-bit": [1.15, 1.05, 0.4], "Hardcore 8-bit": [1.05, 1.05, 0.3] };
    function presetResolved(name) {
        const gv = (n) => { const x = widgetByName(n); return x ? x.value : undefined; };
        const look = gv("look");
        const ks = PFS_KS[gv("key_strength")] ? gv("key_strength") : "Normal";
        const mf = (gv("motion_fix") in PFS_MOTION) ? gv("motion_fix") : "Off";
        const hibit = typeof look === "string" && look.startsWith("Hi-bit");
        const cel = look === "Hi-bit cel shading";
        const qNA = hibit ? "n/a" : undefined;   // quantize rows unused under hi-bit looks
        const tpNA = hibit ? undefined : "n/a";  // hi-bit rows unused under quantize looks
        switch (name) {
            case "adv_key_method": return "flood";
            case "adv_key_tolerance": return PFS_KS[ks][0];
            case "adv_key_shadow": return PFS_KS[ks][1];
            case "adv_key_softness": return 0;
            case "adv_key_erode": return 1;
            case "adv_key_despill": return "on";
            case "adv_key_interior": return "on";
            case "adv_key_interior_tol": return 0.5;
            case "adv_key_interior_max_area": return 2.0;
            case "adv_key_rescue": return "on";
            case "adv_key_temporal_alpha": return "on";
            case "adv_key_drop_detached": return 5;
            case "adv_q_method": return qNA || "kmeans";
            case "adv_q_mapping": return qNA || "lab";
            case "adv_q_saturation": return qNA || (PFS_QLOOK[look] || [1.25])[0];
            case "adv_q_contrast": return qNA || (PFS_QLOOK[look] || [0, 1.1])[1];
            case "adv_q_sharpen": return qNA || (PFS_QLOOK[look] || [0, 0, 0.6])[2];
            case "adv_q_flatten": return qNA || 0;
            case "adv_q_temporal_lock": return qNA || 0;
            case "adv_tp_bands": return tpNA || (cel ? 3 : 1);
            case "adv_tp_hue_shift": return tpNA || (cel ? 0.3 : 0);
            case "adv_tp_vibrancy": return tpNA || 1.15;
            case "adv_tp_cel_contrast": return tpNA || 1.25;
            case "adv_tp_outline": return tpNA || (cel ? "on" : "off");
            case "adv_tp_ambient": return tpNA || 0.35;
            case "adv_tp_shadow_thr": return tpNA || 0.55;
            case "adv_tp_highlight_thr": return tpNA || 0.85;
            case "adv_tp_flatten": return tpNA || 5;
            case "adv_tp_saturation": return tpNA || 1.25;
            case "adv_tp_contrast": return tpNA || 1.1;
            case "adv_tp_sharpen": return tpNA || 0.6;
            case "adv_tp_share": return tpNA || 0.75;
            case "adv_motion_mode": { const m = PFS_MOTION[mf]; return m ? m[0] : "off"; }
            case "adv_motion_threshold": { const m = PFS_MOTION[mf]; return m ? m[1] : 10; }
            case "adv_motion_commit": { const m = PFS_MOTION[mf]; return m ? m[2] : 2; }
            case "adv_motion_hold": { const m = PFS_MOTION[mf]; return m ? m[3] : 3; }
            case "adv_crop_padding": return "auto~10%";   // v3.7.0: proportional margin
            case "adv_crop_snap": return 8;
            case "adv_loop_max_error": return 0.06;
            case "adv_loop_tail": return 0.5;
            case "adv_dedup_threshold": return 0.01;
        }
        return undefined;
    }
    function refreshPresetLabels() {
        for (const it of presetLabels) {
            const rv = presetResolved(it.w.name);
            if (it.kind === "num") {
                it.num.placeholder = rv !== undefined ? String(rv) : "preset";
                it.num.title = ((it.w.options && it.w.options.tooltip) || "") +
                    (rv !== undefined ? "  [inheriting " + rv + " - type a number to override]" : "  (empty / -1 = preset)");
            } else {
                const opt = [...it.ctl.options].find(o => o.value === "preset");
                if (opt) opt.textContent = rv !== undefined ? "preset (" + rv + ")" : "preset";
                if (it.w.value === "preset" && rv !== undefined)
                    it.ctl.title = ((it.w.options && it.w.options.tooltip) || "") + "  [preset = " + rv + "]";
            }
        }
    }
    for (const knob of ["look", "key_strength", "motion_fix"]) {
        const kw = widgetByName(knob);
        if (kw && !kw._pfsPresetHooked) {
            kw._pfsPresetHooked = true;
            const prev = kw.callback;
            kw.callback = function (...a) { if (prev) prev.apply(this, a); try { refreshPresetLabels(); } catch (_) {} };
        }
    }


    function setWidgetValue(w, v) {
        w.value = v;
        if (w.callback) w.callback.call(w, v);
        app.graph.setDirtyCanvas(true, true);
    }

    function addControl(parent, w) {
        const row = document.createElement("div"); row.className = "pfs-qrow";
        const lab = document.createElement("label");
        lab.textContent = prettyName(w.name);
        lab.title = w.name;
        row.appendChild(lab);
        let ctl, sync;
        if (w.type === "combo") {
            ctl = document.createElement("select");
            const vals = Array.isArray(w.options?.values) ? w.options.values : [];
            for (const v of vals) {
                const o = document.createElement("option"); o.value = v; o.textContent = v;
                ctl.appendChild(o);
            }
            ctl.value = w.value;
            if (w.options && w.options.tooltip) ctl.title = w.options.tooltip;
            // v3.6.1: a "preset" choice shows what it resolves to
            if (vals.indexOf("preset") !== -1) {
                presetLabels.push({ kind: "combo", ctl, w });
                const rv = presetResolved(w.name);
                const opt = [...ctl.options].find(o => o.value === "preset");
                if (opt && rv !== undefined) opt.textContent = "preset (" + rv + ")";
                if (w.value === "preset" && rv !== undefined)
                    ctl.title = (w.options.tooltip || "") + "  [preset = " + rv + "]";
            }
            ctl.addEventListener("change", () => setWidgetValue(w, ctl.value));
            sync = () => { if (String(ctl.value) !== String(w.value)) ctl.value = w.value; };
            row.appendChild(ctl);
        } else if (w.type === "toggle" || typeof w.value === "boolean") {
            ctl = document.createElement("input"); ctl.type = "checkbox"; ctl.checked = !!w.value;
            ctl.addEventListener("change", () => setWidgetValue(w, ctl.checked));
            sync = () => { if (ctl.checked !== !!w.value) ctl.checked = !!w.value; };
            row.appendChild(ctl);
        } else if (typeof w.value === "string") {
            if ((w.options && w.options.multiline) || PFS_MULTILINE.has(w.name)) {
                row.classList.add("wrap");
                ctl = document.createElement("textarea");
                ctl.className = "pfs-ta"; ctl.rows = 2; ctl.value = w.value;
                ctl.addEventListener("change", () => setWidgetValue(w, ctl.value));
            } else {
                ctl = document.createElement("input"); ctl.type = "text"; ctl.value = w.value;
                ctl.addEventListener("change", () => setWidgetValue(w, ctl.value));
            }
            sync = () => { if (String(ctl.value) !== String(w.value)) ctl.value = w.value; };
            row.appendChild(ctl);
        } else {
            // numeric: slider (when min+max known) + direct entry box.
            // seed gets a dice button instead of a slider (its range is 2^64).
            const isSeed = w.name === "seed";
            const hasRange = !isSeed && w.options && w.options.min !== undefined && w.options.max !== undefined;
            // v3.5.5-stepfix: the ComfyUI frontend stores widget options.step as the
            // def step x10 (raw def step in options.step2) — litegraph slider legacy
            // (settingStore: addWidget(..., {step: a*10, step2: a})). Reading
            // options.step raw made every slider 10x coarser than designed; narrow
            // ranges became FROZEN (adv_tp_bands [-1,4] -> step 10 -> -1 is the ONLY
            // legal value; every native drag and every programmatic set snapped back).
            // This was the "sliders don't budge" root cause all along.
            const step = (w.options && w.options.step2 > 0) ? w.options.step2
                : (w.options && w.options.step > 0) ? w.options.step / 10 : 1;
            const isInt = Number.isInteger(step);
            // -1 sentinel = "inherit the Look/strength preset" (backend _pick).
            // Show it as a readable placeholder instead of a raw -1 that looks
            // like a broken value.
            const presetSentinel = w.options && w.options.min === -1;
            const showVal = (v) => (presetSentinel && (v === -1 || v === "-1")) ? "" : v;
            const num = document.createElement("input");
            num.type = "number"; num.value = showVal(w.value);
            num.min = w.options?.min ?? ""; num.max = w.options?.max ?? ""; num.step = step;
            if (presetSentinel) {
                const rv = presetResolved(w.name);
                num.placeholder = rv !== undefined ? String(rv) : "preset";
                num.title = (w.options?.tooltip || "") + (rv !== undefined ? "  [inheriting " + rv + " - type a number to override]" : " (empty / -1 = preset)");
                presetLabels.push({ kind: "num", num, w });
            }
            let slider = null;
            let sliding = false;
            const commit = (raw) => {
                let v;
                if (presetSentinel && (raw === "" || raw === "preset")) v = -1;
                else {
                    v = parseFloat(raw);
                    if (!Number.isFinite(v)) v = w.value;
                    if (isInt) v = Math.round(v);
                    if (w.options?.min !== undefined) v = Math.max(w.options.min, v);
                    if (w.options?.max !== undefined) v = Math.min(w.options.max, v);
                }
                setWidgetValue(w, v);
                num.value = showVal(v);
                if (slider) slider.value = v;
            };
            if (hasRange) {
                slider = document.createElement("input");
                slider.type = "range";
                slider.min = w.options.min; slider.max = w.options.max;
                slider.step = step; slider.value = w.value;
                slider.addEventListener("input", () => {
                    num.value = showVal(parseFloat(slider.value));
                    commit(slider.value);
                });
                // never let a sync yank the thumb mid-drag; capture the pointer
                // ourselves so a canvas-level pointer capture (Vue frontend)
                // can't steal the drag and freeze the thumb
                slider.addEventListener("pointerdown", (e) => {
                    sliding = true; e.stopPropagation();
                    try { slider.setPointerCapture(e.pointerId); } catch (_) {}
                });
                const slideEnd = () => { sliding = false; };
                slider.addEventListener("pointerup", slideEnd);
                slider.addEventListener("pointercancel", slideEnd);
                window.addEventListener("pointerup", slideEnd);
                // v3.5.4: manual-drive fallback + deep forensics. Owner's live tab:
                // pointerdown LANDS on sliders but native drags produce ZERO input
                // events (mechanism unknown; everything proven healthy in isolation).
                // Native drag stays primary; if it stalls, we drive the value from
                // pointer x ourselves, so the slider works regardless of the culprit.
                let __activeG = 0;
                slider.addEventListener("input", () => {
                    if (__activeG === 0) __pfsProbe("nongesture-input", { widget: w.name, value: slider.value });
                });
                slider.addEventListener("pointerdown", (e) => {
                    const g = { from: slider.value, moves: 0, native: 0, fell: 0, t0: Date.now(), endedBy: "?", capOk: false, driving: false };
                    __activeG++;
                    try { slider.setPointerCapture(e.pointerId); g.capOk = true; } catch (_) {}
                    const stepN = parseFloat(slider.step) || 1;
                    const minN = parseFloat(slider.min), maxN = parseFloat(slider.max);
                    const drive = (clientX) => {
                        const b = slider.getBoundingClientRect();
                        if (!b.width) return;
                        const frac = Math.min(1, Math.max(0, (clientX - b.left) / b.width));
                        let v = minN + frac * (maxN - minN);
                        v = Math.round(v / stepN) * stepN;
                        v = parseFloat(v.toFixed(6));
                        if (String(slider.value) !== String(v)) {
                            slider.value = v;
                            g.fell++;
                            g.driving = true;
                            slider.dispatchEvent(new Event("input", { bubbles: true }));
                            g.driving = false;
                        }
                    };
                    const onMove = (ev) => {
                        g.moves++;
                        if (g.native === 0 && g.moves >= 2) drive(ev.clientX);
                    };
                    const onInput = () => { if (!g.driving) g.native++; };
                    const finish = (kind, ev) => {
                        window.removeEventListener("pointermove", onMove, true);
                        window.removeEventListener("pointerup", onUp, true);
                        window.removeEventListener("pointercancel", onCancel, true);
                        slider.removeEventListener("input", onInput);
                        __activeG--;
                        g.endedBy = kind;
                        // dead click (no native response, no drag): drive once from x
                        if (g.native === 0 && g.moves === 0) {
                            drive(ev && ev.clientX != null ? ev.clientX : e.clientX);
                        }
                        const r = slider.getBoundingClientRect();
                        const suites = document.querySelectorAll(".pfs-root").length;
                        const from = g.from, to = slider.value, fell = g.fell,
                            moves = g.moves, native = g.native, endedBy = g.endedBy,
                            capOk = g.capOk, ms = Date.now() - g.t0,
                            rect = [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)];
                        setTimeout(() => {
                            __pfsProbe("gesture2", {
                                widget: w.name, from, to, wAfter: w.value,
                                moves, native, fellBack: fell, endedBy, capOk, ms,
                                rect, suites,
                                smin: slider.min, smax: slider.max, sstep: slider.step,
                            });
                        }, 250);
                    };
                    const onUp = (ev) => finish("up", ev);
                    const onCancel = (ev) => finish("cancel", ev);
                    window.addEventListener("pointermove", onMove, true);
                    window.addEventListener("pointerup", onUp, true);
                    window.addEventListener("pointercancel", onCancel, true);
                    slider.addEventListener("input", onInput);
                }, true);
                row.appendChild(slider);
            }
            num.addEventListener("change", () => commit(num.value));
            row.appendChild(num);
            if (isSeed) {
                const dice = document.createElement("button");
                dice.className = "pfs-mini"; dice.textContent = "🎲";
                dice.title = "New random seed";
                dice.addEventListener("click", (e) => {
                    e.stopPropagation();
                    commit(String(Math.floor(Math.random() * 9007194740991)));
                });
                dice.addEventListener("pointerdown", (e) => e.stopPropagation());
                row.appendChild(dice);
            }
            ctl = num;
            sync = () => {
                if (sliding) return;  // drag in progress — the slider is the truth
                if (String(num.value) !== String(showVal(w.value))) num.value = showVal(w.value);
                if (slider && String(slider.value) !== String(w.value)) slider.value = w.value;
            };
        }
        ctl.addEventListener("pointerdown", (e) => e.stopPropagation());
        parent.appendChild(row);
        ctrls.push({ w, ctl, sync });
    }

    const claimed = new Set();
    for (const name of QUICK) {
        const w = widgetByName(name);
        if (w) { addControl(secQuick, w); claimed.add(name); }
    }

    function fillSections(parent, sections, openFirst) {
        let first = true;
        for (const [secTitle, names] of sections) {
            const det = document.createElement("details"); det.className = "pfs-details";
            const sum = document.createElement("summary"); sum.textContent = secTitle;
            det.appendChild(sum);
            const body = document.createElement("div"); body.className = "pfs-body";
            let added = 0;
            for (const name of names) {
                const w = widgetByName(name);
                if (w) { addControl(body, w); claimed.add(name); added++; }
            }
            if (added) {
                if (openFirst && first) det.open = true;
                first = false;
                det.appendChild(body);
                parent.appendChild(det);
            }
        }
    }

    if (!config.tabs) {
        fillSections(side, SECTIONS, false);
        side.insertBefore(secQuick, sideHead.nextSibling);
    } else {
        const strip = document.createElement("div"); strip.className = "pfs-tabstrip";
        const panels = [];
        config.tabs.forEach(([tabName, content], i) => {
            const b = document.createElement("button");
            b.className = "pfs-ptab" + (i === 0 ? " on" : "");
            b.textContent = tabName;
            b.addEventListener("click", (e) => {
                e.stopPropagation();
                panels.forEach((p, j) => { p.style.display = j === i ? "" : "none"; });
                strip.querySelectorAll(".pfs-ptab").forEach((x, j) => x.classList.toggle("on", j === i));
            });
            b.addEventListener("pointerdown", (e) => e.stopPropagation());
            strip.appendChild(b);
            const panel = document.createElement("div");
            if (i !== 0) panel.style.display = "none";
            if (content === "forge") {
                panel.appendChild(secQuick);
                fillSections(panel, SECTIONS, false);
            } else {
                fillSections(panel, content, true);
            }
            panels.push(panel);
        });
        side.appendChild(strip);
        panels.forEach(p => side.appendChild(p));
        flipToForgeTab = () => {
            const btns = strip.querySelectorAll(".pfs-ptab");
            if (btns[1]) btns[1].click();   // 🎨 Forge
        };
    }

    // safety net: anything unlisted still gets a home (the DOM widget isn't
    // in node.widgets yet at this point — addDOMWidget runs below)
    const extra = (node.widgets || []).filter(w => !claimed.has(w.name) && !PFS_INTERNAL.has(w.name));
    if (extra.length) {
        const det = document.createElement("details"); det.className = "pfs-details";
        const sum = document.createElement("summary"); sum.textContent = "More Parameters";
        det.appendChild(sum);
        const body = document.createElement("div"); body.className = "pfs-body";
        for (const w of extra) addControl(body, w);
        det.appendChild(body);
        side.appendChild(det);
    }

    function setAllDetails(open) {
        for (const d of side.querySelectorAll("details.pfs-details")) d.open = open;
    }

    function refreshCtrls() {
        for (const { w, ctl, sync } of ctrls) {
            if (sync && document.activeElement !== ctl) sync();
        }
    }

    // ---- hide every native widget: the suite IS the interface ----
    function hideAllWidgets() {
        for (const w of node.widgets || []) {
            if (w === domWidget) continue;
            hideWidget(w);
        }
    }

    // ---- persistence (properties — never the prompt) ----
    function saveProps() {
        node.properties = node.properties || {};
        node.properties.pfs_ui = {
            stage: st.stage, fps: st.fps, loop: st.loop,
            onion: st.onion, grid: st.grid, ab: st.ab,
            showPal: st.showPal, showTl: st.showTl, showSockets: !!st.showSockets,
        };
        saveLayerProps();
    }
    function applyProps() {
        const p = node.properties && node.properties.pfs_ui;
        if (p) {
            Object.assign(st, {
                stage: p.stage || "final", fps: p.fps || 12,
                loop: p.loop !== false, onion: !!p.onion, grid: !!p.grid,
                ab: !!p.ab,
                showPal: p.showPal !== false, showTl: p.showTl !== false,
                showSockets: !!p.showSockets,
            });
            fpsIn.value = st.fps;
            btnLoop.classList.toggle("on", st.loop);
            btnOnion.classList.toggle("on", st.onion);
            btnGrid.classList.toggle("on", st.grid);
            btnAB.classList.toggle("on", st.ab);
            btnPal.classList.toggle("on", st.showPal);
            btnTl.classList.toggle("on", st.showTl);
            left.classList.toggle("hide", !st.showPal);
            tlWrap.classList.toggle("hide", !st.showTl);
            btnSocks.classList.toggle("on", st.showSockets);
            sockBar.classList.toggle("hide", !st.showSockets);
        }
        restoreLayerProps();
    }

    // ---- stage loading ----
    // SERVER FLATTEN: the server iterates every ui value when merging
    // (execution.py), so dict-valued keys arrive as a list of their KEYS and
    // strings arrive as char arrays — only flat lists of real entries make
    // the trip intact. The backend therefore ships `pf_frames` / `pf_meta`
    // (flat lists of {stage, ...} dicts). We also accept the legacy
    // dict-shaped pf_stages / pf_stage_meta for older backends, and silently
    // skip anything malformed — this loader must NEVER throw, or the suite
    // shows nothing at all.
    function loadStages(payload) {
        st.report = (payload.pf_report || [""])[0] || "";
        const dur = (payload.pf_durations_frames || [])[0];
        st.durations = Array.isArray(dur) && dur.length ? dur : null;

        // ==== NEW: pf_layers format (layer-aware) ====
        const layerList = payload.pf_layers;
        if (Array.isArray(layerList) && layerList.length) {
            // Preserve existing layer transforms/keyframes if layer IDs match
            const oldLayerMap = {};
            for (const l of st.layers) oldLayerMap[l.id] = l;

            // Build the incoming forge layers from the payload
            const incoming = [];
            for (const ld of layerList) {
                const existing = oldLayerMap[ld.id];
                const layer = {
                    id: ld.id || _makeLayerId(),
                    name: ld.name || ("Layer " + (incoming.length + 1)),
                    kind: "normal",
                    source: "forge",
                    refFile: "",
                    visible: existing ? existing.visible : true,
                    opacity: existing ? existing.opacity : 1.0,
                    blend: existing ? existing.blend : "normal",
                    locked: existing ? existing.locked : false,
                    frames: [],
                    transform: existing ? { ...existing.transform } :
                        { x: 0, y: 0, scale: 1.0, anchorX: 0.5, anchorY: 1.0 },
                    keyframes: existing ? { ...existing.keyframes } : {},
                    _dirty: true,
                };
                // Load frame images
                if (Array.isArray(ld.frames)) {
                    layer.frames = ld.frames.map((r, i) => {
                        if (!r || !r.filename) return null;
                        const im = new Image();
                        im.src = viewURL(r);
                        im.onload = () => { layer._dirty = true; _invalidateAllComposites(); draw(); drawTl(); };
                        return { img: im, source: "forge" };
                    });
                }
                incoming.push(layer);
            }

            // USER LAYERS SURVIVE: reference guides, imports and painted
            // layers are never wiped by an execution — only forge-owned
            // (generated) layers get replaced.
            const tgt = st.genTarget || "new";
            let target = null;
            if (tgt === "current") target = st.layers[st.activeLayer] || null;
            else if (tgt !== "new") target = st.layers.find(l => l.id === tgt) || null;

            let regenStart = -1;
            if (target && incoming.length) {
                if (st.regenWindow) {
                    // Surgical regen: splice the regenerated frames over the
                    // selected range ONLY — cels outside it stay untouched.
                    const rw = st.regenWindow;
                    const gen = incoming[0].frames;
                    for (let i = 0; i < rw.count && i < gen.length; i++) {
                        target.frames[rw.start + i] = gen[i];
                    }
                    regenStart = rw.start;
                    incoming.shift();
                } else {
                    // Fill the target layer in place — identity, transform,
                    // keyframes and ref/normal kind all survive the regen.
                    target.frames = incoming[0].frames;
                    incoming.shift();
                }
                target._dirty = true;
            }
            st.regenWindow = null;
            const targetId = target ? target.id : null;
            st.layers = st.layers.filter(l =>
                (l.source && l.source !== "forge") || l.id === targetId);
            st.layers.push(...incoming);
            if (!st.layers.length && incoming.length) st.layers = [incoming[0]];
            const actIdx = st.layers.findIndex(l => l.id ===
                (target ? target.id : (incoming[0] && incoming[0].id)));
            st.activeLayer = actIdx >= 0 ? actIdx : 0;

            // Debug stages: move pipeline stages to debug mode
            st.debugStages = {};
            const debugList = payload.pf_debug_stages;
            if (Array.isArray(debugList)) {
                for (const ds of debugList) {
                    if (ds && ds.stage && Array.isArray(ds.frames)) {
                        st.debugStages[ds.stage] = ds.frames;
                    }
                }
            }

            _recalcTotalFrames();
            _invalidateAllComposites();
            st.frame = regenStart >= 0 ? regenStart : 0;
            st._acc = 0; st.tlScroll = 0; st._palKey = ""; st.frameSel = null;
            reportEl.textContent = st.report;
            saveLayerProps();
            refreshLayerBar();
            updateInfo(); draw(); drawTl();
            return;
        }

        // ==== LEGACY: pf_frames format (backward compat) ====
        // Create a single default layer from the flat frames list
        st.order = Array.isArray(payload.pf_order) ? payload.pf_order.slice() : [];
        st.imgs = {}; st.thumbs = {};
        st.meta = {};
        const metaList = payload.pf_meta;
        if (Array.isArray(metaList)) {
            for (const m of metaList) {
                if (m && typeof m === "object" && typeof m.stage === "string") {
                    st.meta[m.stage] = m;
                }
            }
        }

        const refs = {};
        const flat = payload.pf_frames;
        if (Array.isArray(flat)) {
            for (const r of flat) {
                if (!r || typeof r !== "object" || !r.filename || typeof r.stage !== "string") continue;
                (refs[r.stage] = refs[r.stage] || []).push(r);
            }
        }

        const gifRefs = Array.isArray(payload.pf_export_gif) ? payload.pf_export_gif : [];
        if (gifRefs.length && gifRefs[0] && gifRefs[0].filename) {
            refs.export = gifRefs.slice(0, 1);
            st.meta.export = { frames: 1, w: 0, h: 0, shown: 1 };
            if (!st.order.includes("export")) st.order.push("export");
            st.stage = "export";
        }
        st.stages = refs;

        // Populate legacy stage images (used by drawFrameInto for non-layer path)
        for (const name of Object.keys(refs)) {
            if (!Array.isArray(refs[name])) continue;
            st.imgs[name] = refs[name].map((r) => {
                const im = new Image();
                im.src = viewURL(r);
                im.onload = () => {
                    if (name === "export" && st.meta.export) {
                        st.meta.export.w = im.naturalWidth;
                        st.meta.export.h = im.naturalHeight;
                        updateInfo();
                    }
                    st._palKey = ""; draw(); drawTl();
                };
                return im;
            });
        }

        // If no layers exist yet, create one from the "final" stage frames
        if (!st.layers.length) {
            const finalFrames = refs.final || refs[Object.keys(refs).pop()] || [];
            const layer = {
                id: _makeLayerId(), name: "Generated",
                kind: "normal", source: "forge", refFile: "",
                visible: true, opacity: 1.0, blend: "normal", locked: false,
                frames: finalFrames.map(r => {
                    if (!r || !r.filename) return null;
                    const im = new Image();
                    im.src = viewURL(r);
                    im.onload = () => { layer._dirty = true; _invalidateAllComposites(); draw(); drawTl(); };
                    return { img: im, source: "forge" };
                }),
                transform: { x: 0, y: 0, scale: 1.0, anchorX: 0.5, anchorY: 1.0 },
                keyframes: {},
                _dirty: true,
            };
            st.layers = [layer];
            st.activeLayer = 0;
        }

        if (!refs[st.stage]) st.stage = refs.final ? "final" : (st.order[st.order.length - 1] || "final");
        st.frame = 0; st._acc = 0; st.tlScroll = 0; st._palKey = "";
        _recalcTotalFrames();
        _invalidateAllComposites();
        reportEl.textContent = st.report;
        updateInfo(); draw(); drawTl();
    }

    function stageList() { return st.order.length ? st.order : STAGE_ORDER_FALLBACK; }
    // activeImgs now returns composited frames from layers, not stage frames
    function activeImgs() {
        // If we have layers, return composited frames
        if (st.layers.length) {
            const out = [];
            for (let i = 0; i < st.totalFrames; i++) {
                // We return a placeholder; actual compositing happens in draw()
                out.push({ _composite: true, _frame: i });
            }
            return out;
        }
        // Legacy: return stage images
        return st.imgs[st.stage] || [];
    }
    function frameCount() { return st.totalFrames || (st.imgs[st.stage] || []).length; }

    function updateInfo() {
        const m = st.meta[st.stage];
        if (!m) { infoEl.textContent = "no stage data"; return; }
        infoEl.textContent =
            `${STAGE_LABELS[st.stage] || st.stage}: ${m.frames}f @ ${m.w}×${m.h}` +
            (m.shown < m.frames ? ` (preview shows ${m.shown})` : "");
    }

    // ---- palette extraction (from the current stage+frame) ----
    const palCanvas = document.createElement("canvas");
    function refreshPalette() {
        const img = activeImgs()[st.frame];
        const key = img && img.naturalWidth ? `${st.stage}:${st.frame}:${img.src}` : "";
        if (key === st._palKey) return;
        st._palKey = key;
        st.pal = [];
        if (img && img.naturalWidth) {
            const S = 96;
            const sc = Math.min(1, S / Math.max(img.naturalWidth, img.naturalHeight));
            const w = Math.max(1, Math.round(img.naturalWidth * sc));
            const h = Math.max(1, Math.round(img.naturalHeight * sc));
            palCanvas.width = w; palCanvas.height = h;
            const px = palCanvas.getContext("2d", { willReadFrequently: true });
            px.imageSmoothingEnabled = false;
            px.drawImage(img, 0, 0, w, h);
            try {
                const d = px.getImageData(0, 0, w, h).data;
                const counts = new Map();
                for (let i = 0; i < d.length; i += 4) {
                    if (d[i + 3] < 128) continue;
                    const k = (d[i] << 16) | (d[i + 1] << 8) | d[i + 2];
                    counts.set(k, (counts.get(k) || 0) + 1);
                }
                st.pal = [...counts.entries()].sort((a, b) => b[1] - a[1])
                    .slice(0, 24).map(([k]) => k);
            } catch (e) { /* tainted canvas etc — just skip */ }
        }
        palGrid.innerHTML = "";
        for (const k of st.pal) {
            const hex = "#" + k.toString(16).padStart(6, "0").toUpperCase();
            const sw = document.createElement("div");
            sw.className = "pfs-swatch";
            sw.style.background = hex;
            sw.title = `${hex} — click to copy`;
            sw.addEventListener("pointerdown", (e) => e.stopPropagation());
            sw.addEventListener("click", (e) => {
                e.stopPropagation();
                try { navigator.clipboard.writeText(hex); } catch (err) {}
                st.brushColor = "#" + k.toString(16).padStart(6, "0");
                brushCol.value = st.brushColor;
                sw.style.outline = "1px solid #fff";
                setTimeout(() => { sw.style.outline = ""; }, 180);
            });
            palGrid.appendChild(sw);
        }
        palEmpty.style.display = st.pal.length ? "none" : "";
        palHead.querySelector(".pfs-palcount").textContent =
            st.pal.length ? `${st.pal.length} colors` : "";
    }

    // ---- canvas rendering ----
    const tile = checkerTile();
    const ctx = canvas.getContext("2d");
    const tctx = tl.getContext("2d");

    function viewParams(img, region) {
        // canvas sources (composited frames) expose .width/.height, not .naturalWidth
        const iw = img.naturalWidth || img.width || 1, ih = img.naturalHeight || img.height || 1;
        let scale, ox, oy;
        if (st.zoom <= 0) {
            scale = Math.min(region.w / iw, region.h / ih) * 0.96;
            ox = region.x + (region.w - iw * scale) / 2;
            oy = region.y + (region.h - ih * scale) / 2;
        } else {
            scale = st.zoom;
            ox = region.x + region.w / 2 + st.panX - (iw * scale) / 2;
            oy = region.y + region.h / 2 + st.panY - (ih * scale) / 2;
        }
        return { scale, ox, oy, iw, ih };
    }

    function drawFrameInto(img, region, frameIdx, stageImgs) {
        if (!img || !(img.naturalWidth || img.width)) return;
        const { scale, ox, oy, iw, ih } = viewParams(img, region);
        ctx.save();
        ctx.beginPath(); ctx.rect(region.x, region.y, region.w, region.h); ctx.clip();
        ctx.fillStyle = ctx.createPattern(tile, "repeat");
        ctx.fillRect(ox, oy, iw * scale, ih * scale);
        if (st.onion && frameIdx > 0 && stageImgs) {
            const prev = stageImgs[frameIdx - 1];
            if (prev && prev.naturalWidth && prev !== img) {
                ctx.globalAlpha = 0.35;
                ctx.drawImage(prev, ox, oy, iw * scale, ih * scale);
                ctx.globalAlpha = 1;
            }
        }
        ctx.drawImage(img, ox, oy, iw * scale, ih * scale);
        if (st.grid && scale >= 8) {
            ctx.strokeStyle = "rgba(255,157,69,0.25)"; ctx.lineWidth = 1;
            ctx.beginPath();
            for (let x = 0; x <= iw; x++) { ctx.moveTo(ox + x * scale + .5, oy); ctx.lineTo(ox + x * scale + .5, oy + ih * scale); }
            for (let y = 0; y <= ih; y++) { ctx.moveTo(ox, oy + y * scale + .5); ctx.lineTo(ox + iw * scale, oy + y * scale + .5); }
            ctx.stroke();
        }
        ctx.strokeStyle = "#3a3a48"; ctx.lineWidth = 1;
        ctx.strokeRect(ox - .5, oy - .5, iw * scale + 1, ih * scale + 1);
        ctx.restore();
    }

    function updateStatus() {
        const n = frameCount();
        const zoomTxt = st.zoom <= 0 ? "fit" : `${st.zoom.toFixed(st.zoom < 10 ? 1 : 0)}×`;
        zoomLbl.textContent = zoomTxt;
        if (!n) {
            const label = st.layers.length ? "LAYERS" : (STAGE_LABELS[st.stage] || st.stage).toUpperCase();
            status.innerHTML = `<b>${label}</b><span>no frames — queue a prompt to forge</span>`;
            return;
        }
        if (st.layers.length) {
            const layer = getActiveLayer();
            const layerName = layer ? layer.name : "—";
            const composite = compositeFrame(st.frame);
            const dims = composite ? `${composite.width}×${composite.height}` : "?×?";
            const toolTxt = st.tool.toUpperCase();
            status.innerHTML =
                `<b>${toolTxt}</b><span>Frame: ${st.frame + 1}/${n}</span>` +
                `<span>Layer: ${layerName}</span><span>Sprite: ${dims}</span>` +
                `<span>Zoom: ${zoomTxt}</span>` +
                (st.pal.length ? `<span>Palette: ${st.pal.length} colors</span>` : "");
        } else {
            const m = st.meta[st.stage];
            const stageTxt = (STAGE_LABELS[st.stage] || st.stage).toUpperCase();
            const dims = m && m.w ? `${m.w}×${m.h}` : "?×?";
            status.innerHTML =
                `<b>${stageTxt}</b><span>Frame: ${st.frame + 1}/${n}</span>` +
                `<span>Sprite: ${dims}</span><span>Zoom: ${zoomTxt}</span>` +
                (st.pal.length ? `<span>Palette: ${st.pal.length} colors</span>` : "");
        }
    }

    // ---- export GIF live loop: an <img> holding an animated GIF advances
    // on its own clock, but a canvas snapshot only shows the frame that was
    // current when drawImage ran. While the Export stage is active, keep
    // redrawing on rAF (throttled to ~30fps) so the GIF plays live on the
    // suite canvas and in its timeline cel. draw() re-arms the loop. ----
    function ensureGifLoop() {
        cancelAnimationFrame(st._gifRaf);
        st._gifRaf = 0;
        if (st.stage !== "export" || !(st.imgs.export || []).length) return;
        st._gifRaf = requestAnimationFrame((t) => {
            st._gifRaf = 0;
            if (st.stage !== "export") return;
            if (!st._gifLast || t - st._gifLast >= 33) {
                st._gifLast = t;
                draw();      // re-arms the loop via ensureGifLoop()
                drawTl();
            } else {
                ensureGifLoop();   // throttled frame: re-arm without drawing
            }
        });
    }

    function draw() {
        const dpr = window.devicePixelRatio || 1;
        const cw = cwrap.clientWidth, ch = cwrap.clientHeight;
        if (!cw || !ch) return;
        if (canvas.width !== cw * dpr || canvas.height !== ch * dpr) {
            canvas.width = cw * dpr; canvas.height = ch * dpr;
        }
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.imageSmoothingEnabled = false;
        ctx.fillStyle = "#0a0a0f"; ctx.fillRect(0, 0, cw, ch);

        // ==== Layer compositing path ====
        if (st.layers.length) {
            const composite = compositeFrame(st.frame);
            if (composite && composite.width > 0) {
                // Onion skin: ghost previous composited frame
                if (st.onion && st.frame > 0) {
                    const prevComposite = compositeFrame(st.frame - 1);
                    if (prevComposite && prevComposite !== composite) {
                        drawFrameInto(prevComposite, { x: 0, y: 0, w: cw, h: ch }, st.frame - 1, null);
                    }
                }
                drawFrameInto(composite, { x: 0, y: 0, w: cw, h: ch }, st.frame, null);
            }
            // ---- placement dot overlay ----
            if (st.showPlacementDot && st.placementDot) {
                const pd = st.placementDot;
                const { scale, ox, oy, iw, ih } = viewParams(
                    { naturalWidth: composite ? composite.width : 64, naturalHeight: composite ? composite.height : 64 },
                    { x: 0, y: 0, w: cw, h: ch }
                );
                const px = ox + pd.x * scale;
                const py = oy + pd.y * scale;
                ctx.save();
                ctx.strokeStyle = "#ff9d45"; ctx.lineWidth = 2;
                ctx.beginPath(); ctx.arc(px, py, 8, 0, Math.PI * 2); ctx.stroke();
                ctx.beginPath(); ctx.moveTo(px - 12, py); ctx.lineTo(px + 12, py); ctx.stroke();
                ctx.beginPath(); ctx.moveTo(px, py - 12); ctx.lineTo(px, py + 12); ctx.stroke();
                ctx.fillStyle = "#ff9d45"; ctx.font = "9px sans-serif";
                ctx.fillText("◎ placement", px + 12, py - 4);
                ctx.restore();
            }
            // ---- marquee overlay ----
            if (st.marquee) {
                const m = st.marquee;
                const { scale, ox, oy } = viewParams(
                    { naturalWidth: composite ? composite.width : 64, naturalHeight: composite ? composite.height : 64 },
                    { x: 0, y: 0, w: cw, h: ch }
                );
                ctx.save();
                ctx.strokeStyle = "#ffffff"; ctx.lineWidth = 1;
                ctx.setLineDash([4, 4]);
                ctx.strokeRect(ox + m.x * scale, oy + m.y * scale, m.w * scale, m.h * scale);
                ctx.setLineDash([]);
                ctx.fillStyle = "rgba(255,255,255,0.08)";
                ctx.fillRect(ox + m.x * scale, oy + m.y * scale, m.w * scale, m.h * scale);
                ctx.fillStyle = "#ffffff"; ctx.font = "9px sans-serif";
                ctx.fillText(`${m.w}×${m.h}`, ox + m.x * scale, oy + m.y * scale - 4);
                ctx.restore();
            }
        } else {
            // ==== Legacy single-stage path ====
            const imgs = activeImgs();
            const img = imgs[st.frame];
            if (st.ab && st.imgs.source && st.imgs.source.length) {
                const splitX = Math.round(cw * st.abSplit);
                const srcImgs = st.imgs.source;
                const si = srcImgs[Math.min(st.frame, srcImgs.length - 1)];
                drawFrameInto(si, { x: 0, y: 0, w: splitX, h: ch }, st.frame, srcImgs);
                drawFrameInto(img, { x: splitX, y: 0, w: cw - splitX, h: ch }, st.frame, imgs);
                ctx.strokeStyle = "#ff9d45"; ctx.lineWidth = 2;
                ctx.beginPath(); ctx.moveTo(splitX, 0); ctx.lineTo(splitX, ch); ctx.stroke();
                ctx.fillStyle = "#ff9d45"; ctx.font = "10px sans-serif";
                ctx.fillText("SOURCE", 6, 14);
                ctx.fillText((STAGE_LABELS[st.stage] || st.stage).toUpperCase(), splitX + 6, 14);
            } else {
                drawFrameInto(img, { x: 0, y: 0, w: cw, h: ch }, st.frame, imgs);
            }
            if (!img) {
                ctx.fillStyle = "#555566"; ctx.font = "13px sans-serif";
                ctx.textAlign = "center";
                ctx.fillText("queue a prompt to forge", cw / 2, ch / 2);
                ctx.textAlign = "left";
            }
        }
        refreshPalette();
        updateStatus();
        refreshCtrls();
        refreshLayerBar();
        ensureGifLoop();
    }

    function zoomBy(f) {
        if (st.zoom <= 0) {
            const img = st.layers.length ? compositeFrame(st.frame) : activeImgs()[st.frame];
            if (!img || !(img.naturalWidth || img.width)) return;
            const { scale } = viewParams(img, { x: 0, y: 0, w: cwrap.clientWidth, h: cwrap.clientHeight });
            st.zoom = scale;
            st.panX = 0; st.panY = 0;
        }
        st.zoom = Math.max(0.25, Math.min(64, st.zoom * f));
        draw();
    }

    // ---- timeline: layer rows x frame columns (Aseprite-style) ----
    const TL_GUTTER = 110, TL_HEADER = 18;
    function tlLayout() {
        const W = tl.clientWidth, H = tl.clientHeight;
        // Use real layers if available, else fall back to stage list
        const rows = st.layers.length
            ? st.layers.map((l, i) => ({ type: "layer", idx: i, layer: l }))
            : stageList().map(s => ({ type: "stage", name: s }));
        // Phase 9: prompt lane rides above all rows (One Forge only)
        if (config.tabs) rows.unshift({ type: "prompt" });
        const rowH = Math.max(20, Math.min(32, (H - TL_HEADER) / Math.max(1, rows.length)));
        let maxN = 1;
        if (st.layers.length) {
            maxN = st.totalFrames || 1;
        } else {
            for (const r of rows) maxN = Math.max(maxN, (st.imgs[r.name] || []).length);
        }
        for (const s of st.promptSegs) maxN = Math.max(maxN, (s.end || 0));
        const avail = W - TL_GUTTER - 6;
        let cellW = Math.min(40, Math.max(10, avail / maxN));
        const totalW = cellW * maxN;
        const maxScroll = Math.max(0, totalW - avail);
        st.tlScroll = Math.max(0, Math.min(maxScroll, st.tlScroll));
        return { W, H, rows, rowH, maxN, cellW, avail };
    }

    function drawTl() {
        if (!st.showTl) return;
        const dpr = window.devicePixelRatio || 1;
        const { W, H, rows, rowH, maxN, cellW } = tlLayout();
        if (!W || !H) return;
        if (tl.width !== W * dpr || tl.height !== H * dpr) {
            tl.width = W * dpr; tl.height = H * dpr;
        }
        tctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        tctx.imageSmoothingEnabled = false;
        tctx.fillStyle = "#0d0d13"; tctx.fillRect(0, 0, W, H);

        const off = st.tlScroll;
        const curN = frameCount();

        // ---- header: frame numbers ----
        tctx.font = "8.5px sans-serif"; tctx.textBaseline = "middle";
        for (let i = 0; i < maxN; i++) {
            const x = TL_GUTTER + i * cellW - off;
            if (x + cellW < TL_GUTTER || x > W) continue;
            const cur = i === st.frame;
            if (cur) {
                tctx.fillStyle = "#3a2c1a";
                tctx.fillRect(x, 0, cellW, TL_HEADER);
            }
            tctx.fillStyle = i < curN ? (cur ? "#ff9d45" : "#8a8a99") : "#3f3f4c";
            if (cellW >= 14 || i % 5 === 0) {
                tctx.textAlign = "center";
                tctx.fillText(String(i + 1), x + cellW / 2, TL_HEADER / 2 + .5);
            }
        }
        // header/gutter corner
        tctx.fillStyle = "#101018";
        tctx.fillRect(0, 0, TL_GUTTER, TL_HEADER);
        tctx.fillStyle = "#6f6f7e"; tctx.textAlign = "left";
        tctx.fillText("LAYERS \\ FRAMES", 6, TL_HEADER / 2 + .5);

        // ---- rows ----
        rows.forEach((row, r) => {
            const y = TL_HEADER + r * rowH;

            if (row.type === "prompt") {
                // ==== PROMPT LANE (Phase 9): per-segment prompt clips ====
                tctx.fillStyle = "#0e1218";
                tctx.fillRect(0, y, W, rowH);
                tctx.strokeStyle = "#1e1e28"; tctx.lineWidth = 1;
                tctx.beginPath(); tctx.moveTo(0, y + .5); tctx.lineTo(W, y + .5); tctx.stroke();

                tctx.fillStyle = "#101018";
                tctx.fillRect(0, y, TL_GUTTER, rowH);
                tctx.fillStyle = "#6fb7ff"; tctx.font = "8.5px sans-serif";
                tctx.textAlign = "left";
                tctx.fillText("PROMPT ✎", 8, y + rowH / 2 + .5);

                for (let si = 0; si < st.promptSegs.length; si++) {
                    const seg = st.promptSegs[si];
                    const x0 = TL_GUTTER + seg.start * cellW - off;
                    const x1 = TL_GUTTER + seg.end * cellW - off;
                    if (x1 < TL_GUTTER || x0 > W) continue;
                    const cx0 = Math.max(x0, TL_GUTTER);
                    const sel = si === st.activePromptSeg;
                    tctx.fillStyle = sel ? "#1d3550" : "#14202e";
                    tctx.fillRect(cx0 + 1, y + 3, Math.max(6, x1 - cx0) - 2, rowH - 6);
                    tctx.strokeStyle = sel ? "#6fb7ff" : "#2c4a6a";
                    tctx.strokeRect(cx0 + 1.5, y + 3.5, Math.max(6, x1 - cx0) - 3, rowH - 7);
                    tctx.fillStyle = "#9fc4e8"; tctx.font = "8px sans-serif";
                    tctx.save();
                    tctx.beginPath();
                    tctx.rect(cx0 + 3, y, Math.max(0, x1 - cx0) - 6, rowH);
                    tctx.clip();
                    tctx.fillText(seg.prompt || "(empty — right-click to edit)", cx0 + 5, y + rowH / 2 + .5);
                    tctx.restore();
                }
                return;
            }

            if (row.type === "layer") {
                // ==== REAL LAYER ROW ====
                const layer = row.layer;
                const isCur = row.idx === st.activeLayer;

                // row background
                tctx.fillStyle = isCur ? "#171722" : (r % 2 ? "#0f0f16" : "#0d0d13");
                tctx.fillRect(0, y, W, rowH);
                tctx.strokeStyle = "#1e1e28"; tctx.lineWidth = 1;
                tctx.beginPath(); tctx.moveTo(0, y + .5); tctx.lineTo(W, y + .5); tctx.stroke();

                // label gutter
                tctx.fillStyle = isCur ? "#1a1a26" : "#101018";
                tctx.fillRect(0, y, TL_GUTTER, rowH);

                // visibility icon
                const eyeX = 6, eyeY = y + rowH / 2;
                tctx.fillStyle = layer.visible ? "#7fd67f" : "#3f3f4c";
                tctx.font = "10px sans-serif"; tctx.textAlign = "left";
                tctx.fillText(layer.visible ? "👁" : "○", eyeX, eyeY + 3);

                // lock icon
                tctx.fillStyle = layer.locked ? "#ff6b6b" : "#3f3f4c";
                tctx.fillText(layer.locked ? "🔒" : "", eyeX + 16, eyeY + 3);

                // layer name
                tctx.fillStyle = isCur ? "#ff9d45" : (layer.visible ? "#9a9aa8" : "#555566");
                tctx.font = isCur ? "bold 9px sans-serif" : "9px sans-serif";
                tctx.fillText(layer.name, eyeX + 30, y + rowH / 2 + .5);

                // badges (advance x so they never overlap)
                let badgeX = eyeX + 30 + tctx.measureText(layer.name).width + 4;
                // reference badge — shows which <Picture> slot the layer feeds
                if (layer.kind === "ref") {
                    const slot = computeRefBinds()[layer.id];
                    tctx.font = "8px sans-serif";
                    const label = "🔖" + (slot ? slot.toUpperCase() : "");
                    // bright blue = bound to a gen slot; dim = guide-only
                    // (hidden, or both slots taken by manual pushes)
                    tctx.fillStyle = slot ? "#6fb7ff" : "#3f5a78";
                    tctx.fillText(label, badgeX, y + rowH / 2 + .5);
                    badgeX += tctx.measureText(label).width + 5;
                }

                // opacity badge
                if (layer.opacity < 1) {
                    tctx.fillStyle = "#6f6f7e"; tctx.font = "7.5px sans-serif";
                    const label = Math.round(layer.opacity * 100) + "%";
                    tctx.fillText(label, badgeX, y + rowH / 2 + .5);
                    badgeX += tctx.measureText(label).width + 5;
                }

                // frame cels
                for (let i = 0; i < curN; i++) {
                    const x = TL_GUTTER + i * cellW - off;
                    if (x + cellW < TL_GUTTER || x > W) continue;
                    const fr = layer.frames[i] ||
                        (layer.kind === "ref" ? layer.frames.find(f => f) : null);
                    const cw = cellW - 3, chh = rowH - 5;
                    const cx = x + 1, cy = y + 2;

                    // keyframe diamond
                    if (layer.keyframes[i]) {
                        tctx.fillStyle = "#ff9d45";
                        tctx.save();
                        tctx.translate(cx + cw / 2, cy - 1);
                        tctx.rotate(Math.PI / 4);
                        tctx.fillRect(-3, -3, 6, 6);
                        tctx.restore();
                    }

                    tctx.fillStyle = fr ? "#0c0c14" : "#08080c";
                    tctx.fillRect(cx, cy, cw, chh);
                    if (fr && frameSurf(fr) && surfW(frameSurf(fr))) {
                        const sf = frameSurf(fr);
                        const s = Math.min(cw / surfW(sf), chh / surfH(sf));
                        const dw = surfW(sf) * s, dh = surfH(sf) * s;
                        tctx.drawImage(sf, cx + (cw - dw) / 2, cy + (chh - dh) / 2, dw, dh);
                    }
                    tctx.strokeStyle = "#26262f";
                    tctx.strokeRect(cx + .5, cy + .5, cw - 1, chh - 1);
                    // Phase 9: dragged frame-range selection highlight
                    if (st.frameSel && st.frameSel.layer === row.idx
                            && i >= st.frameSel.start && i <= st.frameSel.end) {
                        tctx.fillStyle = "rgba(255,157,69,0.16)";
                        tctx.fillRect(cx, cy, cw, chh);
                        tctx.strokeStyle = "rgba(255,157,69,0.65)";
                        tctx.strokeRect(cx + .5, cy + .5, cw - 1, chh - 1);
                    }
                    if (isCur && i === st.frame) {
                        tctx.strokeStyle = "#ff9d45"; tctx.lineWidth = 2;
                        tctx.strokeRect(cx - .5, cy - .5, cw + 2, chh + 2);
                        tctx.lineWidth = 1;
                    }
                }

                // active layer indicator (yellow bar on left)
                if (isCur) {
                    tctx.fillStyle = "#ff9d45";
                    tctx.fillRect(0, y, 2, rowH);
                }

            } else {
                // ==== LEGACY STAGE ROW (backward compat) ====
                const name = row.name;
                const skipped = st.meta[name] && st.meta[name].skipped;
                const imgs = st.imgs[name] || [];
                const isCur = name === st.stage;

                tctx.fillStyle = isCur ? "#171722" : (r % 2 ? "#0f0f16" : "#0d0d13");
                tctx.fillRect(0, y, W, rowH);
                tctx.strokeStyle = "#1e1e28"; tctx.lineWidth = 1;
                tctx.beginPath(); tctx.moveTo(0, y + .5); tctx.lineTo(W, y + .5); tctx.stroke();

                tctx.fillStyle = isCur ? "#1a1a26" : "#101018";
                tctx.fillRect(0, y, TL_GUTTER, rowH);
                tctx.fillStyle = skipped ? "#45454f" : (isCur ? "#ff9d45" : "#9a9aa8");
                tctx.font = isCur ? "bold 9.5px sans-serif" : "9.5px sans-serif";
                tctx.textAlign = "left";
                const label = STAGE_LABELS[name] || name;
                tctx.fillText((skipped ? "⊘ " : "● ") + label, 8, y + rowH / 2 + .5);
                tctx.font = "8.5px sans-serif";

                for (let i = 0; i < imgs.length; i++) {
                    const x = TL_GUTTER + i * cellW - off;
                    if (x + cellW < TL_GUTTER || x > W) continue;
                    const im = imgs[i];
                    const cw = cellW - 3, chh = rowH - 5;
                    const cx = x + 1, cy = y + 2;
                    tctx.fillStyle = "#08080c";
                    tctx.fillRect(cx, cy, cw, chh);
                    if (im && im.naturalWidth) {
                        const s = Math.min(cw / im.naturalWidth, chh / im.naturalHeight);
                        const dw = im.naturalWidth * s, dh = im.naturalHeight * s;
                        tctx.drawImage(im, cx + (cw - dw) / 2, cy + (chh - dh) / 2, dw, dh);
                    }
                    tctx.strokeStyle = "#26262f";
                    tctx.strokeRect(cx + .5, cy + .5, cw - 1, chh - 1);
                    if (isCur && i === st.frame) {
                        tctx.strokeStyle = "#ff9d45"; tctx.lineWidth = 2;
                        tctx.strokeRect(cx - .5, cy - .5, cw + 2, chh + 2);
                        tctx.lineWidth = 1;
                    }
                }
                if (!imgs.length && !skipped) {
                    tctx.fillStyle = "#3f3f4c"; tctx.textAlign = "left";
                    tctx.fillText("—", TL_GUTTER + 6 - off, y + rowH / 2 + .5);
                }
            }
        });

        // ---- playhead (vertical line at current frame) ----
        if (curN > 0) {
            const phX = TL_GUTTER + st.frame * cellW + cellW / 2 - off;
            if (phX >= TL_GUTTER && phX <= W) {
                tctx.strokeStyle = "rgba(255,157,69,0.5)"; tctx.lineWidth = 1;
                tctx.beginPath(); tctx.moveTo(phX, TL_HEADER); tctx.lineTo(phX, H); tctx.stroke();
            }
        }

        // gutter divider
        tctx.strokeStyle = "#26262f";
        tctx.beginPath(); tctx.moveTo(TL_GUTTER - .5, 0); tctx.lineTo(TL_GUTTER - .5, H); tctx.stroke();
    }

    function tlPick(ev) {
        const r = tl.getBoundingClientRect();
        const x = ev.clientX - r.left, y = ev.clientY - r.top;
        const { rows, rowH, maxN, cellW } = tlLayout();
        if (y < TL_HEADER) {
            // ---- header click: scrub to frame ----
            if (x < TL_GUTTER) return;
            const i = Math.floor((x - TL_GUTTER + st.tlScroll) / cellW);
            const n = frameCount();
            if (n) st.frame = Math.max(0, Math.min(n - 1, i));
        } else {
            const rIdx = Math.floor((y - TL_HEADER) / rowH);
            const row = rows[Math.min(rIdx, rows.length - 1)];
            if (!row) return;
            if (row.type === "prompt") return;  // prompt lane has its own handlers

            if (row.type === "layer") {
                // ==== REAL LAYER ROW ====
                const layer = row.layer;
                const layerIdx = row.idx;

                // Click in gutter: toggle visibility (eye icon area)
                if (x < 22) {
                    layer.visible = !layer.visible;
                    _invalidateAllComposites();
                    saveLayerProps();
                    if (layer.kind === "ref") refreshRefSlots();
                    draw(); drawTl();
                    return;
                }
                // Click on lock icon area
                if (x >= 22 && x < 36) {
                    layer.locked = !layer.locked;
                    saveLayerProps();
                    drawTl();
                    return;
                }
                // Click on name area: select this layer
                if (x < TL_GUTTER) {
                    st.activeLayer = layerIdx;
                    draw(); drawTl(); saveLayerProps();
                    return;
                }
                // Click on frame cels: select frame + layer
                if (x >= TL_GUTTER) {
                    st.activeLayer = layerIdx;
                    const i = Math.floor((x - TL_GUTTER + st.tlScroll) / cellW);
                    st.frame = Math.max(0, Math.min(frameCount() - 1, i));
                    st.activeFrame = st.frame;
                    draw(); drawTl(); saveLayerProps();
                    return;
                }
            } else {
                // ==== LEGACY STAGE ROW ====
                const name = row.name;
                const skipped = st.meta[name] && st.meta[name].skipped;
                if (!skipped && (st.imgs[name] || []).length) {
                    st.stage = name;
                    if (x >= TL_GUTTER) {
                        const i = Math.floor((x - TL_GUTTER + st.tlScroll) / cellW);
                        st.frame = Math.max(0, Math.min(st.imgs[name].length - 1, i));
                    } else {
                        st.frame = Math.min(st.frame, st.imgs[name].length - 1);
                    }
                    updateInfo();
                }
            }
        }
        st._palKey = "";
        draw(); drawTl(); saveLayerProps();
    }

    // ---- playback ----
    function tick() {
        cancelAnimationFrame(st._raf);
        if (!st.playing) return;
        const step = (t) => {
            if (!st.playing) return;
            if (!st._lastT) st._lastT = t;
            const dt = t - st._lastT; st._lastT = t;
            st._acc += dt;
            const durFrames = (st.durations && st.durations[st.frame]) || 1;
            const frameMs = 1000 * durFrames / st.fps;
            if (st._acc >= frameMs) {
                st._acc = 0;
                const n = frameCount();
                if (n) {
                    let nf = st.frame + 1;
                    if (nf >= n) { if (st.loop) nf = 0; else { st.playing = false; btnPlay.textContent = "▶"; nf = n - 1; } }
                    st.frame = nf;
                    draw(); drawTl();
                }
            }
            st._raf = requestAnimationFrame(step);
        };
        st._raf = requestAnimationFrame(step);
    }

    // ---- pointer interaction: canvas tools (pan, move, marquee, place, draw) ----
    // Convert client coords to sprite-pixel coords
    // ---- drawn-ref upload: ship the visible composite to the backend ----
    let _drawnRefSeq = 0, _drawnRefTimer = 0;
    function hasDrawing() {
        return st.layers.some(l => (l.frames || []).some(f => f && (f.canvas || f.source === "paint")));
    }
    async function uploadDrawnRef() {
        if (!st.drawnRef || !hasDrawing()) return;
        const comp = compositeFrame(st.frame);
        if (!comp || !comp.width) return;
        const blob = await new Promise(res => comp.toBlob(res, "image/png"));
        if (!blob) return;
        const fd = new FormData();
        fd.append("image", blob, `pf_drawnref_${node.id}_${++_drawnRefSeq}.png`);
        fd.append("type", "temp");
        fd.append("overwrite", "true");
        try {
            const r = await fetch("/upload/image", { method: "POST", body: fd });
            const j = await r.json();
            const w = widgetByName("drawn_ref_image");
            if (j && j.name && w) {
                setWidgetValue(w, j.name);
                console.info("[PixelForge] drawn ref armed:", j.name);
            }
        } catch (err) {
            console.warn("[PixelForge] drawn-ref upload failed:", err);
        }
    }
    function queueDrawnRefUpload() {
        if (!st.drawnRef) return;
        clearTimeout(_drawnRefTimer);
        _drawnRefTimer = setTimeout(uploadDrawnRef, 600);
    }

    // ---- gen-ref slots: push the ACTIVE layer's frame to <Picture 1/2> ----
    async function pushLayerToRefSlot(slot) {
        const layer = getActiveLayer();
        if (!layer) return;
        const fr = layer.frames[st.frame] || layer.frames.find(f => f);
        const surf = frameSurf(fr);
        if (!surf || !surfW(surf)) { console.info("[PixelForge] ref slot: active layer has no frame to push"); return; }
        const wname = slot === "p1" ? "drawn_ref_image" : "drawn_ref_image_2";
        const w = widgetByName(wname);
        if (!w) { console.info("[PixelForge] ref slot: backend has no", wname, "widget (Super Forge?)"); return; }
        const cv = document.createElement("canvas");
        cv.width = surfW(surf); cv.height = surfH(surf);
        const cx = cv.getContext("2d"); cx.imageSmoothingEnabled = false;
        cx.drawImage(surf, 0, 0);
        const blob = await new Promise(res => cv.toBlob(res, "image/png"));
        if (!blob) return;
        try {
            const fd = new FormData();
            fd.append("image", blob, `pf_refslot_${node.id}_${slot}_${Date.now().toString(36)}.png`);
            fd.append("type", "temp");
            fd.append("overwrite", "true");
            const r = await fetch("/upload/image", { method: "POST", body: fd });
            const j = await r.json();
            if (j && j.name) {
                setWidgetValue(w, j.name);
                st.refSlots[slot] = j.name;
                saveLayerProps(); refreshRefSlots();
                console.info(`[PixelForge] ref slot ${slot} armed from layer "${layer.name}":`, j.name);
            }
        } catch (e) { console.warn("[PixelForge] ref slot push failed:", e); }
    }
    function clearRefSlot(slot) {
        const wname = slot === "p1" ? "drawn_ref_image" : "drawn_ref_image_2";
        const w = widgetByName(wname);
        if (w) setWidgetValue(w, "");
        st.refSlots[slot] = "";
        saveLayerProps(); refreshRefSlots();
    }

    // ---- video ref slot V1: import a clip as <Video 1> (motion/style) ----
    async function uploadVidRef(file) {
        const w = widgetByName("ref_video_1");
        if (!w) { console.info("[PixelForge] video ref: backend has no ref_video_1 widget (Super Forge?)"); return; }
        if (file.size > 50 * 1024 * 1024) {
            console.warn("[PixelForge] video ref: clip is over 50MB — trim it to the 2-15s you actually need");
            return;
        }
        try {
            const fd = new FormData();
            fd.append("image", file, `pf_vidref_${node.id}_${Date.now().toString(36)}_${file.name.replace(/[^a-zA-Z0-9.\-_]/g, "_")}`);
            fd.append("type", "input");
            fd.append("overwrite", "true");
            const r = await fetch("/upload/image", { method: "POST", body: fd });
            const j = await r.json();
            if (j && j.name) {
                const v = (j.subfolder ? j.subfolder + "/" : "") + j.name;
                setWidgetValue(w, v);
                st.vidRef = v;
                saveLayerProps(); refreshRefSlots();
                console.info("[PixelForge] video ref V1 armed:", v);
            }
        } catch (e) { console.warn("[PixelForge] video ref upload failed:", e); }
    }
    function clearVidRef() {
        const w = widgetByName("ref_video_1");
        if (w) setWidgetValue(w, "");
        st.vidRef = "";
        saveLayerProps(); refreshRefSlots();
    }

    // ---- auto-bind: visible 🔖 ref layers ARE the gen refs ----
    // One mental model: a visible ref layer feeds the generation as
    // <Picture 1> / <Picture 2> automatically (layer order, bottom→top).
    // Manual P1/P2 pushes and the ✎⤴ drawn-ref toggle are overrides that
    // own their slot; auto-bind only fills the FREE slots. Hidden layers
    // are skipped; deleting/hiding/un-🔖-ing a layer unbinds it next queue.
    function layerRefSurf(layer) {
        if (!layer || layer.kind !== "ref") return null;
        const fr = (layer.frames || []).find(f => f && frameSurf(f) && surfW(frameSurf(f)));
        return fr ? frameSurf(fr) : null;
    }
    function computeRefBinds() {
        // returns { layerId: "p1"|"p2" } — the auto (non-manual) bindings
        const p1Taken = !!st.refSlots.p1 || !!(st.drawnRef && hasDrawing());
        const p2Taken = !!st.refSlots.p2;
        const binds = {};
        const refs = st.layers.filter(l => l && l.kind === "ref"
            && l.visible !== false && layerRefSurf(l));
        let ri = 0;
        for (const slot of ["p1", "p2"]) {
            if (slot === "p1" ? p1Taken : p2Taken) continue;
            if (ri < refs.length) binds[refs[ri++].id] = slot;
        }
        return binds;
    }
    let _autoRefSeq = 0;
    async function autoBindRefLayers() {
        const w1 = widgetByName("drawn_ref_image");
        if (!w1) return;  // Super Forge node: no ref widgets — nothing to do
        const w2 = widgetByName("drawn_ref_image_2");
        const binds = computeRefBinds();
        if (!st._autoRefs) st._autoRefs = { p1: "", p2: "" };
        for (const slot of ["p1", "p2"]) {
            const w = slot === "p1" ? w1 : w2;
            if (!w) continue;
            const manual = !!st.refSlots[slot]
                || (slot === "p1" && st.drawnRef && hasDrawing());
            if (manual) { st._autoRefs[slot] = ""; continue; }  // override owns the slot
            const lid = Object.keys(binds).find(k => binds[k] === slot);
            const layer = lid ? st.layers.find(l => l.id === lid) : null;
            let name = "";
            if (layer) {
                // Imported PNGs already live in the temp dir — reuse the file
                // directly (no re-upload, stable name). Anything else (jpg/webp
                // import, painted ref) is re-encoded to PNG so the backend's
                // .png-only loader + alpha bbox-crop always work.
                if (layer.refFile && /\.png$/i.test(layer.refFile)) {
                    name = layer.refFile;
                } else {
                    const surf = layerRefSurf(layer);
                    const cv = document.createElement("canvas");
                    cv.width = surfW(surf); cv.height = surfH(surf);
                    const cx = cv.getContext("2d"); cx.imageSmoothingEnabled = false;
                    cx.drawImage(surf, 0, 0);
                    const blob = await new Promise(res => cv.toBlob(res, "image/png"));
                    if (blob) {
                        try {
                            const fd = new FormData();
                            fd.append("image", blob, `pf_autoref_${node.id}_${slot}_${Date.now().toString(36)}_${++_autoRefSeq}.png`);
                            fd.append("type", "temp");
                            fd.append("overwrite", "true");
                            const r = await fetch("/upload/image", { method: "POST", body: fd });
                            const j = await r.json();
                            if (j && j.name) name = j.name;
                        } catch (e) { console.warn("[PixelForge] auto-ref upload failed:", e); }
                    }
                }
            }
            // Only touch the widget when we have a fresh bind, or when WE set
            // the previous value (st._autoRefs) — never clobber anything else.
            if (name || st._autoRefs[slot]) {
                if ((w.value || "") !== name) setWidgetValue(w, name);
                st._autoRefs[slot] = name;
                if (name) console.info(`[PixelForge] auto-ref: layer "${layer.name}" -> <Picture ${slot === "p1" ? 1 : 2}>`);
            }
        }
    }

    // ==================== Phase 9: cel ops + surgical regen + prompt lane ====
    function afterCelOps() {
        st.frameSel = null;  // selection indices are stale after cel surgery
        _recalcTotalFrames(); _invalidateAllComposites();
        saveLayerProps(); draw(); drawTl();
    }
    function _celSurf(layer, f) {
        const s = frameSurf(layer && layer.frames[f]);
        return (s && surfW(s)) ? s : null;
    }
    function _celCopyCanvas(surf) {
        const cv = document.createElement("canvas");
        cv.width = surfW(surf); cv.height = surfH(surf);
        const cx = cv.getContext("2d"); cx.imageSmoothingEnabled = false;
        cx.drawImage(surf, 0, 0);
        return cv;
    }
    function celCopy(layerIdx, f) {
        const s = _celSurf(st.layers[layerIdx], f);
        st.celClipboard = s ? _celCopyCanvas(s) : null;
        if (s) console.info(`[PixelForge] cel ${f + 1} copied`);
    }
    function celPaste(layerIdx, f) {
        const layer = st.layers[layerIdx];
        if (!layer || !st.celClipboard) return;
        if (layer.locked) { console.info("[PixelForge] layer is locked"); return; }
        layer.frames[f] = { img: null, canvas: _celCopyCanvas(st.celClipboard), source: "paint" };
        afterCelOps();
    }
    function celDuplicate(layerIdx, f) {
        const layer = st.layers[layerIdx];
        if (!layer) return;
        if (layer.locked) { console.info("[PixelForge] layer is locked"); return; }
        const s = _celSurf(layer, f);
        layer.frames.splice(f + 1, 0,
            s ? { img: null, canvas: _celCopyCanvas(s), source: "paint" } : null);
        afterCelOps();
    }
    function celInsertBlank(layerIdx, f) {
        const layer = st.layers[layerIdx];
        if (!layer) return;
        if (layer.locked) { console.info("[PixelForge] layer is locked"); return; }
        layer.frames.splice(f, 0, null);
        afterCelOps();
    }
    function celClear(layerIdx, f) {
        const layer = st.layers[layerIdx];
        if (!layer) return;
        if (layer.locked) { console.info("[PixelForge] layer is locked"); return; }
        layer.frames[f] = null;
        afterCelOps();
    }
    function celDelete(layerIdx, f) {
        const layer = st.layers[layerIdx];
        if (!layer) return;
        if (layer.locked) { console.info("[PixelForge] layer is locked"); return; }
        layer.frames.splice(f, 1);
        afterCelOps();
    }

    // ---- surgical regen: regenerate ONLY the selected frame range ----
    // Frontend-orchestrated: seconds snaps up to cover the range (H3's
    // 17k+5 grid), a fresh seed busts the cache, the gen targets the layer,
    // and loadStages splices the new frames over [start, start+count).
    function regenRange(layerIdx, start, end) {
        const layer = st.layers[layerIdx];
        if (!layer) return;
        const wSec = widgetByName("seconds");
        if (!wSec) { console.info("[PixelForge] regen: no seconds widget (Super Forge?)"); return; }
        const count = end - start + 1;
        let n = Math.max(5, count);
        while (n % 17 !== 5) n++;
        setWidgetValue(wSec, n / 24);
        const wSeed = widgetByName("seed");
        if (wSeed) setWidgetValue(wSeed, Math.floor(Math.random() * 0xffffffff));
        st.genTarget = layer.id;
        st.regenWindow = { start, count };
        saveLayerProps(); refreshLayerBar();
        console.info(`[PixelForge] surgical regen: "${layer.name}" frames ${start + 1}–${end + 1} `
            + `(gen ${n}f @24fps, splice first ${count})`);
        app.queuePrompt();
    }

    // ---- prompt lane ops ----
    function promptSegAdd(frame) {
        st.promptSegs.push({ start: Math.max(0, frame), end: Math.max(0, frame) + 22, prompt: "" });
        st.promptSegs.sort((a, b) => a.start - b.start);
        st.activePromptSeg = st.promptSegs.findIndex(s => s.end === Math.max(0, frame) + 22 && s.start === Math.max(0, frame));
        saveLayerProps(); drawTl();
        promptSegEdit(st.activePromptSeg);
    }
    function promptSegEdit(i) {
        const seg = st.promptSegs[i];
        if (seg == null) return;
        openPromptEditor(i);
    }
    function promptSegDelete(i) {
        if (i < 0 || i >= st.promptSegs.length) return;
        st.promptSegs.splice(i, 1);
        st.activePromptSeg = -1;
        saveLayerProps(); drawTl();
    }

    // ---- small floating popup (context menu + prompt editor share CSS) ----
    let _pfsPopup = null;
    function closePopup() {
        if (_pfsPopup) { _pfsPopup.remove(); _pfsPopup = null; }
        window.removeEventListener("pointerdown", _popupOutside, true);
        window.removeEventListener("keydown", _popupKey, true);
    }
    function _popupOutside(e) {
        if (_pfsPopup && !_pfsPopup.contains(e.target)) closePopup();
    }
    function _popupKey(e) {
        if (e.key === "Escape") { e.stopPropagation(); closePopup(); }
    }
    function _openPopup(el, x, y) {
        closePopup();
        el.style.position = "fixed";
        el.style.zIndex = 100000;
        el.style.background = "#16161f";
        el.style.border = "1px solid #2a2a38";
        el.style.borderRadius = "6px";
        el.style.boxShadow = "0 6px 24px rgba(0,0,0,0.6)";
        el.style.font = "11px sans-serif";
        el.style.color = "#c8c8d4";
        // keep canvas/app shortcuts from seeing editor keystrokes
        el.addEventListener("keydown", (ev) => {
            if (ev.key !== "Escape") ev.stopPropagation();
        });
        document.body.appendChild(el);
        const r = el.getBoundingClientRect();
        el.style.left = Math.max(4, Math.min(x, window.innerWidth - r.width - 8)) + "px";
        el.style.top = Math.max(4, Math.min(y, window.innerHeight - r.height - 8)) + "px";
        _pfsPopup = el;
        window.addEventListener("pointerdown", _popupOutside, true);
        window.addEventListener("keydown", _popupKey, true);
    }
    function _ctxItem(menu, label, tip, fn, disabled) {
        const it = document.createElement("div");
        it.textContent = label;
        it.title = tip || "";
        it.style.padding = "5px 14px";
        it.style.cursor = disabled ? "default" : "pointer";
        it.style.whiteSpace = "nowrap";
        it.style.opacity = disabled ? "0.38" : "1";
        if (!disabled) {
            it.addEventListener("mouseenter", () => { it.style.background = "#23233a"; });
            it.addEventListener("mouseleave", () => { it.style.background = ""; });
            it.addEventListener("click", (e) => { e.stopPropagation(); closePopup(); fn(); });
        }
        menu.appendChild(it);
        return it;
    }
    function _ctxSep(menu) {
        const s = document.createElement("div");
        s.style.borderTop = "1px solid #2a2a38";
        s.style.margin = "3px 0";
        menu.appendChild(s);
    }

    // ---- timeline right-click context menu (Chain Studio-style) ----
    function openTlMenu(e, hit) {
        const menu = document.createElement("div");
        menu.style.padding = "4px 0";
        if (hit.row && hit.row.type === "prompt" || hit.header) {
            // prompt lane / header: segment ops
            if (hit.segIdx >= 0) {
                _ctxItem(menu, "✎ Edit prompt segment…", "", () => promptSegEdit(hit.segIdx));
                _ctxItem(menu, "✕ Delete segment", "", () => promptSegDelete(hit.segIdx));
            } else {
                _ctxItem(menu, "＋ Add prompt segment here",
                    "Per-segment prompt clip: appended to the base prompt when the gen "
                    + "window overlaps it. Supports <Picture 1> / <Video 1> tags.",
                    () => promptSegAdd(hit.frame));
            }
        } else if (hit.row && hit.row.type === "layer" && hit.frame >= 0) {
            const li = hit.row.idx;
            const layer = st.layers[li];
            const sel = st.frameSel && st.frameSel.layer === li
                && hit.frame >= st.frameSel.start && hit.frame <= st.frameSel.end
                ? st.frameSel : null;
            const a = sel ? sel.start : hit.frame;
            const b = sel ? sel.end : hit.frame;
            _ctxItem(menu,
                sel ? `🔁 Regen frames ${a + 1}–${b + 1}` : "🔁 Regen this frame",
                "Surgical regen: re-generate just this range (fresh seed) and splice "
                + "it back over these cels — everything else stays untouched.",
                () => regenRange(li, a, b));
            _ctxSep(menu);
            _ctxItem(menu, "Copy cel", "", () => celCopy(li, hit.frame),
                !_celSurf(layer, hit.frame));
            _ctxItem(menu, "Paste cel", "", () => celPaste(li, hit.frame),
                !st.celClipboard);
            _ctxItem(menu, "Duplicate cel", "Insert a copy of this cel right after it",
                () => celDuplicate(li, hit.frame));
            _ctxItem(menu, "Insert blank cel", "Shift later cels right by one",
                () => celInsertBlank(li, hit.frame));
            _ctxItem(menu, "Clear cel", "Empty this cel (no shift)",
                () => celClear(li, hit.frame), !layer || !layer.frames[hit.frame]);
            _ctxItem(menu, "Delete cel", "Remove this cel, shift later cels left",
                () => celDelete(li, hit.frame));
            _ctxSep(menu);
            _ctxItem(menu, "Duplicate layer", "", () => { duplicateLayer(li); draw(); drawTl(); });
            _ctxItem(menu, "Delete layer", "", () => { removeLayer(li); draw(); drawTl(); },
                st.layers.length <= 1);
        } else {
            return; // nothing useful here
        }
        menu.addEventListener("pointerdown", (e2) => e2.stopPropagation());
        _openPopup(menu, e.clientX, e.clientY);
    }

    // ---- prompt segment editor (window.prompt is dead in Electron) ----
    function openPromptEditor(segIdx) {
        const seg = st.promptSegs[segIdx];
        if (!seg) return;
        const box = document.createElement("div");
        box.style.padding = "10px";
        box.style.width = "320px";
        const lbl = document.createElement("div");
        lbl.textContent = `Prompt · frames ${seg.start + 1}–${seg.end}`;
        lbl.style.marginBottom = "6px";
        lbl.style.color = "#6fb7ff";
        const ta = document.createElement("textarea");
        ta.value = seg.prompt || "";
        ta.rows = 4;
        ta.placeholder = "e.g. the knight swings his sword — <Picture 1> keeps identity, <Video 1> drives motion";
        ta.style.width = "100%";
        ta.style.boxSizing = "border-box";
        ta.style.background = "#0d0d13";
        ta.style.color = "#c8c8d4";
        ta.style.border = "1px solid #2a2a38";
        ta.style.borderRadius = "4px";
        ta.style.font = "11px sans-serif";
        ta.style.resize = "vertical";
        const row = document.createElement("div");
        row.style.marginTop = "8px";
        row.style.textAlign = "right";
        const mkB = (t, fn) => {
            const b = document.createElement("button");
            b.textContent = t;
            b.style.marginLeft = "6px";
            b.style.background = "#23233a";
            b.style.color = "#c8c8d4";
            b.style.border = "1px solid #2a2a38";
            b.style.borderRadius = "4px";
            b.style.padding = "3px 12px";
            b.style.cursor = "pointer";
            b.addEventListener("click", (e) => { e.stopPropagation(); fn(); });
            return b;
        };
        row.appendChild(mkB("Delete", () => { closePopup(); promptSegDelete(segIdx); }));
        row.appendChild(mkB("Cancel", () => closePopup()));
        row.appendChild(mkB("Save", () => {
            seg.prompt = ta.value;
            saveLayerProps(); drawTl(); closePopup();
        }));
        box.append(lbl, ta, row);
        box.addEventListener("pointerdown", (e2) => e2.stopPropagation());
        // anchor near the segment on the timeline
        const r = tl.getBoundingClientRect();
        const { cellW } = tlLayout();
        const x = r.left + TL_GUTTER + seg.start * cellW - st.tlScroll;
        _openPopup(box, Math.min(x, window.innerWidth - 340), r.top - 10);
        ta.focus();
    }

    // ---- suite → widget sync (runs before every queued prompt) ----
    // The placement dot and marquee are suite-side state; the backend reads
    // them through the placement_x/y and selection_* widgets. Syncing at
    // queue time keeps the widgets (workflow save / API) the single source
    // of truth without spamming widget writes on every mouse move.
    function syncSuiteWidgets() {
        const comp = compositeFrame(st.frame);
        const cw = comp && comp.width ? comp.width : 0;
        const ch = comp && comp.height ? comp.height : 0;
        let dx = 0, dy = 0;
        if (st.placementDot && cw && ch) {
            dx = Math.round(st.placementDot.x - cw / 2);
            dy = Math.round(st.placementDot.y - ch / 2);
        }
        const wpx = widgetByName("placement_x"); if (wpx) setWidgetValue(wpx, dx);
        const wpy = widgetByName("placement_y"); if (wpy) setWidgetValue(wpy, dy);
        // normalize the marquee (drags can produce negative w/h)
        let sx = 0, sy = 0, sw = 0, sh = 0;
        if (st.marquee && (st.marquee.w || st.marquee.h)) {
            const m = st.marquee;
            sx = Math.round(Math.min(m.x, m.x + m.w));
            sy = Math.round(Math.min(m.y, m.y + m.h));
            sw = Math.round(Math.abs(m.w));
            sh = Math.round(Math.abs(m.h));
        }
        const wsx = widgetByName("selection_x"); if (wsx) setWidgetValue(wsx, sx);
        const wsy = widgetByName("selection_y"); if (wsy) setWidgetValue(wsy, sy);
        const wsw = widgetByName("selection_w"); if (wsw) setWidgetValue(wsw, sw);
        const wsh = widgetByName("selection_h"); if (wsh) setWidgetValue(wsh, sh);
        // Phase 9: prompt lane + gen window (regen offset) ride hidden widgets
        const wps = widgetByName("prompt_segments");
        if (wps) setWidgetValue(wps, JSON.stringify(st.promptSegs || []));
        const wgs = widgetByName("gen_win_start");
        if (wgs) setWidgetValue(wgs, st.regenWindow ? st.regenWindow.start : 0);
    }
    if (!window._pfDrawnRefUploads) window._pfDrawnRefUploads = new Set();
    window._pfDrawnRefUploads.add(uploadDrawnRef);
    window._pfDrawnRefUploads.add(syncSuiteWidgets);
    window._pfDrawnRefUploads.add(autoBindRefLayers);

    function clientToSprite(cx, cy) {
        const r = canvas.getBoundingClientRect();
        // The Vue frontend scales the whole widget wrapper (transform:
        // scale(ds.scale)), so the rect is in VISUAL px while draw() works
        // in unscaled layout px. k converts visual -> layout coordinates.
        const k = (cwrap.clientWidth ? r.width / cwrap.clientWidth : 1) || 1;
        const cw = r.width / k, ch = r.height / k;
        const composite = st.layers.length ? compositeFrame(st.frame) : null;
        const imgW = composite ? composite.width : 64;
        const imgH = composite ? composite.height : 64;
        const vp = viewParams({ naturalWidth: imgW, naturalHeight: imgH }, { x: 0, y: 0, w: cw, h: ch });
        const sx = (cx - r.left) / k - vp.ox;
        const sy = (cy - r.top) / k - vp.oy;
        return { x: sx / vp.scale, y: sy / vp.scale };
    }

    let drag = null;
    canvas.addEventListener("pointerdown", (e) => {
        e.stopPropagation(); e.preventDefault();
        canvas.setPointerCapture(e.pointerId);
        root.focus({ preventScroll: true });
        const r = canvas.getBoundingClientRect();
        const x = e.clientX - r.left;

        // ---- AB split divider ----
        if (st.ab && Math.abs(x - r.width * st.abSplit) < 8) {
            drag = { mode: "split" };
            return;
        }

        // ---- tool-specific behavior ----
        if (st.tool === "move") {
            const layer = getActiveLayer();
            if (layer && !layer.locked) {
                drag = { mode: "move", sx: e.clientX, sy: e.clientY, origX: layer.transform.x, origY: layer.transform.y };
                canvas.classList.add("panning");
            }
            return;
        }
        if (st.tool === "marquee") {
            const sp = clientToSprite(e.clientX, e.clientY);
            drag = { mode: "marquee", sx: sp.x, sy: sp.y };
            st.marquee = { x: sp.x, y: sp.y, w: 0, h: 0 };
            return;
        }
        if (st.tool === "place") {
            const sp = clientToSprite(e.clientX, e.clientY);
            st.placementDot = { x: Math.round(sp.x), y: Math.round(sp.y) };
            draw(); saveLayerProps();
            return;
        }
        if (st.tool === "draw") {
            const layer = getActiveLayer();
            if (layer && !layer.locked) {
                const fr = ensureDrawableFrame(layer, st.frame);
                const sp = clientToSprite(e.clientX, e.clientY);
                paintLine(fr, sp.x, sp.y, sp.x, sp.y);
                delete st._compositeCache[st.frame];
                drag = { mode: "draw", layer, fr, lx: sp.x, ly: sp.y };
                draw(); drawTl();
            }
            return;
        }

        // ---- pointer tool: pan (default) ----
        if (st.zoom <= 0) zoomBy(1);
        drag = { mode: "pan", lx: e.clientX, ly: e.clientY };
        canvas.classList.add("panning");
    });
    canvas.addEventListener("pointermove", (e) => {
        if (!drag) return;
        if (drag.mode === "pan") {
            const r0 = canvas.getBoundingClientRect();
            const k0 = (cwrap.clientWidth ? r0.width / cwrap.clientWidth : 1) || 1;
            st.panX += (e.clientX - drag.lx) / k0; st.panY += (e.clientY - drag.ly) / k0;
            drag.lx = e.clientX; drag.ly = e.clientY;
            draw();
        } else if (drag.mode === "split") {
            const r = canvas.getBoundingClientRect();
            st.abSplit = Math.max(0.15, Math.min(0.85, (e.clientX - r.left) / r.width));
            draw();
        } else if (drag.mode === "move") {
            const layer = getActiveLayer();
            if (layer) {
                const dpr = window.devicePixelRatio || 1;
                const r = canvas.getBoundingClientRect();
                const composite = compositeFrame(st.frame);
                const imgW = composite ? composite.width : 64;
                const imgH = composite ? composite.height : 64;
                const k1 = (cwrap.clientWidth ? r.width / cwrap.clientWidth : 1) || 1;
                const vp = viewParams({ naturalWidth: imgW, naturalHeight: imgH }, { x: 0, y: 0, w: r.width / k1, h: r.height / k1 });
                const dx = (e.clientX - drag.sx) / k1 / vp.scale;
                const dy = (e.clientY - drag.sy) / k1 / vp.scale;
                layer.transform.x = drag.origX + dx;
                layer.transform.y = drag.origY + dy;
                layer._dirty = true;
                _invalidateAllComposites();
                draw();
            }
        } else if (drag.mode === "draw") {
            // Interpolate between events so fast strokes stay continuous;
            // walk coalesced events for extra density when available.
            const evs = e.getCoalescedEvents ? e.getCoalescedEvents() : [e];
            for (const ev of (evs.length ? evs : [e])) {
                const sp = clientToSprite(ev.clientX, ev.clientY);
                paintLine(drag.fr, drag.lx, drag.ly, sp.x, sp.y);
                drag.lx = sp.x; drag.ly = sp.y;
            }
            delete st._compositeCache[st.frame];
            draw(); drawTl();
        } else if (drag.mode === "marquee") {
            const sp = clientToSprite(e.clientX, e.clientY);
            const x0 = Math.min(drag.sx, sp.x), y0 = Math.min(drag.sy, sp.y);
            const x1 = Math.max(drag.sx, sp.x), y1 = Math.max(drag.sy, sp.y);
            st.marquee = { x: Math.round(x0), y: Math.round(y0), w: Math.round(x1 - x0), h: Math.round(y1 - y0) };
            draw();
        }
    });
    const endDrag = () => {
        if (drag && drag.mode === "move") saveLayerProps();
        if (drag && drag.mode === "draw") { drag.layer._dirty = true; _invalidateAllComposites(); draw(); drawTl(); queueDrawnRefUpload(); }
        drag = null; canvas.classList.remove("panning");
    };
    canvas.addEventListener("pointerup", endDrag);
    canvas.addEventListener("pointercancel", endDrag);
    canvas.addEventListener("wheel", (e) => {
        e.stopPropagation(); e.preventDefault();
        zoomBy(e.deltaY < 0 ? 1.2 : 1 / 1.2);
    }, { passive: false });

    // timeline interaction: click cels / drag-select ranges / scrub /
    // prompt-lane drag+resize / right-click context menu / wheel-scroll
    function tlHit(e) {
        const r = tl.getBoundingClientRect();
        const x = e.clientX - r.left, y = e.clientY - r.top;
        const { rows, rowH, cellW } = tlLayout();
        const header = y < TL_HEADER;
        const rIdx = header ? -1 : Math.floor((y - TL_HEADER) / rowH);
        const row = rIdx >= 0 ? rows[Math.min(rIdx, rows.length - 1)] : null;
        const gutter = x < TL_GUTTER;
        const frame = !gutter
            ? Math.floor((x - TL_GUTTER + st.tlScroll) / cellW) : -1;
        let segIdx = -1, segEdge = "";
        if (row && row.type === "prompt" && frame >= 0) {
            for (let i = 0; i < st.promptSegs.length; i++) {
                const s = st.promptSegs[i];
                if (frame >= s.start && frame < s.end) {
                    segIdx = i;
                    const x0 = TL_GUTTER + s.start * cellW - st.tlScroll;
                    const x1 = TL_GUTTER + s.end * cellW - st.tlScroll;
                    if (Math.abs(x - x0) <= 4) segEdge = "l";
                    else if (Math.abs(x - x1) <= 4) segEdge = "r";
                    break;
                }
            }
        }
        return { x, y, header, row, frame, segIdx, segEdge, gutter };
    }

    let tlDown = false, tlDrag = null;
    tl.addEventListener("pointerdown", (e) => {
        e.stopPropagation();
        if (e.button === 2) return;  // contextmenu handles it
        tlDown = true;
        tl.setPointerCapture(e.pointerId);
        const hit = tlHit(e);
        tlDrag = null;
        if (hit.row && hit.row.type === "prompt") {
            // prompt lane: select / move / edge-resize segments
            st.activePromptSeg = hit.segIdx;
            if (hit.segIdx >= 0) {
                const seg = st.promptSegs[hit.segIdx];
                tlDrag = { mode: hit.segEdge === "l" ? "seg-resize-l"
                    : hit.segEdge === "r" ? "seg-resize-r" : "seg-move",
                    seg, anchor: hit.frame, oStart: seg.start, oEnd: seg.end };
            }
            drawTl();
            return;
        }
        if (hit.row && hit.row.type === "layer" && hit.frame >= 0 && !hit.gutter) {
            // cel: click = cursor, drag = frame-range selection
            st.activeLayer = hit.row.idx;
            st.frame = Math.max(0, Math.min(frameCount() - 1, hit.frame));
            st.activeFrame = st.frame;
            st.frameSel = null;
            tlDrag = { mode: "sel", layer: hit.row.idx, anchor: hit.frame };
            draw(); drawTl(); saveLayerProps();
            return;
        }
        tlPick(e);  // header scrub + gutter eye/lock/name
        tlDrag = hit.header ? null : { mode: "noop" };
    });
    tl.addEventListener("pointermove", (e) => {
        if (!tlDown) return;
        const hit = tlHit(e);
        if (tlDrag && tlDrag.mode === "sel" && hit.frame >= 0) {
            st.frame = Math.max(0, Math.min(frameCount() - 1, hit.frame));
            st.frameSel = { layer: tlDrag.layer,
                start: Math.min(tlDrag.anchor, hit.frame),
                end: Math.max(tlDrag.anchor, hit.frame) };
            draw(); drawTl();
            return;
        }
        if (tlDrag && tlDrag.mode === "seg-move" && hit.frame >= 0) {
            const df = hit.frame - tlDrag.anchor;
            const len = tlDrag.oEnd - tlDrag.oStart;
            tlDrag.seg.start = Math.max(0, tlDrag.oStart + df);
            tlDrag.seg.end = tlDrag.seg.start + len;
            drawTl();
            return;
        }
        if (tlDrag && tlDrag.mode === "seg-resize-l" && hit.frame >= 0) {
            tlDrag.seg.start = Math.max(0,
                Math.min(tlDrag.oStart + (hit.frame - tlDrag.anchor), tlDrag.seg.end - 1));
            drawTl();
            return;
        }
        if (tlDrag && tlDrag.mode === "seg-resize-r" && hit.frame >= 0) {
            tlDrag.seg.end = Math.max(tlDrag.seg.start + 1,
                tlDrag.oEnd + (hit.frame - tlDrag.anchor));
            drawTl();
            return;
        }
        if (!tlDrag) tlPick(e);  // header scrub drag keeps old behavior
    });
    const tlUp = () => {
        if (tlDrag && tlDrag.mode && tlDrag.mode.indexOf("seg-") === 0) {
            st.promptSegs.sort((a, b) => a.start - b.start);
            st.activePromptSeg = st.promptSegs.indexOf(tlDrag.seg);
            saveLayerProps();
        }
        if (tlDrag && tlDrag.mode === "sel" && st.frameSel
                && st.frameSel.start === st.frameSel.end) {
            st.frameSel = null;  // plain click, not a range
        }
        tlDrag = null; tlDown = false;
        drawTl();
    };
    tl.addEventListener("pointerup", tlUp);
    tl.addEventListener("pointercancel", tlUp);
    tl.addEventListener("contextmenu", (e) => {
        e.stopPropagation(); e.preventDefault();
        const hit = tlHit(e);
        if (hit.gutter && !(hit.row && hit.row.type === "layer")) return;
        if (hit.header && hit.frame < 0) return;
        openTlMenu(e, hit);
    });
    tl.addEventListener("dblclick", (e) => {
        const hit = tlHit(e);
        if (hit.row && hit.row.type === "prompt" && hit.segIdx >= 0) {
            e.stopPropagation();
            promptSegEdit(hit.segIdx);
        }
    });
    tl.addEventListener("wheel", (e) => {
        e.stopPropagation(); e.preventDefault();
        const { maxN, cellW, avail } = tlLayout();
        const maxScroll = Math.max(0, cellW * maxN - avail);
        st.tlScroll = Math.max(0, Math.min(maxScroll, st.tlScroll + e.deltaY));
        drawTl();
    }, { passive: false });

    root.addEventListener("pointerdown", (e) => {
        // Let form controls (sliders, selects, inputs) handle their own events
        const t = e.target;
        if (t && /^(INPUT|SELECT|TEXTAREA)$/i.test(t.tagName)) return;
        e.stopPropagation();
    });

    // ---- resize handling: the layout engine gives us the node's leftover
    // space; we just redraw into whatever we get (both directions) ----
    const ro = new ResizeObserver(() => { draw(); drawTl(); });
    ro.observe(cwrap); ro.observe(tlWrap);

    // One-time size hygiene: floor for fresh nodes, and snap back saved
    // monster heights from the ratchet era.
    function fitNode() {
        let w = node.size[0], h = node.size[1];
        let changed = false;
        if (w < NODE_MIN_W) { w = NODE_MIN_W; changed = true; }
        if (h < NODE_MIN_H || h > NODE_MAX_RESTORE_H) { h = NODE_DEFAULT_H; changed = true; }
        if (changed) node.setSize([w, h]);
    }

    // ---- DOM widget host: min-height floor via the layout API, no ceiling.
    // No computeSize here on purpose — see the header note. ----
    const domWidget = node.addDOMWidget("pf_suite", "pf_suite", root, {
        serialize: false,
        hideOnZoom: false,
        getValue: () => "",
        setValue: () => {},
        getMinHeight: () => MIN_SUITE_H,
    });
    domWidget.serializeValue = () => undefined;   // UI state never enters the prompt

    // WIDGET SHIELD (v3.2.1): the 1.48.x frontend's WidgetLegacy inspector
    // binds a hidden WidgetLegacy component to every legacy widget when the
    // node is SELECTED; its draw() does `widget.y = 0; widget.width =
    // parentElement.clientWidth` (~214px side-panel slot). The DomWidgets
    // overlay then computes the suite wrapper as (widget.width ?? node.width)
    // - 2*margin = ~194px and repositions using widget.y=0 -> "clicked the
    // node and it went half size / popped up out of the frame", and the
    // watchdog's re-pin fought the overlay's reactive writes every draw
    // (constant arrange+redraw churn = the "memory leak" feel). The suite's
    // geometry is fully derived from the node, so hard-shield both fields:
    Object.defineProperty(domWidget, "width", {
        configurable: true, enumerable: true,
        get: () => node.size[0], set: () => {},
    });
    Object.defineProperty(domWidget, "y", {
        configurable: true, enumerable: true,
        get: () => SUITE_TOP, set: () => {},
    });

    // ---- layout watchdog: the frontend re-arranges widgets on every canvas
    // draw, but a late-appearing widget (a native image preview if a backend
    // ever leaks ui.images, core value-control add-ons, …) joins the space
    // split and leaves the suite stuck at a fraction of the node (the
    // "half-size lock"). Hide strays and re-arrange if our computed height
    // drifts from the node's actual leftover space. Also keeps the socket
    // strip's link states fresh.
    // Authoritative wrapper-geometry sync: the frontend re-syncs DOM widget
    // geometry (its .dom-widget wrapper) from widget.y/computedHeight on its
    // own draw hooks — but those hooks read stale layout values after a
    // resize and then STOP (canvas no longer dirty), leaving the suite
    // locked at a stale/half size. Compare the wrapper's ACTUAL inline
    // geometry against the node's true geometry and rewrite on any real
    // deviation. (No write-cache: the frontend clobbers inline styles without
    // clearing it, which used to blind the watchdog to its own writes being
    // undone — the original "half-size lock".)
    const syncWrapGeometry = () => {
        const wrap = domWidget.element && domWidget.element.parentElement;
        if (!wrap || !wrap.classList || !wrap.classList.contains("dom-widget") || !app.canvas) return;
        // WIDTH PIN (the "half-width lock", Vue frontend >= ~1.48): the
        // frontend's DomWidgets pipeline recomputes the wrapper box on every
        // canvas draw as
        //   size = [(widget.width ?? node.width) - 2*margin,
        //           (widget.computedHeight ?? 50) - 2*margin]
        // If widget.width ever gets stamped with a stale/wrong value, the
        // frontend's own reactive writes keep RE-imposing it — the suite
        // renders squished horizontally. Pin the DATA to the node's live
        // width so the frontend's own math always lands on full width.
        // (Identical to the ?? fallback when unset: no-op when healthy.)
        if (domWidget.width !== node.size[0]) domWidget.width = node.size[0];
        const m = domWidget.margin != null ? domWidget.margin : 10;
        const wy = domWidget.y || 0;
        const wch = (typeof domWidget.computedHeight === "number")
            ? domWidget.computedHeight : Math.max(MIN_SUITE_H, node.size[1] - wy);
        const gw = node.size[0] - 2 * m;
        const gh = wch - 2 * m;
        const dev = (a, b) => Math.abs((parseFloat(a) || 0) - b) > 1;
        const wrapPos = getComputedStyle(wrap).position;
        // SELF-MANAGED GEOMETRY (v3.5.2 — authoritative): the Vue DomWidgets
        // overlay is too flaky for this widget — it claims the wrapper late,
        // dies mid-session, and goes rAF-starved in background tabs — so WE
        // own the wrapper geometry from creation. The math is litegraph's
        // core convention, client = (canvasPos + offset) * scale, verified
        // pixel-identical to the frontend's own writes when its overlay IS
        // healthy, so an occasional foreign write lands on the same numbers
        // and no fight is ever visible. (History: v3.5.0 added ds.offset
        // AFTER scaling — any pan at scale != 1 drifted the suite off the
        // node frame — and the yield/claim handshake oscillated ownership.
        // That was the "suite keeps popping out of the node frame" glitch.)
        if (wrapPos !== "absolute") {
            const ds2 = app.canvas.ds;
            if (!ds2) return;
            st._selfPos = true;
            if (st._installSelfPosSync) st._installSelfPosSync();
            const rect2 = app.canvas.canvas ? app.canvas.canvas.getBoundingClientRect() : { left: 0, top: 0 };
            const gl2 = rect2.left + (node.pos[0] + m + ds2.offset[0]) * ds2.scale;
            const gt2 = rect2.top + (node.pos[1] + m + wy + ds2.offset[1]) * ds2.scale;
            const wantT2 = `scale(${ds2.scale})`;
            if (wrap.style.position !== "fixed") { wrap.style.position = "fixed"; wrap.style.zIndex = "5"; }
            if (dev(wrap.style.left, gl2) || dev(wrap.style.top, gt2) ||
                dev(wrap.style.width, gw) || dev(wrap.style.height, gh) ||
                wrap.style.transform !== wantT2) {
                wrap.style.transformOrigin = "0 0";
                wrap.style.transform = wantT2;
                wrap.style.left = gl2 + "px";
                wrap.style.top = gt2 + "px";
                wrap.style.width = gw + "px";
                wrap.style.height = gh + "px";
            }
            return;
        }
        // LEGACY frontend (absolute wrapper): we own the full geometry.
        // (Only reachable when position === "absolute" — real legacy.)
        if (wrapPos !== "absolute") return;
        const ds = app.canvas.ds;
        if (!ds) return;
        const rect = app.canvas.canvas ? app.canvas.canvas.getBoundingClientRect() : { left: 0, top: 0 };
        const gl = rect.left + (node.pos[0] + m + ds.offset[0]) * ds.scale;
        const gt = rect.top + (node.pos[1] + m + wy + ds.offset[1]) * ds.scale;
        const wantT = `scale(${ds.scale})`;
        if (dev(wrap.style.left, gl) || dev(wrap.style.top, gt) ||
            dev(wrap.style.width, gw) || dev(wrap.style.height, gh) ||
            wrap.style.transform !== wantT) {
            wrap.style.transformOrigin = "0 0";
            wrap.style.transform = wantT;
            wrap.style.left = gl + "px";
            wrap.style.top = gt + "px";
            wrap.style.width = gw + "px";
            wrap.style.height = gh + "px";
        }
    };

    // Self-managed mode interaction sync: drags/zooms feel live instead of
    // waiting for the 800ms watchdog tick.
    st._installSelfPosSync = () => {
        if (st._selfPosSyncInstalled || !app.canvas || !app.canvas.canvas) return;
        st._selfPosSyncInstalled = true;
        const schedule = () => {
            if (st._syncQueued) return;
            st._syncQueued = true;
            requestAnimationFrame(() => {
                st._syncQueued = false;
                if (st._selfPos) syncWrapGeometry();
            });
        };
        st._selfPosSchedule = schedule;
        app.canvas.canvas.addEventListener("pointermove", schedule, { passive: true });
        app.canvas.canvas.addEventListener("wheel", schedule, { passive: true });
    };

    // First paint: position immediately, do not wait for the first tick.
    syncWrapGeometry();
    requestAnimationFrame(syncWrapGeometry);

    st._watch = setInterval(() => {
        if (!node.graph) return;
        const wrapEl = domWidget.element && domWidget.element.parentElement;
        // Self-managed mode: the overlay's v-show is dead too, so hide/show
        // the wrapper ourselves on collapse and workflow-tab switches.
        if (st._selfPos && wrapEl) {
            const gone = node.collapsed || (node.flags && node.flags.collapsed) ||
                (app.canvas && app.canvas.graph && node.graph !== app.canvas.graph);
            const wantVis = gone ? "hidden" : "";
            if ((wrapEl.style.visibility || "") !== wantVis) wrapEl.style.visibility = wantVis;
            if (gone) return;
        }
        if (node.collapsed || (node.flags && node.flags.collapsed)) return;
        if (node.widgets_start_y !== SUITE_TOP) node.widgets_start_y = SUITE_TOP;
        if (node.drawSlots !== PFS_NO_DRAW) node.drawSlots = PFS_NO_DRAW;
        if (node.hideOutputImages !== true) node.hideOutputImages = true;   // native output overlay opt-out
        if (node.imgs && node.imgs.length) node.imgs.length = 0;   // leaked native preview
        for (const w of node.widgets || []) {
            if (w !== domWidget && !w._pfsHidden) hideWidget(w);
        }
        // Arrange FIRST so computedHeight is fresh for the geometry sync:
        // if the space split drifted (a stray widget joined, the frontend's
        // own layout pipeline lagged a resize, …) re-arrange so the suite
        // claims the node's full leftover height again.
        const y = domWidget.y || 0;
        if (y > 0 && typeof domWidget.computedHeight === "number") {
            const expect = node.size[1] - y;
            if (Math.abs(domWidget.computedHeight - expect) > 12 && node.arrange) {
                node.arrange();
                app.graph.setDirtyCanvas(true, true);
            }
        }
        syncWrapGeometry();
        refreshSockets();
        // Kill stray image-output DOM widgets every tick (belt-and-suspenders
        // with the onExecuted defense below). The Vue frontend may create
        // these asynchronously after execution; the 800ms interval catches
        // them even if onExecuted didn't fire in time.
        hideStrayImageWidgets();
    }, 800);

    // ---- stray image-output widget killer ----
    // In ComfyUI frontends >= ~1.2x, nodes with OUTPUT_NODE + IMAGE return
    // get a native image-preview DOM widget bolted onto them by the
    // ImageCompositor / Painter system. This widget renders the sprite
    // OUTSIDE the suite canvas and steals layout space. We detect and hide
    // any such widget that is NOT our pf_suite DOM widget.
    function hideStrayImageWidgets() {
        for (const w of node.widgets || []) {
            if (w === domWidget) continue;
            if (w._pfsHidden) continue;
            // DOM widgets created by the frontend for image output have a
            // .element that contains <canvas> or <img> — hide them.
            if (w.element && w.element.classList &&
                w.element.classList.contains("dom-widget")) {
                const hasCanvas = w.element.querySelector("canvas");
                const hasImg = w.element.querySelector("img");
                if (hasCanvas || hasImg) {
                    hideWidget(w);
                }
            }
        }
    }

    // ---- public hooks used by the extension wrapper ----
    return {
        state: st,
        onExecuted(message) {
            // Defense-in-depth (LAYOUT WAR): if a backend ever leaks
            // ui.images/animated again, the frontend bolts a native preview
            // onto the node — sprite outside the suite + half-size split.
            // Strip the canvas image list right away; the watchdog hides any
            // stray widget that snuck in.
            if (node.imgs && node.imgs.length) node.imgs.length = 0;
            // Kill any stray image-output DOM widgets the frontend may have
            // bolted on (Vue frontend ImageCompositor / Painter path).
            hideStrayImageWidgets();
            if (message && (message.pf_layers || message.pf_frames || message.pf_stages || message.pf_export_gif)) loadStages(message);
        },
        onResize() { draw(); drawTl(); syncWrapGeometry(); },
        onConfigure() {
            applyProps();
            // Guarantee at least one layer after ANY restore path — a saved
            // workflow can carry pfs_layers: [] from an older/broken session.
            if (!st.layers.length) addLayer("Layer 1");
            refreshCtrls();
            refreshSockets();
            refreshLayerBar();
            fitNode();
            draw(); drawTl();
        },
        onRemoved() {
            if (window._pfDrawnRefUploads) window._pfDrawnRefUploads.delete(uploadDrawnRef);
            cancelAnimationFrame(st._raf);
            cancelAnimationFrame(st._gifRaf);
            clearInterval(st._watch);
            ro.disconnect();
            if (st._selfPosSyncInstalled && app.canvas && app.canvas.canvas) {
                app.canvas.canvas.removeEventListener("pointermove", st._selfPosSchedule);
                app.canvas.canvas.removeEventListener("wheel", st._selfPosSchedule);
            }
        },
        init() {
            hideAllWidgets();
            fitNode();
            refreshSockets();
            // Create a default layer so the Aseprite-style timeline shows
            // immediately (before any execution populates pf_layers).
            if (!st.layers.length) {
                addLayer("Layer 1");
            }
            refreshLayerBar();
            drawTl();
        },
    };
}

// ---------------------------------------------------------------- extension
app.registerExtension({
    name: "pixelforge.superforge",
    async setup() {
        // drawn-ref: flush pending uploads before a prompt is submitted, so
        // queueing right after a stroke still ships the latest drawing.
        const origQP = app.queuePrompt;
        if (typeof origQP === "function" && !origQP._pfWrapped) {
            const wrapped = async function (...args) {
                try {
                    const ups = window._pfDrawnRefUploads ? [...window._pfDrawnRefUploads] : [];
                    await Promise.all(ups.map(f => f()));
                } catch (e) { /* never block queueing */ }
                return origQP.apply(this, args);
            };
            wrapped._pfWrapped = true;
            app.queuePrompt = wrapped;
        }
    },
    beforeRegisterNodeDef(nodeType, nodeData) {
        const config = NODE_CONFIGS[nodeData.name];
        if (!config) return;

        const origCreate = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = origCreate ? origCreate.apply(this, arguments) : undefined;
            this._pfs = createForge(this, config);
            this._pfs.init();
            return r;
        };

        const origExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            if (origExecuted) origExecuted.apply(this, arguments);
            if (this._pfs) this._pfs.onExecuted(message);
        };

        const origResize = nodeType.prototype.onResize;
        nodeType.prototype.onResize = function (size) {
            if (origResize) origResize.apply(this, arguments);
            if (this._pfs) this._pfs.onResize(size);
        };

        const origConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function (info) {
            if (origConfigure) origConfigure.apply(this, arguments);
            if (this._pfs) this._pfs.onConfigure();
        };

        const origRemoved = nodeType.prototype.onRemoved;
        nodeType.prototype.onRemoved = function () {
            if (this._pfs) this._pfs.onRemoved();
            if (origRemoved) origRemoved.apply(this, arguments);
        };
    },
});
