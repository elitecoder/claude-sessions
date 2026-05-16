#!/usr/bin/env python3
"""
seed-demo-data.py — generates a synthetic Claude session corpus into a temp
HOME directory so claude-dashboard can be screenshotted with generic content.

Writes:
  $DEMO_HOME/.claude/projects/<encoded-cwd>/<uuid>.jsonl    (sessions)
  $DEMO_HOME/.claude/cmux-registry.json                     (live workspaces)
  $DEMO_HOME/.claude/cmux-dashboard-embeddings.sqlite        (summaries+embeds)

Usage:
  python3 seed-demo-data.py [DEMO_HOME]

Default DEMO_HOME is /tmp/claude-sessions-demo. Idempotent — wipes and rewrites
on every run.
"""
import datetime
import hashlib
import json
import os
import random
import shutil
import sqlite3
import struct
import sys
import uuid

# Deterministic so reruns produce identical output.
random.seed(20260515)

DEMO_HOME = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "/tmp/claude-sessions-demo")
CLAUDE_DIR = os.path.join(DEMO_HOME, ".claude")
PROJECTS_DIR = os.path.join(CLAUDE_DIR, "projects")
REGISTRY_PATH = os.path.join(CLAUDE_DIR, "cmux-registry.json")
FAKE_WS_PATH = os.path.join(CLAUDE_DIR, "fake-workspaces.json")
EMBED_DB = os.path.join(CLAUDE_DIR, "cmux-dashboard-embeddings.sqlite")

# Provider IDs we pre-populate the sqlite for. Must match what
# claude-dashboard reads when CLAUDE_DASHBOARD_SUMMARY=ollama and
# CLAUDE_DASHBOARD_EMBED=ollama (the defaults).
SUMMARY_PROVIDER = "ollama"
SUMMARY_MODEL = "qwen2.5:1.5b-instruct"
EMBED_PROVIDER = "ollama"
EMBED_MODEL = "nomic-embed-text"
EMBED_DIM = 64  # synthetic — doesn't have to match the real model's 768

NOW = datetime.datetime(2026, 5, 15, 14, 30, 0).timestamp()

