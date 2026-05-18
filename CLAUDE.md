# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository state

This repo currently contains **only specification and design documents** — no source code, build system, or tests exist yet. The `deskstation-daemon/` and `deskstation-firmware/` directories each hold `docs/` (plan, spec, designs) that describe what the two future codebases should look like; the `src/`, `main/`, `pyproject.toml`, `CMakeLists.txt`, etc. shown in `spec/03-project-structure.md` have **not been created**. Implementation is planned to start at milestone M0 in `deskstation-*/docs/plan/00-roadmap.md`.

When asked to "build", "run tests", or "lint", first check whether the relevant subproject has been scaffolded — if not, the request needs to start with M0 setup, not with running a command.

The two `docs/` trees under `deskstation-daemon/` and `deskstation-firmware/` are currently **identical copies** of the same documentation set. Treat them as one source of truth — if you edit a spec, update both, or first ask the user whether the duplication should be resolved (e.g. moved to a shared top-level `docs/`).

The top-level `*.md` and `*.html` files (`00-roadmap.md`, `01-architecture.md`, `00-all-screens.html`, etc.) appear to be older flat copies of what is now organized under `deskstation-*/docs/`. Prefer the versioned copies under the subprojects.

## System architecture

Deskstation is a two-part system; understanding the split is essential before touching either side.

**Host (Ubuntu, Python 3.11+ asyncio daemon — `deskstation-daemon/`):**
- Owns all business logic, state, and external API integrations (Jira, Bitbucket, Gmail, Google Calendar, Google Chat, weather, Claude usage, todo.md watcher, dbus notifications).
- Organized into `pollers/` (interval-driven async tasks), `listeners/` (event-driven: dbus, watchdog), `engines/` (in-memory state machines: pomodoro, standup, reminders), `executors/` (subprocess macros), `store/` (SQLite cache + history), and `ui_state.py` (aggregator that builds per-screen snapshot payloads).
- `bridge/serial_bridge.py` is the critical component everything else sits on — async USB CDC reader/writer with heartbeat and reconnect.

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
