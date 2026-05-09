#!/usr/bin/env bash
# claude-sessions uninstaller.
#
# Reverses install.sh. Removes binaries, the LaunchAgent, and the SessionStart
# hook entry from settings.json. Does NOT delete ~/.claude/cmux-registry.json
# (that's your data — remove it manually if you want).

set -euo pipefail

USER_NAME="${USER:-$(id -un)}"
HOME_DIR="${HOME}"
LABEL="com.${USER_NAME}.claude-dashboard"
PLIST_PATH="$HOME_DIR/Library/LaunchAgents/${LABEL}.plist"

echo "claude-sessions: uninstalling for user=$USER_NAME"

# --- stop and remove LaunchAgent ---------------------------------------
UID_LOCAL="$(id -u)"
launchctl bootout "gui/${UID_LOCAL}/${LABEL}" >/dev/null 2>&1 || true
launchctl unload "$PLIST_PATH" >/dev/null 2>&1 || true
[[ -f "$PLIST_PATH" ]] && rm -f "$PLIST_PATH" && echo "  [ok] removed $PLIST_PATH"

# --- remove binaries ---------------------------------------------------
for f in \
  "$HOME_DIR/.local/bin/claude-dashboard" \
  "$HOME_DIR/.local/bin/claude-dashboard-ctl" \
  "$HOME_DIR/.local/bin/cmux-resume" \
  "$HOME_DIR/.local/bin/cmux-resume-smart" \
  "$HOME_DIR/.claude/hooks/cmux-registry.py"; do
  [[ -f "$f" ]] && rm -f "$f" && echo "  [ok] removed $f"
done

# --- detach the SessionStart hook from settings.json -------------------
SETTINGS="$HOME_DIR/.claude/settings.json"
if [[ -f "$SETTINGS" ]]; then
  cp "$SETTINGS" "$SETTINGS.bak.$(date +%Y%m%d-%H%M%S)"
  python3 - "$SETTINGS" <<'PY'
import json, os, sys
p = sys.argv[1]
with open(p) as f:
    data = json.load(f)
hooks = data.get("hooks", {})
ss = hooks.get("SessionStart", [])
new = []
for entry in ss:
    kept_hooks = [h for h in entry.get("hooks", []) if "cmux-registry.py" not in h.get("command","")]
    if kept_hooks:
        entry["hooks"] = kept_hooks
        new.append(entry)
hooks["SessionStart"] = new
if not hooks["SessionStart"]:
    del hooks["SessionStart"]
tmp = p + ".tmp"
with open(tmp, "w") as f:
    json.dump(data, f, indent=2)
os.replace(tmp, p)
print("  [ok] removed SessionStart hook from settings.json")
PY
fi

echo
echo "Done. ~/.claude/cmux-registry.json was left in place; delete manually if desired."