# ----- session corpus ------------------------------------------------------
#
# Each entry produces one JSONL file. Keep topics generic and open-source-y so
# screenshots don't leak any internal context. The "topic" string drives a
# tiny vector embedding so semantic search picks neighbors the way a real
# embedder would.
SESSIONS = [
    {
        "title": "Refactor onboarding flow into discrete steps",
        "cwd": "~/dev/saas-app",
        "age_min": 12,
        "topic": "react ui refactor",
        "first_user": "Split the onboarding wizard into one component per step so we can swap them out independently.",
        "last_user": "Looks good. Add a 'back' button on every step except the first.",
        "last_assistant": "Done. Each step renders inside <OnboardingShell> which now exposes prev/next as props; the first step receives prev=null which hides the back button.",
        "summary": "Broke the monolithic OnboardingWizard into one component per step under src/onboarding/steps/, threaded prev/next through OnboardingShell, and added a conditional back button. Step transitions now go through a single reducer, which made it easy to wire up the new 'skip' affordance the design team asked for.",
        "deep": [
            "I'm worried about losing form state when a user navigates back. Are we persisting it?",
            "Yes — the reducer holds the full form state in a single useReducer at OnboardingShell. Step components are stateless and read/write via dispatch. Navigation never unmounts the shell, so the state survives.",
        ],
        "live": True,
    },
    {
        "title": "Add rate limiting to the public API",
        "cwd": "~/dev/api-gateway",
        "age_min": 47,
        "topic": "backend rate limit api",
        "first_user": "We need to add per-IP rate limiting to /v1/* endpoints. 100 requests per minute should be the default.",
        "last_user": "Can you also add a header showing the remaining quota?",
        "last_assistant": "Added X-RateLimit-Remaining and X-RateLimit-Reset headers on every response. Token bucket lives in Redis under rl:{ip}:{minute} with a 60s TTL.",
        "summary": "Implemented token-bucket rate limiting on /v1/* using a Redis-backed counter keyed by (ip, minute). Returns 429 with Retry-After once the bucket is empty, and exposes X-RateLimit-Remaining + X-RateLimit-Reset on every response. Unit tests cover the boundary cases (exactly-100, 101st request, second-bucket reset).",
        "deep": [
            "Should we exempt our internal health-check IPs?",
            "Yes — added an allowlist via RATE_LIMIT_EXEMPT env var (comma-separated CIDRs). The middleware short-circuits before the Redis call when the request matches.",
        ],
    },
    {
        "title": "Track down a flaky integration test",
        "cwd": "~/dev/api-gateway",
        "age_min": 96,
        "topic": "testing flaky integration",
        "first_user": "test_checkout_creates_order has been failing about 1 in 5 runs on CI. Can you figure out why?",
        "last_user": "Nice catch. Let's add a reproducer test that always exercises that path.",
        "last_assistant": "The race was in the test setup: we seeded an Order, then immediately queried by created_at>=NOW(). When the seed and the query landed in the same millisecond, the >= sometimes lost to clock skew. Fixed by switching to id-based filtering, and added a deterministic time-travel test.",
        "summary": "Found a millisecond-precision race between the test seed and the assertion query. Replaced created_at >= NOW() with an id-based filter and added time_travel.test.ts to lock the regression in. CI flake rate dropped from ~20% to 0 over 50 reruns.",
        "deep": [
            "How are you simulating the clock?",
            "Using sinon.useFakeTimers around the seed step so the seeded row's timestamp is exactly equal to the query bound, plus one assertion at +0ms and one at +1ms.",
        ],
    },
    {
        "title": "Set up CI workflow with caching",
        "cwd": "~/dev/saas-app",
        "age_min": 180,
        "topic": "devops github actions ci",
        "first_user": "Set up a GitHub Actions workflow that lints, tests, and builds on every PR. Cache node_modules.",
        "last_user": "Make it run on macOS too so we catch path-case bugs.",
        "last_assistant": "Added a matrix with ubuntu-latest and macos-latest. Both share a single cache key keyed on package-lock hash. Build time dropped from 6m to 2m on warm cache.",
        "summary": "Added .github/workflows/ci.yml with a matrix of ubuntu-latest and macos-latest. actions/setup-node@v4 + actions/cache@v4 keyed on the lockfile hash brought warm-cache builds from ~6m down to ~2m. Lint/test/build run in parallel jobs that fan out from a single setup job.",
    },
    {
        "title": "Migrate from styled-components to CSS Modules",
        "cwd": "~/dev/saas-app",
        "age_min": 240,
        "topic": "react frontend css refactor",
        "first_user": "We're getting hit hard by styled-components' bundle size. Let's move everything to CSS Modules.",
        "last_user": "How much did the bundle shrink?",
        "last_assistant": "Total JS dropped 84 kB (gzipped). The runtime cost of styled-components on cold render is also gone — first paint improved from 1.4s to 1.1s in the lighthouse run.",
        "summary": "Ported all 142 styled() components to CSS Modules. Wrote a codemod (jscodeshift) that handled 90% of the call sites; the remaining 14 used dynamic theming and got rewritten by hand to use CSS variables. Bundle dropped 84 kB gzipped and Lighthouse first-paint improved by ~300 ms.",
    },
    {
        "title": "Wire Stripe webhook signature verification",
        "cwd": "~/dev/checkout-service",
        "age_min": 360,
        "topic": "stripe payments webhooks",
        "first_user": "We need to verify Stripe webhook signatures before processing them. Right now we trust the request body blindly.",
        "last_user": "What about replay attacks?",
        "last_assistant": "Stripe's signature includes a timestamp; I'm rejecting any event whose timestamp is more than 5 minutes off from server time. Combined with the constant-time signature check, that closes the replay window.",
        "summary": "Added stripe.webhooks.constructEvent verification at the top of /webhooks/stripe. Raw body is captured before json parsing (express.raw middleware on this route only). Rejects on signature mismatch and on timestamps older than 300s to defeat replay. Added 4 unit tests covering valid, tampered, expired, and malformed payloads.",
        "deep": [
            "How are we storing the webhook secret?",
            "STRIPE_WEBHOOK_SECRET in env, loaded via dotenv-safe. The .env.example was updated to include it as required so missing-secret crashes at boot, not at first webhook.",
        ],
    },
    {
        "title": "Optimize the user-dashboard query",
        "cwd": "~/dev/api-gateway",
        "age_min": 540,
        "topic": "sql postgres performance query",
        "first_user": "The /me/dashboard endpoint is taking 800ms p95. It's hitting Postgres with what looks like a single big query — can you take a look?",
        "last_user": "Down to 40ms? Beautiful.",
        "last_assistant": "EXPLAIN showed a sequential scan over `events` (12M rows). Added a partial index on (user_id, created_at DESC) WHERE archived=false; planner picks it up immediately. p95 went from 800ms to 38ms.",
        "summary": "Profiled /me/dashboard; the bottleneck was a sequential scan over events (12M rows, only ~2% non-archived). Added a partial index on (user_id, created_at DESC) WHERE archived=false. p95 dropped from 800ms to ~40ms. Documented the index in db/migrations/2026-04-22_events_active_idx.sql.",
        "live": True,
    },
    {
        "title": "Build a tiny log-tail CLI in Go",
        "cwd": "~/dev/tools/logtail",
        "age_min": 720,
        "topic": "go cli tool",
        "first_user": "I want a single-file Go CLI that tails our JSON logs and pretty-prints them with color by level. Like pino-pretty but for our format.",
        "last_user": "Add a --grep flag so I can filter inline.",
        "last_assistant": "Added --grep that compiles a Go regexp and skips any line whose .msg field doesn't match. Throughput stays at ~50k lines/s on my M2.",
        "summary": "Wrote logtail.go (~180 LOC, single file, stdlib-only) that decodes our JSON log format and prints level-colored lines. Supports --grep with regexp filtering on the .msg field, --since for cutoff, and --follow that opens the file in O_RDONLY and seeks to end. Benchmarked at ~50k lines/s on M2.",
    },
    {
        "title": "Fix the race condition in worker pool",
        "cwd": "~/dev/job-runner",
        "age_min": 1080,
        "topic": "concurrency goroutine race",
        "first_user": "go test -race is flagging a data race in pool.go between Submit and Close. Help me fix it.",
        "last_user": "Confirmed clean under -race for 1000 iterations. Thanks.",
        "last_assistant": "The bug was that Submit read pool.closed without holding the mutex. Restructured Close to swap the channel under the mutex and have Submit re-check after acquiring the lock. -race is clean.",
        "summary": "Diagnosed a Submit/Close data race in pool.go via go test -race. Fix was to hold pool.mu while reading pool.closed in Submit and to do the channel-swap in Close while holding the same mutex. Added a stress test that fires 10k concurrent Submits with one Close mid-stream; passes 1000 iterations under -race cleanly.",
    },
    {
        "title": "Generate OpenAPI spec from controllers",
        "cwd": "~/dev/api-gateway",
        "age_min": 1440,
        "topic": "openapi rest api documentation",
        "first_user": "Can we auto-generate an OpenAPI 3.1 spec from our controller decorators? Right now openapi.yaml is hand-edited and drifts.",
        "last_user": "Diff against the hand-edited file?",
        "last_assistant": "openapi.diff.yaml shows what changed: 14 endpoints we'd missed entirely, 8 with wrong response codes, 3 with stale schemas. The generated version is the new source of truth — committing it now.",
        "summary": "Built scripts/gen-openapi.ts that walks the controllers, reads the @Route + @Body decorators, and emits an OpenAPI 3.1 document. Replaced the hand-edited openapi.yaml; the diff caught 25 drift bugs that had accumulated over 6 months. CI now runs the generator and fails the PR if openapi.yaml is out of sync.",
    },
    {
        "title": "Stand up Postgres replication on staging",
        "cwd": "~/work/infra",
        "age_min": 2160,
        "topic": "postgres infra replication",
        "first_user": "Set up streaming replication from our staging primary to a read replica. We want lag-tolerant analytics queries to land on the replica.",
        "last_user": "Lag under 1s on a 2vCPU replica is great.",
        "last_assistant": "Configured WAL streaming, primary_slot_name=replica1, hot_standby=on. Tested under a 5k-row/s synthetic load and replication lag stayed at ~600ms p95.",
        "summary": "Stood up streaming replication from staging-pg-primary to staging-pg-replica1 using a replication slot (replica1). Configured wal_level=replica, max_wal_senders=10, hot_standby=on. Verified replication lag stays under 1s p95 under 5k-row/s synthetic load. Documented the failover runbook in docs/ops/postgres-replica.md.",
    },
    {
        "title": "Write E2E tests for the checkout flow",
        "cwd": "~/dev/checkout-service",
        "age_min": 2880,
        "topic": "playwright e2e checkout",
        "first_user": "Write Playwright tests covering the happy path of checkout: add to cart, enter shipping, pay with test card, see receipt.",
        "last_user": "Can you also test the 3DS challenge path?",
        "last_assistant": "Added a second spec that uses Stripe's 4000002500003155 test card to trigger the 3DS modal, completes the challenge, and verifies the order lands in 'requires_capture' before the webhook completes it.",
        "summary": "Added e2e/checkout-happy.spec.ts covering add-to-cart → shipping → Stripe test-card → receipt. Added e2e/checkout-3ds.spec.ts that exercises the 3DS challenge path with Stripe's 4000002500003155 test card and asserts the order reaches 'requires_capture' before transitioning to 'paid' on webhook delivery.",
    },
    {
        "title": "Implement dark mode toggle",
        "cwd": "~/dev/saas-app",
        "age_min": 4320,
        "topic": "ui theming dark mode css",
        "first_user": "Implement a dark-mode toggle. It should respect prefers-color-scheme on first load, then remember the user's choice in localStorage.",
        "last_user": "Make sure server-rendered HTML doesn't flash light-mode before the JS picks up.",
        "last_assistant": "Added a tiny inline script in <head> that reads the cookie and sets data-theme on <html> before paint. The flash is gone — verified via slow-network throttle.",
        "summary": "Added a ThemeProvider that resolves theme = (cookie || prefers-color-scheme), persists changes to a 1-year cookie, and exposes a toggle. To prevent FOUC, an inline script in <head> sets data-theme on <html> before stylesheets load — verified flash-free under 6x CPU + Slow 3G throttling.",
    },
    {
        "title": "Reduce frontend bundle size",
        "cwd": "~/dev/saas-app",
        "age_min": 6480,
        "topic": "webpack bundle size performance",
        "first_user": "Our JS bundle is 2.4 MB minified, 720 kB gzipped. I want to get it under 1 MB minified before launch.",
        "last_user": "1.1 MB → 780 kB gzipped. Ship it.",
        "last_assistant": "Final tally: 2.4 MB → 1.1 MB minified. Biggest wins were lodash (full → lodash-es + babel-plugin-lodash, -180 kB), moment → date-fns (-280 kB), and route-level code-splitting on the dashboard tree (-340 kB).",
        "summary": "Cut the production bundle from 2.4 MB to 1.1 MB minified (720 kB → 470 kB gzipped). Top wins: lodash → lodash-es with babel-plugin-lodash (-180 kB), moment → date-fns (-280 kB), route-level code-splitting on the dashboard tree (-340 kB). Added webpack-bundle-analyzer to CI as a budget gate so this doesn't silently regress.",
    },
    {
        "title": "Add structured logging with pino",
        "cwd": "~/dev/api-gateway",
        "age_min": 8640,
        "topic": "logging observability node",
        "first_user": "We're console.log-ing in 60 places and our log aggregator can't parse any of it. Let's adopt pino across the service.",
        "last_user": "Looks great in Grafana.",
        "last_assistant": "Replaced all console.* with a pino logger that emits NDJSON. Request id flows through via async-local-storage so every log line is auto-tagged with reqId, method, route. Grafana parses the stream natively now.",
        "summary": "Adopted pino across api-gateway. Replaced ~60 console.* calls and added a request-scoped child logger via async-local-storage so reqId, method, and route appear automatically on every line. Pretty-printed in dev, NDJSON in prod. Grafana Loki picks up the structure natively now, which unlocked the 'errors by route' panel.",
    },
    {
        "title": "Refactor error boundaries in the dashboard",
        "cwd": "~/dev/saas-app",
        "age_min": 11520,
        "topic": "react error boundary",
        "first_user": "When one widget on the dashboard throws, the whole page goes white. Wrap each widget in its own error boundary so a single failure stays contained.",
        "last_user": "Test it by throwing in one of them?",
        "last_assistant": "Added a deliberate throw in <RecentActivity /> and confirmed only that tile shows the fallback; the other 6 keep rendering. Sentry captures the original error with a 'widget' tag so we can see which one failed.",
        "summary": "Wrapped every dashboard widget in a <WidgetBoundary name='...'> that catches render errors and shows a small inline 'reload' fallback. Sentry receives each error tagged with widget=<name>, so the alert tells us which tile blew up without us having to grep the stack. Verified containment by deliberately throwing in <RecentActivity />.",
    },
    {
        "title": "Hook up Google OAuth login",
        "cwd": "~/dev/saas-app",
        "age_min": 17280,
        "topic": "oauth google authentication login",
        "first_user": "Add 'Sign in with Google' alongside the existing email/password form. Use NextAuth.",
        "last_user": "What scopes are we asking for?",
        "last_assistant": "Just openid, email, profile. Anything more would feel intrusive for a sign-in flow. The user record is keyed on the Google sub claim so account linking by email isn't a vulnerability.",
        "summary": "Added Google as a NextAuth provider alongside Credentials. Scopes are openid + email + profile only. Account records are keyed on the Google sub claim (not the email), which closes the account-linking-by-email attack class. Wrote a migration that adds users.google_sub UNIQUE and a backfill plan for existing email-only accounts.",
    },
    {
        "title": "Cache invalidation for the product catalog",
        "cwd": "~/dev/api-gateway",
        "age_min": 25920,
        "topic": "cache redis invalidation backend",
        "first_user": "Stale prices in the catalog are causing customer complaints. Design a cache-invalidation strategy that's tolerant of admin edits.",
        "last_user": "Tagging-based invalidation is exactly what I had in mind.",
        "last_assistant": "Implemented tag-based invalidation: every cache entry stores its tag set, and admin writes publish to a 'catalog:tags' pubsub channel. Subscribers on each app server drop matching keys. Stale-on-error means a Redis blip falls back to cached data instead of erroring.",
        "summary": "Designed and shipped tag-based cache invalidation for the product catalog. Each cache entry stores its tag set (sku, category, vendor); admin writes publish a tag-invalidation event over Redis pubsub, and every app server's subscriber drops matching keys locally. Stale-on-error means a Redis outage falls back to cached data rather than erroring the whole catalog page.",
    },
    {
        "title": "Investigate memory leak in image processor",
        "cwd": "~/dev/media-pipeline",
        "age_min": 34560,
        "topic": "memory leak debugging node",
        "first_user": "The image-processor worker's RSS climbs from 200 MB to 4 GB over ~6 hours and OOMs. Help me find the leak.",
        "last_user": "Heap snapshot diffing was the right call. Thanks.",
        "last_assistant": "Two leaks: (1) a Map<requestId, Buffer> in the queue ack path that was set on enqueue but only deleted on success (errors leaked the entry), (2) sharp() instances we forgot to .destroy() on the failure path. Plugged both, RSS is flat at 240 MB over 24 hours now.",
        "summary": "Tracked down two memory leaks in image-processor by diffing heap snapshots taken 30 min apart under load. (1) An ack-tracking Map was only cleaned up on success; errors leaked entries. (2) sharp() instances on the error path weren't .destroy()'d. After both fixes, RSS is flat at 240 MB over 24h, down from a 200MB → 4GB OOM curve every 6h.",
    },
    {
        "title": "Migrate build system from webpack to Vite",
        "cwd": "~/dev/saas-app",
        "age_min": 43200,
        "topic": "vite webpack build tooling",
        "first_user": "Cold dev startup is at 28 seconds. Try porting to Vite and see if we can get it under 3.",
        "last_user": "Cold start is 1.4s now. Done.",
        "last_assistant": "Cold dev start: 28s → 1.4s. Production build: 90s → 22s. The hard part was our 14 webpack-only loaders; rewrote 6 as Vite plugins, dropped 5, and replaced 3 with native ESM imports. All e2e tests still green.",
        "summary": "Ported the build pipeline from webpack 5 to Vite 5. Cold dev start went from 28s to 1.4s; production builds from 90s to 22s. Rewrote 6 webpack-only loaders as Vite plugins, dropped 5 that were no longer needed (CSS Modules, asset URLs, env injection are all native in Vite), and replaced 3 with plain ESM imports. All E2E specs still green.",
    },
]


