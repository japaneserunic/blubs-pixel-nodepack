"""Pixel-art-tuned sampling for the MiniMax-H3 turbo path.

Two nodes, both non-destructive (defaults = stock behavior, wire-in-but-
untouched is bit-identical to the current workflow):

  PixelForgeH3FlatSigmas   MODEL + steps -> SIGMAS
      Custom sigma schedules for the distilled 4-step turbo LoRA. Stock
      schedules spend the tail steps refining gradients/grain that the
      pixelize pass deletes anyway. tail_compress warps the schedule to
      front-load composition and skip the ultra-low-sigma tail, so the VAE
      hands the quantizer flatter color fields for free.

  PixelForgeH3PixelSampler SAMPLER -> SAMPLER (wraps MiniMaxH3TurboSampler)
      Three knobs, all default 0 (off):
      - temporal_blend: correlates the init noise across frames
        (variance-preserving blend toward frame 0's noise), so pixel shimmer
        and palette flicker are never generated in the first place.
      - loop_noise: bends late-frame noise progressively back toward frame 0,
        so walk cycles actually loop instead of Loop Trim hunting for a cut
        point that doesn't exist.
      - edge_commit: last-latent spatial grain damping (tiny binomial blur
        mix) so high-frequency ringing that becomes keying halo is softened
        before the VAE decode.

Implementation notes: the H3 latent is a FLAT pack [video | audio] (see
ComfyUI-MiniMax-H3-Turbo), handed to the sampler with arbitrary leading dims
(observed [B, 1, V+A]). Video shape is recovered from the guider conds'
latent_shapes exactly like the turbo sampler does; all noise/latent surgery
is restricted to the video half, audio passes through untouched.
"""

import math

import torch
import torch.nn.functional as F

import comfy.samplers


# ---------------------------------------------------------------------------
# latent pack helpers (mirrors ComfyUI-MiniMax-H3-Turbo's _latent_shapes)

def _latent_shapes(model):
    """[video_shape, audio_shape] the sampler is packing over, or None.

    Checks the object AND its .inner_model: SamplerCustomAdvanced hands the
    wrapper the guider (conds live there), while inside KSAMPLER.sample the
    wrapped sampler sees KSamplerX0Inpaint (guider one level down)."""
    cands = [model]
    inner = getattr(model, "inner_model", None)
    if inner is not None:
        cands.append(inner)
    for obj in cands:
        conds = getattr(obj, "conds", None)
        if conds:
            for cond_list in conds.values():
                for c in (cond_list or []):
                    mc = c.get("model_conds", {}) if isinstance(c, dict) else {}
                    if "latent_shapes" in mc:
                        return mc["latent_shapes"].cond
    return None


def _split_video(t, shapes):
    """flat (..., V+A) -> (video reshaped to (-1, *shapes[0][1:]), audio,
    lead_shape, v_numel) or None. Leading dims are whatever the pack carries
    (H3 hands the sampler [B, 1, V+A] — NOT a plain 2-dim [B, V+A])."""
    if not shapes:
        return None
    vshape = list(shapes[0])
    v_numel = math.prod(vshape[1:])
    if t.shape[-1] < v_numel:
        return None
    lead = t.shape[:-1]
    v = t[..., :v_numel].reshape(-1, *vshape[1:])
    a = t[..., v_numel:]
    return v, a, lead, v_numel


def _merge_video(v, a, lead, v_numel):
    return torch.cat([v.reshape(*lead, v_numel), a], dim=-1)


# ---------------------------------------------------------------------------
# noise shaping (variance-preserving)

