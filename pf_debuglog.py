"""Self-report probe endpoint for the PixelForge suite (v3.5.3-probe).

The in-page pf_studio.js POSTs pointer forensics here so live diagnostics
need NOTHING from the owner but normal use. Appends JSONL to
_probe_log.jsonl next to this file. Temporary instrumentation — remove once
the stuck-slider case closes.
"""

import json
import os
import time

from aiohttp import web
from server import PromptServer

_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_probe_log.jsonl")


@PromptServer.instance.routes.post("/pixelforge/probe")
async def pixelforge_probe(request):
    try:
        data = await request.json()
    except Exception:
        data = {"unparsed": (await request.text())[:4000]}
    try:
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "data": data}) + "\n")
    except Exception:
        pass
    return web.json_response({"ok": True})