def encode_cwd(cwd):
    """Mirror Claude Code's project-dir naming: replace / with -."""
    expanded = cwd.replace("~", os.path.expanduser("~"))
    # Mirror what real Claude Code does: substitute path separators with -.
    return expanded.replace("/", "-")


def iso(ts):
    return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def write_jsonl(path, sess_id, cwd, age_seconds, ai_title, first_user, last_user, last_assistant, deep_pairs):
    """Write one synthetic Claude session JSONL.

    Layout matches what real Claude Code writes: each line is a JSON event
    with a `type` (user, assistant, ai-title) and a `message.content`
    string or list-of-text-blocks. claude-dashboard reads through these in
    order, so we order them so the parser picks first/last/title correctly.
    """
    end_ts = NOW - 5  # last assistant reply 5s before now (relative to age)
    start_ts = end_ts - age_seconds
    lines = []

    # ai-title line first.
    lines.append({"type": "ai-title", "aiTitle": ai_title, "sessionId": sess_id})

    # First user prompt.
    parent = str(uuid.uuid4())
    fu_uuid = str(uuid.uuid4())
    lines.append({
        "parentUuid": None,
        "isSidechain": False,
        "type": "user",
        "message": {"role": "user", "content": first_user},
        "uuid": fu_uuid,
        "timestamp": iso(start_ts),
        "userType": "external",
        "cwd": cwd.replace("~", os.path.expanduser("~")),
        "sessionId": sess_id,
    })

    # Optional deep-search-only pairs sandwiched in the middle.
    last_uuid = fu_uuid
    t = start_ts + 30
    for i in range(0, len(deep_pairs), 2):
        u_uuid = str(uuid.uuid4())
        lines.append({
            "parentUuid": last_uuid,
            "isSidechain": False,
            "type": "user",
            "message": {"role": "user", "content": deep_pairs[i]},
            "uuid": u_uuid,
            "timestamp": iso(t),
            "userType": "external",
            "cwd": cwd.replace("~", os.path.expanduser("~")),
            "sessionId": sess_id,
        })
        t += 8
        if i + 1 < len(deep_pairs):
            a_uuid = str(uuid.uuid4())
            lines.append({
                "parentUuid": u_uuid,
                "isSidechain": False,
                "type": "assistant",
                "message": {"role": "assistant", "content": [{"type": "text", "text": deep_pairs[i + 1]}]},
                "uuid": a_uuid,
                "timestamp": iso(t),
                "sessionId": sess_id,
            })
            last_uuid = a_uuid
            t += 12

    # Last user prompt.
    lu_uuid = str(uuid.uuid4())
    lines.append({
        "parentUuid": last_uuid,
        "isSidechain": False,
        "type": "user",
        "message": {"role": "user", "content": last_user},
        "uuid": lu_uuid,
        "timestamp": iso(end_ts - 8),
        "userType": "external",
        "cwd": cwd.replace("~", os.path.expanduser("~")),
        "sessionId": sess_id,
    })

    # Last assistant reply.
    lines.append({
        "parentUuid": lu_uuid,
        "isSidechain": False,
        "type": "assistant",
        "message": {"role": "assistant", "content": [{"type": "text", "text": last_assistant}]},
        "uuid": str(uuid.uuid4()),
        "timestamp": iso(end_ts),
        "sessionId": sess_id,
    })

    with open(path, "w") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")

    # Backdate the file's mtime so the dashboard's "age" is correct.
    os.utime(path, (end_ts, end_ts))


