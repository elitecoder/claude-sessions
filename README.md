# claude-sessions

A small macOS toolkit for anyone running [Claude Code](https://www.claude.com/product/claude-code) inside [cmux](https://cmux.com):

- **A browser dashboard** listing every Claude Code session you've ever had, with AI-written titles, last prompt, last reply, and one-click "Resume in new workspace" or "Resume into this existing workspace".
- **A SessionStart hook** that quietly records which cmux workspace each Claude session is running in, so the dashboard always knows which sessions are live vs. idle.
- **Two terminal pickers** (`cmux-resume`, `cmux-resume-smart`) for the same job without leaving the shell.

Built because cmux closes all Claude sessions on quit, and `claude --resume` only resumes the *most recent* session per directory — unusable if you're running five sessions in the same repo at once.

## What the dashboard looks like

- Cards grouped in a responsive grid, dark UI.
- Each card shows: AI-written title (Claude writes these automatically during a session — we just pick them up), age, message count, `cwd`, kickoff prompt, last user prompt, last assistant reply.
- **Resume in new workspace** → creates a fresh cmux workspace at the session's original cwd, runs `claude --resume <id>`, renames the workspace to the AI title.
- **Resume in existing workspace** (via dropdown) → respawns the focused pane of any live workspace you pick, replacing whatever was there. Amber-tinted confirm dialog if that workspace is already running a Claude session.
- Auto-refreshes every 10s. Countdown pill in the bottom-left, click to refresh now.

## Install (macOS)

```bash
git clone https://github.com/elitecoder/claude-sessions.git
cd claude-sessions
./install.sh
```

That's it. The installer:

1. Copies the scripts to `~/.local/bin/`.
2. Copies the SessionStart hook to `~/.claude/hooks/cmux-registry.py`.
3. Renders `launchd/com.USER.claude-dashboard.plist.template` into `~/Library/LaunchAgents/com.$USER.claude-dashboard.plist` with your user/home baked in.
4. Adds one entry to `~/.claude/settings.json` → `hooks.SessionStart[]` (non-destructive; skipped if already present). Backs up settings.json first.
5. Loads the LaunchAgent so the dashboard starts now *and* auto-starts at login.
6. Opens `http://127.0.0.1:18577/healthz` to verify.

Then open the dashboard:

```bash
claude-dashboard-ctl open
```

If `~/.local/bin` isn't on your PATH, the installer prints a hint.

## Requirements

- macOS (for `launchd`; the dashboard itself is cross-platform, but the installer isn't).
- Python 3 (stdlib only — no pip install).
- [cmux](https://cmux.com) — technically optional (the dashboard will still render), but Resume buttons need it.
- [Claude Code](https://www.claude.com/product/claude-code) — these tools work against session files written by Claude Code at `~/.claude/projects/*/*.jsonl`.

## How it works

### The SessionStart hook (`hooks/cmux-registry.py`)

Claude Code fires a `SessionStart` event every time a session starts (both `startup` and `resume` sources). The hook reads Claude's JSON payload from stdin plus a few `CMUX_*` env vars that cmux auto-injects into every pane, and appends one entry per workspace to `~/.claude/cmux-registry.json`:

```json
{
  "<cmux-workspace-uuid>": {
    "session_id": "...",
    "cwd": "/Users/me/dev/…",
    "ts": 1778204253
  }
}
```

The hook is idempotent — re-running in the same workspace overwrites the entry. It fails silently if anything goes wrong; hooks must never break Claude itself.

### The dashboard (`bin/claude-dashboard`)

A ~500-line Python stdlib HTTP server on `127.0.0.1:18577`:

- `GET /` — the dashboard HTML (client-side polling, no SSE, no deps).
- `GET /api/sessions` — returns every session from `~/.claude/projects/*/*.jsonl`, parsed for `ai-title` records, first/last user message, last assistant message, cwd. Cross-referenced with the registry so "active" sessions can be flagged or filtered.
- `POST /api/resume` — `{session_id, cwd, title, workspace_id?}`. If `workspace_id` is supplied, runs `cmux respawn-pane` against that workspace's terminal surface. Otherwise runs `cmux new-workspace` at the cwd. Either way, renames the workspace to the title and focuses it.
- `GET /healthz` — `{"ok": true}`.

Nothing listens on the public network — `127.0.0.1` only.

### The launchd agent

Renders from `launchd/com.USER.claude-dashboard.plist.template` at install time. `KeepAlive=true`, `RunAtLoad=true`, `ThrottleInterval=5`. Logs at `~/Library/Logs/claude-dashboard/{out,err}.log`.

### The terminal pickers (`bin/cmux-resume*`)

For when you don't want to open a browser:

- `cmux-resume` — simple picker. Lists recent sessions, you pick a number, runs `claude --resume <id>` in the current terminal via `exec`. Hides sessions currently active in a live cmux workspace (use `--all` to see everything).
- `cmux-resume-smart` — registry-aware. If you run it from a workspace that already has a registered Claude session, offers to resume that one directly. Falls back to the picker otherwise.

## Configuration

- Port — export `CLAUDE_DASHBOARD_PORT` before running the daemon. (The installer plist hardcodes `18577`; edit the plist or re-run install.sh after changing it.)
- Max sessions shown in the dashboard — `CLAUDE_DASHBOARD_MAX` (default 60).
- Everything else is zero-config. No settings file to maintain.

## Uninstall

```bash
./uninstall.sh
```

Removes the binaries, LaunchAgent, and the hook entry from `settings.json`. Leaves `~/.claude/cmux-registry.json` alone — delete manually if you want.

## What this does NOT do

- Does not modify Claude Code's own session files. Read-only.
- Does not proxy or intercept Claude's network traffic. The dashboard reads JSONL files on disk.
- Does not start/stop Claude — only cmux workspaces. When you click Resume, cmux runs `claude --resume <id>` as if you'd typed it in a terminal.
- Does not persist any data beyond `~/.claude/cmux-registry.json` (a simple workspace→session map).

## Known quirks

- **Pre-existing sessions are not in the registry** until they go through their next `SessionStart` (e.g., via `/clear` or `--resume`). Until then, they'll show as "idle" in the dashboard even if they're actually running. Click Resume anyway — it creates a fresh workspace with the session, and the old one can be closed.
- **`cmux respawn-pane` is destructive.** If you pick "Resume into <existing workspace>" against a workspace already running a Claude session, that session's process gets killed. The UI warns with amber styling and a confirm dialog, but if you click through: it's gone (the JSONL is still on disk; resume it in a new workspace).
- **Workspaces with no terminal surface** (e.g., browser-only workspaces) can't be targeted. The API returns an error that surfaces as a red toast in the UI.

## License

Apache 2.0. See `LICENSE`.
