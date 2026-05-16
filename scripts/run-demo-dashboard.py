#!/usr/bin/env python3
"""
run-demo-dashboard.py — boots claude-dashboard against the seeded demo HOME,
substituting a static "fake-workspaces.json" for the real cmux call so the
dashboard renders the synthetic live-workspace state instead of whatever
cmux is actually running on this machine.

Usage:
  python3 run-demo-dashboard.py [DEMO_HOME] [PORT]
"""
import json
import os
import sys

DEMO_HOME = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "/tmp/claude-sessions-demo")
PORT = sys.argv[2] if len(sys.argv) > 2 else "18599"

os.environ["HOME"] = DEMO_HOME
os.environ["CLAUDE_DASHBOARD_PORT"] = PORT
os.environ["CLAUDE_DASHBOARD_SUMMARY"] = "ollama"
os.environ["CLAUDE_DASHBOARD_EMBED"] = "ollama"

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DASHBOARD_PATH = os.path.join(REPO, "bin", "claude-dashboard")


def _fake_workspaces():
    """Reads fake-workspaces.json next to the registry, returns the same shape
    real live_workspaces returns: {workspace_id: {title, ref, selected}}."""
    path = os.path.join(DEMO_HOME, ".claude", "fake-workspaces.json")
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


# Load claude-dashboard's source, monkey-patch live_workspaces, then exec.
with open(DASHBOARD_PATH) as f:
    source = f.read()

ns = {"__name__": "__main__", "__file__": DASHBOARD_PATH}
# Strip the trailing `if __name__ == '__main__': main()` so we control startup.
source_no_main = source.replace(
    'if __name__ == "__main__":\n    main()',
    "# entry point bypassed by run-demo-dashboard.py",
)
exec(compile(source_no_main, DASHBOARD_PATH, "exec"), ns)
ns["live_workspaces"] = _fake_workspaces
ns["main"]()
