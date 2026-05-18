# Roadmap — plan implementacji krok po kroku

Sumaryczny plan podzielony na 8 faz (M0–M7). Każda faza ma konkretny, weryfikowalny rezultat. Faza M0 to setup, M1 to pierwsze "hello world" przez kabel, dalej budujemy ekran po ekranie.

Sugerowana kolejność = kolejność najmniejszego ryzyka. **Najpierw dowieść że transport USB działa pewnie**, potem warstwa UI, potem integracje API.

---

## M0 — Setup środowiska i repozytoriów

Cel: gotowe środowisko deweloperskie po obu stronach. Bez integracji, bez UI, tylko że wszystko się kompiluje i flashuje.

### Host (Ubuntu)

1. Repo `deskstation-daemon`, struktura katalogów (patrz `spec/03-project-structure.md`).
2. `pyproject.toml` z `uv` albo `poetry`. Zależności: `pyserial-asyncio`, `pydantic`, `watchdog`, `pyyaml`, `python-dotenv`. Integracje API dodajemy w późniejszych fazach.
3. `config.yaml.example` z kompletem ustawień (puste klucze, ścieżki). `config.yaml` w `.gitignore`.
4. `main.py` z asyncio event loop, logger (`structlog`), graceful shutdown na SIGTERM.
5. `pre-commit` z `ruff` i `mypy` strict.

### Firmware (ESP32-S3)

1. Repo `deskstation-firmware`, ESP-IDF v5.x project.
2. Klonowanie BSP od Waveshare dla ESP32-S3-Touch-LCD-7 (link w docs Waveshare).
3. Podstawowy `main.c` z init panelu, init touch, init LVGL. Goal: wyświetlić "Hello World" na ekranie.
4. Konfiguracja USB CDC ACM (sdkconfig: `CONFIG_TINYUSB_CDC_ENABLED=y`).
5. Smoke test: po podłączeniu USB host widzi `/dev/ttyACM0`, można echo i odebrać po stronie ESP.

**Definicja ukończenia M0:**
- `cd deskstation-daemon && python -m deskstation` startuje bez błędu, loguje "ready"
- ESP32 po flashu wyświetla cokolwiek na ekranie
- Host: `echo "ping" > /dev/ttyACM0` → ESP loguje "ping" przez serial monitor

**Oczekiwany czas:** 1–2 wieczory

---

## M1 — Transport USB serial: wiadomości obie strony

Cel: solidny, niezawodny kanał komunikacji. **Wszystko inne stoi na tym, więc dopracować zanim ruszymy dalej.**

### Host

1. `bridge/serial_bridge.py` — `asyncio` reader + writer dla `/dev/ttyACM0`, 921600 baud.
2. Newline-delimited JSON parser (jeden komunikat = jedna linia).
3. `bridge/protocol.py` — `pydantic` modele dla każdego typu wiadomości (patrz `spec/02-serial-protocol.md`).
4. Heartbeat task: wysyła `{"v":1,"type":"heartbeat"}` co 5s, monitoruje brak pongów.
5. Reconnect logic: po `OSError` (odpięty kabel) próbuje co 2s aż wróci.
6. Test harness: tryb mock który drukuje wiadomości na stdout zamiast slać przez USB.

### Firmware

1. Task FreeRTOS: czyta z USB CDC, parsuje JSON (`cJSON`), kładzie do queue.
2. Task FreeRTOS: czyta z output queue, pisze do USB CDC.
3. Implementuje `heartbeat`, `ack`, `toast` (proste typy do testów).
4. Główny task UI nasłuchuje queue, na razie tylko loguje co przyszło.
5. Wysyła `{"v":1,"type":"hello","data":{"firmware_version":"0.1.0"}}` po połączeniu.

**Definicja ukończenia M1:**
- Host wysyła `toast` → ESP wyświetla małe powiadomienie u góry (placeholder).
- ESP wysyła `screen_changed` → host loguje.
- Heartbeat działa w obie strony, brak pongów > 15s = oba systemy oznaczają disconnect.
- Wyciągnięcie kabla i ponowne podłączenie = auto-recovery bez restartu.

