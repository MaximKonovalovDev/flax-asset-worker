"""
HTTP server (port 8766) that wraps Python-only worker capabilities.
The C# FAW plugin calls this for:

  - Browser-based auth flows (Fab/OAuth, Epic/Playwright, Mixamo/web)
  - Blender mesh optimization
  - AI image/model generation (Colab, ComfyUI, local)
  - Format conversion (fbx→gltf, etc.)

Start:  python -m assetboy.worker_server
"""

from __future__ import annotations

import json
import os
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Callable

PORT = int(os.environ.get("ASSETBOY_WORKER_PORT", "8766"))

routes: dict[str, Callable[[dict], dict]] = {}


def route(path: str):
    """Decorator to register a handler for a path."""
    def decorator(fn):
        routes[path] = fn
        return fn
    return decorator


# ── handlers ──

@route("health")
def handle_health(payload: dict) -> dict:
    return {
        "status": "ok",
        "service": "assetboy-worker",
        "port": PORT,
        "routes": sorted(routes.keys())
    }


@route("providers/list")
def handle_providers_list(payload: dict) -> dict:
    """List Python-available providers (auth-heavy ones)."""
    return {
        "providers": [
            {"id": "fab", "name": "Fab.com", "requires_auth": True, "category": "marketplace"},
            {"id": "epic", "name": "Epic Games", "requires_auth": True, "category": "marketplace"},
            {"id": "mixamo", "name": "Mixamo", "requires_auth": True, "category": "animation"},
            {"id": "unity", "name": "Unity Asset Store", "requires_auth": True, "category": "marketplace"},
            {"id": "blender", "name": "Blender Optimize", "requires_auth": False, "category": "cleanup"},
            {"id": "colab", "name": "Colab Gen", "requires_auth": True, "category": "generation"},
        ]
    }


@route("fab/auth")
def handle_fab_auth(payload: dict) -> dict:
    """Placeholder: Fab.com OAuth via Playwright."""
    return {"status": "not_implemented", "hint": "Use Python/assetboy/providers/fab_hybrid.py"}


@route("mixamo/download")
def handle_mixamo_download(payload: dict) -> dict:
    """Placeholder: Mixamo animation download via Playwright."""
    return {"status": "not_implemented", "hint": "Use Python/assetboy/providers/mixamo_auth.py"}


@route("blender/optimize")
def handle_blender_optimize(payload: dict) -> dict:
    """Placeholder: Blender mesh optimization."""
    return {"status": "not_implemented", "hint": "Use Python/assetboy/cleanup/blender_batch.py"}


@route("generate/image")
def handle_generate_image(payload: dict) -> dict:
    """Placeholder: AI image generation."""
    return {"status": "not_implemented", "hint": "Use Python/assetboy/providers/generator.py or colab_runner.py"}


# ── HTTP server ──

class WorkerHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        path = self.path.strip("/")
        if path not in routes:
            self._json(404, {"error": f"Unknown route: {path}", "available": sorted(routes.keys())})
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode() if length > 0 else "{}"
            payload = json.loads(body)
            result = routes[path](payload)
            self._json(200, {"success": True, "data": result})
        except json.JSONDecodeError:
            self._json(400, {"success": False, "error": "Invalid JSON"})
        except Exception as e:
            self._json(500, {"success": False, "error": str(e)})

    def do_GET(self):
        self.do_POST()

    def _json(self, code: int, data: dict):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, fmt, *args):
        pass  # silent


def start_server():
    server = HTTPServer(("127.0.0.1", PORT), WorkerHandler)
    print(f"[AssetBoy Worker] Listening on http://127.0.0.1:{PORT}")
    print(f"[AssetBoy Worker] Routes: {sorted(routes.keys())}")
    server.serve_forever()


def main():
    # Register real providers if available
    try:
        from assetboy.providers.fab_hybrid import fab_auth_handler
        routes["fab/auth"] = fab_auth_handler
        print("[AssetBoy Worker] Loaded Fab.com provider")
    except ImportError:
        pass

    try:
        from assetboy.providers.mixamo_auth import mixamo_download_handler
        routes["mixamo/download"] = mixamo_download_handler
        print("[AssetBoy Worker] Loaded Mixamo provider")
    except ImportError:
        pass

    try:
        from assetboy.cleanup.blender_batch import blender_optimize_handler
        routes["blender/optimize"] = blender_optimize_handler
        print("[AssetBoy Worker] Loaded Blender provider")
    except ImportError:
        pass

    start_server()


if __name__ == "__main__":
    main()