def _shape_noise(noise, shapes, temporal_blend, loop_noise):
    sp = _split_video(noise, shapes)
    if sp is None:
        return noise
    v, a, lead, vn = sp
    if v.dim() != 5 or v.shape[2] < 2:
        return noise                      # no temporal axis -> leave it alone
    T = v.shape[2]
    n0 = v[:, :, 0:1]                     # frame-0 noise = shared component
    out = v
    if temporal_blend > 0:
        b = float(temporal_blend)
        c0 = math.sqrt(max(0.0, 1.0 - b * b))
        mixed = c0 * out + b * n0.expand_as(out)
        # t=0 would double-count its own noise (variance inflate): keep it.
        mixed = torch.cat([out[:, :, 0:1], mixed[:, :, 1:]], dim=2)
        out = mixed
    if loop_noise > 0:
        l = float(loop_noise)
        t = torch.arange(T, device=out.device, dtype=out.dtype)
        w = l * (t / max(1, T - 1)) ** 2   # 0 at frame 0 -> l at the last frame
        w = w.view(1, 1, T, 1, 1)
        c = (1.0 - w * w).clamp(min=0.0).sqrt()
        out = c * out + w * n0.expand_as(out)
    return _merge_video(out, a, lead, vn)


# ---------------------------------------------------------------------------
# edge commit (final-latent grain damping, video half only)

def _binomial_kernel(dtype, device):
    k = torch.tensor([[1., 2., 1.], [2., 4., 2.], [1., 2., 1.]],
                     dtype=dtype, device=device) / 16.0
    return k.view(1, 1, 3, 3)


def _edge_commit(samples, shapes, strength):
    sp = _split_video(samples, shapes)
    if sp is None:
        return samples
    v, a, lead, vn = sp
    if v.dim() != 5:
        return samples
    B, C, T, H, W = v.shape
    if H < 4 or W < 4:
        return samples
    k = float(strength)
    x = v.permute(0, 2, 1, 3, 4).reshape(B * T, C, H, W)
    k3 = _binomial_kernel(x.dtype, x.device).expand(C, 1, 3, 3)
    xp = F.pad(x, (1, 1, 1, 1), mode="replicate")
    blur = F.conv2d(xp, k3, groups=C)
    x = x * (1.0 - k) + blur * k
    v = x.reshape(B, T, C, H, W).permute(0, 2, 1, 3, 4)
    return _merge_video(v, a, lead, vn)


# ---------------------------------------------------------------------------
# wrapper sampler

class _PixelSamplerWrapper(comfy.samplers.Sampler):
    """SAMPLER-object wrapper: intercepts init noise + final latents around
    the wrapped sampler (MiniMaxH3TurboSampler or any other SAMPLER)."""

    def __init__(self, inner, temporal_blend, loop_noise, edge_commit):
        self.inner = inner
        self.temporal_blend = temporal_blend
        self.loop_noise = loop_noise
        self.edge_commit = edge_commit

    def max_denoise(self, model_wrap, sigmas):
        inner = getattr(self.inner, "max_denoise", None)
        if inner is not None:
            return inner(model_wrap, sigmas)
        return super().max_denoise(model_wrap, sigmas)

    def sample(self, model_wrap, sigmas, extra_args, callback, noise,
               latent_image=None, denoise_mask=None, disable_pbar=False):
        shapes = _latent_shapes(model_wrap)
        if noise is not None and (self.temporal_blend > 0 or self.loop_noise > 0):
            noise = _shape_noise(noise, shapes, self.temporal_blend,
                                 self.loop_noise)
        out = self.inner.sample(model_wrap, sigmas, extra_args, callback,
                                noise, latent_image, denoise_mask,
                                disable_pbar)
        if self.edge_commit > 0:
            out = _edge_commit(out, shapes, self.edge_commit)
        return out


