# Pomodoro — state machine i zachowanie

Pomodoro to centralny komponent stacji. Tu szczegółowa specyfikacja co się dzieje w jakim stanie.

## Stany

```
                ┌──────────┐
                │   idle   │ ◄────────────────┐
                └────┬─────┘                  │
                     │                        │
        task_clicked / start_loose            │
                     │                        │
                     ▼                        │
                ┌──────────┐    cancel        │
        ┌──────►│  active  ├──────────────────┤
        │       └────┬─────┘                  │
        │            │                        │
        │  pause     │ timer = 0 OR           │
        │            │ stop_with_log          │
        │            │                        │
        │            ├──── pomodoros_today    │
        │            │     % 4 == 0?          │
        │            │                        │
        │       ┌────▼─────┐                  │
        │       │ paused   │                  │
        │       └────┬─────┘                  │
        │            │ resume                 │
        │            ▼                        │
        │       (back to active)              │
        │                                     │
        │      ┌──────────────┐               │
        └──────┤ short_break  ├───────────────┤
               │  (5 min)     │  timer = 0    │
               └──────────────┘  OR skip      │
                                              │
               ┌──────────────┐               │
               │  long_break  ├───────────────┘
               │  (20 min)    │   timer = 0
               └──────────────┘   OR skip
```

## Transitions

### `idle` → `active`

**Trigger:** ESP wysyła `task_clicked` lub `pomodoro_action.start_loose`.

**Akcje:**
- Ustaw `task_key` (z `task_clicked.key`) lub null (loose).
- `remaining_sec = 1500` (25 min).
- `total_sec = 1500`.
- `started_at = now()`.
- Push `pomodoro_state` z `state=active` → ESP wchodzi w fullscreen focus mode.
- Włącz DnD:
  - Wyślij notification suppression przez dbus (TODO: konkretna implementacja w M3).
  - Opcjonalnie: zmień status w Slack/Google Chat na "🍅 Focus" (jeśli skonfigurowane).
- Start tickera 1s, który dekrementuje `remaining_sec` i pcha `pomodoro_state` co sekundę.

### `active` → `paused`

**Trigger:** `pomodoro_action.pause`.

**Akcje:**
- Zatrzymaj ticker.
- Zapisz `paused_at = now()`.
- `remaining_sec` zostaje na tym co było.
- Push `pomodoro_state` z `state=paused`.
- **DnD pozostaje włączony.**

### `paused` → `active`

**Trigger:** `pomodoro_action.resume`.

**Akcje:**
- Wznów ticker od `remaining_sec` (kontynuuje od miejsca, NIE restart).
- Push `pomodoro_state` z `state=active`.

### `active` lub `paused` → break

**Trigger:**
- Timer dochodzi do 0 (z `active`), LUB
- `pomodoro_action.stop_with_log`.

**Akcje:**
1. **Oblicz `elapsed_sec`:**
   - Jeśli timer doszedł do 0: `elapsed_sec = total_sec` (25 min).
   - Jeśli `stop_with_log`: `elapsed_sec = total_sec - remaining_sec`.
2. **Logowanie do Jiry** (jeśli `task_key` nie null):
   - `jira.add_worklog(task_key, time_spent_seconds=elapsed_sec, started=started_at)`.
   - Log w SQLite tabeli `pomodoro_history` zawsze, niezależnie od taska.
3. **Inkrement countera dziennego:** `pomodoros_today += 1`.
4. **Wyłącz DnD.**
5. **Wybór długości przerwy:**
   - Jeśli `pomodoros_today % 4 == 0` → `long_break` 20 min.
   - Inaczej → `short_break` 5 min.
6. **Push `top_bar`** z nowym `pomodoros_today`.
7. **Push `fullscreen`** z `kind=break_short` lub `break_long`, treść:
   - **Short:** "Wstań i napij się wody" + ikony water/eyes/stretch.
   - **Long:** "Długa przerwa 20 min — odejdź od biurka, idź na spacer, zjedz coś" + ikony walk/water.
8. Start tickera przerwy.

### `active` lub `paused` → `idle` (cancel)

**Trigger:** `pomodoro_action.cancel`.

**Akcje:**
- Zatrzymaj ticker.
- **NIE loguj do Jiry.**
- **NIE inkrementuj `pomodoros_today`.**
- Wyłącz DnD.
- Push `pomodoro_state` z `state=idle`.
- ESP wraca do karuzeli.

### `short_break` / `long_break` → `idle`

**Trigger:**
- Timer przerwy dochodzi do 0, LUB
- `pomodoro_action.skip_break`.

