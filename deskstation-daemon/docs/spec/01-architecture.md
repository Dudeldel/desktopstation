# Architektura systemu

## Diagram wysokopoziomowy

```
┌─────────────────────────────────────────────────────────────────────┐
│                         UBUNTU HOST                                 │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                    DESKSTATION DAEMON                        │   │
│  │                                                              │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐      │   │
│  │  │ Jira     │  │ Bitbucket│  │ Google   │  │ Gmail    │      │   │
│  │  │ poller   │  │ poller   │  │ Calendar │  │ poller   │      │   │
│  │  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘      │   │
│  │       │             │             │             │            │   │
│  │  ┌────▼─────┐  ┌────▼─────┐  ┌────▼─────┐  ┌────▼─────┐      │   │
│  │  │ Google   │  │ dbus     │  │ Pomodoro │  │ Todo.md  │      │   │
│  │  │ Chat     │  │ listener │  │ engine   │  │ watcher  │      │   │
│  │  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘      │   │
│  │       │             │             │             │            │   │
│  │  ┌────▼─────┐  ┌────▼─────┐  ┌────▼─────┐                    │   │
│  │  │ Weather  │  │ Claude   │  │ Macro    │                    │   │
│  │  │ poller   │  │ usage    │  │ executor │                    │   │
│  │  └────┬─────┘  └────┬─────┘  └────┬─────┘                    │   │
│  │       │             │             │                          │   │
│  │  ┌────▼─────────────▼─────────────▼─────────────────────┐    │   │
│  │  │                  STATE STORE (SQLite)                │    │   │
│  │  └────┬─────────────────────────────────────────────────┘    │   │
│  │       │                                                      │   │
│  │  ┌────▼─────────────────────────────────────────────────┐    │   │
│  │  │              SERIAL BRIDGE (USB CDC)                 │    │   │
│  │  │  - JSON line protocol                                │    │   │
│  │  │  - bidirectional (push state, receive commands)      │    │   │
│  │  │  - heartbeat + reconnect logic                       │    │   │
│  │  └────┬─────────────────────────────────────────────────┘    │   │
│  └───────┼──────────────────────────────────────────────────────┘   │
│          │                                                          │
│      /dev/ttyACM0                                                   │
└──────────┼──────────────────────────────────────────────────────────┘
           │
           │ USB (CDC Serial, 921600 baud)
           │
┌──────────▼──────────────────────────────────────────────────────────┐
│                  ESP32-S3 (Waveshare 7" LCD)                        │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                  SERIAL PROTOCOL HANDLER                     │   │
│  │                  (parses JSON, dispatches)                   │   │
│  └──────────────────────┬───────────────────────────────────────┘   │
│                         │                                           │
│  ┌──────────────────────▼───────────────────────────────────────┐   │
│  │                    UI STATE MANAGER                          │   │
│  │  - current screen (1/2/3/4 + macro overlay)                  │   │
│  │  - pomodoro state (idle/active/break/paused)                 │   │
│  │  - cached data for each screen                               │   │
│  └──────────────────────┬───────────────────────────────────────┘   │
│                         │                                           │
│  ┌──────────────────────▼───────────────────────────────────────┐   │
│  │                  LVGL RENDERER (8.x)                         │   │
│  │  - Top bar (always-on)                                       │   │
│  │  - Carousel screens (1/2/3/4)                                │   │
│  │  - Fullscreen overlays (pomodoro, reminders, macros)         │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

## Filozofia podziału

**ESP32 jest renderer'em + input handler'em.** Bez stanu biznesowego, bez logiki API. Powody:
- Łatwiejszy debug — wszystko co istotne dzieje się na hoście, gdzie mam pełnoprawny Python i logi.
- Łatwiejsza iteracja — zmiana w logice biznesowej nie wymaga reflash firmware.
- Bezpieczeństwo — secrets (tokens API) nigdy nie trafiają na ESP, zostają na hoście.
- Wydajność — pollery API by zarżnęły ESP, na hoście są trywialne.

**Host pcha snapshoty.** Bez diff'ów, bez stanu rozmytego między dwoma końcami. Kiedy zmienia się cokolwiek na ekranie X → host wysyła pełny `screen_X` payload. Powody:
- Prostota — ESP po prostu zastępuje swoje cached data.
- Recovery — po reboot ESP, host pcha snapshot wszystkiego, ESP się odbudowuje.
- Idempotencja — multiple wysłania tej samej wiadomości = ten sam wynik.

**ESP wysyła zdarzenia.** Pozostaje cienki klient: `task_clicked`, `meeting_join`, `macro_trigger`. Host reaguje (np. uruchamia pomodoro, otwiera URL, exec'uje proces).

## Kluczowe komponenty hosta

### Pollers (`pollers/`)

Każdy poller to async task w głównej event loop, pollujący API w swoim interwale. Schemat:

```python
async def jira_poller():
    while True:
        try:
            data = await fetch_jira_data()
            await state_store.update("jira", data)
            await ui_state.recompute_screen_1()
        except Exception:
            logger.exception("jira poll failed")
        await asyncio.sleep(60)