def content_hash(text):
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def summary_chash(s, provider, model):
    """Mirror _summary_chash_cheap in claude-dashboard.

    Hash inputs: 'sum\\n{provider}\\n{model}\\n{title}\\n{first_user}\\n{last_user}\\n{last_assistant}'.
    Stays in sync with bin/claude-dashboard:_summary_chash_cheap.
    """
    sig = f"sum\n{provider}\n{model}\n{s['ai_title']}\n{s['first_user']}\n{s['last_user']}\n{s['last_assistant']}"
    return content_hash(sig)


def embed_doc_chash(s, summary):
    """Mirror _embed_doc_for in claude-dashboard. Summary first, then title,
    first_user, last_user, last_assistant."""
    parts = []
    if summary:
        parts.append(summary)
    parts.append(s["ai_title"])
    parts.append(s["first_user"])
    if s["last_user"] != s["first_user"]:
        parts.append(s["last_user"])
    parts.append(s["last_assistant"])
    text = "\n".join(parts)
    if len(text) > 4000:
        text = text[:4000]
    return content_hash(text)


# Topic-token vocabulary for the synthetic embedder. Each session's "topic"
# string maps onto a small bag of unit-vector axes; cosine similarity between
# two sessions is then driven by their shared tokens. Good enough that
# "concurrency bug" pulls "race condition", "stripe payment" pulls
# "checkout flow", etc.
TOPIC_AXES = {}


