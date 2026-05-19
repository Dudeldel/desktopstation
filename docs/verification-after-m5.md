# Post-M5 verification plan

End-to-end verification of M2 + M3 + M4 + M5 before starting M6. Each stage isolates the layer below it so a failure tells you exactly where to look. Everything below is meant to run on the development machine (Linux desktop with the ESP32-S3 board plugged in via USB).

## Deferred verifications carried into this milestone

| Milestone | What was never verified |
|---|---|
| M2 | Firmware visual — carousel layout, top bar, dot indicator, autoscroll |
| M3 | Pomodoro state overlay, fullscreen break overlay, screen module taps |
| M4 | Real Jira + Bitbucket data on screen_1 / screen_3, pomodoro → Jira worklog round-trip |
| M5 | Google OAuth flow, Gmail / Chat / Calendar real data, dbus desktop notifications, `xdg-open` round-trip on tap |

## Risk note before flashing

Firmware tree hasn't been rebuilt since `e289434` (M3.6 — break overlay landed). The daemon protocol has stayed backwards-compatible since then (only additive new message types on the daemon side; the firmware silently ignores envelopes whose `type` it doesn't know), but `idf.py build` has not been run against the current firmware tree in the SDD session. **Build it first.** If it doesn't compile, everything else here is moot.

## Stages

Each row of the table is a self-contained verification. Run them in order; abort at the first failure and root-cause before continuing.

### 1. Firmware builds

Proves: M2/M3 code still compiles after all the protocol shape changes the daemon has been through.

```bash
cd deskstation-firmware
. ~/esp/esp-idf/export.sh
idf.py build
```

Pass criteria: build completes, no errors. Warnings about unused vars are fine.

### 2. Daemon starts on mock bridge

Proves: M4/M5 wiring doesn't crash startup, config loads, no Python import errors.

Setup `deskstation-daemon/config.yaml`:

```yaml
bridge:
  mode: mock
mock:
  enabled: false
jira:
  enabled: false
bitbucket:
  enabled: false
gmail:
  enabled: false
gchat:
  enabled: false
calendar:
  enabled: false
dbus:
  enabled: false
```

Run:

```bash
cd deskstation-daemon
uv run deskstation
```

Tail the JSONL log in another shell:

```bash
tail -f ~/.local/share/deskstation/logs/daemon.jsonl
```

Pass criteria:
- `ready` event with `bridge_mode=mock` appears within a second.
- No exceptions in the log.
- `Ctrl-C` shuts down cleanly with a `shutdown_complete` event.

### 3. Flash firmware, visually verify M2 + M3

Proves: LVGL renders correctly, touch input works, autoscroll runs.

```bash
cd deskstation-firmware
bash tools/flash.sh /dev/ttyACM0
```

`flash.sh` builds, flashes, and opens a serial monitor. Watch for the boot banner.

Visual checks (in order on the panel):

- **Top bar (40 px header):** clock `--:--`, "MAKRO" button on the right with accent color. The clock placeholder is expected — it only updates once a daemon is pushing `top_bar` messages.
- **Carousel:** four tiles, swipe left/right moves between them. Each tile shows placeholder labels (M2 mock-poller content if daemon is running, else empty layout).
- **Dot indicator:** four dots between the top bar and the carousel; the active dot uses the accent color, others are dim.
- **Autoscroll:** wait 10 s without touching — the carousel should advance one tile. After a touch event, the timer resets to 30 s for one cycle, then back to 10 s.
- **Pomodoro overlay test (optional, requires daemon):** can defer until stage 5.

Common failures: blank screen → PSRAM / panel-init log lines in the serial monitor will explain. White bar at top → direct-mode framebuffer regression (was the M2 task that fixed this).

### 4. Daemon ↔ firmware via USB CDC

Proves: M1 transport intact, daemon pushes mock screen data, firmware renders it.

In `config.yaml`:

```yaml
bridge:
  mode: serial
serial:
  device: /dev/ttyACM0
mock:
  enabled: true        # turn the M2 mock pollers ON for this stage
```

Keep all M4/M5 integrations disabled. Restart daemon (`Ctrl-C`, `uv run deskstation`).

Pass criteria in the JSONL log:
- `hello_received` event with the firmware version.
- `bridge_mode=serial` and no `serial_reconnect` events.
- `mocks_skip_applied` does *not* appear (all real pollers off, so all five mock pollers run).

On the panel:
- Top bar fills in with mocked clock/date/weather/usage/pomodoro counter.
- Each of the four screens shows mocked Polish content (DEV-1234 tasks, fake notifications, fake PRs, fake todo items).
- Disconnect USB → panel goes idle. Reconnect → daemon emits `reconnect_resending_ui_state`, panel repopulates within ~1 s.

### 5. M4 — Jira + Bitbucket real data

Proves: real OAuth-ish flow (token-based), real screen_1 / screen_3, pomodoro worklog round-trip.

#### Secrets

Create `~/.config/deskstation/secrets.yaml`:

```yaml
jira:
  base_url: "https://your-domain.atlassian.net"
  email: "you@example.com"
  api_token: "ATATT3..."          # https://id.atlassian.com/manage-profile/security/api-tokens

bitbucket:
  workspace: "your-workspace"
  email: "you@example.com"
  api_token: "ATBB..."            # https://bitbucket.org/account/settings/app-passwords/
  username: "your-bb-nickname"    # optional; falls back to email local-part
```

```bash
chmod 600 ~/.config/deskstation/secrets.yaml
```

#### Config

In `config.yaml`:

