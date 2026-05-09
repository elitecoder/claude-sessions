#!/usr/bin/env python3
"""
Claude Code hook: maintains a registry mapping cmux workspace -> Claude session.

Triggered on SessionStart. Reads the JSON payload Claude pipes on stdin, plus
CMUX_* env vars (auto-set in every cmux pane), and writes one entry per
workspace to ~/.claude/cmux-registry.json. Each new SessionStart in the same
workspace overwrites the prior entry — so the registry always reflects "what
session is running in each workspace right now". Cleanup of dead workspaces
happens lazily in cmux-resume.

Silent on any failure — must never break Claude.
"""
import fcntl
import json
import os
import sys
import time

REGISTRY = os.path.expanduser("~/.claude/cmux-registry.json")
LOCK = REGISTRY + ".lock"


def main():
    ws = os.environ.get("CMUX_WORKSPACE_ID")
    if not ws:
        return
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    sid = payload.get("session_id")
    if not sid:
        return
    cwd = payload.get("cwd", "")

    os.makedirs(os.path.dirname(REGISTRY), exist_ok=True)
    with open(LOCK, "a+") as lockf:
        fcntl.flock(lockf, fcntl.LOCK_EX)
        try:
            with open(REGISTRY) as f:
                reg = json.load(f)
        except Exception:
            reg = {}
        reg[ws] = {
            "session_id": sid,
            "cwd": cwd,
            "surface_id": os.environ.get("CMUX_SURFACE_ID", ""),
            "tab_id": os.environ.get("CMUX_TAB_ID", ""),
            "panel_id": os.environ.get("CMUX_PANEL_ID", ""),
            "claude_pid": os.environ.get("CMUX_CLAUDE_PID", ""),
            "ts": time.time(),
            "transcript_path": payload.get("transcript_path", ""),
        }
        tmp = REGISTRY + ".tmp"
        with open(tmp, "w") as f:
            json.dump(reg, f, indent=2)
        os.replace(tmp, REGISTRY)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
