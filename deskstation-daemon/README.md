# deskstation-daemon

Python asyncio daemon — host side of the Deskstation system. Talks to ESP32 firmware over USB CDC (`/dev/ttyACM0`).

## Quick start

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/) (one-time: `pipx install uv` or `curl -LsSf https://astral.sh/uv/install.sh | sh`).

```bash
cd deskstation-daemon

# Install deps and create venv
uv sync --all-extras

# Run tests
uv run pytest -v

# Type check + lint
uv run mypy src/
uv run ruff check src/ tests/

# Run the daemon (requires ESP32 plugged into /dev/ttyACM0)
cp config.yaml.example config.yaml
uv run deskstation
```

For development without a connected ESP32:

```bash
# Switch to mock bridge in config.yaml: bridge.mode = mock
uv run deskstation
```

## Logs

`~/.local/share/deskstation/logs/daemon.jsonl` (one JSON event per line, rotated at 10 MB × 3).

## Layout

- `src/deskstation/bridge/` — serial transport, protocol models, heartbeat
- `src/deskstation/main.py` — asyncio entry, wires it all
- `tests/` — pytest, headless (no ESP needed thanks to MockBridge)

## Configuring real integrations (M4)

M4 adds live Jira + Bitbucket pollers. Until you fill in credentials and enable them, the M2 mocks for Sprint Board and PR Board keep running.

### Secrets file

Live in `~/.config/deskstation/secrets.yaml` (mode `0600` — the daemon logs a warning if the file is more permissive):

```yaml
jira:
  base_url: "https://your-domain.atlassian.net"
  email: "you@example.com"
  api_token: "ATATT3..."  # https://id.atlassian.com/manage-profile/security/api-tokens
bitbucket:
  workspace: "your-workspace"
  email: "you@example.com"
  api_token: "ATBB..."  # https://bitbucket.org/account/settings/app-passwords/ (App password with Pull Requests: Read + Pipelines: Read)
  username: "your-bb-nickname"  # optional; falls back to email local-part if absent
```

Then:

```bash
chmod 600 ~/.config/deskstation/secrets.yaml
```

### Config

Two new sections in `config.yaml`:

```yaml
jira:
  project_key: "DEV"           # your "lead project" — drives the sprint query
  poll_interval_sec: 60.0
  enabled: true
bitbucket:
  workspace: "your-workspace"  # must match secrets.bitbucket.workspace
  repos:
    - "service-a"
    - "service-b"
  poll_interval_sec: 60.0
  enabled: true
```

### Behavior

- The real poller is **skipped** (and the M2 mock for that screen keeps running) when any of these is true:
  - the corresponding secrets block is missing,
  - `enabled: false`,
  - for Jira: `project_key` is empty,
  - for Bitbucket: `repos` is empty.
- The pomodoro `stop_with_log` action automatically posts a Jira worklog when a real Jira client is configured.
- On a transient Jira/Bitbucket error, the daemon shows the last successful values (cached at `~/.local/share/deskstation/state/api_cache.sqlite3`) until the next successful poll.
- On an auth error (401/403), the poller short-circuits and stops calling the API until the daemon is restarted. Look for `jira_poller_auth_failed` / `bitbucket_poller_auth_failed` log lines.

### Verifying setup

1. Start the daemon: `cd deskstation-daemon && uv run deskstation`.
2. Watch the JSONL log: `tail -f ~/.local/share/deskstation/logs/daemon.jsonl`.
3. Look for `mocks_skip_applied` — confirms the real pollers replaced the M2 mocks.
4. After ~60s, watch for `jira_request` / `bitbucket_request` events.

## Configuring Google integrations (M5)

M5 adds live Gmail, Google Chat, Google Calendar pollers plus a freedesktop dbus notification listener. They feed a single `screen_2` view through a merger (priority: dbus > gmail > gchat) and populate `screen_1.next_meeting`. Until you complete the OAuth dance and enable each source, the M2 mock for Comms keeps running.

### One-time OAuth setup

1. Create (or reuse) a Google Cloud project at <https://console.cloud.google.com/>.
2. Enable **Gmail API**, **Chat API**, **Calendar API** in the GCP console.
3. Configure the OAuth consent screen — both **Internal** (Workspace org) and **External** (personal account) work for a desktop client. Add yourself as a test user if you pick **External**.
4. Create an OAuth client of type **Desktop application**. Download the JSON.
5. Save it to `~/.config/deskstation/google_client.json` and lock the mode down:

   ```bash
   chmod 600 ~/.config/deskstation/google_client.json
   ```

6. Run the one-shot auth helper — it opens a browser, completes the consent flow, and writes `~/.config/deskstation/google_token.json`:

   ```bash
   cd deskstation-daemon
   uv run deskstation auth-google
   ```

   The daemon also logs `google_oauth_not_configured` on startup if `google_client.json` exists but the token is missing — that's the same hint to run the helper.

### Config additions in `config.yaml`

```yaml
gmail:
  enabled: true
  poll_interval_sec: 60.0
gchat:
  enabled: true
  my_email: "you@example.com"  # used for @-mention detection
  poll_interval_sec: 60.0
calendar:
  enabled: true
  near_interval_sec: 60.0       # polling cadence when next meeting < 30 min
  far_interval_sec: 300.0
  near_window_sec: 1800
dbus:
  enabled: true
  app_name_patterns:
    - "WhatsApp*"
    - "Messenger*"
    - "Slack*"
  buffer_size: 32
```

### Smoke tests

