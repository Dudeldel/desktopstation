# Deskstation

Dedykowana stacja na biurko: dashboard pracy z integracjami Jira, Bitbucket, Google Workspace, komunikatorów, todo i makr, plus pomodoro z auto-loggingiem do Jiry.

## Hardware

- **Wyświetlacz:** Waveshare ESP32-S3-Touch-LCD-7
- **SoC:** ESP32-S3N16R8 (240 MHz dual-core LX7, 16 MB Flash, 8 MB PSRAM)
- **Panel:** 7" IPS 800×480, 65K kolorów, RGB interface
- **Touch:** Capacitive, 5-point, I²C
- **Połączenie z hostem:** USB Type-C (CDC ACM serial)
- **Host:** Ubuntu, Python 3.11+ daemon

## Architektura w skrócie

```
ESP32-S3 (LVGL UI) <--USB CDC--> Ubuntu daemon (Python asyncio) <--APIs--> Jira/Bitbucket/Google/dbus
```

ESP32 jest "głupim terminalem" — renderuje UI w LVGL, wysyła zdarzenia użytkownika, dostaje pełne snapshoty stanu. Cała logika i integracje na hoście.

## Struktura dokumentacji

- [`plan/`](plan/) — plan implementacji krok po kroku, kamienie milowe
- [`spec/`](spec/) — specyfikacja techniczna: protokół, struktura komponentów, decyzje architektoniczne
- [`designs/`](designs/) — mockupy UI wszystkich ekranów (HTML do podglądu w przeglądarce)

## Quick links

- [Roadmap](plan/00-roadmap.md) — pełny plan z fazami M0–M7
- [Architecture](spec/01-architecture.md) — diagram systemu, podział odpowiedzialności
- [Serial protocol](spec/02-serial-protocol.md) — format wiadomości host ↔ ESP32
- [UI screens](designs/README.md) — wizualne mockupy wszystkich widoków

## Stack

**Host (Ubuntu):**
- Python 3.11+, asyncio
- `pyserial-asyncio` — USB CDC
- `atlassian-python-api` — Jira, Bitbucket
- `google-api-python-client` — Gmail, Calendar, Chat
- `dbus-next` — notyfikacje Messenger/WhatsApp via Chrome
- `watchdog` — monitorowanie `todo.md`
- `SQLite` — lokalny cache stanu i historia pomodoro

**Firmware (ESP32-S3):**
- ESP-IDF v5.x
- LVGL 8.x
- Waveshare BSP dla tej płytki
- USB CDC ACM (TinyUSB)

## Quick start

Monorepo z dwoma subprojektami. Każdy ma własny setup.

### Daemon (host, Python)

Wymaga `uv` ([install guide](https://docs.astral.sh/uv/getting-started/installation/)) i Python 3.11+.

```bash
cd deskstation-daemon
uv sync --all-extras
cp config.yaml.example config.yaml         # edytuj jeśli chcesz
uv run deskstation                          # startuje daemon
uv run pytest                               # testy
```

### Firmware (ESP32-S3)

Wymaga Linuxa.

```bash
cd deskstation-firmware
bash tools/install_esp_idf.sh               # one-shot, ~15 min
. ~/esp/esp-idf/export.sh                   # aktywuje ESP-IDF
idf.py set-target esp32s3
bash tools/flash.sh /dev/ttyACM0            # build + flash + monitor
```

## Status

M0 + M1 done: bootstrap + niezawodny transport USB CDC z heartbeat + reconnect + 5 typami wiadomości (hello/heartbeat/toast/ack/screen_changed). UI to placeholder. Pełen plan w `docs/plan/00-roadmap.md`.
