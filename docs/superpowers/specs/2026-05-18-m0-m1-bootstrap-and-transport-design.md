# M0 + M1 — Bootstrap + Transport USB serial

**Status:** approved (brainstorm 2026-05-18)
**Scope:** fazy M0 i M1 z roadmapy, scalone w jeden spec
**Cel końcowy:** żywy, niezawodny kanał komunikacji host ↔ ESP32 po USB CDC, z heartbeat / reconnect / minimalnym zestawem wiadomości. Wszystko inne (UI, pollery, engines) odłożone na M2+.

---

## 1. Repo layout

Monorepo, jedno repo na GitHubie (`github.com/Dudeldel/desktopstation`). Dwa samodzielne subprojekty współdzielą dokumentację, ale każdy ma swój build system.

```
desktopstation/                                                  ← git root
├── README.md
├── CLAUDE.md                                                    ← guidance dla Claude Code
├── .gitignore                                                   ← top-level (patrz niżej)
├── docs/                                                        ← jedno źródło prawdy
│   ├── plan/00-roadmap.md
│   ├── spec/01-architecture.md
│   ├── spec/02-serial-protocol.md
│   ├── spec/03-project-structure.md                             ← edit: "Dwa osobne repo" → "Monorepo"
│   ├── spec/04-pomodoro-engine.md
│   ├── designs/*.html + styles.css
│   └── superpowers/specs/2026-05-18-m0-m1-bootstrap-and-transport-design.md
├── deskstation-daemon/                                          ← scaffold w sekcji 2
└── deskstation-firmware/                                        ← scaffold w sekcji 3
```

**Zmiana względem dotychczasowego stanu:** konsolidujemy zduplikowane `deskstation-daemon/docs/` i `deskstation-firmware/docs/` do jednego top-level `docs/`. Top-level luźne pliki (`00-roadmap.md`, `01-architecture.md`, `02-serial-protocol.md`, `03-project-structure.md`, `04-pomodoro-engine.md`, `00-all-screens.html`) są starszymi kopiami — usuwamy.

**Dlaczego monorepo zamiast dwóch repo (wbrew spec/03):** zmiana w serial protokole dotyka obu stron i musi iść atomic; jeden remote/jeden PR minimalizuje ryzyko desynchronizacji. Spec/03 zostanie zaktualizowany.

### `.gitignore` (top-level)

Jeden plik na root, sekcje per subdir:

```
# Daemon (Python)
deskstation-daemon/.venv/
deskstation-daemon/__pycache__/
deskstation-daemon/**/__pycache__/
deskstation-daemon/*.egg-info/
deskstation-daemon/.pytest_cache/
deskstation-daemon/.mypy_cache/
deskstation-daemon/.ruff_cache/
deskstation-daemon/config.yaml          # local override, secrets-adjacent
deskstation-daemon/.env                 # local secrets

# Firmware (ESP-IDF)
deskstation-firmware/build/
deskstation-firmware/sdkconfig          # resolved config; commitujemy tylko .defaults
deskstation-firmware/sdkconfig.old
deskstation-firmware/managed_components/
deskstation-firmware/dependencies.lock

# Logi (gdyby ktoś uruchomił daemon z lokalnymi flagami)
*.jsonl

# IDE / OS
.vscode/
.idea/
.DS_Store
```

---

## 2. Daemon scaffold (host, Python)

### Stack

- Python 3.11+
- `uv` (zarządzanie venv + deps + lock + entry script)
- `pydantic` v2.5+ (modele wiadomości protokołu)
- `pydantic-settings` (config z YAML + env)
- `pyserial-asyncio` (USB CDC)
- `pyyaml` (config)
- `python-dotenv` (env override w dev)
- `structlog` (JSON logging)
- dev: `ruff`, `mypy --strict`, `pytest`, `pytest-asyncio`, `pre-commit`

### Struktura katalogów

