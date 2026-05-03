"""
Bridge module: Python AssetBoy ↔ C# FAW plugin.

Two-way communication:
  1. Python calls C# HTTP server (localhost:8790) for providers, lanes, library
  2. C# calls Python HTTP server (localhost:8766) for auth-heavy providers,
     browser automation, Blender, AI generation

Usage:
  from assetboy.bridge import AssetWorkerClient
  client = AssetWorkerClient()
  providers = client.list_providers()
  result = client.download("polyhaven", "brick_wall_01")
"""

from __future__ import annotations

import json
import sys
import time
from typing import Optional
from urllib import request, error


CORE_URL = "http://localhost:8790"
REQUEST_TIMEOUT = 120


class AssetWorkerError(Exception):
    pass


class AssetWorkerClient:
    """HTTP client that talks to the C# FAW plugin."""

    def __init__(self, base_url: str = CORE_URL):
        self.base_url = base_url.rstrip("/")

    # ── health ──

    def health(self) -> dict:
        return self._get("/api/v1/health")

    def is_alive(self) -> bool:
        try:
            resp = self.health()
            return resp.get("status") == "ok"
        except Exception:
            return False

    # ── providers ──

    def list_providers(self) -> list[dict]:
        resp = self._post("/api/v1/providers/list", {})
        return resp.get("providers", [])

    def download(self, provider_id: str, asset_id: str, config: Optional[dict] = None) -> dict:
        payload = {"asset_id": asset_id}
        if config:
            payload["config"] = config
        return self._post(f"/api/v1/providers/{provider_id}/download", payload)

    def install(self, provider_id: str, asset_id: str, category: str, name: Optional[str] = None) -> dict:
        payload = {
            "asset_id": asset_id,
            "provider": provider_id,
            "category": category,
            "name": name or asset_id
        }
        return self._post("/api/v1/library/install", payload)

    # ── lanes ──

    def list_lanes(self) -> list[dict]:
        resp = self._post("/api/v1/lanes/list", {})
        return resp.get("lanes", [])

    # ── library ──

    def search_library(self, query: str = "") -> list[dict]:
        resp = self._post("/api/v1/library/search", {"query": query})
        return resp.get("results", [])

    def list_ready(self) -> list[dict]:
        resp = self._post("/api/v1/library/ready", {})
        return resp.get("ready_assets", [])

    # ── HTTP helpers ──

    def _get(self, path: str) -> dict:
        url = f"{self.base_url}{path}"
        try:
            with request.urlopen(url, timeout=REQUEST_TIMEOUT) as resp:
                return json.loads(resp.read().decode())
        except error.URLError as e:
            raise AssetWorkerError(f"Cannot reach AssetWorker at {self.base_url}: {e}") from e
        except json.JSONDecodeError as e:
            raise AssetWorkerError(f"Invalid JSON from AssetWorker: {e}") from e

    def _post(self, path: str, payload: dict) -> dict:
        url = f"{self.base_url}{path}"
        data = json.dumps(payload).encode("utf-8")
        req = request.Request(url, data=data, headers={"Content-Type": "application/json"})
        try:
            with request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                return json.loads(resp.read().decode())
        except error.URLError as e:
            raise AssetWorkerError(f"Cannot reach AssetWorker at {self.base_url}: {e}") from e
        except json.JSONDecodeError as e:
            raise AssetWorkerError(f"Invalid JSON from AssetWorker: {e}") from e


# ── CLI ──

def main():
    """Quick test: python -m assetboy.bridge"""
    client = AssetWorkerClient()

    if not client.is_alive():
        print(f"ERROR: AssetWorker not running at {CORE_URL}", file=sys.stderr)
        print("Start the Flax Editor with FAW plugin enabled.", file=sys.stderr)
        sys.exit(1)

    print(f"✓ AssetWorker alive at {CORE_URL}")
    print(f"  Providers: {len(client.list_providers())}")
    print(f"  Ready assets: {len(client.list_ready())}")
    print(f"  Lanes: {len(client.list_lanes())}")


if __name__ == "__main__":
    main()
