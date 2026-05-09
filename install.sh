#!/usr/bin/env bash
# claude-sessions installer.
#
# Lays out:
#   $HOME/.local/bin/claude-dashboard
#   $HOME/.local/bin/claude-dashboard-ctl
#   $HOME/.local/bin/cmux-resume
#   $HOME/.local/bin/cmux-resume-smart
#   $HOME/.claude/hooks/cmux-registry.py
#   $HOME/Library/LaunchAgents/com.<USER>.claude-dashboard.plist   (macOS only)
#
# Then wires the SessionStart hook into $HOME/.claude/settings.json (non-destructive)
# and loads the LaunchAgent so the dashboard starts immediately and at login.
#
# Re-running is safe — it overwrites the installed scripts but does not duplicate
# the hook entry in settings.json.

set -euo pipefail

# --- preflight -----------------------------------------------------------

if [[ "$(uname)" != "Darwin" ]]; then
  echo "claude-sessions currently requires macOS (for launchd + cmux)." >&2
  echo "You can still copy bin/* and hooks/* manually if you want the CLI tools on Linux." >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USER_NAME="${USER:-$(id -un)}"
HOME_DIR="${HOME}"

echo "claude-sessions: installing for user=$USER_NAME home=$HOME_DIR"

command -v python3 >/dev/null || { echo "python3 required"; exit 1; }

# Warn (don't fail) if cmux isn't installed — dashboard still works, just can't open workspaces.
CMUX_BIN="/Applications/cmux.app/Contents/Resources/bin/cmux"
if [[ ! -x "$CMUX_BIN" ]]; then
  echo "  [warn] cmux not found at $CMUX_BIN — the dashboard will start, but Resume buttons"
  echo "         won't work until you install cmux (https://cmux.com)."
fi

# --- lay out binaries ----------------------------------------------------

BIN_DIR="$HOME_DIR/.local/bin"
HOOKS_DIR="$HOME_DIR/.claude/hooks"
LAUNCHD_DIR="$HOME_DIR/Library/LaunchAgents"
LOG_DIR="$HOME_DIR/Library/Logs/claude-dashboard"

mkdir -p "$BIN_DIR" "$HOOKS_DIR" "$LAUNCHD_DIR" "$LOG_DIR"

install -m 0755 "$REPO_ROOT/bin/claude-dashboard"     "$BIN_DIR/claude-dashboard"
install -m 0755 "$REPO_ROOT/bin/claude-dashboard-ctl" "$BIN_DIR/claude-dashboard-ctl"
install -m 0755 "$REPO_ROOT/bin/cmux-resume"          "$BIN_DIR/cmux-resume"
install -m 0755 "$REPO_ROOT/bin/cmux-resume-smart"    "$BIN_DIR/cmux-resume-smart"
install -m 0755 "$REPO_ROOT/hooks/cmux-registry.py"   "$HOOKS_DIR/cmux-registry.py"

echo "  [ok] copied scripts to $BIN_DIR and $HOOKS_DIR"

# --- render and install the LaunchAgent plist ----------------------------

LABEL="com.${USER_NAME}.claude-dashboard"
PLIST_PATH="$LAUNCHD_DIR/${LABEL}.plist"
TEMPLATE="$REPO_ROOT/launchd/com.USER.claude-dashboard.plist.template"

# sed -i on macOS requires '' arg for in-place; use a temp file to stay portable.
sed \
  -e "s|__USER__|${USER_NAME}|g" \
  -e "s|__HOME__|${HOME_DIR}|g" \
  "$TEMPLATE" > "$PLIST_PATH"

echo "  [ok] wrote $PLIST_PATH"

# --- wire the SessionStart hook into Claude settings --------------------

SETTINGS="$HOME_DIR/.claude/settings.json"
if [[ -f "$SETTINGS" ]]; then
  # Back up once per install run
  BACKUP="$SETTINGS.bak.$(date +%Y%m%d-%H%M%S)"
  cp "$SETTINGS" "$BACKUP"
  echo "  [ok] backed up settings.json → $BACKUP"
else
  # Create a minimal shell so subsequent code can add the hook
  mkdir -p "$(dirname "$SETTINGS")"
  echo '{}' > "$SETTINGS"
  echo "  [ok] created empty $SETTINGS"
fi

python3 - "$SETTINGS" <<'PY'
import json, os, sys
p = sys.argv[1]
with open(p) as f:
    data = json.load(f)

hooks = data.setdefault("hooks", {})
session_start = hooks.setdefault("SessionStart", [])

already = any(
    any("cmux-registry.py" in h.get("command", "") for h in entry.get("hooks", []))
    for entry in session_start
    if isinstance(entry, dict)
)
if already:
    print("  [ok] SessionStart hook already present — skipping")
else:
    session_start.append({
        "matcher": "",
        "hooks": [{
            "type": "command",
            "command": "$HOME/.claude/hooks/cmux-registry.py",
            "timeout": 5,
        }],
    })
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, p)
    print("  [ok] added SessionStart hook to settings.json")
PY

# --- ensure the cmux-registry file exists (empty is fine) ---------------

REGISTRY="$HOME_DIR/.claude/cmux-registry.json"
if [[ ! -f "$REGISTRY" ]]; then
  echo '{}' > "$REGISTRY"
  echo "  [ok] created empty $REGISTRY"
fi

# --- load the LaunchAgent ------------------------------------------------

# bootstrap is the modern launchctl verb; load is the legacy one.
# Some combinations of macOS + logged-in GUI session only accept one.
UID_LOCAL="$(id -u)"
launchctl bootout "gui/${UID_LOCAL}/${LABEL}" >/dev/null 2>&1 || true
launchctl bootstrap "gui/${UID_LOCAL}" "$PLIST_PATH" >/dev/null 2>&1 \
  || launchctl load "$PLIST_PATH" >/dev/null 2>&1 \
  || true

sleep 1
PORT="$(grep -o 'CLAUDE_DASHBOARD_PORT</key>[^<]*<string>[^<]*' "$PLIST_PATH" | tail -1 | grep -o '[0-9]*$' || echo 18577)"
if curl -sf "http://127.0.0.1:${PORT}/healthz" >/dev/null 2>&1; then
  echo
  echo "✓ claude-sessions is installed and the dashboard is running."
  echo "  Open:  http://127.0.0.1:${PORT}/"
  echo "  Ctl:   claude-dashboard-ctl {status|open|restart|logs}"
else
  echo
  echo "⚠  LaunchAgent loaded but HTTP health check failed."
  echo "   Try:  claude-dashboard-ctl logs"
fi

# --- PATH hint -----------------------------------------------------------

case ":${PATH}:" in
  *":${BIN_DIR}:"*)
    ;;
  *)
    echo
    echo "⚠  $BIN_DIR is not on your PATH."
    echo "   Add this to your shell rc:"
    echo "     export PATH=\"\$HOME/.local/bin:\$PATH\""
    ;;
esac
