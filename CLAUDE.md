# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository state

M0 + M1 + M2 + M4 + M5 + M6 complete: daemon scaffold (Python asyncio, uv, pytest, structlog) i firmware scaffold (ESP-IDF v5.3 + LVGL 8.x). Transport USB CDC działa z heartbeat / reconnect / 5 typami wiadomości. Warstwa UI (M2) z makietami ekranów, integracje Jira + Bitbucket (M4) z httpx-owym klientem, SQLite cache i hookiem worklog z pomodoro, oraz M5 — Gmail, Google Chat, Google Calendar pollery + freedesktop dbus listener, scalone na `screen_2` przez `Screen2Merger` (priorytet dbus > gmail > gchat) i napędzające `screen_1.next_meeting`. M6 dodaje: `TodoFileListener` (watchdog + bytes-level rewrite zachowujący CRLF), `MacroExecutor` (config-deklarowane makra, `shell=False`, ESP wywołuje tylko po `id`), `StandupEngine` (Jira + Bitbucket + git log → fullscreen brief na żądanie), `RemindersEngine` (water/eyes co 25 min poza pomodoro), keyless OpenMeteo weather i ccusage Claude-usage. Per-field top_bar setters (`set_weather`, `set_claude_usage`, `set_clock`) zapobiegają nadpisywaniu się źródeł na pasku. Znane ograniczenie: slot `fullscreen` w `UIState` jest jednomiejscowy — przypomnienie wody może nadpisać aktywny brief standupu.

**Build / test / run commands:**

| Co | Komenda |
|---|---|
| Daemon tests | `cd deskstation-daemon && uv run pytest -v` |
| Daemon mypy + ruff | `cd deskstation-daemon && uv run mypy src/ && uv run ruff check src/ tests/` |
| Daemon run (live) | `cd deskstation-daemon && uv run deskstation` |
| Daemon run (mock bridge) | `bridge.mode: mock` w `config.yaml`, potem `uv run deskstation` |
| Firmware build | `cd deskstation-firmware && idf.py build` (po `. ~/esp/esp-idf/export.sh`) |
| Firmware flash + monitor | `cd deskstation-firmware && bash tools/flash.sh /dev/ttyACM0` |

**Logs:** `~/.local/share/deskstation/logs/daemon.jsonl` (rotating, 10 MB × 3).

The top-level `docs/` is the single source of truth for plan/spec/designs. Per-milestone specs and plans go to `docs/superpowers/{specs,plans}/`.

## System architecture

Deskstation is a two-part system; understanding the split is essential before touching either side.

**Host (Ubuntu, Python 3.11+ asyncio daemon — `deskstation-daemon/`):**
- Owns all business logic, state, and external API integrations (Jira, Bitbucket, Gmail, Google Calendar, Google Chat, weather, Claude usage, todo.md watcher, dbus notifications).
- Organized into `pollers/` (interval-driven async tasks), `listeners/` (event-driven: dbus, watchdog), `engines/` (in-memory state machines: pomodoro, standup, reminders), `executors/` (subprocess macros), `store/` (SQLite cache + history), and `ui_state.py` (aggregator that builds per-screen snapshot payloads).
- `bridge/serial_bridge.py` is the critical component everything else sits on — async USB CDC reader/writer with heartbeat and reconnect.
- M4 added live API integrations: `deskstation.clients.{jira,bitbucket}` (httpx REST wrappers), `deskstation.pollers.{jira,bitbucket}` (interval tasks with auth-failure short-circuit), `deskstation.store.api_cache` (last-known-good SQLite cache so the UI survives transient errors), and `deskstation.secrets` (loader for `~/.config/deskstation/secrets.yaml` with 0600 mode check).
- M5 added the comms + calendar stack: `deskstation.auth_google` (one-shot OAuth setup CLI), `deskstation.clients.{gmail,gchat,gcal}` (googleapiclient-based wrappers, cache-through reads, auth/transient error split), `deskstation.pollers.{gmail,gchat,calendar}` (interval pollers — Calendar has an adaptive near/far cadence around upcoming meetings), `deskstation.listeners.dbus_notifications` (freedesktop notification monitor with an app-name allowlist), and `deskstation.engines.screen2_merger` (single owner of the `screen_2` dispatch — merges Gmail / Chat / dbus by source priority + per-source index, caps at 16 items, also indexes per-notification action URLs for `xdg-open`).

**Firmware (ESP32-S3 + Waveshare 7" LCD, ESP-IDF v5.x + LVGL 8.x — `deskstation-firmware/`):**
- Dumb terminal: renders LVGL UI, sends user events, receives full state snapshots. No business state, no API calls, no secrets.
- FreeRTOS tasks: `lvgl_task` (core 1), `usb_rx_task` / `usb_tx_task` / `ui_dispatch_task` (core 0).
- Dual framebuffer in PSRAM (800×480×16bpp).

### Three rules that drive design decisions

1. **Host pushes full snapshots, never diffs.** When anything on screen X changes, host sends the complete `screen_X` payload. Idempotent, survives reboot, recovers cleanly after reconnect.
2. **ESP sends events, not state.** `task_clicked`, `meeting_join`, `macro_trigger`, `pomodoro_action` — host reacts.
3. **Secrets never leave the host.** API tokens, OAuth refresh tokens live in `~/.config/deskstation/secrets.yaml` (mode 0600). Macro commands come from `config.yaml`, loaded read-only at startup; the ESP cannot inject arbitrary commands.

### Serial protocol (USB CDC ACM, `/dev/ttyACM0`)

- Newline-delimited JSON, one message per line: `{"v": 1, "type": "...", "data": {...}}`.
- 921600 baud (nominal — CDC ignores it).
- Heartbeat every 5s both directions; >15s silence = disconnect → host pushes a full snapshot on reconnect.
- Host rate-limits to 5 updates/s per screen; 30s interval for non-visible screens.
- Full message catalog in `deskstation-daemon/docs/spec/02-serial-protocol.md`. Pydantic models on the host (`bridge/protocol.py`) and matching `cJSON` parsing on firmware must be kept in sync; bump `v` on breaking changes and support both versions during transition.

## Working with this repo

- Read `deskstation-*/docs/spec/01-architecture.md` before changing the host/firmware boundary or adding a new integration — the rationale for why ESP is a thin client (debuggability, hot-reload, secret isolation, performance) constrains where new code goes.
- Read `deskstation-*/docs/spec/02-serial-protocol.md` before adding or modifying a message type. Changes touch both sides.
- Read `deskstation-*/docs/plan/00-roadmap.md` (phases M0–M7) to understand what is in scope for the current phase. The user has explicitly sequenced this to validate the USB transport (M1) before building UI layers (M2+) or integrations (M3+).
- Specs are written in Polish; preserve the language when editing them.

## Conventions (from spec)

- Conventional Commits: `feat(jira): ...`, `fix(pomodoro): ...`, `chore(deps): ...`.
- Branches: `main` (stable), `dev` (active), `feat/<phase>-<desc>` merged into `dev`.
- Versioning: semver tags per milestone (`v0.1.0` after M1, …, `v1.0.0` after M7).
- Host code targets Python 3.11+ with `ruff` + `mypy --strict` + `pytest` (planned via `pyproject.toml` dev extras).
- Firmware uses `idf.py build flash monitor`; baseline `sdkconfig.defaults` enables TinyUSB CDC, PSRAM (octal mode), 1 kHz FreeRTOS tick, LVGL 16bpp.