**Oczekiwany czas:** 2–3 wieczory

---

## M2 — Warstwa UI: layout, pasek górny, karuzela 4 ekranów

Cel: cała struktura wizualna działa, ekrany pokazują dane mockowe podawane przez host.

### Firmware (większość pracy tutaj)

1. **LVGL theme:** ciemny motyw (#0d0d10 background, #16161a card, #1d9e75 accent). Custom font Inter/Source Sans Pro z polskimi znakami.
2. **Top bar (40px):** czas, data, pogoda, Claude usage, pomodoro counter, przycisk MAKRO. Updates z `top_bar` wiadomości.
3. **Carousel container (440px pod paskiem):** `lv_tileview` z 4 tilami, swipe lewo/prawo.
4. **Indykator pozycji** (kropki) pod paskiem.
5. **Autoscroll:** timer 10s przełącza na następny tile. **Touch event resetuje timer na 30s.** Pomodoro fullscreen wstrzymuje timer.
6. **Ekran 1** (Jira): layout dwukolumnowy + meeting bar na dole.
7. **Ekran 2** (Komunikacja): pełnoekranowa lista notyfikacji.
8. **Ekran 3** (Dev): PR-y lewa kolumna, CI + standup prawa.
9. **Ekran 4** (Todo): lista checkboxów.

Każdy ekran przyjmuje typ wiadomości (`screen_1`, `screen_2`, `screen_3`, `screen_4`), reren­deruje całość na pełnym snapshocie. Bez optymalizacji incremental update — full redraw przy każdej wiadomości.

### Host

1. **Mock data generator** w `pollers/mock.py`: co X sekund wysyła syntetyczne dane do każdego ekranu, żeby firmware miał czym renderować. Faktyczne integracje API dochodzą w M3–M5.
2. `ui_state.py` — aggregator który zbiera stan ze wszystkich modułów i pcha snapshoty do `serial_bridge`.

**Definicja ukończenia M2:**
- Wszystkie 4 ekrany renderują dane z mocków.
- Swipe lewo/prawo działa płynnie.
- Autoscroll co 10s, reset na touch, pauza w pomodoro.
- Pasek górny zawsze widoczny, wszystkie 5 elementów updateowane z host.
- UI nie freezuje przy szybkich update'ach (test: mock co 1s).

**Oczekiwany czas:** 1–2 tygodnie (najwięcej UI roboty)

---

## M3 — Pomodoro engine + integracja z ekranem 1

Cel: pomodoro w pełni funkcjonalny, łącznie z fullscreen, przerwami i counterem. Loggingu do Jiry jeszcze nie ma — będzie w M4.

### Host

1. `engines/pomodoro.py` — stan machine: `idle | active | paused | short_break | long_break`.
2. **Stany przejść:**
   - `task_clicked` (od ESP) → `active` z `task_key`, czas 25:00
   - `pomodoro_action.start_loose` → `active` bez `task_key`
   - `pomodoro_action.pause` → `paused`, zapamiętuje remaining time
   - `pomodoro_action.resume` → `active`, kontynuuje od tego punktu
   - `pomodoro_action.stop_with_log` → idle, **TODO: log do Jiry w M4**, counter +1, jeśli `pomodoros_today % 4 == 0` → `long_break` 20 min, inaczej `short_break` 5 min
   - `pomodoro_action.cancel` → idle, **bez logu**, **bez counter+1**
   - timer dochodzi do 00:00 → same co `stop_with_log`
3. **Counter dzienny:** reset o północy (cron-like task w asyncio). Przechowywany w SQLite.
4. Push `pomodoro_state` na każdej zmianie stanu + co 1s gdy active (do timera).
5. Push `fullscreen` typu `break_short` / `break_long` przy starcie przerwy.
6. Push `top_bar` update z `pomodoros_today` po każdym ukończonym pomidorze.

### Firmware

1. **Fullscreen overlay manager:** kiedy przyjdzie `pomodoro_state.state == "active"` → ekran focus mode (czarny + duży timer). `idle` → wraca do karuzeli.
2. **Break overlay:** kiedy przyjdzie `fullscreen.kind in (break_short, break_long)` → zielony ekran z reminderem + timer.
3. **Click handler na taskach (ekran 1):** wysyła `task_clicked` z keyem.
4. Przyciski Pause / Resume / Stop and Log / Cancel → wysyłają `pomodoro_action`.
5. Counter `🍅` w pasku górnym aktualizuje się z `top_bar` update.

**Definicja ukończenia M3:**
- Klik w taska na ekranie 1 (mock data) → pomodoro startuje, fullscreen focus.
- Po 25 min (lub stop_with_log) → przerwa 5 min, zielony ekran.
- Po 4 pomodorach → przerwa 20 min.
- Pause / resume / cancel działają.
- Counter w pasku górnym inkrementuje się, resetuje o północy.
- Cancel **nie inkrementuje** countera, stop_with_log **inkrementuje** nawet jeśli było 5 minut.

**Oczekiwany czas:** 1 tydzień

---

## M4 — Integracja Jira + Bitbucket (ekran 1 + 3)

Cel: realne dane zamiast mocków na ekranach 1 i 3. Pomodoro loguje czas do Jiry.

### Host

1. **Jira poller** (`pollers/jira.py`):
   - Query 1: moje taski w statusach Draft/To Do/In Progress (wszystkie projekty)
   - Query 2: wszystkie taski w aktywnym sprincie projektu PROJ (config: który projekt)
   - Query 3: sprint info (nazwa, start/end date, points done/total)
   - Status counts z query 2 (groupby status)
   - Poll co 60s
2. **Bitbucket poller** (`pollers/bitbucket.py`):
   - Moje otwarte PR-y (status=OPEN, author=me)
   - PR-y do mojego review (reviewer=me, status=OPEN)
   - Poll co 60s
   - CI/CD status: ostatni run pipeline'u na main + develop dla każdego repo (config: lista repo)
3. **Pomodoro → Jira worklog:** po `stop_with_log` jeśli `task_key != null`, wywołaj `jira.add_worklog(task_key, seconds=elapsed)`.
4. Cache w SQLite: zapamiętaj ostatnie dane, jeśli API timeout to pokaż stare + warning.

### Firmware

Bez zmian — protokół ten sam, tylko dane realne zamiast mocków.

**Definicja ukończenia M4:**
- Ekran 1 lewa: realne moje taski z Jiry, klik startuje pomodoro.
- Ekran 1 prawa: realny sprint projektu PROJ, taski z inicjałami przypisanych.
- Ekran 3 lewa: realne PR-y, posortowane (review najpierw, potem moje), wiek widoczny.
- Ekran 3 prawa: realne pipeline'y CI.
- Po pomodoro `stop_with_log` z taskiem: worklog widoczny w Jirze.

**Oczekiwany czas:** 1 tydzień

---

## M5 — Komunikacja (ekran 2) + Google Calendar (meetings na ekranie 1)

Cel: powiadomienia i spotkania.

### Host

1. **Gmail poller** (`pollers/gmail.py`):
   - Label INBOX, query `is:unread newer_than:1d`
   - Dla każdego: sender, subject, snippet, timestamp, message_id
   - Poll co 60s
   - OAuth2 setup (refresh token w `~/.config/deskstation/google_token.json`)
2. **Google Chat poller** (`pollers/gchat.py`):
   - Lista spaces, dla każdego ostatnie wiadomości
   - Filter: DM lub `@me` mention, unread
   - Poll co 60s
3. **dbus notification listener** (`listeners/dbus_notifications.py`):
   - Subskrybuje `org.freedesktop.Notifications` signal `Notify`
   - Filter po `app_name` — Chrome/Chromium z hint o WhatsApp/Messenger
   - Real-time push do ESP gdy przyjdzie nowa notyfikacja
   - Tip: testuj przez `notify-send -a "WhatsApp Web" "Marek" "test"`
4. **Google Calendar poller** (`pollers/calendar.py`):
   - Eventy na dziś + jutro
   - Filter: tylko z `hangoutLink` (= Google Meet)
   - Poll co 5 min, ale co 1 min jeśli najbliższe spotkanie < 30 min
   - Highlight `imminent=true` gdy `time_until_start < 15 min`
5. **Merge wszystkich źródeł** do uniformowej listy chronologicznej dla `screen_2`.

### Firmware

1. **Tap handler na notyfikacji:** wysyła `notification_action` z ID → host otwiera `xdg-open` z deeplinkiem.
2. **Tap handler na meetingu:** wysyła `meeting_join` z ID → host otwiera Meet URL w Chrome.

**Definicja ukończenia M5:**
- Ekran 2: realne nieprzeczytane z Gmail + Google Chat + dbus (WhatsApp/Messenger).
- Tap notyfikacja → otwiera w domyślnym kliencie/przeglądarce.
- Ekran 1 dół: realne nadchodzące Meets, < 15 min ma pomarańczową obwódkę.
- Tap "Dołącz" → otwiera Meet w Chrome (nowe okno).

**Oczekiwany czas:** 1.5 tygodnia (OAuth2 setup może zabrać)

---

## M6 — Todo, makra, standup, reminders, pogoda, Claude usage

Cel: domknięcie wszystkich pozostałych ficzerów MVP.

### Host

1. **Todo watcher** (`listeners/todo_file.py`):
   - `watchdog` na ścieżce z config (`config.todo_file_path`)
   - Parser markdown: `- [ ] tekst !priority #tag @YYYY-MM-DD`
   - Każda linia ma stabilne ID (numer linii + hash treści)
   - `todo_toggle` od ESP → edit pliku (zmiana `[ ]` na `[x]` w danej linii)
2. **Macro executor** (`executors/macros.py`):
   - Definicje makr w `config.yaml`: dla każdego makra `id`, `label`, `icon`, lista komend
   - `macro_trigger` od ESP → uruchom `subprocess.run` dla każdej komendy w liście
   - Wbudowane: pomodoro start, quick capture (otwiera dialog do dopisania linii do todo.md)
3. **Standup generator** (`engines/standup.py`):
   - On-demand (na `standup_request`)
   - Yesterday window: 24h wstecz od teraz, max do północy
   - Źródła: Jira (closed yesterday, assignee=me) + Bitbucket (merged PRs yesterday, author=me) + git log commits (config: lista repo paths lokalnych)
4. **Weather poller** (`pollers/weather.py`):
   - OpenMeteo API (bez klucza), współrzędne z config
   - Poll co 15 min
   - Pole: temp, icon code, opis
5. **Claude usage** (`pollers/claude_usage.py`):
   - **Wymaga doprecyzowania** (TODO przed M6): jakie konkretnie źródło — Anthropic API admin endpoint, ccusage, własna telemetria z Claude Code?
   - Poll co 5 min
6. **Reminders engine** (`engines/reminders.py`):
   - Sync z pomodoro: gdy startuje przerwa 5 min, jest to też reminder na wodę + oczy
   - Gdy pomodoro **NIE jest aktywne**: też lecą remindery co 25 min (fullscreen z tekstem), bo użytkownik prosił "wszystkie reminderey leca razem z pomodoro" + "tak" do "remindery poza pomodoro"
   - Dismissible (przycisk "OK")

### Firmware

1. **Makra overlay:** klik MAKRO w pasku → grid 4×3 fullscreen, klik przycisku → `macro_trigger`, klik X → zamknij.
2. **Todo screen interactions:** tap checkbox → `todo_toggle`.
3. **Standup brief fullscreen:** kiedy przyjdzie `standup_brief` → fullscreen z listą wczorajszych osiągnięć.
4. **Reminders fullscreen:** ten sam komponent co `break_short`, inny content.

**Definicja ukończenia M6:**
- Wszystkie 4 ekrany w pełni funkcjonalne z realnym I/O.
- Makra działają (przykład: "Start work" otwiera 3–4 apki).
- Przycisk standup → fullscreen brief z wczorajszymi cyframi.
- Remindery na wodę / oczy lecą.
- Pogoda i Claude usage w pasku górnym aktualne.

**Oczekiwany czas:** 1.5 tygodnia

---

## M7 — Polish + reliability

Cel: stabilność dzienna. Stacja ma działać 8h dziennie bez restartów.

1. **Stress test:** 24h ciągłej pracy bez restartów, logi sprawdzone pod kątem ostrzeżeń/błędów.
2. **OAuth refresh:** wszystkie Google tokeny same się refresh-ują, sprawdzić edge case 401 → refresh → retry.
3. **Offline tolerance:** kiedy daemon nie ma neta, ESP pokazuje banner "Offline" w pasku, nie crashuje.
4. **ESP soft reset recovery:** po `esp_restart()` host nie traci queue, pcha pełen snapshot stanu.
5. **Memory profiling firmware:** sprawdzić że nie ma leak (LVGL i FreeRTOS), długo działa stabilnie.
6. **Backup config:** dokumentacja jak postawić od zera na nowej maszynie (Ansible / Makefile).
7. **systemd service:** daemon jako user service, autostart, restart on failure.
8. **Update flow:** jak zaktualizować firmware bez kabla USB — może OTA przez WiFi w późniejszej iteracji.

**Definicja ukończenia M7:**
- Stacja włącza się rano, działa cały dzień, wyłącza wieczorem (lub działa 24/7) bez interwencji.
- Wyciągnięcie kabla USB i podpięcie z powrotem = bezbolesny recovery.
- Brak neta przez 10 min = degradacja graceful (cached data + banner), nie crash.

**Oczekiwany czas:** 1 tydzień rozłożony w czasie + iteracje gdy pojawią się buggi w użyciu

---

## Po MVP — backlog

Zachowane na późniejsze fazy:
- Tactiq podsumowania
- Status "jestem na callu" (lampka pod drzwiami przez Zigbee/Hue)
- BME680 / SCD41 — temperatura, wilgotność, CO2 w pokoju
- GTD upgrade listy todo (contexts @, projects, someday/maybe)
- Time tracking poza pomodoro (manualny start/stop dla taska)
- NFC reader do logowania czasu
- Currencies / akcje w pasku
- Reminders na pociągi
- Status "paczka w drodze" (InPost API)

---

## Sumaryczny timeline (orientacyjnie, wieczorami po pracy)

| Faza | Czas | Cumulative |
|---|---|---|
| M0 Setup | 1–2 wieczory | 2d |
| M1 USB transport | 2–3 wieczory | 5d |
| M2 UI scaffolding | 1–2 tygodnie | ~3 tyg |
| M3 Pomodoro | 1 tydzień | ~4 tyg |
| M4 Jira/Bitbucket | 1 tydzień | ~5 tyg |
| M5 Komunikacja + Calendar | 1.5 tygodnia | ~6.5 tyg |
| M6 Reszta MVP | 1.5 tygodnia | ~8 tyg |
| M7 Polish | rozłożone | continuous |

**Total do MVP:** około 2 miesiące pracy wieczorowej, plus weekendy.

## Kolejność decyzji do podjęcia (pre-M0)

1. **Claude usage source** — Anthropic admin API? ccusage? Własna telemetria? Jeśli się nie zdecyduje, ten widget startuje pusty i dochodzi w M6.
2. **Lista projektów Bitbucket** do CI/CD monitoringu — config przed M4.
3. **Projekt Jira jako "lead project"** — config przed M4.
4. **Ścieżka do `todo.md`** — config przed M6.
5. **Lista makr i ich komendy** — config przed M6, można też zacząć z 2–3 i rozszerzać.
