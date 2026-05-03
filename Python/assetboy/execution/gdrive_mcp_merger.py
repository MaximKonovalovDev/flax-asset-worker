from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
from pathlib import Path


def _slug(value: str, fallback: str = "item") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value).strip())
    cleaned = cleaned.strip("._-")
    return cleaned or fallback


def drive_folder_for_colab(profile_id: str, pack_id: str, batch_id: str | None = None) -> str:
    """Return a stable Google Drive folder path for a Colab batch handoff."""
    parts = ["AssetBoy", "colab", _slug(profile_id), _slug(pack_id)]
    if batch_id:
        parts.append(_slug(batch_id))
    return "/".join(parts)


def build_drive_stage_plan(
    *,
    local_artifacts_dir: str | Path,
    drive_folder: str,
    upload_items: list[dict[str, object]],
    download_items: list[dict[str, object]] | None = None,
    notes: list[str] | None = None,
) -> dict[str, object]:
    """Build a plain JSON-friendly plan for staging a Colab batch through Google Drive."""
    return {
        "schema_version": "assetboy.gdrive_stage_plan.v1",
        "local_artifacts_dir": str(Path(local_artifacts_dir)),
        "drive_folder": drive_folder,
        "upload_items": upload_items,
        "download_items": download_items or [],
        "notes": notes or [],
    }


def proxy():
    # Setup environment
    env = os.environ.copy()

    # Start the actual google-drive-mcp process
    proc = subprocess.Popen(
        ["npx.cmd", "-y", "@piotr-agier/google-drive-mcp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=sys.stderr,
        env=env,
        text=True,
        bufsize=1,
    )

    universal_tool = {
        "name": "gdrive_action",
        "description": "Universal wrapper for all Google Drive tools to bypass the 100-tool IDE limit. Pass the precise tool name and its arguments serialized as a JSON string.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tool_name": {
                    "type": "string",
                    "description": "Name of the tool (e.g. search, uploadFile, downloadFile, readTextFile, etc)",
                },
                "arguments_json": {
                    "type": "string",
                    "description": "A JSON string containing the arguments (e.g. '{\"name\": \"test.txt\"}')",
                },
            },
            "required": ["tool_name", "arguments_json"],
        },
    }

    # We need to buffer the description update so it only happens once
    tools_injected = False

    def read_parent():
        for line in sys.stdin:
            try:
                msg = json.loads(line)
                if msg.get("method") == "tools/call" and msg.get("params", {}).get("name") == "gdrive_action":
                    args = msg["params"].get("arguments", {})
                    real_tool = args.get("tool_name")
                    real_args = json.loads(args.get("arguments_json", "{}"))

                    msg["params"]["name"] = real_tool
                    msg["params"]["arguments"] = real_args

                proc.stdin.write(json.dumps(msg) + "\n")
                proc.stdin.flush()
            except Exception:
                proc.stdin.write(line)
                proc.stdin.flush()

    def read_child():
        nonlocal tools_injected
        for line in proc.stdout:
            try:
                msg = json.loads(line)
                if "result" in msg and "tools" in msg["result"]:
                    # Intercept tools/list response
                    if not tools_injected:
                        original_tools = [t["name"] for t in msg["result"]["tools"]]
                        universal_tool["description"] += f" Available sub-tools: {', '.join(original_tools)}."
                        tools_injected = True

                    msg["result"]["tools"] = [universal_tool]

                sys.stdout.write(json.dumps(msg) + "\n")
                sys.stdout.flush()
            except Exception:
                sys.stdout.write(line)
                sys.stdout.flush()

    t1 = threading.Thread(target=read_parent, daemon=True)
    t2 = threading.Thread(target=read_child, daemon=True)
    t1.start()
    t2.start()
    proc.wait()


if __name__ == "__main__":
    proxy()
