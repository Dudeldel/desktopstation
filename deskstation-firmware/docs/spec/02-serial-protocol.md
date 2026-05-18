# Serial protocol — host ↔ ESP32

## Transport

- **Fizyczny:** USB CDC ACM przez Type-C port (NIE przez UART bridge!)
- **Device path:** `/dev/ttyACM0` (Ubuntu domyślnie)
- **Baudrate:** 921600 (technicznie ignorowane przez CDC ale ustawić dla zgodności)
- **Encoding:** UTF-8
- **Framing:** newline-delimited JSON. Każda wiadomość = jedna linia zakończona `\n`.

## Format wiadomości

Każda wiadomość:

```json
{"v": 1, "type": "<message_type>", "data": { ... }}
```

- `v` — wersja protokołu, obecnie 1
- `type` — string, identyfikator typu wiadomości (lista poniżej)
- `data` — payload, struktura zależy od typu

## Versioning

Wersja 1 jest pierwotna. Breaking changes → bumpować na 2, host i ESP sprawdzają `v` przy parsowaniu. Można obsługiwać oba wersje jednocześnie przez okres przejściowy.

## Heartbeat i reconnect

- Co 5 sekund obie strony wysyłają `{"v":1,"type":"heartbeat","data":{}}`.
- Brak heartbeat > 15s = oznacz disconnect:
  - Host: oznacz ESP jako offline, próbuj reconnect.
  - ESP: pokaż banner "Disconnected" w pasku górnym, dane są stale.
- Po reconnect: host pcha pełny snapshot wszystkiego (top_bar, screen_1..4, pomodoro_state, macro_list).

## Backpressure

- Host nie wysyła update'ów częściej niż 5/s na ekran (rate limit).
- Update'y dla niewidocznych ekranów: co 30s zamiast co 5s.
- ESP może odpowiadać `ack` na update'y (opcjonalne, do debug'u).

---

## Wiadomości host → ESP

### `top_bar` — always-on pasek górny

```json
{
  "v": 1,
  "type": "top_bar",
  "data": {
    "time": "14:23",
    "date": "2026-05-18",
    "weather": {
      "temp": 18,
      "icon": "cloud",
      "desc": "Pochmurno"
    },
    "claude_usage": {
      "percent": 42,
      "label": "4.2/10 USD"
    },
    "pomodoros_today": 3,
    "connected": true
  }
}
```

- `weather.icon` — kod ikony (`sun`, `cloud`, `rain`, `snow`, `storm`, `fog`)
- `connected` — flaga dla wskaźnika "host w sieci" (na razie zawsze true)

### `screen_1` — Jira

```json
{
  "v": 1,
  "type": "screen_1",
  "data": {
    "my_tasks": [
      {
        "key": "DEV-1234",
        "summary": "Refactor auth middleware",
        "status": "in_progress",
        "project": "DEV",
        "priority": "high"
      }
    ],
    "lead_project": {
      "key": "PROJ",
      "name": "Mój projekt",
      "sprint": {
        "name": "Sprint 12",
        "days_left": 4,
        "points_done": 12,
        "points_total": 30
      },
      "status_counts": {
        "todo": 8,
        "in_progress": 5,
        "review": 2,
        "done": 15
      },
      "tasks": [
        {
          "key": "PROJ-41",
          "summary": "User onboarding flow",
          "status": "in_progress",
          "assignee_initials": "AK",
          "assignee_color": "green"
        }
      ]
    },
    "meetings": [
      {
        "id": "abc123",
        "title": "Team standup",
        "start": "14:30",
        "minutes_until": 7,
        "duration_min": 30,
        "attendees": 6,
        "meet_url": "https://meet.google.com/xxx-yyyy-zzz",
        "imminent": true
      }
    ]
  }
}
```

- `status` enum: `draft`, `todo`, `in_progress`, `review`, `done`
- `priority` enum: `high`, `medium`, `low`, `null`
- `assignee_color` enum: `green`, `purple`, `coral`, `blue`, `pink`, `amber`, `gray`
- `imminent` — true gdy `minutes_until < 15`

### `screen_2` — komunikacja