class PixelForgeH3PixelSampler:
    """Wraps your existing H3 turbo sampler with pixel-art noise/latent
    shaping. All knobs default 0 = identical to the wrapped sampler."""

    CATEGORY = "PixelForge/h3"
    FUNCTION = "wrap"
    RETURN_TYPES = ("SAMPLER",)
    DESCRIPTION = ("Pixel-art sampler wrapper for the H3 turbo path. "
                   "temporal_blend correlates noise across frames (kills pixel "
                   "shimmer/palette flicker at the source — try 0.3-0.6), "
                   "loop_noise bends late frames back toward frame 0 so cycles "
                   "loop, edge_commit damps last-latent grain before VAE decode "
                   "(softens keying halo). All 0 = stock behavior. Plug between "
                   "MiniMaxH3TurboSampler and SamplerCustomAdvanced.")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "sampler": ("SAMPLER",),
            "temporal_blend": ("FLOAT", {
                "default": 0.0, "min": 0.0, "max": 1.0, "step": 0.05,
                "tooltip": "Correlate init noise across frames (variance-"
                           "preserving blend toward frame 0's noise). 0 = off. "
                           "0.3-0.6 is the flicker-killing sweet spot; high "
                           "values freeze detail changes between frames."}),
            "loop_noise": ("FLOAT", {
                "default": 0.0, "min": 0.0, "max": 1.0, "step": 0.05,
                "tooltip": "Bend late-frame noise back toward frame 0 "
                           "(quadratic ramp). 0 = off. Makes generated cycles "
                           "actually loop; 0.2-0.5 suggested."}),
            "edge_commit": ("FLOAT", {
                "default": 0.0, "min": 0.0, "max": 1.0, "step": 0.05,
                "tooltip": "Final-latent grain damping (3x3 binomial mix, "
                           "video half only). 0 = off. Softens the "
                           "high-frequency ringing that becomes chroma-key "
                           "halo. 0.2-0.4 suggested."}),
        }}

    def wrap(self, sampler, temporal_blend, loop_noise, edge_commit):
        if temporal_blend <= 0 and loop_noise <= 0 and edge_commit <= 0:
            return (sampler,)          # untouched: pass the stock sampler through
        return (_PixelSamplerWrapper(sampler, temporal_blend, loop_noise,
                                     edge_commit),)


# ---------------------------------------------------------------------------
# flat sigmas

class PixelForgeH3FlatSigmas:
    """Sigma schedule for the distilled turbo path: front-load composition,
    compress the low-noise tail the quantize pass deletes anyway."""

    CATEGORY = "PixelForge/h3"
    FUNCTION = "get_sigmas"
    RETURN_TYPES = ("SIGMAS",)
    DESCRIPTION = ("Custom sigma schedule for pixel-art H3 runs. tail_compress "
                   "warps the schedule upward at the low-sigma end so steps go "
                   "to composition/flat color fields instead of fine-grain "
                   "refinement you delete in quantize. 0 = identical to "
                   "BasicScheduler. Try 0.3-0.5 on the 4-step turbo LoRA.")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "model": ("MODEL",),
            "scheduler": (comfy.samplers.SCHEDULER_NAMES,),
            "steps": ("INT", {"default": 4, "min": 1, "max": 64}),
            "tail_compress": ("FLOAT", {
                "default": 0.0, "min": 0.0, "max": 0.9, "step": 0.05,
                "tooltip": "Compress the low-noise tail: 0 = stock schedule, "
                           "higher = steps skip ultra-fine refinement and "
                           "spend on composition. 0.3-0.5 suggested for "
                           "4-step turbo pixel art."}),
        }}

    def get_sigmas(self, model, scheduler, steps, tail_compress):
        sigmas = comfy.samplers.calculate_sigmas(
            model.get_model_object("model_sampling"), scheduler, steps).clone()
        if tail_compress <= 0:
            return (sigmas,)
        e = 1.0 - 0.7 * float(tail_compress)      # exponent warp, <1 raises lows
        body = sigmas[:-1].clamp(min=0.0)
        s_max = float(body.max())
        if s_max <= 0:
            return (sigmas,)
        warped = s_max * (body / s_max) ** e
        warped[0] = body[0]                        # keep exact sigma_max entry
        sigmas[:-1] = warped
        sigmas[-1] = 0.0
        return (sigmas,)


NODE_CLASS_MAPPINGS = {
    "PixelForgeH3PixelSampler": PixelForgeH3PixelSampler,
    "PixelForgeH3FlatSigmas": PixelForgeH3FlatSigmas,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "PixelForgeH3PixelSampler": "H3 Pixel Sampler (PixelForge)",
    "PixelForgeH3FlatSigmas": "H3 Flat Sigmas (PixelForge)",
}
