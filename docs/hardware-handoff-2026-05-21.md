# Hardware handoff — picking up on a different PC

**Date:** 2026-05-21
**Last commit on master:** `6655e81` — `fix(lock): keep overlay on top + gate autoscroll resume + listener start order`

This note exists because the daemon side of M6 + the screen-lock feature is
done and live-verified, but the **ESP32 panel was not on this machine**, so
nothing has been flashed since `e289434` (M3.6 — break overlay landed in
firmware). The next Claude session, on a PC that has the panel plugged in
and ESP-IDF installed, should resume from here.

The earlier generic verification plan at [`docs/verification-after-m5.md`](verification-after-m5.md)
is still the right document for the broader sequence. This file is the
delta: what's already been verified daemon-side since that plan was
written, and what hardware tests are new.

## What's already verified (daemon side, this session)

Live-tested on the original machine against real APIs while the panel was
unavailable. **You can trust these without re-running.**

| Source | Status |
|---|---|
| Jira (`POST /rest/api/3/search/jql`) | 200 OK, screen_1 pushed |
| Bitbucket (after the `a7cace0` UUID + `6aba682` nickname patches) | 200 OK on all four endpoints, screen_3 pushed |
| Gmail | first poll returns successfully, screen_2 pushed |
| Google Calendar | first poll returns successfully |
| Google Chat | API approach abandoned — daemon catches it via dbus instead (see `caf3312` for the classifier) |
| OpenMeteo weather | 200 OK, top_bar.weather patched |
| dbus desktop notifications | listener active, 25 captures in a single tick on a noisy desktop |
| Todo file watcher | file-edit → reparse → screen_4 push round-trip confirmed |
| Macro executor | `hello` macro runs `echo` end-to-end |
| Reminders engine | water/eyes alternation at 1s interval |
| Standup engine | live `git log` against this repo, 5 commits + truncation hint |
| ccusage Claude usage | wrapper at `~/.config/deskstation/ccusage_percent.py` returns ~28% (matches claude.ai/usage within rounding) |
| `screensaver` listener (NEW) | `screensaver_listener_active` emitted on the session bus; signal classification is unit-tested but **end-to-end Super+L round-trip was not exercised on the original machine** |

## What needs hardware

In rough priority order.

### 1. Build firmware

The firmware tree has not been built since `e289434`. M2/M3 still need to
compile after every protocol shape change that's landed since. The lock
feature added a new envelope variant + a new overlay component.

```bash
cd deskstation-firmware
. ~/esp/esp-idf/export.sh
idf.py build
```

Expect: clean build, no errors. Warnings about unused vars are fine.

If anything fails to compile, the most likely culprits are the
**post-M3.6 changes that were never built**:
- `protocol.h` / `protocol.c` — `MSG_LOCK_STATE` enum + `lock_state_payload_t`
  union member + parser branch (commit `37d81cd`).
- `ui/lock_overlay.h` / `ui/lock_overlay.c` — new files (commit `37d81cd`).
- `ui/pomodoro_overlay.{h,c}` — gained a `pomodoro_overlay_visible()`
  exposure (commit `6655e81`).
- `main.c` — new `MSG_LOCK_STATE` dispatch case + a "keep lock on top after
  every dispatch" guard (commits `37d81cd` and `6655e81`).
- `CMakeLists.txt` — `ui/lock_overlay.c` was added to SRCS (commit `37d81cd`).

### 2. Flash and smoke-test the existing UI

Follow stages 3–4 of [`verification-after-m5.md`](verification-after-m5.md)
to confirm M2 + M3 still work after the build. Nothing about those layers
changed on the daemon side; if the panel renders carousel + autoscroll +
top bar like before, the foundation is fine.

### 3. Verify the lock overlay end-to-end (NEW)

This is the load-bearing verification for the latest feature.

Setup on the new machine:
- Pull master so you have the `37d81cd` + `6655e81` commits.
- Build + flash firmware (step 1).
- The daemon needs a `config.yaml` with `screensaver.enabled: true`. The
  example shows the block; `config.yaml` itself is gitignored. The
  minimum to drive the panel for this test is:
  ```yaml
  bridge:
    mode: serial
  serial:
    device: /dev/ttyACM0
  screensaver:
    enabled: true
  # Everything else can stay at defaults (off) — we don't need real APIs to
  # test the lock path.
  ```
- Run the daemon: `cd deskstation-daemon && uv run deskstation`.
- Tail the log in another shell: `tail -f ~/.local/share/deskstation/logs/daemon.jsonl`.

Test sequence:

1. Confirm `screensaver_listener_active` lands in the JSONL on startup.
2. **Lock the desktop** (Super+L on GNOME, equivalent on KDE/etc.). On the
   panel you should see an opaque overlay with an X-style icon and
   "EKRAN ZABLOKOWANY" — instantly, < 1 s after the lock.
3. **Try to swipe** the panel and **try to tap** anywhere on it. Nothing
   should happen. No `screen_changed`, `task_clicked`, etc. events should
   reach the daemon (grep the JSONL).
4. **Unlock the desktop.** Overlay should disappear, carousel returns.
5. JSONL should show two `ui_state_sent screen=lock_state` events — one
   on lock, one on unlock.

Edge cases to exercise (the `6655e81` commit was specifically about these):