```json
{
  "v": 1,
  "type": "screen_2",
  "data": {
    "unread_count": 8,
    "notifications": [
      {
        "id": "n1",
        "source": "whatsapp",
        "sender": "Marek Nowak",
        "preview": "Hej, jutro o 18 nadal pasuje?",
        "timestamp": "2026-05-18T14:21:00",
        "minutes_ago": 2,
        "read": false,
        "action_url": "https://web.whatsapp.com/..."
      }
    ]
  }
}
```

- `source` enum: `gmail`, `gchat`, `whatsapp`, `messenger`
- `action_url` — co otworzyć po kliknięciu

### `screen_3` — dev

```json
{
  "v": 1,
  "type": "screen_3",
  "data": {
    "prs": {
      "mine_count": 3,
      "review_count": 2,
      "items": [
        {
          "id": "PR-42",
          "title": "Add caching layer to user service",
          "repo": "backend",
          "kind": "review",
          "author_initials": "MJ",
          "author_color": "purple",
          "age_hours": 52,
          "files": 12,
          "additions": 234,
          "deletions": 56,
          "approvals": null,
          "approvals_required": 2
        }
      ]
    },
    "ci": [
      {
        "repo": "backend",
        "branch": "main",
        "status": "success",
        "minutes_ago": 12
      },
      {
        "repo": "frontend",
        "branch": "main",
        "status": "failed",
        "minutes_ago": 25
      }
    ],
    "standup_preview": {
      "closed": 3,
      "merged": 2,
      "commits": 12
    }
  }
}
```

- `pr.kind` enum: `mine`, `review`
- `ci.status` enum: `success`, `failed`, `running`, `cancelled`

### `screen_4` — todo

```json
{
  "v": 1,
  "type": "screen_4",
  "data": {
    "file_path": "~/todo.md",
    "done_count": 3,
    "total_count": 9,
    "items": [
      {
        "id": "line_3",
        "text": "Wysłać raport kwartalny do księgowej",
        "done": false,
        "priority": "high",
        "tags": ["praca"],
        "deadline": "2026-05-18",
        "deadline_label": "dziś"
      }
    ]
  }
}
```

- `id` musi być stabilny między reloadami pliku (np. `line_<numer>_<hash_first8>`)
- `deadline_label` opcjonalny string już sformatowany ("dziś", "jutro", "20 maj", null)

### `pomodoro_state`

```json
{
  "v": 1,
  "type": "pomodoro_state",
  "data": {
    "state": "active",
    "remaining_sec": 847,
    "total_sec": 1500,
    "task_key": "DEV-1234",
    "task_summary": "Refactor auth middleware",
    "pomodoro_number_today": 4
  }
}
```

- `state` enum: `idle`, `active`, `paused`, `short_break`, `long_break`
- `task_key` null dla "loose" pomodoro bez przypisanego taska
- Wysyłane co 1s gdy `active` (do timera), na zmianę stanu zawsze

### `fullscreen` — overlay przerwy / reminderów

```json
{
  "v": 1,
  "type": "fullscreen",
  "data": {
    "kind": "break_short",
    "title": "Krótka przerwa",
    "message": "Wstań i napij się wody",
    "submessage": "Spójrz przez okno na coś oddalonego o 6 metrów przez 20 sekund.",
    "duration_sec": 300,
    "activities": ["water", "eyes", "stretch"],
    "dismissible": true
  }
}
```

- `kind` enum: `break_short`, `break_long`, `water`, `eyes`, `standup`
- `activities` — lista ikon do pokazania (`water`, `eyes`, `stretch`, `walk`)

### `standup_brief`

```json
{
  "v": 1,
  "type": "standup_brief",
  "data": {
    "date": "2026-05-17",
    "jira_closed": [
      {"key": "DEV-1230", "summary": "Fix login redirect"}
    ],
    "prs_merged": [
      {"title": "Update auth tokens", "repo": "backend"}
    ],
    "commits": [
      {"repo": "backend", "count": 8},
      {"repo": "frontend", "count": 4}
    ]
  }
}
```

### `macro_list`

