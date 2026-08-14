"""ComfyUI-PixelForge-H3 — turn MiniMax H3 video output into real pixel-art
sprite animations AND single sprites (gen + ref2va edit), with an Aseprite
bridge. Self-contained: no other custom node pack is modified or required
(pure numpy/PIL/torch + native types)."""

from .pf_pixelize import NODE_CLASS_MAPPINGS as _Q_C, NODE_DISPLAY_NAME_MAPPINGS as _Q_D
from .pf_sprite import (PixelForgeAutoCrop, PixelForgeChromaKey, PixelForgeFrameDedup,
                        PixelForgeLoopTrim, PixelForgeSheetPack)
from .pf_h3 import (PixelForgeFrameStep, PixelForgeFirstFrame, PixelForgeH3EditPrompt,
                    PixelForgeH3FrameGrid, PixelForgeH3Prompt, PixelForgeH3StillPrompt,
                    PixelForgePrepForH3, PixelForgeVideoToFrames)
from .pf_aseprite import NODE_CLASS_MAPPINGS as _A_C, NODE_DISPLAY_NAME_MAPPINGS as _A_D
from .pf_finalize import NODE_CLASS_MAPPINGS as _F_C, NODE_DISPLAY_NAME_MAPPINGS as _F_D
from .pf_grid import NODE_CLASS_MAPPINGS as _G_C, NODE_DISPLAY_NAME_MAPPINGS as _G_D
from .pf_sampler import NODE_CLASS_MAPPINGS as _S_C, NODE_DISPLAY_NAME_MAPPINGS as _S_D
from .pf_temporal import NODE_CLASS_MAPPINGS as _T_C, NODE_DISPLAY_NAME_MAPPINGS as _T_D
from .pf_easy import NODE_CLASS_MAPPINGS as _E_C, NODE_DISPLAY_NAME_MAPPINGS as _E_D

NODE_CLASS_MAPPINGS = {
    **_Q_C,
    "PixelForgeChromaKey": PixelForgeChromaKey,
    "PixelForgeAutoCrop": PixelForgeAutoCrop,
    "PixelForgeLoopTrim": PixelForgeLoopTrim,
    "PixelForgeFrameDedup": PixelForgeFrameDedup,
    "PixelForgeSheetPack": PixelForgeSheetPack,
    "PixelForgeH3Prompt": PixelForgeH3Prompt,
    "PixelForgeH3StillPrompt": PixelForgeH3StillPrompt,
    "PixelForgeH3EditPrompt": PixelForgeH3EditPrompt,
    "PixelForgePrepForH3": PixelForgePrepForH3,
    "PixelForgeFirstFrame": PixelForgeFirstFrame,
    "PixelForgeH3FrameGrid": PixelForgeH3FrameGrid,
    "PixelForgeVideoToFrames": PixelForgeVideoToFrames,
    "PixelForgeFrameStep": PixelForgeFrameStep,
    **_A_C,
    **_F_C,
    **_G_C,
    **_S_C,
    **_T_C,
    **_E_C,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    **_Q_D,
    "PixelForgeChromaKey": "Sprite Chroma Key (PixelForge)",
    "PixelForgeAutoCrop": "Sprite Auto-Crop && Anchor (PixelForge)",
    "PixelForgeLoopTrim": "Sprite Loop Trim (PixelForge)",
    "PixelForgeFrameDedup": "Sprite Frame Dedup (PixelForge)",
    "PixelForgeSheetPack": "Sprite Sheet Pack (PixelForge)",
    "PixelForgeH3Prompt": "H3 Sprite Prompt (PixelForge)",
    "PixelForgeH3StillPrompt": "H3 Single Sprite Prompt (PixelForge)",
    "PixelForgeH3EditPrompt": "H3 Sprite Edit Prompt (PixelForge)",
    "PixelForgePrepForH3": "H3 Prep Sprite For Edit (PixelForge)",
    "PixelForgeFirstFrame": "Extract Single Frame (PixelForge)",
    "PixelForgeH3FrameGrid": "H3 Frame Grid Snap (PixelForge)",
    "PixelForgeVideoToFrames": "H3 Video To Sprite Frames (PixelForge)",
    "PixelForgeFrameStep": "H3 Frame Decimate (PixelForge)",
    **_A_D,
    **_F_D,
    **_G_D,
    **_S_D,
    **_T_D,
    **_E_D,
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