6. **Lock during an active pomodoro.** Tap a task on screen_1 to start a
   pomodoro (need real Jira data or M2 mock for this — flip
   `mock.enabled: true` if no Jira). While the pomodoro fullscreen is up,
   lock the desktop. The lock overlay should appear ABOVE the pomodoro
   overlay (not below — that would be the security defeat fixed by
   `6655e81`). Watch the panel for ~10 s; the pomodoro overlay's
   per-second updates must NOT pop above the lock overlay.

7. **Unlock during an active pomodoro.** Carousel autoscroll should
   **NOT** resume (because pomodoro is still active). This is what the
   `pomodoro_overlay_visible()` helper was added for.

8. **Reboot the panel while locked.** Press the ESP32 reset button while
   the desktop is still locked. After reboot, the daemon should resend
   the lock state via `resend_all`, and the overlay should re-paint.
   This is what the `resend_all` change on the lock state covers
   (`test_resend_all_carries_current_lock_state`).

If any of 6–8 fail, capture the JSONL window + a panel photo and treat
it as a real regression of `6655e81`.

### 4. M6 firmware gaps (deferred, file as backlog)

Three M6 features have daemon support but no firmware rendering yet —
they were called out at the end of M6 as "next firmware milestone". The
daemon will push these and the firmware will quietly ignore or
fall-through, no errors. Schedule for whenever the panel has bench time:

- **`fullscreen{kind="standup"}`** — daemon pushes the standup brief
  (24-h Jira + Bitbucket + git log digest) as a fullscreen overlay. The
  firmware's fullscreen overlay handles `break_short`/`break_long`/
  `water`/`eyes` cases but probably falls through on `standup`. Test:
  add `standup.enabled: true` to config, write a small Python harness
  that injects a `standup_request` envelope into the bridge (no firmware
  button for it yet either), confirm the brief appears.
- **`notification.source == "chat"`** — screen_2 row pill color may be
  hard-coded to only the M2 sources. Chat notifications via dbus will
  render with the fallback pill until firmware adds a Chat case.
- **`standup_request` ESP→host event** — there's no firmware button that
  emits this yet. M6 protocol allows it; UI needs a button somewhere
  (probably on screen_3 or in the macro overlay).

### 5. Optional: real integration test on the new machine

The daemon's API integrations (Jira/Bitbucket/Google/dbus) work on the
new machine only if you set up secrets there too. The original machine's
`~/.config/deskstation/{secrets.yaml, google_client.json, google_token.json}`
**should not be copied across** — they're machine-local credentials and
the OAuth refresh token is tied to that machine's redirect URI.

If you want real data on the new machine:
- Re-run the setup at `deskstation-daemon/setup.example.md` from scratch
  (yes, it means a new pair of API tokens). The form lives in the repo
  at that path.
- Generate a fresh Google OAuth token via `uv run deskstation auth-google`.

If you just want to test the lock overlay end-to-end without real APIs,
skip this — use the minimal config in step 3 above.

## Known limitations to flag in the lock verification

- **Lock icon is `LV_SYMBOL_CLOSE` (an X), not a real lock glyph.** LVGL 8
  has no built-in lock symbol and the project's Polish font subset
  doesn't bake `U+F023` in. The Polish "EKRAN ZABLOKOWANY" label carries
  the meaning. Follow-up: regenerate the Montserrat subset under
  `deskstation-firmware/main/ui/fonts/` with the FontAwesome lock glyph.
- **No live-bus integration test on the daemon side.** The dbus listener's
  `classify_signal` is exhaustively unit-tested but the actual bus
  subscription path was confirmed only by booting the daemon and seeing
  `screensaver_listener_active`. The end-to-end Super+L round-trip on
  the original machine was attempted but not completed (the user moved
  to a different PC before locking). The new machine's tests in step 3
  above close this gap.

## Quick orientation if you're cold

- **Repo root:** wherever you clone this. Two subdirs: `deskstation-daemon/`
  (Python) and `deskstation-firmware/` (ESP-IDF C).
- **Daemon entry point:** `cd deskstation-daemon && uv run deskstation`.
  Logs to `~/.local/share/deskstation/logs/daemon.jsonl`.
- **Firmware entry point:** `cd deskstation-firmware && . ~/esp/esp-idf/export.sh && idf.py build flash monitor`.
- **Architecture rules:** the host pushes full snapshots, never diffs; the
  ESP is a thin client; secrets never leave the host. See
  [`docs/spec/01-architecture.md`](spec/01-architecture.md) and
  [`CLAUDE.md`](../CLAUDE.md) (top-level) for the full convention.
- **The just-finished feature:** screen-lock overlay. Daemon listens to
  `org.freedesktop.ScreenSaver.ActiveChanged`; pushes `lock_state{locked: bool}`;
  firmware renders an opaque overlay on `lv_layer_top` that swallows
  touch. See commits `37d81cd` (feature) and `6655e81` (review-driven
  follow-ups: security re-foreground, autoscroll gating, listener
  start-order).

## What's safe to skip if you're short on time

- M6 firmware gaps (section 4) — backlog item, not blocking.
- Real API integration on the new machine (section 5) — orthogonal to
  the lock-overlay test.

What you **should not** skip: section 3 (lock end-to-end) and especially
edge cases 6–8. Those are the only verification we don't have yet.