```yaml
jira:
  enabled: true
  project_key: "DEV"               # your lead project — drives the sprint query
  poll_interval_sec: 60.0
bitbucket:
  enabled: true
  workspace: "your-workspace"
  repos:
    - "service-a"
    - "service-b"
  poll_interval_sec: 60.0
```

Restart daemon.

#### Pass criteria

JSONL log:
- `mocks_skip_applied skip=["screen_1","screen_3"]`.
- `jira_request endpoint=search/jql` events at the configured interval.
- `bitbucket_request endpoint=...` events likewise.
- No `*_auth_failed` events.

Panel:
- Screen 1 shows your real Jira tasks (today + sprint queue) and any next meeting (still empty for now — calendar arrives in stage 6).
- Screen 3 shows your real PRs + CI badges.

#### Pomodoro worklog round-trip

Tap a Jira task on screen 1. The pomodoro overlay should appear with the task key + summary. Either wait the full 25 minutes or press **STOP+LOG**. A few seconds after the stop:

- In Jira, open the task → **Work log** tab → there should be a fresh entry with the elapsed time and a timestamp matching the stop event.
- JSONL log: `pomodoro_completed task_key=...` followed by no `worklog_disabled_auth_error` events.

If the worklog disabled itself due to a 401, the JSONL log will show `worklog_disabled_auth_error` once. Re-check your Jira API token.

### 6. M5 — Google integrations

Proves: OAuth setup CLI works, real Gmail + Chat + Calendar data, meeting bar fills in.

#### One-time OAuth setup

1. Create a Google Cloud project (or reuse).
2. Enable Gmail API, Chat API, Calendar API.
3. Configure the OAuth consent screen (internal or external — both work).
4. Create an OAuth client of type **Desktop application**. Download the JSON.
5. Save it to `~/.config/deskstation/google_client.json` and `chmod 600` it.
6. Run the setup CLI:

   ```bash
   cd deskstation-daemon
   uv run deskstation auth-google
   ```

   A browser tab opens for the consent flow. Approve the scopes. The CLI writes `~/.config/deskstation/google_token.json`. Running the CLI again should print "Google credentials already valid; no action needed."

#### Config

In `config.yaml`:

```yaml
gmail:
  enabled: true
  poll_interval_sec: 60.0
gchat:
  enabled: true
  my_email: "you@example.com"    # used for @-mention detection in spaces
  poll_interval_sec: 60.0
calendar:
  enabled: true
  near_interval_sec: 60.0
  far_interval_sec: 300.0
  near_window_sec: 1800
```

Restart daemon.

#### Pass criteria

JSONL log:
- `mocks_skip_applied skip=["screen_1","screen_2","screen_3"]`.
- `gmail_request`, `gchat_request`, `gcal_request` events at the configured intervals.

Panel:
- Screen 2 shows your real unread Gmail + Chat notifications (DM messages or @-mentions).
- Screen 1's meeting bar (bottom) shows your next Meet-enabled calendar event, with "za N min" / "TRWA" badge.

#### xdg-open round-trip

Tap a notification card on screen 2 → host should run `xdg-open` of the deep link (Gmail web UI or Chat space). Tap the meeting bar → host opens the Meet URL in your browser. JSONL should show the corresponding `notification_action` or `meeting_join` event followed by no errors.

### 7. M5 — dbus desktop notifications

Proves: dbus listener captures Notify signals, classifier maps app names, Screen2Merger blends them with Gmail/Chat.

In `config.yaml`:

```yaml
dbus:
  enabled: true
  app_name_patterns:
    - "WhatsApp*"
    - "Messenger*"
    - "Slack*"
  buffer_size: 32
```

Restart daemon. Watch for `dbus_listener_active patterns=[...]` in the JSONL.

Smoke test from a terminal:

```bash
notify-send -a "WhatsApp Web" "Marek" "test message"
```

Pass criteria:
- Notification appears on screen 2 within ~1 s, sender `"Marek"`, preview `"test message"`, source pill colored for WhatsApp.
- It ranks **above** any Gmail / Chat items in the screen 2 list (dbus has highest priority in `Screen2Merger`).

Troubleshooting:
- `dbus_listener_unavailable` in log → session bus rejected monitoring. Some Wayland sessions or hardened policies block `org.freedesktop.DBus.Monitoring`. Falling back to a non-monitor mode is M6 territory; for now this just means dbus capture is disabled.

## "Minimum sanity test" if you only have an hour

Stages 1 → 2 → 3 → 4 prove the whole transport + UI pipeline mechanically works without any external service. Stages 5 / 6 / 7 verify the integrations and can be done one at a time as you populate each credential.

If 1-4 all pass but 5-7 are blocked on credentials, that's still a clean point to start M6 — the foundations are sound.

## What "pass" gets you

- Stages 1-2: foundation. Code compiles, daemon boots.
- Stages 3-4: M1 + M2 + M3 verified. The "thin client + host pushes snapshots" architecture works.
- Stage 5: M4 verified. Real productivity-tool data on the device.
- Stage 6: M5 (Google) verified.
- Stage 7: M5 (dbus) verified.

After all seven, ready to start M6: todo file watcher, macro executor, standup engine, reminders engine, weather poller, Claude usage poller.

## If you find a real bug

- Capture: the JSONL log lines around the failure + a photo of the panel if visual.
- Don't try to fix it inline — file the issue against the milestone it belongs to and unblock the verification.
- Most likely failure modes:
  - dbus session-bus policy denial → log warning, skip.
  - Jira `400` from JQL → check `project_key` doesn't contain quotes or special chars.
  - OAuth `403` → consent screen scopes don't match the requested scopes.
  - Firmware white bar → already known regression; the direct-mode framebuffer fix is in `e289434`. If it returns, rebuild from clean.
