"""Mock data pollers for M2 dev mode.

Each poller runs as an asyncio task and pushes synthetic, plausible Polish-language
content to UIState at a configurable interval. No real API calls are made.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections import deque
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING

import structlog

from deskstation.bridge.protocol import (
    JiraTask,
    MeetingBar,
    Notification,
    PullRequest,
    StandupItem,
    TodoItem,
    TopBarData,
)

if TYPE_CHECKING:
    from deskstation.ui_state import UIState

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Day-name mapping (Polish, abbreviated)
# ---------------------------------------------------------------------------

_PL_DAY = {
    "Mon": "pon",
    "Tue": "wt",
    "Wed": "śr",
    "Thu": "czw",
    "Fri": "pt",
    "Sat": "sob",
    "Sun": "ndz",
}

_WEATHER_OPTIONS = ["18°C ☀", "12°C ☁", "8°C 🌧"]


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


class MockPoller:
    """Async task wrapper: runs tick() in a loop, catching + logging exceptions."""

    def __init__(self, ui_state: UIState, interval_sec: float = 5.0) -> None:
        self.ui_state = ui_state
        self.interval_sec = interval_sec

    async def tick(self) -> None:  # pragma: no cover
        raise NotImplementedError

    async def run_forever(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception as exc:
                log.warning("poller_tick_error", poller=type(self).__name__, error=str(exc))
            await asyncio.sleep(self.interval_sec)


# ---------------------------------------------------------------------------
# TopBarPoller
# ---------------------------------------------------------------------------


class TopBarPoller(MockPoller):
    """Pushes real clock + date, fake weather, fake claude_usage, counted pomodoros."""

    def __init__(self, ui_state: UIState, interval_sec: float = 5.0) -> None:
        super().__init__(ui_state, interval_sec)
        self._started_at = time.monotonic()
        self._pomodoros = 0

    async def tick(self) -> None:
        now = datetime.now()
        clock = now.strftime("%H:%M")

        eng_day = now.strftime("%a")
        pl_day = _PL_DAY.get(eng_day, eng_day.lower())
        date = f"{pl_day} {now.strftime('%d.%m')}"

        weather = random.choice(_WEATHER_OPTIONS)
        claude_usage = f"{random.randint(10, 90)}%"

        # Increment pomodoro counter roughly once per minute
        elapsed_min = (time.monotonic() - self._started_at) / 60.0
        self._pomodoros = int(elapsed_min)

        data = TopBarData(
            clock=clock,
            date=date,
            weather=weather,
            claude_usage=claude_usage,
            pomodoro_counter=self._pomodoros,
        )
        self.ui_state.set_top_bar(data)


# ---------------------------------------------------------------------------
# Screen1Poller
# ---------------------------------------------------------------------------

_JIRA_TODAY: list[tuple[str, str, str, bool]] = [
    ("DEV-1234", "Refaktoryzacja silnika pomodoro", "In Progress", True),
    ("DEV-1198", "Dodaj obsługę webhook Bitbucket", "In Progress", False),
    ("DEV-1201", "Poprawka: race condition w store", "Code Review", False),
    ("DEV-1185", "Dokumentacja protokołu szeregowego", "Done", False),
    ("DEV-1177", "Migracja bazy danych do SQLite", "Done", False),
]

_JIRA_QUEUED: list[tuple[str, str, str, bool]] = [
    ("DEV-1240", "Integracja z Google Calendar", "To Do", False),
    ("DEV-1241", "Ekran pogodowy - widget top bar", "To Do", False),
    ("DEV-1245", "Obsługa notyfikacji dbus", "To Do", False),
    ("DEV-1250", "Testy integracyjne M2", "To Do", False),
]

_FAKE_MEETING = MeetingBar(
    title="Standup zespołu",
    time="10:00-10:15",
    join_url="https://meet.example.com/standup",
    in_minutes=5,
)


class Screen1Poller(MockPoller):
    """Pushes Jira task lists + cycles next_meeting between None and a fake meeting."""

    def __init__(self, ui_state: UIState, interval_sec: float = 5.0) -> None:
        super().__init__(ui_state, interval_sec)
        self._tick_count = 0

    async def tick(self) -> None:
        today = [
            JiraTask(key=k, summary=s, status=st, is_current=cur)
            for k, s, st, cur in random.sample(_JIRA_TODAY, k=random.randint(3, 5))
        ]
        queued = [
            JiraTask(key=k, summary=s, status=st, is_current=cur)
            for k, s, st, cur in random.sample(_JIRA_QUEUED, k=random.randint(2, 4))
        ]
        # Cycle next_meeting: show meeting every third tick
        next_meeting: MeetingBar | None = _FAKE_MEETING if self._tick_count % 3 == 0 else None
        self._tick_count += 1

        self.ui_state.set_screen_1(
            today_tasks=today,
            queued_tasks=queued,
            next_meeting=next_meeting,
        )


# ---------------------------------------------------------------------------
# Screen2Poller
# ---------------------------------------------------------------------------

_NOTIF_SOURCES = ["gmail", "chat", "messenger"]

_NOTIF_TEMPLATES: list[tuple[str, str]] = [
    ("Anna Kowalska", "Czy możesz sprawdzić PR #42?"),
    ("Piotr Nowak", "Spotkanie przesunięte na 14:00"),
    ("Marta Wiśniewska", "Deploy na staging gotowy"),
    ("Tomasz Jabłoński", "Błąd krytyczny na produkcji!"),
    ("Agnieszka Zielińska", "Kod review - kilka komentarzy"),
    ("Michał Krawczyk", "Zlecenie zatwierdzone"),
    ("Karolina Lewandowska", "Zmiana wymagań w DEV-1240"),
    ("Bartek Szymański", "Proszę o pilny kontakt"),
]


class Screen2Poller(MockPoller):
    """Maintains a rolling deque of up to 8 notifications, adding one per tick."""

    def __init__(self, ui_state: UIState, interval_sec: float = 5.0) -> None:
        super().__init__(ui_state, interval_sec)
        self._notifications: deque[Notification] = deque(maxlen=8)
        self._counter = 0

    async def tick(self) -> None:
        sender, preview = random.choice(_NOTIF_TEMPLATES)
        source = _NOTIF_SOURCES[self._counter % len(_NOTIF_SOURCES)]
        self._counter += 1
        notif = Notification(
            source=source,  # type: ignore[arg-type]
            sender=sender,
            preview=preview,
            time_ago=f"{random.randint(1, 59)}m temu",
            id=f"n{self._counter}",
        )
        self._notifications.appendleft(notif)
        self.ui_state.set_screen_2(list(self._notifications))


# ---------------------------------------------------------------------------
# Screen3Poller
# ---------------------------------------------------------------------------

_PR_TEMPLATES: list[tuple[str, str, str, str]] = [
    ("pr-101", "feat(daemon): dodaj silnik pomodoro", "jdudek", "deskstation-daemon"),
    ("pr-102", "fix(firmware): naprawa timingów RGB", "mwisniewska", "deskstation-firmware"),
    ("pr-103", "chore(deps): aktualizacja pydantic 2.7", "anowak", "deskstation-daemon"),
    ("pr-104", "feat(daemon): integracja Google Calendar", "tjablonski", "deskstation-daemon"),
]

_PR_STATUSES = ["open", "approved", "needs_review", "changes_requested"]
_CI_STATUSES = ["passing", "failing", "running", "unknown"]

_STANDUP_ITEMS = [
    StandupItem(text="Zakończyłem M1 - transport USB działa", done=True),
    StandupItem(text="Implementuję UIState i pollers (M2)", done=False),
    StandupItem(text="Jutro: integracja z Jira API (M3)", done=False),
]


class Screen3Poller(MockPoller):
    """Pushes PRs with rotating statuses + fixed standup items."""

    def __init__(self, ui_state: UIState, interval_sec: float = 5.0) -> None:
        super().__init__(ui_state, interval_sec)
        self._tick_count = 0

    async def tick(self) -> None:
        prs = [
            PullRequest(
                id=pr_id,
                title=title,
                author=author,
                repo=repo,
                status=_PR_STATUSES[(i + self._tick_count) % len(_PR_STATUSES)],  # type: ignore[arg-type]
                ci=_CI_STATUSES[(i + self._tick_count) % len(_CI_STATUSES)],  # type: ignore[arg-type]
            )
            for i, (pr_id, title, author, repo) in enumerate(
                random.sample(_PR_TEMPLATES, k=random.randint(2, 4))
            )
        ]
        self._tick_count += 1
        self.ui_state.set_screen_3(prs=prs, standup=list(_STANDUP_ITEMS))


# ---------------------------------------------------------------------------
# Screen4Poller
# ---------------------------------------------------------------------------

_TODO_ITEMS_FIXED = [
    TodoItem(id="t1", text="Przegląd kodu pull requestów", done=False),
    TodoItem(id="t2", text="Aktualizacja dokumentacji M2", done=True),
    TodoItem(id="t3", text="Napisać testy integracyjne", done=False),
    TodoItem(id="t4", text="Spotkanie z zespołem o 15:00", done=False),
    TodoItem(id="t5", text="Deploy na środowisko testowe", done=True),
]


class Screen4Poller(MockPoller):
    """Pushes fixed todo list, toggling one item per tick."""

    def __init__(self, ui_state: UIState, interval_sec: float = 5.0) -> None:
        super().__init__(ui_state, interval_sec)
        self._items = [item.model_copy() for item in _TODO_ITEMS_FIXED]
        self._toggle_idx = 0

    async def tick(self) -> None:
        # Toggle one item's done flag
        item = self._items[self._toggle_idx % len(self._items)]
        self._items[self._toggle_idx % len(self._items)] = item.model_copy(
            update={"done": not item.done}
        )
        self._toggle_idx += 1
        self.ui_state.set_screen_4(list(self._items))


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def start_all_mocks(
    ui_state: UIState,
    interval_sec: float = 5.0,
    *,
    skip: set[str] | None = None,
) -> list[asyncio.Task[None]]:
    """Instantiate one poller per screen and start each as an asyncio Task.

    `skip` is an optional set of screen keys to omit (valid keys:
    ``"top_bar"``, ``"screen_1"``, ``"screen_2"``, ``"screen_3"``,
    ``"screen_4"``). Unknown keys are silently ignored. When ``skip`` is
    ``None`` all five mock pollers are started — the default M2-era behaviour.

    Returns the list of Task handles for cancellation on shutdown.
    """
    skip = skip or set()
    factories: list[tuple[str, Callable[[], MockPoller]]] = [
        ("top_bar", lambda: TopBarPoller(ui_state, interval_sec)),
        ("screen_1", lambda: Screen1Poller(ui_state, interval_sec)),
        ("screen_2", lambda: Screen2Poller(ui_state, interval_sec)),
        ("screen_3", lambda: Screen3Poller(ui_state, interval_sec)),
        ("screen_4", lambda: Screen4Poller(ui_state, interval_sec)),
    ]
    return [asyncio.create_task(make().run_forever()) for key, make in factories if key not in skip]
