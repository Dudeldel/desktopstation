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

## Status

M0 + M1 + M2 + M4 complete: scaffold + USB transport, UI screens with mocks, pomodoro engine, live Jira + Bitbucket pollers with cache + worklog hook. See `docs/superpowers/plans/` and the roadmap for what comes next.
