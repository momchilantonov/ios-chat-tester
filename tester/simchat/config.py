"""Configuration: one JSON file, `config.json` next to this package (copied from config.example.json)."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

HOME = Path(__file__).resolve().parent.parent  # .github/chat-tester

DEFAULTS: Dict[str, Any] = {
    "app": {"bundle_id": "", "launch_arguments": []},
    "repos": {},
    "simulator": {"udid": "", "open_simulator_app": True},
    "driver": {"port": 8787, "manage": True, "token": "", "xcodebuild_args": ""},
    "chat": {
        "composer_ids": [],
        "send_ids": [],
        "send_labels": ["Send"],
        "typing_ids": [],
        "typing_labels": [],
    },
    "pace_ms": 400,
    "waits": {"reply_timeout_s": 45, "quiet_ms": 2000, "poll_ms": 600, "send_confirm_s": 10},
    "endpoints": {},
    "logs": {},
    "error_patterns": ["Traceback", "ERROR", "Exception"],
}


def _merge(base: Dict[str, Any], over: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for key, value in over.items():
        if key.startswith("_"):
            continue  # "_comment" keys
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            out[key] = _merge(base[key], value)
        else:
            out[key] = value
    return out


def config_path() -> Path:
    env = os.environ.get("SIMCHAT_CONFIG")
    return Path(env).expanduser() if env else HOME / "config.json"


def load_config() -> Dict[str, Any]:
    path = config_path()
    problems = []
    data: Dict[str, Any] = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            problems.append("%s is not valid JSON: %s" % (path, exc))
    else:
        problems.append("%s missing - copy config.example.json to config.json and fill it in" % path)
    cfg = _merge(DEFAULTS, data)
    if not cfg["app"]["bundle_id"]:
        problems.append("app.bundle_id is empty")
    cfg["_problems"] = problems
    cfg["_path"] = str(path)
    return cfg