```json
{
  "v": 1,
  "type": "macro_list",
  "data": {
    "macros": [
      {
        "id": "start_work",
        "label": "Start work",
        "subtitle": "IDE + Slack + Jira",
        "icon": "play",
        "color": "green"
      }
    ]
  }
}
```

- `icon` — Tabler icon name lub własna mapowana w firmware
- `color` enum: `green`, `coral`, `blue`, `purple`, `amber`, `gray`, `pink`, `teal`

### `toast` — krótkie powiadomienie

```json
{
  "v": 1,
  "type": "toast",
  "data": {
    "level": "info",
    "text": "Jira synced"
  }
}
```

- `level` enum: `info`, `warning`, `error`

### `heartbeat`

```json
{"v": 1, "type": "heartbeat", "data": {}}
```

---

## Wiadomości ESP → host

### `hello` — po starcie firmware

```json
{
  "v": 1,
  "type": "hello",
  "data": {
    "firmware_version": "0.1.0",
    "free_heap": 152340,
    "psram_free": 8123456
  }
}
```

Host odpowiada pełnym snapshotem stanu (wszystkie ekrany + top_bar + pomodoro_state).

### `screen_changed`

```json
{
  "v": 1,
  "type": "screen_changed",
  "data": {"screen": 2, "via": "swipe"}
}
```

- `via` enum: `swipe`, `dot_click`, `autoscroll`

### `task_clicked` — z ekranu 1, start pomodoro

```json
{
  "v": 1,
  "type": "task_clicked",
  "data": {"key": "DEV-1234"}
}
```

### `pomodoro_action`

```json
{
  "v": 1,
  "type": "pomodoro_action",
  "data": {"action": "pause"}
}
```

- `action` enum: `pause`, `resume`, `stop_with_log`, `cancel`, `start_loose`, `skip_break`

### `meeting_join`

```json
{
  "v": 1,
  "type": "meeting_join",
  "data": {"id": "abc123"}
}
```

Host wywołuje `xdg-open <meet_url>`.

### `notification_action`

```json
{
  "v": 1,
  "type": "notification_action",
  "data": {"id": "n2"}
}
```

Host wywołuje `xdg-open <action_url>` lub specyficzny handler per source.

### `todo_toggle`

```json
{
  "v": 1,
  "type": "todo_toggle",
  "data": {"id": "line_3", "done": true}
}
```

Host edytuje plik `todo.md` zamieniając `- [ ]` na `- [x]` w danej linii.

### `macro_trigger`

```json
{
  "v": 1,
  "type": "macro_trigger",
  "data": {"id": "start_work"}
}
```

### `standup_request`

```json
{"v": 1, "type": "standup_request", "data": {}}
```

Host generuje brief, odpowiada `standup_brief`.

### `fullscreen_dismiss`

```json
{
  "v": 1,
  "type": "fullscreen_dismiss",
  "data": {"kind": "break_short"}
}
```

### `ack` (opcjonalny)

```json
{"v": 1, "type": "ack", "data": {"of_type": "screen_1"}}
```

### `heartbeat`

```json
{"v": 1, "type": "heartbeat", "data": {}}
```

---

## Walidacja po stronie hosta

Wszystkie typy wiadomości jako pydantic models w `bridge/protocol.py`:

```python
from pydantic import BaseModel, Field
from typing import Literal

class TopBarData(BaseModel):
    time: str
    date: str
    weather: WeatherInfo
    claude_usage: ClaudeUsage
    pomodoros_today: int
    connected: bool = True

class TopBarMessage(BaseModel):
    v: Literal[1] = 1
    type: Literal["top_bar"] = "top_bar"
    data: TopBarData
```

Przy wysyłce: `bridge.send(TopBarMessage(data=...))` → serializacja JSON → linia → `/dev/ttyACM0`.

Przy odbiorze: parse JSON → dispatch po `type` → walidacja modelu → handler.

## Test harness

W `tests/test_protocol.py`:

- Round-trip każdej wiadomości (model → JSON → model = identity).
- Mock serial bridge dla testów daemon bez fizycznego ESP.
- Replay zapisanej sesji wiadomości jako fixture.
