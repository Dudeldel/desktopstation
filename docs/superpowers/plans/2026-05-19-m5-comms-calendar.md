# M5 — Communications (screen_2) + Google Calendar meetings on screen_1 (Plan)

**Date:** 2026-05-19
**Authored:** Claude (executing /subagent-driven-development per user request)
**Scope:** Real data on screen_2 (Gmail + Google Chat + dbus desktop notifications) and meeting bar on screen_1.

---

## Working constraints

- **No OAuth credentials in this session.** Plan builds the OAuth2 setup CLI + the pollers, with mock-driven tests. User runs `deskstation auth-google` interactively after M5 lands.
- **Field shapes:** Reuse the existing M2 `Notification`/`MeetingBar` models. Spec-fidelity refresh (richer screen_2 shape with `unread_count`, `action_url` per item) is deferred.
- **dbus testing:** Stub the dbus listener with a `notify-send`-driven manual smoke test step in the README. The async dbus-glib integration is hard to unit-test without a fixture; the implementation uses `dbus-next` (pure-asyncio, modern fork).
- **HTTP:** `httpx` (already added in M4.1) plus `google-auth` + `google-api-python-client` for OAuth/Calendar/Gmail. Tests use respx where possible.

---

## Common context

Same as M4 — same gates, same commit conventions, same branch.

---

## Task M5.1 — Google OAuth2 setup utility