```
deskstation-daemon/
├── README.md                       ← jak postawić & uruchomić (krok-po-kroku)
├── pyproject.toml
├── uv.lock                         ← committed
├── .python-version                 ← 3.11
├── config.yaml.example             ← tylko serial.* dla M0+M1
├── .env.example                    ← pusty placeholder dla M0+M1
├── .pre-commit-config.yaml
│
├── src/deskstation/
│   ├── __init__.py
│   ├── __main__.py                 ← `python -m deskstation`
│   ├── main.py                     ← asyncio entry, signal handlers
│   ├── config.py                   ← pydantic-settings, YAML + env
│   ├── logging_setup.py            ← structlog JSON → plik + pretty console
│   └── bridge/
│       ├── __init__.py
│       ├── interface.py            ← typing.Protocol: BridgeProtocol
│       ├── serial_bridge.py        ← pyserial-asyncio impl + reconnect
│       ├── mock_bridge.py          ← in-memory kolejki do testów
│       └── protocol.py             ← pydantic modele dla 5 wiadomości M1
│
└── tests/
    ├── conftest.py
    ├── test_protocol.py
    └── test_bridge.py
```

### Bridge — interfejs i dwie implementacje

`bridge/interface.py` definiuje `typing.Protocol`:

```python
class BridgeProtocol(Protocol):
    async def send(self, envelope: Envelope) -> None: ...
    def stream(self) -> AsyncIterator[Envelope]: ...
    async def close(self) -> None: ...
```

`serial_bridge.py` to produkcyjna implementacja oparta o `pyserial-asyncio`. `mock_bridge.py` to test-friendly implementacja: dwie `asyncio.Queue` (inbound, outbound); `send` puszcza na outbound, `stream` yielduje z inbound. Testy mogą wstrzykiwać i odbierać.

Wybór bridge'a w `main.py` po config: `bridge.mode: serial | mock`. Mock-mode przydaje się też w dev gdy ESP nie jest podłączony.

### Heartbeat & reconnect

Osobny `asyncio.Task` `heartbeat_task`:
- Push `Envelope(type="heartbeat", data=HeartbeatData())` co 5 sekund.
- Track ostatni RX heartbeat timestamp (in-memory, bez persistence).
- Brak RX > 15 s: log `event=disconnected`. Po następnym przyjętym heartbeat: log `event=reconnected`, wyślij ponowny stan (w M1 to znaczy: nic — bo nie ma jeszcze snapshotów).

Reconnect po stronie `SerialBridge`:
- W pętli `stream()`: na `OSError` (wyrwany kabel) → zamknij port → `asyncio.sleep(config.serial.reconnect_interval_sec)` → spróbuj otworzyć ponownie → kontynuuj.
- Brak limitu prób — leci aż wróci.

### Signal handlers

W `main.py`:
- `SIGTERM`, `SIGINT` → set event flag → wszystkie taski mają sprawdzać flagę między iteracjami.
- Graceful shutdown: cancel taski, await wszystkie, `bridge.close()`, flush structlog.

### Logging

`structlog` z JSON renderer:
- File handler: `~/.local/share/deskstation/logs/daemon.jsonl` (one event per line)
- Console handler: pretty format, tylko gdy `--dev` flag (default off)
- Standardowe pola: `timestamp`, `level`, `event`, dodatkowe dowolne `kwargs`

### Config (M0+M1 minimum)

`config.yaml.example`:

```yaml
serial:
  device: /dev/ttyACM0
  baudrate: 921600
  reconnect_interval_sec: 2

bridge:
  mode: serial  # alternatywa: mock
```

`.env.example` pusty z komentarzem "secrets pojawią się w M4+".

### Co NIE robimy w daemon-side M0+M1

SQLite, pollery, listeners, engines, executors, `ui_state.py`, integracje API. Wszystko to dochodzi w M2+ per faza.

---

## 3. Firmware scaffold (ESP32-S3, ESP-IDF + LVGL)

### Stack

- ESP-IDF v5.x (świeży install w M0)
- LVGL 8.x (przez ESP component manager)
- Waveshare BSP dla ESP32-S3-Touch-LCD-7 (git submodule)
- cJSON (wbudowany w ESP-IDF)
- TinyUSB (wbudowany w ESP-IDF, CDC ACM)