**Akcje:**
- Push `pomodoro_state` z `state=idle`.
- Push `fullscreen_dismiss` (lub po prostu nie pcha już `fullscreen`, ESP wraca do karuzeli).
- Następne pomodoro **NIE startuje automatycznie** — czeka na user action (klik w taska albo "start pomodoro" makro).

## Counter dzienny

- Pole w SQLite: `pomodoro_history(date, count)`.
- `pomodoros_today` = `SELECT count FROM pomodoro_history WHERE date = CURRENT_DATE`.
- Reset o północy: cron-like task w asyncio, czeka do najbliższej północy, dodaje nowy wiersz z `count=0`.
- Wyświetlane w pasku górnym jako 🍅 N.

## Stan po reboot daemonu

- Po restarcie host nie pamięta że było `active` (idle reset).
- ESP po reboot wysyła `hello` → host odsyła `pomodoro_state.state=idle` → ESP wraca do karuzeli.
- `pomodoros_today` zachowane w SQLite, zostaje przywrócone.

## Reminders engine — interakcja z pomodoro

Reminders to osobny moduł, ale ściśle skoordynowany.

**Gdy pomodoro `active` lub `paused`:**
- Remindery są **wyciszone** — nie pchaj `fullscreen` dla water/eyes.
- Następna przerwa pomodoro pełni rolę remindera (woda + oczy automatycznie).

**Gdy pomodoro `idle`:**
- Remindery działają niezależnie.
- Co 25 min od ostatniej przerwy / startu daemona → push `fullscreen` z `kind=water`.
- Co 20 min → push `fullscreen` z `kind=eyes` (rule 20-20-20).
- Jeśli user dismissed → reset timera tego remindera, następny za 25/20 min.

**Race condition:** jeśli pomodoro startuje w trakcie remindera fullscreen — pomodoro overrides, fullscreen znika.

## Edge cases

### "Loose pomodoro" (bez taska)

- `task_key = null`, reszta tak samo.
- `stop_with_log` z nullowym taskiem **NIE loguje do Jiry** (tylko do SQLite history).
- Counter inkrementuje normalnie.

### Pause i czas trwa godzinami

- Brak limitu czasu pauzy.
- User wraca po godzinie, klika resume → timer kontynuuje.
- Jeśli minęła północ podczas pauzy: pomodoro nadal valid, ale po zakończeniu inkrementuje counter **dzisiejszy** (nie wczorajszy).

### Cancel podczas przerwy

- Nie ma "cancel break" jako osobnej akcji.
- `skip_break` → idle, czysto.

### Klik w inny task podczas active pomodoro

**Opcje:**
- A) Ignoruj klik z toast'em "pomodoro w toku".
- B) Auto-cancel obecnego pomodoro (bez loga) i start nowego.
- C) Auto stop_with_log obecnego i start nowego.

**Wybór:** A) — najmniej zaskakujące. User musi świadomie zakończyć current przed startem nowego. Pokaż toast: "Zakończ pomodoro DEV-1234 zanim zaczniesz nowy."

### Pomodoro start podczas remindera

- Reminder fullscreen ustępuje (push `fullscreen_dismiss` lub bezpośrednio `pomodoro_state.active`).
- User nie traci reminder permanentnie — wraca w następnym oknie.

## Konfiguracja

W `config.yaml`:

```yaml
pomodoro:
  focus_duration_sec: 1500       # 25 min
  short_break_sec: 300           # 5 min
  long_break_sec: 1200           # 20 min
  long_break_every: 4            # co ile pomodor długa
  log_to_jira: true
  dnd_slack_status: "🍅 Focus, back in 25"   # null = nie zmieniaj
  dnd_chat_status: true
```

## Persistence: schema SQLite

```sql
CREATE TABLE pomodoro_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,     -- ISO 8601
    ended_at TEXT NOT NULL,
    duration_sec INTEGER NOT NULL,
    task_key TEXT,                -- NULL for loose
    completed BOOLEAN NOT NULL    -- true = naturalny koniec, false = stop_with_log
);

CREATE INDEX idx_pomodoro_started ON pomodoro_history(started_at);
CREATE INDEX idx_pomodoro_task ON pomodoro_history(task_key);
```

Query dla countera dziennego:

```sql
SELECT COUNT(*) FROM pomodoro_history
WHERE date(started_at) = date('now', 'localtime');
```

Query dla statystyk per task (przyszłość):

```sql
SELECT task_key, SUM(duration_sec) FROM pomodoro_history
WHERE task_key IS NOT NULL AND date(started_at) >= date('now', '-7 days')
GROUP BY task_key
ORDER BY SUM(duration_sec) DESC;
```