**Files:**
- Modify: `pyproject.toml` — add `google-auth>=2.30`, `google-auth-oauthlib>=1.2`, `google-api-python-client>=2.130`, `dbus-next>=0.2.3`.
- Create: `deskstation-daemon/src/deskstation/auth_google.py` — interactive CLI exposed as `deskstation auth-google`:
  - Reads `~/.config/deskstation/google_client.json` (user's Google Cloud project OAuth client). Errors with instructions if missing.
  - Scopes: `gmail.readonly`, `chat.messages.readonly` (when available; fallback to `chat.spaces.readonly`), `calendar.readonly`.
  - Runs the local-server OAuth flow, writes the refresh token to `~/.config/deskstation/google_token.json` (mode 0600).
  - Idempotent: if token file exists and refresh works, just confirms validity.
- Modify: `src/deskstation/__main__.py` to add the `auth-google` subcommand alongside the existing daemon launch.

**Tests:**
- `tests/test_auth_google.py` — token round-trip on disk; permission check; error when client.json missing. Use a mock OAuth flow object.

**Verification + Commit:** `feat(daemon): Google OAuth setup utility (M5.1)`

---

## Task M5.2 — Gmail poller

**Files:**
- Create: `deskstation-daemon/src/deskstation/clients/gmail.py` — `GmailClient`:
  - Loads credentials from `google_token.json`, refreshes if expired.
  - `list_unread_recent(query: str = "is:unread newer_than:1d") -> list[GmailMessage]` — uses Gmail API users.messages.list + batched get for headers (From, Subject, snippet, internalDate, id).
  - Cached via the M4.1 `ApiCache`.
- Create: `deskstation-daemon/src/deskstation/pollers/gmail.py` — `GmailPoller`. Per tick → `client.list_unread_recent()` → map to `Notification(source="gmail", sender=From-display-name, preview=subject, time_ago, id=message_id)`. Pushes the list (merged with other sources in M5.5).

**Tests:** `tests/test_gmail_client.py` with a mocked discovery client; `tests/test_gmail_poller.py` with a mocked client.

**Verification + Commit:** `feat(daemon): Gmail poller (M5.2)`

---

## Task M5.3 — Google Chat poller

**Files:**
- Create: `deskstation-daemon/src/deskstation/clients/gchat.py` — `GoogleChatClient`:
  - `list_dm_spaces() -> list[Space]` — `spaces.list` filtered to `type=DIRECT_MESSAGE` + `SPACE` with my membership.
  - `list_recent_messages(space_name: str, since: datetime) -> list[ChatMessage]` — `spaces.messages.list`.
- Create: `deskstation-daemon/src/deskstation/pollers/gchat.py` — for each DM/space, fetch messages since last check. Filter: DM or `@me` mention. Push `Notification(source="chat", sender=display_name, preview=text, time_ago, id=name)`.

**Tests:** as above with mocked discovery.

**Verification + Commit:** `feat(daemon): Google Chat poller (M5.3)`

---

## Task M5.4 — dbus desktop notification listener

**Files:**
- Create: `deskstation-daemon/src/deskstation/listeners/__init__.py` (empty).
- Create: `deskstation-daemon/src/deskstation/listeners/dbus_notifications.py` — `DbusNotificationListener` using `dbus-next`. Connects to session bus, subscribes to `org.freedesktop.Notifications.Notify` via the **monitoring** interface (not just owning the name; the WhatsApp/Messenger Chrome PWAs emit Notify on a different sender). Filter by `app_name` matching configurable patterns (e.g., `WhatsApp`, `Messenger`, `Chrome` with body-prefix match).
- The listener pushes notifications into a shared in-memory ring buffer that the merge layer (M5.5) consumes.

**Tests:** difficult to unit-test the dbus binding itself; instead test the parsing logic (`_classify_app_name`) and the ring buffer behavior. README smoke test: `notify-send -a "WhatsApp Web" Marek "test"` → notification appears on screen_2.

**Verification + Commit:** `feat(daemon): dbus notification listener (M5.4)`

---

## Task M5.5 — Screen_2 merge layer

**Files:**
- Create: `deskstation-daemon/src/deskstation/engines/screen2_merger.py` — `Screen2Merger` aggregates notifications from `GmailPoller`, `GoogleChatPoller`, `DbusNotificationListener`. Maintains a deduplicated, time-sorted list (max 16 items). On any source update → push merged list via `ui_state.set_screen_2(notifications=...)`. Newest first.

**Tests:** `tests/test_screen2_merger.py` — feed mixed sources, assert ordering + dedup.

**Verification + Commit:** `feat(daemon): screen_2 source merger (M5.5)`

---

## Task M5.6 — Google Calendar poller + screen_1 meeting bar

**Files:**
- Create: `deskstation-daemon/src/deskstation/clients/gcal.py` — `GoogleCalendarClient` with `list_upcoming(window_hours: int = 36) -> list[Meeting]` using calendar.events.list (`timeMin`=now, `timeMax`=now+window, `singleEvents=true`, `orderBy=startTime`). Only events with `hangoutLink`.
- Create: `deskstation-daemon/src/deskstation/pollers/calendar.py` — `CalendarPoller`. Picks the next imminent meeting. Adaptive interval: 5 min when next meeting > 30 min away, 1 min when <= 30 min. Sets `ui_state.set_screen_1(next_meeting=MeetingBar(title, time="HH:MM-HH:MM", join_url=hangoutLink, in_minutes))`.

**Tests:** `tests/test_calendar_poller.py` with mocked client.

**Verification + Commit:** `feat(daemon): Google Calendar poller + meeting bar (M5.6)`

---

## Task M5.7 — ESP→host meeting_join / notification_action handlers

**Files:**
- Modify: `deskstation-daemon/src/deskstation/bridge/protocol.py` — add `MeetingJoinMsg{id}` and `NotificationActionMsg{id}` per `docs/spec/02-serial-protocol.md`. These are aliases for what the firmware already calls `notification_clicked` (legacy) — keep both message types during transition; firmware emits notification_clicked, daemon accepts both as the same action.
- Modify: `deskstation-daemon/src/deskstation/main.py` — dispatcher handles both: looks up the notification/meeting URL from the in-memory index maintained by Screen2Merger/CalendarPoller and runs `subprocess.run(["xdg-open", url])`.

**Tests:** dispatcher routes the messages correctly; xdg-open subprocess is mocked.

**Verification + Commit:** `feat(daemon): meeting_join + notification_action handlers (M5.7)`

---

## Task M5.8 — Disable M2 Screen2 mock; integration test; docs

**Files:**
- Modify: `pollers/mock.py` `start_all_mocks(skip=...)` to also accept "screen_2".
- Modify: `main.py` to skip screen_2 mock when any real source is active.
- Create: `tests/test_integration_m5.py` — wire mocked Gmail + Chat clients + a fake dbus listener, run a poll, assert merged screen_2 payload.
- Modify: `deskstation-daemon/README.md` — add "Google integrations" section with the auth-google flow + the dbus smoke test command.
- Modify: top-level `CLAUDE.md` — append M5 to milestone list.

**Verification + Commit:** `feat(daemon): wire M5 sources, docs (M5.8)`

---

## Definition of done

- All eight tasks committed.
- `uv run pytest -q && uv run mypy src/ && uv run ruff check src/ tests/` green.
- With `google_token.json` populated, daemon shows real Gmail/Chat unread on screen_2 and real upcoming Meets on screen_1's meeting bar; `notify-send -a "WhatsApp Web" Marek "test"` appears on screen_2 within ~1 s.