### Struktura katalogów

```
deskstation-firmware/
├── README.md                       ← setup + flash + monitor (zakłada zero ESP-IDF knowledge)
├── CMakeLists.txt
├── sdkconfig.defaults              ← commitowane, sdkconfig NIE (gitignore w root)
├── partitions.csv
├── idf_component.yml               ← lvgl/lvgl: "^8.4"
│
├── main/
│   ├── CMakeLists.txt              ← REQUIRES json, lvgl, waveshare_bsp, esp_tinyusb
│   ├── main.c                      ← app_main: init → start 4 task
│   ├── board.h / board.c           ← init LCD + touch + PSRAM przez Waveshare BSP
│   ├── usb_cdc.h / usb_cdc.c       ← TinyUSB CDC + 2 kolejki (RX/TX)
│   ├── protocol.h / protocol.c     ← cJSON parse/serialize envelope
│   ├── ui_state.h / ui_state.c     ← minimal: connection state + last toast
│   └── ui/
│       ├── ui.h / ui.c             ← LVGL: ekran "Hello, Deskstation. M0+M1." + widget toast
│       └── toast.h / toast.c       ← top-center label, fade-out po 3s
│
├── components/
│   └── waveshare_bsp/              ← git submodule
│
└── tools/
    ├── install_esp_idf.sh
    └── flash.sh                    ← skrót: idf.py build flash monitor -p /dev/ttyACM0
```