```

Pollery są niezależne — failure jednego nie wpływa na inne.

### Listeners (`listeners/`)

Event-driven, nie pollują. Np. `watchdog` na pliku todo, dbus signal handler. Reagują na zdarzenia natychmiast.

### Engines (`engines/`)

Trzymają stan biznesowy w pamięci (+ persistence w SQLite gdzie potrzeba). Pomodoro engine to klasyczny state machine. Standup engine generuje raport on-demand z innych źródeł.

### Executors (`executors/`)

Wykonują polecenia hosta: `subprocess.run` na komendy z `config.yaml`, `xdg-open` na URL-e, edytowanie plików.

### State store (SQLite)

Trzyma:
- Historię pomodoro (do countera dziennego + statystyk w przyszłości)
- Cache ostatnich danych z API (do graceful degradation gdy net off)
- Ostatnie pozycje plików (gdzie był todo.md przed zmianą)

### Serial bridge (`bridge/`)

Async reader/writer dla `/dev/ttyACM0`. Walidacja pydantic przed wysyłką. Heartbeat task. Reconnect on disconnect. **Krytyczny komponent — wszystko inne na nim stoi.**

### UI state aggregator (`ui_state.py`)

Subskrybuje zmiany ze wszystkich modułów. Rebuilduje payload-y dla każdego ekranu. Wysyła do `serial_bridge`. Rate-limit per screen (max 5 update/s).

## Komunikacja: kierunki przepływu

**Host → ESP:**
- Update'y stanu (top_bar, screen_1..4, pomodoro_state, fullscreen, standup_brief, macro_list)
- Toasty / błędy
- Heartbeat

**ESP → Host:**
- User actions (task_clicked, meeting_join, notification_action, todo_toggle, macro_trigger, pomodoro_action, fullscreen_dismiss)
- Stan UI (screen_changed)
- Heartbeat pongi
- Hello po starcie

## Decyzje technologiczne — uzasadnienie

### Python + asyncio (host)

- Wszystkie integracje mają dojrzałe biblioteki: `atlassian-python-api`, `google-api-python-client`, `dbus-next`.
- Jedna pętla obsłuży wszystkie pollery równolegle bez wątków.
- Szybka iteracja, łatwy hot-reload w trakcie pracy.
- Markdown todo.md = trywialny parsing regexem.

**Czemu nie Node:** dbus support gorszy, mniej dojrzałe klienty Google Workspace.
**Czemu nie Rust:** overkill dla I/O-bound poller'ów, więcej kodu pod każdą integrację.
**Czemu nie Go:** klient Atlassian/Google mniej dojrzały.

### ESP-IDF + LVGL 8.x (firmware)

- Waveshare daje gotowy BSP dla tej płytki.
- LVGL ma carousel, animacje, touch out-of-the-box.
- USB CDC działa pewniej w ESP-IDF niż w Arduino.
- Pełna kontrola task scheduling przez FreeRTOS.

**Czemu nie Arduino:** mniej kontroli, gorszy support USB CDC, wolniejszy build.
**Czemu nie MicroPython:** za wolne dla LVGL na 800×480 z animacjami.

### USB CDC zamiast WiFi

- Stacja stoi przy hoście — kabel naturalny.
- Zero konfiguracji sieci, zero auth (host wie który `/dev/ttyACM0` to stacja).
- Zasilanie z tego samego kabla.
- Latency rzędu 1ms zamiast 10–100ms dla WebSocket.
- ESP może być w trybie offline-wifi, nie traci nic.

### SQLite zamiast plików JSON

- Atomicność zapisów (ACID).
- Łatwe query historyczne (counter pomodoro per day, statystyki).
- Jedna ścieżka pliku, brak rozproszenia.

## Bezpieczeństwo

- **Secrets** (tokens API, OAuth refresh) w `~/.config/deskstation/secrets.yaml`, mode 0600, nigdy w repo.
- **OAuth tokens** Google: tylko `refresh_token` long-lived, access tokeny short-lived w pamięci.
- **dbus listener** filtruje powiadomienia tylko z whitelist'y app_name (Chrome + lista hostów).
- **Macro executor** komendy z config.yaml — read-only po starcie daemon. Brak eval/exec z user input z UI (ESP nie może wstrzyknąć arbitrary command).
- **Serial** plaintext, ale lokalny — kabel USB nie wychodzi z pokoju.

## Obserwowalność

- `structlog` z JSON output → `~/.local/share/deskstation/logs/daemon.jsonl`
- Każdy poller loguje sukces/failure
- Metryki: czas trwania pollu per API, liczba wiadomości w/out per sekundę
- ESP loguje przez UART (port 6 na płytce — osobny od USB CDC) podczas dev'u
