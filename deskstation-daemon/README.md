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

## Status

M0 + M1 + M2 + M4 + M5 complete: scaffold + USB transport, UI screens with mocks, pomodoro engine, live Jira + Bitbucket pollers with cache + worklog hook, Gmail + Chat + Calendar pollers + dbus notification listener feeding a merged `screen_2`. See `docs/superpowers/plans/` and the roadmap for what comes next.