### `sdkconfig.defaults`

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
```

### FreeRTOS tasks (M1)

| Task | Core | Prio | Zadanie |
|---|---|---|---|
| `lvgl_task` | 1 | 2 | `lv_timer_handler()` co 5 ms |
| `usb_rx_task` | 0 | 5 | czyta bajt-po-bajcie z CDC, na `\n` → linia do RX queue |
| `usb_tx_task` | 0 | 5 | drenuje TX queue → pisze do CDC |
| `ui_dispatch_task` | 0 | 3 | drenuje RX queue → cJSON parse → dispatch handler |

Wszystkie taski rozpoczynają od `app_main()`. Kolejki to FreeRTOS `xQueueCreate` — RX queue `char* line` o pojemności np. 16, TX queue tak samo.

### Boot sequence (`app_main`)

1. Init PSRAM, LCD, touch (Waveshare BSP API), LVGL.
2. Init TinyUSB CDC.
3. Wystartuj 4 taski.
4. Wystaw na ekran fullscreen "Hello, Deskstation. M0+M1."
5. Push do TX queue: `{"v":1,"type":"hello","data":{"firmware_version":"0.1.0","free_heap":<int>,"psram_free":<int>}}` (heap/psram odczytane via `esp_get_free_heap_size()` / `heap_caps_get_free_size(MALLOC_CAP_SPIRAM)`).
6. Push do TX queue: `{"v":1,"type":"screen_changed","data":{"screen":0,"via":"autoscroll"}}` — sygnał że ESP→host kierunek działa (`screen:0` = boot/initial; firmware używa `via:"autoscroll"` jako placeholder dla zdarzeń niespowodowanych użytkownikiem).
7. Startuje wewnętrzny timer FreeRTOS — co 5 s push `heartbeat`, watch ostatni RX timestamp.

### Heartbeat firmware-side

Logika heartbeat-u idzie w `protocol.c` (organizacja plików zostaje na fazę writing-plans):
- Co 5 s push `heartbeat`.
- `last_rx_heartbeat_ms` atomic; jeśli `now - last > 15000` → wyświetl toast "Disconnected" (przez UI handler), nie crashuj.
- Po przyjętym heartbeat z hosta po disconnect: wyślij ponowny `hello` (uzasadnienie: host w przyszłości dostanie z tego sygnał do push pełnego snapshotu — w M1 to no-op).

### UI w M1 (minimum)

- Pełnoekranowy tekst "Hello, Deskstation. M0+M1." na środku. Czarne tło, biały tekst. Placeholder, zostanie wyrzucony w M2.
- Widget toast: kontener `lv_obj_t*` u góry ekranu, hidden domyślnie. `toast_show(text, level)` ustawia text, kolor (info/warn/error), pokazuje, ustawia `lv_timer` na fade-out po 3 s.
- Brak touch handlerów, brak carousel, brak top bar. Wszystko dochodzi w M2.

### Co NIE robimy w firmware-side M0+M1

Carousel, 4 ekrany, top bar, touch event handlers, autoscroll, fonty z polskimi znakami (na razie ASCII placeholder), `screen_X` rendery, fullscreen overlays.

---

## 4. Serial protocol — M1 subset

### Wybór typów

| Kierunek | Typ | Cel | Payload |
|---|---|---|---|
| obie strony | `heartbeat` | keepalive, 5s interval | `{}` |
| host → ESP | `toast` | krótkie powiadomienie u góry | `{"text": "string", "level": "info\|warning\|error"}` |
| ESP → host | `ack` | (opcjonalne) ESP potwierdza odebraną wiadomość od hosta — w M1 użyteczne dla `toast`, dla debug | `{"of_type": "screen_1"}` |
| ESP → host | `hello` | po starcie / reconnect | `{"firmware_version": "0.1.0", "free_heap": 152340, "psram_free": 8123456}` |
| ESP → host | `screen_changed` | (testowe w M1) potwierdza ESP→host | `{"screen": 2, "via": "swipe\|dot_click\|autoscroll"}` |

Pola dokładnie odpowiadają `docs/spec/02-serial-protocol.md` (linie 334–471). Żadne pola nie są deferred — bierzemy pełne shape z spec/02.

**Uwaga o `ack`:** typ obsługiwany w protokole na obu końcach (model pydantic + handler firmware-side), ale wysyłka jest opcjonalna. W M1 firmware **nie musi** wysyłać ack na każdy toast — wystarczy że protokół to obsługuje gdyby kiedyś przyszedł. Daemon dostaje ack, loguje, nic z nim nie robi.

### Wire format

Newline-delimited JSON, UTF-8. Jedna wiadomość = jedna linia zakończona `\n`. Wersja `v=1` hardcoded.

```
{"v":1,"type":"toast","data":{"text":"Hello from host","level":"info"}}\n
```

### Modele daemon-side (`bridge/protocol.py`)

```python
class HelloData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    firmware_version: str
    free_heap: int
    psram_free: int

class HeartbeatData(BaseModel):
    model_config = ConfigDict(extra="forbid")

class ToastData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str
    level: Literal["info", "warning", "error"] = "info"

class AckData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    of_type: str

class ScreenChangedData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    screen: int
    via: Literal["swipe", "dot_click", "autoscroll"]

class Envelope(BaseModel):
    v: Literal[1] = 1
    type: Literal["hello", "heartbeat", "toast", "ack", "screen_changed"]
    data: HelloData | HeartbeatData | ToastData | AckData | ScreenChangedData
