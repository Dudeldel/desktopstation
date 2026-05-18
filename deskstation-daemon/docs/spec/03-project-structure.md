# Struktura projektu

Dwa osobne repozytoria, niezależne lifecycle, niezależne wersjonowanie.

## `deskstation-daemon` (host, Python)

```
deskstation-daemon/
├── README.md
├── pyproject.toml
├── .env.example
├── config.yaml.example
├── .gitignore             # excludes config.yaml, .env, *.db, logs/
├── .pre-commit-config.yaml
│
├── src/deskstation/
│   ├── __init__.py
│   ├── __main__.py             # python -m deskstation
│   ├── main.py                 # asyncio entry, signal handlers
│   ├── config.py               # pydantic settings, load from yaml + env
│   │
│   ├── bridge/
│   │   ├── __init__.py
│   │   ├── serial_bridge.py    # USB CDC reader/writer
│   │   ├── protocol.py         # pydantic models for all messages
│   │   └── mock_bridge.py      # for testing without ESP
│   │
│   ├── pollers/
│   │   ├── __init__.py
│   │   ├── base.py             # Poller abstract class
│   │   ├── jira.py
│   │   ├── bitbucket.py
│   │   ├── gmail.py
│   │   ├── gchat.py
│   │   ├── calendar.py
│   │   ├── weather.py
│   │   ├── claude_usage.py
│   │   └── mock.py             # synthetic data for development
│   │
│   ├── listeners/
│   │   ├── __init__.py
│   │   ├── dbus_notifications.py
│   │   └── todo_file.py        # watchdog-based file watcher
│   │
│   ├── engines/
│   │   ├── __init__.py
│   │   ├── pomodoro.py         # state machine, timer, logging
│   │   ├── standup.py          # on-demand brief generator
│   │   └── reminders.py        # water/eyes/stretch scheduler
│   │
│   ├── executors/
│   │   ├── __init__.py
│   │   └── macros.py           # subprocess runner from config
│   │
│   ├── store/
│   │   ├── __init__.py
│   │   ├── sqlite.py           # connection, migrations
│   │   └── models.py           # SQLAlchemy or plain dataclasses
│   │
│   └── ui_state.py             # aggregator: builds screen payloads
│
├── tests/
│   ├── conftest.py
│   ├── test_protocol.py        # roundtrip all message types
│   ├── test_pomodoro.py        # state machine
│   ├── test_todo_parser.py
│   └── test_bridge.py          # with mock_bridge
│
└── scripts/
    ├── setup_oauth.py          # run once to get Google refresh tokens
    └── seed_db.py              # creates initial SQLite schema
```

### Kluczowe pliki w detalu

**`pyproject.toml` (sugerowane zależności):**

```toml
[project]
name = "deskstation"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "pyserial-asyncio>=0.6",
    "pydantic>=2.5",
    "pydantic-settings>=2.0",
    "pyyaml>=6.0",
    "python-dotenv>=1.0",
    "structlog>=24.0",
    "watchdog>=4.0",
    "atlassian-python-api>=3.41",
    "google-api-python-client>=2.0",
    "google-auth-oauthlib>=1.2",
    "dbus-next>=0.2.3",
    "httpx>=0.27",
    "aiosqlite>=0.20",
]

[project.optional-dependencies]
dev = ["ruff", "mypy", "pytest", "pytest-asyncio", "pre-commit"]

[project.scripts]
deskstation = "deskstation.__main__:main"

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.mypy]
strict = true
```

**`config.yaml.example`:**

```yaml
serial:
  device: /dev/ttyACM0
  baudrate: 921600
  reconnect_interval_sec: 2

jira:
  url: https://yourcompany.atlassian.net
  email: you@example.com
  api_token: ${JIRA_API_TOKEN}
  lead_project_key: PROJ
  my_tasks_jql: "assignee = currentUser() AND status IN ('Draft', 'To Do', 'In Progress')"
  poll_interval_sec: 60

bitbucket:
  workspace: yourcompany
  username: yourusername
  app_password: ${BITBUCKET_APP_PASSWORD}
  repos:
    - backend
    - frontend
    - infrastructure
  poll_interval_sec: 60

google:
  oauth_creds_path: ~/.config/deskstation/google_oauth.json
  token_path: ~/.config/deskstation/google_token.json

todo:
  file_path: ~/todo.md

weather:
  latitude: 51.1079
  longitude: 17.0385
  poll_interval_sec: 900

claude_usage:
  source: ccusage              # or "anthropic_api" or "disabled"

macros:
  - id: start_work
    label: "Start work"
    subtitle: "IDE + Slack + Jira"
    icon: play
    color: green
    commands:
      - ["code", "/home/user/projects/main"]
      - ["slack"]
      - ["xdg-open", "https://yourcompany.atlassian.net/jira/your-work"]

  - id: chrome_tabs
    label: "Chrome 6 tabs"
    subtitle: "Jira, Bitbucket, ..."
    icon: browser
    color: blue
    commands:
      - ["google-chrome", "--new-window",
         "https://jira.example.com",
         "https://bitbucket.example.com",
         "https://meet.google.com",
         "https://mail.google.com",
         "https://chat.google.com",
         "https://calendar.google.com"]
```