def embed_for_topic(topic, query=False):
    """Return a deterministic 64-d float vector for a topic string. Tokens
    in the topic are projected to fixed axes; vector is L2-normalized."""
    vec = [0.0] * EMBED_DIM
    tokens = topic.lower().split()
    for tok in tokens:
        if tok not in TOPIC_AXES:
            # Hash the token to a stable axis index. Spread across the 64 dims.
            h = int.from_bytes(hashlib.sha256(tok.encode()).digest()[:4], "little")
            TOPIC_AXES[tok] = h % EMBED_DIM
        idx = TOPIC_AXES[tok]
        vec[idx] += 1.0
    norm = sum(x * x for x in vec) ** 0.5
    if norm > 0:
        vec = [x / norm for x in vec]
    return vec


def main():
    if os.path.exists(CLAUDE_DIR):
        shutil.rmtree(CLAUDE_DIR)
    os.makedirs(PROJECTS_DIR, exist_ok=True)

    # Database — schema mirrors what claude-dashboard creates on first run.
    conn = sqlite3.connect(EMBED_DB)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS embeddings (
            provider TEXT NOT NULL,
            model    TEXT NOT NULL,
            chash    TEXT NOT NULL,
            dim      INTEGER NOT NULL,
            vec      BLOB NOT NULL,
            PRIMARY KEY (provider, model, chash)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            sess     TEXT PRIMARY KEY,
            mtime    REAL NOT NULL,
            chash    TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS summaries (
            provider TEXT NOT NULL,
            model    TEXT NOT NULL,
            chash    TEXT NOT NULL,
            summary  TEXT NOT NULL,
            PRIMARY KEY (provider, model, chash)
        )
    """)

    registry = {}
    fake_workspaces = {}
    # Add a few "decoy" workspaces (no Claude session) so the workspace
    # picker dropdown looks non-trivial in screenshots.
    for title in ("Inbox triage", "Open PRs", "release-notes scratch"):
        fake_workspaces[str(uuid.uuid4())] = {"title": title, "ref": "", "selected": False}
    for s in SESSIONS:
        sess_id = str(uuid.uuid4())
        s["sess"] = sess_id
        encoded = encode_cwd(s["cwd"])
        proj_dir = os.path.join(PROJECTS_DIR, encoded)
        os.makedirs(proj_dir, exist_ok=True)
        path = os.path.join(proj_dir, f"{sess_id}.jsonl")
        age_seconds = s["age_min"] * 60
        write_jsonl(
            path,
            sess_id,
            s["cwd"],
            age_seconds,
            s["title"],
            s["first_user"],
            s["last_user"],
            s["last_assistant"],
            s.get("deep") or [],
        )
        # Stash for the sqlite seeding pass.
        s["jsonl_path"] = path

        # Register a couple of sessions as live so the green border + workspace
        # picker have content to point at.
        if s.get("live"):
            ws_id = str(uuid.uuid4()).upper()
            registry[ws_id] = {
                "session_id": sess_id,
                "cwd": s["cwd"].replace("~", os.path.expanduser("~")),
                "ts": iso(NOW - age_seconds),
            }
            # Mirror into fake-workspaces.json so the run-demo-dashboard.py
            # monkey-patched live_workspaces() reports them as alive.
            fake_workspaces[ws_id] = {
                "title": s["title"][:40],
                "ref": "",
                "selected": False,
            }

    # Pre-fill the summaries table so cards show summaries on first paint
    # without a live Ollama call. Same key shape as claude-dashboard expects.
    for s in SESSIONS:
        # Map our parsed-session shape onto the dashboard's parsed shape.
        parsed = {
            "ai_title": s["title"],
            "first_user": s["first_user"],
            "last_user": s["last_user"],
            "last_assistant": s["last_assistant"],
        }
        chash = summary_chash(parsed, SUMMARY_PROVIDER, SUMMARY_MODEL)
        conn.execute(
            "INSERT OR REPLACE INTO summaries (provider, model, chash, summary) VALUES (?,?,?,?)",
            (SUMMARY_PROVIDER, SUMMARY_MODEL, chash, s["summary"]),
        )

    # Pre-fill embeddings so semantic search works immediately. We cover all
    # but the last 3 sessions so the indexing pill / "missing N sessions"
    # banner has something to display in the screenshot for that flow.
    sessions_to_embed = SESSIONS[:-3]
    for s in sessions_to_embed:
        parsed = {
            "ai_title": s["title"],
            "first_user": s["first_user"],
            "last_user": s["last_user"],
            "last_assistant": s["last_assistant"],
        }
        chash = embed_doc_chash(parsed, s["summary"])
        vec = embed_for_topic(s["topic"])
        blob = struct.pack(f"{len(vec)}f", *vec)
        conn.execute(
            "INSERT OR REPLACE INTO embeddings (provider, model, chash, dim, vec) VALUES (?,?,?,?,?)",
            (EMBED_PROVIDER, EMBED_MODEL, chash, len(vec), blob),
        )

    conn.commit()
    conn.close()

    with open(REGISTRY_PATH, "w") as f:
        json.dump(registry, f, indent=2)
    with open(FAKE_WS_PATH, "w") as f:
        json.dump(fake_workspaces, f, indent=2)

    print(f"seeded {len(SESSIONS)} sessions into {DEMO_HOME}")
    print(f"  registry entries (live workspaces): {len(registry)}")
    print(f"  summaries cached: {len(SESSIONS)}")
    print(f"  embeddings cached: {len(sessions_to_embed)} of {len(SESSIONS)} (3 left for indexing-pill demo)")


if __name__ == "__main__":
    main()