```

Discriminated union po `type` (pydantic v2 obsługuje to nativnie z `Field(discriminator="type")` — szczegół implementacyjny w fazie writing-plans).

### Error handling, obie strony

1. **Malformed JSON** (parse fail) — log warn + skip. Nigdy crash.
2. **Unknown type** — log warn + skip. Forward-compat: M2 dorzuca nowe typy, M1 firmware/daemon je ignoruje.
3. **Validation fail** (np. `toast` bez `text`) — log warn + skip.
4. **`v != 1`** — log warn + skip. W M1 obsługujemy tylko v=1.
5. **Linia > 4 KB** — log warn + drop. Zabezpieczenie przed garbage po reconnect.

### Versioning

Pole `v` przy każdej wiadomości. Breaking change w przyszłości → bump na `v=2`, oba końce mogą obsługiwać oba okres przejściowy. W M1 wszystko hardcoded `v=1`.

### Konsekwencja dla monorepo

Daemon i firmware mają **dokładnie te same 5 typów**. Dodanie nowego typu (np. `top_bar` w M2) musi iść atomic, w jednym commicie dotykającym obu subdirów. Uzasadnienie dla monorepo.

---

## 5. Strategia testów

### 5.1 Daemon-side (pytest, headless)

`tests/test_protocol.py`:
- Per typ M1: seriaizuj → string → parsuj z powrotem → wynik struct-equal.
- Reject malformed: pusty string, JSON bez `v`, `v=2`, unknown `type`, brak `data`, `data` bez wymaganego pola.
- Linia > 4 KB → rejected.

`tests/test_bridge.py` z `mock_bridge`:
- Roundtrip: daemon push `toast` → mock odbiera z outbound queue → assertion na zawartość.
- Heartbeat: po 5 s daemon wysyła heartbeat (czas fake'owany przez `asyncio` event loop time advance albo `freezegun`).
- Disconnect timeout: brak RX > 15 s (fake-time) → daemon loguje `disconnected`.
- Reconnect simulation: zamknij mock, otwórz → daemon wraca i wysyła ponowny `hello` po przyjętym z drugiej strony heartbeacie.

Cel czasowy: cały suite <2 s, deterministyczny.

### 5.2 Firmware-side (compile-only)

`idf.py build` musi przechodzić bez warningów na `-Wall -Wextra`. Unit testy Unity/CMock odkładamy — w M1 nieadekwatne do ROI.

### 5.3 Hardware-in-the-loop (manualnie, na płytce)

Checklist sprzętowa — uruchamiasz po podłączeniu ESP:

- [ ] `idf.py build flash monitor -p /dev/ttyACM0` przechodzi; ESP wyświetla "Hello, Deskstation. M0+M1."
- [ ] `uv run deskstation` startuje, loguje `event=ready` do `~/.local/share/deskstation/logs/daemon.jsonl`
- [ ] Daemon loguje `event=hello_received` z `firmware_version=0.1.0`
- [ ] Daemon loguje `event=screen_changed_received` z `screen=boot`
- [ ] Wysyłka toast z hosta (przez dev REPL / sygnał) → toast widoczny na ESP, znika po 3 s
- [ ] Heartbeat: oba kierunki logują przyjęcie co 5 s
- [ ] **Disconnect test:** wyciągnij kabel USB. Po 15 s daemon loguje `disconnected`, ESP pokazuje toast "Disconnected".
- [ ] **Reconnect test:** podłącz kabel. Bez restartu obu stron: daemon wraca, ESP wysyła `hello`, daemon przyjmuje.
- [ ] **30-min soak test:** oba uruchomione, zero crashów, logi czyste, brak rosnącego heap usage na ESP.

### 5.4 Tryb mock daemona

`config.yaml` opcja `bridge.mode: mock`. Daemon używa `MockBridge` zamiast `SerialBridge` — startuje bez ESP. Przyda się gdy w przyszłych fazach iterujemy logikę bez ciągłego flashowania.

---

## 6. Definicja done

### Automatyczna (CI-able)

1. `uv run pytest -v` zielone, <2 s.
2. `uv run ruff check && uv run mypy src/` bez błędów.
3. `idf.py build` w `deskstation-firmware/` przechodzi bez warningów.
4. `uv run pre-commit run --all-files` przechodzi.

### Hardware (manualnie wieczorem)

Wszystkie 9 punktów z sekcji 5.3 zhaczkowane.

---

## 7. Pliki

### Tworzone

**Top-level:**
- `.gitignore`
- `.gitmodules` (powstaje przy `git submodule add` dla Waveshare BSP)
- `docs/` (przeniesienie z dwóch zduplikowanych kopii)
- `docs/superpowers/specs/2026-05-18-m0-m1-bootstrap-and-transport-design.md` (ten dokument)

**`deskstation-daemon/`:**
- `README.md`, `pyproject.toml`, `uv.lock`, `.python-version`, `config.yaml.example`, `.env.example`, `.pre-commit-config.yaml`
- `src/deskstation/`: `__init__.py`, `__main__.py`, `main.py`, `config.py`, `logging_setup.py`
- `src/deskstation/bridge/`: `__init__.py`, `interface.py`, `serial_bridge.py`, `mock_bridge.py`, `protocol.py`
- `tests/`: `conftest.py`, `test_protocol.py`, `test_bridge.py`

**`deskstation-firmware/`:**
- `README.md`, `CMakeLists.txt`, `sdkconfig.defaults`, `partitions.csv`, `idf_component.yml`
- `main/`: `CMakeLists.txt`, `main.c`, `board.h`, `board.c`, `usb_cdc.h`, `usb_cdc.c`, `protocol.h`, `protocol.c`, `ui_state.h`, `ui_state.c`
- `main/ui/`: `ui.h`, `ui.c`, `toast.h`, `toast.c`
- `components/waveshare_bsp/` (git submodule)
- `tools/install_esp_idf.sh`, `tools/flash.sh`

### Zmieniane

- `docs/spec/03-project-structure.md` — sekcja "Dwa osobne repozytoria" zmieniana na "Monorepo (jedno repo, dwa subdir-y, jedna ścieżka docs)"
- `CLAUDE.md` (top-level) — aktualizacja sekcji "Repository state" (kod istnieje już po M0+M1) i sekcji "Working with this repo" (komendy build/test/run)
- `README.md` (top-level) — dorzucamy sekcję "Quick start" z komendami dla daemona i firmware'u

### Usuwane

- Top-level: `00-all-screens.html`, `00-roadmap.md`, `01-architecture.md`, `02-serial-protocol.md`, `03-project-structure.md`, `04-pomodoro-engine.md`
- `deskstation-daemon/docs/`, `deskstation-firmware/docs/` (zduplikowane, zastąpione przez `docs/`)

---

## 8. Poza scope (świadomie odłożone na M2+)

| Komponent | Dochodzi w |
|---|---|
| Top bar, carousel, 4 ekrany, touch handlers | M2 |
| Mock data generator pollerów | M2 |
| `ui_state.py` aggregator | M2 |
| Pomodoro engine, fullscreen focus, breaks | M3 |
| SQLite store (pierwsza realna potrzeba: historia pomodoro) | M3 |
| Jira/Bitbucket pollers | M4 |
| Gmail/Chat/Calendar pollers, dbus listener | M5 |
| Todo watcher, makra, standup, reminders, pogoda, Claude usage | M6 |
| systemd service, OAuth refresh w pełni, offline tolerance, OTA | M7 |
| Wszystkie pozostałe typy wiadomości protokołu | per faza M2+ |
| GitHub Actions CI | nie wpisane w M0+M1; pre-commit lokalnie daje >80% korzyści |
| Unit testy firmware (Unity/CMock) | rozważymy w M2 jeśli będzie potrzeba |

---

## 9. Założenia i ryzyka

- **Setup ESP-IDF v5.x może trwać dłużej** niż 1–2h. Plan implementacji wyniesie go na początek, żeby blok firmware nie zatrzymał daemon-side.
- **Waveshare BSP** wymaga że pinout/init pasują do konkretnej rewizji płytki ESP32-S3-Touch-LCD-7. Jeśli rev różni się — może trzeba dostosować `board.c`. Diagnostyka: jeśli LCD nie świeci, sprawdzamy rev w README Waveshare.
- **`/dev/ttyACM0` może być inne** (np. `/dev/ttyACM1` jeśli inne CDC podpięte). Config to obsługuje. README wyjaśni jak sprawdzić: `ls /dev/ttyACM*` lub `dmesg | tail`.
- **uv musi być zainstalowane lokalnie** przed odpaleniem daemon — README daemona ma instrukcję `pipx install uv` lub curl installer.
- **Hardware test przesunięty** — user nie ma teraz podłączonej płytki; sekcja 5.3 wykona się po podłączeniu (wieczorem).
