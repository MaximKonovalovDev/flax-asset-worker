"""
flax_mcp_bridge.py
Thin helper that calls the FlaxMCP HTTP server (JSON-RPC 2.0) and returns the parsed result.
Zero extra dependencies — uses stdlib urllib only.
"""
from __future__ import annotations

import json
import uuid
from typing import Any
import urllib.error
import urllib.request


def _with_default_intent(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        return arguments

    existing_intent = str(arguments.get("intent") or "").strip()
    if existing_intent:
        return arguments

    normalized_tool = str(tool_name or "").strip()
    scoped_intent = f"asset_factory/{normalized_tool}" if normalized_tool else "asset_factory/tool_call"

    action_name = str(arguments.get("action") or "").strip()
    if action_name:
        scoped_intent = f"{scoped_intent}/{action_name}"

    enriched = dict(arguments)
    enriched["intent"] = scoped_intent
    return enriched


def call_tool(tool_name: str, arguments: dict[str, Any], port: int = 8080, timeout: int = 30) -> dict:
    """
    Call one FlaxMCP tool and return the parsed JSON-RPC response.

    Raises:
        ConnectionRefusedError  — editor not running / MCP plugin not started
        RuntimeError            — server responded but tool returned an error
    """
    resolved_arguments = _with_default_intent(tool_name, arguments)
    payload = json.dumps({
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": resolved_arguments,
        },
    }).encode("utf-8")

    req = urllib.request.Request(
        f"http://127.0.0.1:{port}",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
    except ConnectionRefusedError:
        raise ConnectionRefusedError(
            f"FlaxMCP server is not responding on port {port}. "
            "Make sure the Flax Editor is open with the FlaxMCP plugin loaded."
        )
    except urllib.error.URLError as exc:
        raise ConnectionRefusedError(
            f"Could not reach FlaxMCP server: {exc.reason}. "
            "Open Flax Editor → wait for [FlaxMCP] Initialized in the logs → retry."
        )

    data = json.loads(body)

    # JSON-RPC error block
    if "error" in data:
        raise RuntimeError(f"MCP tool error: {data['error']}")

    return data.get("result", data)


# ---------------------------------------------------------------------------
# Pre-built dungeon layout templates
# ---------------------------------------------------------------------------
DUNGEON_PRESETS: dict[str, list[str]] = {
    "colosseum": [
        "WPPAGPPW",
        "WFFFFFFW",
        "PFSBBSFP",
        "AFFFBFFA",
        "GFFBBFFG",
        "PFSBBSFP",
        "WFFFFFFW",
        "WPPAGPPW",
    ],
    "throne_arena": [
        "WWPASPWW",
        "WFFFFFFW",
        "PFTBBTFP",
        "AFFSSFFA",
        "GFFBBFFG",
        "AFFSSFFA",
        "WFFFFFFW",
        "WWPAGPWW",
    ],
    "temple_pit": [
        "WPAAAPW",
        "WFTTTFW",
        "AFSBBSFA",
        "AFBBBBFA",
        "GFSBBSFG",
        "AFSBBSFA",
        "WFTTTFW",
        "WPAAAPW",
    ],
}

# Legend maps to the actual prefab paths discovered on disk in your Flax project.
ROMAN_ARENA_LEGEND: dict[str, str] = {
    "W": "Content/Prefabs/RomanArena/SM_castle_wall.prefab",
    "G": "Content/Prefabs/RomanArena/SM_castle_gate.prefab",
    "F": "Content/Prefabs/RomanArena/SM_platform_planks.prefab",
    "P": "Content/Prefabs/RomanArena/SM_barrel.prefab",
    "T": "Content/Prefabs/RomanArena/SM_cannon.prefab",
    "S": "Content/Prefabs/RomanArena/SM_rocks_a.prefab",
    "B": "Content/Prefabs/RomanArena/SM_crate.prefab",
    "A": "Content/Prefabs/RomanArena/SM_castle_wall.prefab",
}