- **dbus**: `notify-send -a "WhatsApp Web" "Test" "hello"` — should appear on `screen_2` within ~1 s.
- **Gmail**: send yourself an email; watch the JSONL log (`tail -f ~/.local/share/deskstation/logs/daemon.jsonl`) for `gmail_request` events. The new notification should appear within `poll_interval_sec`.
- **Calendar**: create a Google Meet event for "now + 5 min"; watch `screen_1` for the meeting bar to appear.
- **Tap a notification** on the device — should trigger `xdg-open` on the host with the relevant Gmail / Chat / Meet URL.

### Troubleshooting

- `dbus_listener_unavailable` log line → the session bus refused the monitoring request; restart your session or check the policy in `/etc/dbus-1/session.conf`. The daemon keeps running with dbus disabled.
- `gmail_request_failed status=403` (or `401`) log line → the OAuth token may need to be re-issued. Re-run `uv run deskstation auth-google`.
- A notification tap doesn't trigger `xdg-open` → check the `id` is still in scope. The merger caps at 16 items and prunes older entries on every update; a notification id stops resolving once it's been evicted.

## M6 — Todo, macros, standup, reminders, weather, Claude usage

M6 layers six new sources on top of M5. Everything is opt-in via `config.yaml`; with no config the daemon behaves exactly like the M5 build.

- **Weather** (`weather.enabled: true` + latitude/longitude) — patches the top bar
  every 15 min via the keyless OpenMeteo `/v1/forecast` endpoint (no API key
  needed). WMO code → emoji icon mapping; temperature rounds to an integer °C.
- **Claude usage** (`claude_usage.enabled: true`) — shells out to the configured
  argv (default `["ccusage", "--json"]`) every 5 min and parses out today's spend
  for the top bar. Auto-disables (logs once) on missing binary so the daemon
  doesn't spam logs on hosts without `ccusage` installed.
- **Todo file** (`todo.enabled: true` + `todo.path`) — `watchdog` reparses the
  Markdown file on every save and pushes `screen_4`. Tapping a checkbox on the
  device round-trips through `todo_clicked` → `TodoFileListener.toggle` →
  in-place rewrite. The rewrite is bytes-level so indent and Windows CRLF line
  endings survive untouched.
- **Macros** (`macros.enabled: true` + `macros.definitions`) — each macro has an
  `id`, `label`, `icon`, and an argv list. The firmware can only invoke macros
  **by `id`** (no argv injection from the ESP). Commands run sequentially with
  `shell=False` and a per-command timeout (`macros.timeout_sec`, default 10 s);
  a non-zero rc is logged but execution continues to the next command. A bad
  binary (e.g. `FileNotFoundError`) is also logged-and-skipped, never raised.
- **Standup brief** (`standup.enabled: true` + `standup.repos`) — on a
  `standup_request` event from the panel, builds a 24 h brief from Jira (issues
  resolved by the current user in the last 24 h), Bitbucket (PRs you merged in
  the last 24 h), and `git log --author=<email>` across the configured local
  repos. Pushes a `fullscreen{kind=standup}` snapshot. The git command has its
  own 10 s timeout so a hung repo can't park the dispatch handler. Each source
  failure is isolated via `asyncio.gather(return_exceptions=True)` so one dead
  source doesn't blank the brief.
- **Reminders** (`reminders.enabled: true`) — water/eyes alternating fullscreen
  every `reminders.interval_sec` (default 25 min) **while pomodoro is idle**.
  Silent during active/paused/break states (the break overlay already covers
  those).

### M6.1 top-bar source dispatch

When `weather.enabled` or `claude_usage.enabled` is true, the daemon swaps the
M2 mock `TopBarPoller` for a real `ClockPoller` (minute-resolution clock + date)
and uses dedicated per-field setters (`UIState.set_weather`,
`set_claude_usage`, `set_clock`) so the three sources can patch the top bar
independently without clobbering one another.

### Config snippet

```yaml
weather:
  enabled: true
  latitude: 52.23
  longitude: 21.01
  poll_interval_sec: 900
claude_usage:
  enabled: true
  command: ["ccusage", "--json"]
  poll_interval_sec: 300
todo:
  enabled: true
  path: "~/todo.md"
macros:
  enabled: true
  timeout_sec: 10.0
  definitions:
    - id: "lock"
      label: "Lock screen"
      icon: "🔒"
      commands: [["loginctl", "lock-session"]]
standup:
  enabled: true
  git_author_email: "you@example.com"
  repos:
    - "~/code/service-a"
    - "~/code/service-b"
reminders:
  enabled: true
  interval_sec: 1500   # 25 min
```

### Known M6 limitations

- The `fullscreen` slot in `UIState` is **single-tenant**. The standup brief,
  the pomodoro break overlay, and the reminders engine all write to the same
  `UIState._fullscreen`. A water reminder firing while a standup brief is on
  screen will silently overwrite it. A priority-aware overlay model is out of
  M6 scope; the current workaround is to disable reminders during periods when
  you expect to be reading a standup brief, or to dismiss the standup before
  it can be clobbered. A real fix needs a small priority + queue layer on the
  fullscreen slot.

## Status

M0 + M1 + M2 + M4 + M5 + M6 complete: scaffold + USB transport, UI screens with mocks, pomodoro engine, live Jira + Bitbucket pollers with cache + worklog hook, Gmail + Chat + Calendar pollers + dbus notification listener feeding a merged `screen_2`, plus M6's todo watcher, config-declared macros, on-demand standup brief, idle-state water/eyes reminders, keyless OpenMeteo weather, and ccusage-driven Claude usage in the top bar. See `docs/superpowers/plans/` and the roadmap for what comes next.