**`.env.example`:**

```
JIRA_API_TOKEN=
BITBUCKET_APP_PASSWORD=
```

---

## `deskstation-firmware` (ESP32, ESP-IDF + LVGL)

```
deskstation-firmware/
├── README.md
├── CMakeLists.txt
├── sdkconfig.defaults              # baseline ESP-IDF config
├── partitions.csv
├── .gitignore
│
├── main/
│   ├── CMakeLists.txt
│   ├── main.c                      # app_main entry
│   ├── board.h / board.c           # pins, LCD/touch init from Waveshare BSP
│   ├── usb_cdc.c / usb_cdc.h       # TinyUSB CDC reader/writer
│   ├── protocol.c / protocol.h     # JSON parsing, message types
│   ├── ui_state.c / ui_state.h     # cached state of all screens
│   │
│   └── ui/
│       ├── ui.c / ui.h             # LVGL init, top bar, carousel
│       ├── theme.c / theme.h       # colors, fonts, common styles
│       ├── top_bar.c
│       ├── screen_1_jira.c
│       ├── screen_2_messages.c
│       ├── screen_3_dev.c
│       ├── screen_4_todo.c
│       ├── overlay_pomodoro.c
│       ├── overlay_break.c
│       ├── overlay_standup.c
│       └── overlay_macros.c
│
├── components/
│   ├── waveshare_bsp/              # cloned from Waveshare repo
│   ├── lvgl/                       # LVGL 8.x as submodule or component
│   └── cjson/                      # JSON parser (in ESP-IDF by default)
│
└── tools/
    └── flash.sh                    # convenience: idf.py build flash monitor
```

### Sugerowany `sdkconfig.defaults`

```
CONFIG_TINYUSB_CDC_ENABLED=y
CONFIG_TINYUSB_CDC_RX_BUFSIZE=2048
CONFIG_TINYUSB_CDC_TX_BUFSIZE=2048

CONFIG_SPIRAM=y
CONFIG_SPIRAM_MODE_OCT=y
CONFIG_SPIRAM_USE_MALLOC=y
CONFIG_SPIRAM_MALLOC_ALWAYSINTERNAL=16384

CONFIG_FREERTOS_HZ=1000
CONFIG_ESP_TASK_WDT_TIMEOUT_S=10

CONFIG_LV_COLOR_DEPTH_16=y
CONFIG_LV_USE_PERF_MONITOR=y          # dev only, off na prod
```

### Najważniejsze decyzje firmware

**Dual framebuffer w PSRAM:** 800×480×2B = 750 KB per bufor, 1.5 MB razem. Mieści się luźno w 8 MB PSRAM.

**Tasks (FreeRTOS):**
- `lvgl_task` (core 1, priority 2) — tick + flush LVGL co 5 ms
- `usb_rx_task` (core 0, priority 5) — czyta z USB CDC do queue
- `usb_tx_task` (core 0, priority 5) — drenuje output queue, pisze do USB CDC
- `ui_dispatch_task` (core 0, priority 3) — drenuje rx queue, parsuje JSON, woła update'y UI

**Fonty:** Inter Medium / Regular zaprekompilowane w trzech rozmiarach (12, 14, 18, 36, 140 px). Polskie znaki via Unicode range w lv_font_conv. Plik fontu w `components/fonts/`.

**Ikony:** Tabler Icons jako font subset (tylko używane glify), albo SVG-to-LVGL convert. Zalecane font subset — prościej.

---

## Konwencje obu repo

### Branche

- `main` — stabilne, działa na biurku.
- `dev` — bieżące fazy implementacji.
- `feat/<faza>-<opis>` — pojedyncze ficzery, mergowane do `dev`.

### Commits

Konwencja [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(jira): add poller for my open tasks
fix(pomodoro): pause should freeze remaining_sec
chore(deps): bump pydantic to 2.5.3
```

### Tagi wersji

Semver: `v0.1.0` po M1, `v0.2.0` po M2, ..., `v1.0.0` po M7.

### CI (opcjonalne, ale pomocne)

- GitHub Actions: ruff + mypy + pytest na każdy push do `dev`/`main`.
- ESP-IDF: build w Docker action żeby sprawdzić że firmware się kompiluje.
