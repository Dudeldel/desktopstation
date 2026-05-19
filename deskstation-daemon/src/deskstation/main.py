"""Asyncio entry point: wires bridge, heartbeat, message dispatch."""

import asyncio
import signal
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

from deskstation import auth_google
from deskstation.bridge.heartbeat import ConnectionMonitor, heartbeat_sender
from deskstation.bridge.interface import BridgeProtocol
from deskstation.bridge.mock_bridge import MockBridge
from deskstation.bridge.protocol import (
    AckMsg,
    FullscreenDismissMsg,
    HeartbeatMsg,
    HelloMsg,
    MeetingJoinMsg,
    NotificationActionMsg,
    NotificationClickedMsg,
    PomodoroActionMsg,
    ScreenChangedMsg,
    TaskClickedMsg,
    ToastMsg,
)
from deskstation.bridge.serial_bridge import SerialBridge, default_serial_factory
from deskstation.clients.bitbucket import BitbucketClient
from deskstation.clients.gcal import GoogleCalendarClient
from deskstation.clients.gchat import GoogleChatClient
from deskstation.clients.gmail import GmailClient
from deskstation.clients.jira import JiraClient
from deskstation.config import Config, load_config
from deskstation.engines.pomodoro import PomodoroEngine
from deskstation.engines.screen2_merger import Screen2Merger
from deskstation.listeners.dbus_notifications import DbusNotificationListener
from deskstation.logging_setup import configure_logging
from deskstation.pollers.bitbucket import BitbucketPoller
from deskstation.pollers.calendar import CalendarPoller
from deskstation.pollers.gchat import GoogleChatPoller
from deskstation.pollers.gmail import GmailPoller
from deskstation.pollers.jira import JiraPoller
from deskstation.pollers.mock import start_all_mocks
from deskstation.secrets import load_secrets
from deskstation.store.api_cache import ApiCache
from deskstation.store.pomodoro_store import PomodoroStore
from deskstation.ui_state import UIState

log = structlog.get_logger(__name__)


def _build_bridge(cfg: Config) -> BridgeProtocol:
    if cfg.bridge.mode == "mock":
        log.info("bridge_mode_mock")
        return MockBridge()
    factory = default_serial_factory(cfg.serial.device, cfg.serial.baudrate)
    return SerialBridge(factory, reconnect_interval_sec=cfg.serial.reconnect_interval_sec)


async def _xdg_open(url: str) -> None:
    """Run ``xdg-open <url>`` off the event loop, logging any errors.

    ``check=False`` keeps non-zero exits from bubbling as exceptions —
    xdg-open's exit codes vary by handler and a failure here shouldn't
    crash the dispatcher.
    """
    try:
        await asyncio.to_thread(subprocess.run, ["xdg-open", url], check=False)
    except Exception as exc:
        log.warning("xdg_open_failed", url=url, error=str(exc))


@dataclass
class DispatchContext:
    """Bundle of dependencies passed to every dispatch handler.

    New M6+ dependencies (weather, standup, reminders, macros, todo) land
    here as optional kwargs so handler signatures stay uniform.
    """

    bridge: BridgeProtocol
    monitor: ConnectionMonitor
    ui_state: UIState
    pomodoro: PomodoroEngine
    merger: Screen2Merger | None = None
    calendar_poller: CalendarPoller | None = None


def handle_hello(ctx: DispatchContext, env: HelloMsg) -> None:
    log.info("hello_received", firmware_version=env.data.firmware_version)


def handle_heartbeat(ctx: DispatchContext, env: HeartbeatMsg) -> None:
    log.debug("heartbeat_received")


def handle_screen_changed(ctx: DispatchContext, env: ScreenChangedMsg) -> None:
    log.info("screen_changed_received", screen=env.data.screen)


def handle_ack(ctx: DispatchContext, env: AckMsg) -> None:
    log.debug("ack_received", of_type=env.data.of_type)


def handle_toast(ctx: DispatchContext, env: ToastMsg) -> None:
    log.warning("toast_from_esp_ignored", text=env.data.text)


def handle_task_clicked(ctx: DispatchContext, env: TaskClickedMsg) -> None:
    # M3: start a pomodoro for the clicked task. task_summary lookup
    # arrives in M4 with the real Jira poller; for now we pass None.
    ctx.pomodoro.start_task(env.data.key)


def handle_pomodoro_action(ctx: DispatchContext, env: PomodoroActionMsg) -> None:
    action = env.data.action
    if action == "pause":
        ctx.pomodoro.pause()
    elif action == "resume":
        ctx.pomodoro.resume()
    elif action == "stop_with_log":
        ctx.pomodoro.stop_with_log()
    elif action == "cancel":
        ctx.pomodoro.cancel()
    elif action == "start_loose":
        ctx.pomodoro.start_loose()
    elif action == "skip_break":
        ctx.pomodoro.skip_break()


def handle_fullscreen_dismiss(ctx: DispatchContext, env: FullscreenDismissMsg) -> None:
    # Dismissing a break overlay short-circuits the break (same as skip_break).
    log.info("fullscreen_dismissed", kind=env.data.kind)
    ctx.pomodoro.skip_break()


async def handle_notification_action(
    ctx: DispatchContext,
    env: NotificationActionMsg | NotificationClickedMsg,
) -> None:
    # NotificationClickedMsg is the legacy M2 name; firmware still emits it.
    # Both resolve to the same lookup-then-xdg-open path.
    notification_id = env.data.id
    if ctx.merger is None:
        log.warning(
            "notification_action_no_merger",
            notification_id=notification_id,
        )
        return
    url = ctx.merger.lookup_url(notification_id)
    if url is None:
        log.warning(
            "notification_action_unknown_id",
            notification_id=notification_id,
        )
        return
    await _xdg_open(url)


async def handle_meeting_join(ctx: DispatchContext, env: MeetingJoinMsg) -> None:
    meeting_id = env.data.id
    if ctx.calendar_poller is None:
        log.warning("meeting_join_no_calendar", meeting_id=meeting_id)
        return
    url = ctx.calendar_poller.lookup_meeting_url(meeting_id)
    if url is None:
        log.warning("meeting_join_unknown_id", meeting_id=meeting_id)
        return
    await _xdg_open(url)


# Envelope class → handler. Heterogeneous return types (sync None vs async
# coroutine) are intentional: the dispatch loop awaits whatever shape the
# handler returns. ``Any`` carries the type union; mypy doesn't gain from
# narrowing here since the dispatch site already keys on runtime ``type(env)``.
_HANDLERS: dict[type, Callable[..., Any]] = {
    HelloMsg: handle_hello,
    HeartbeatMsg: handle_heartbeat,
    ScreenChangedMsg: handle_screen_changed,
    AckMsg: handle_ack,
    ToastMsg: handle_toast,
    TaskClickedMsg: handle_task_clicked,
    PomodoroActionMsg: handle_pomodoro_action,
    FullscreenDismissMsg: handle_fullscreen_dismiss,
    NotificationActionMsg: handle_notification_action,
    NotificationClickedMsg: handle_notification_action,  # legacy alias
    MeetingJoinMsg: handle_meeting_join,
}


async def _dispatch(ctx: DispatchContext) -> None:
    was_connected = ctx.monitor.is_connected
    async for env in ctx.bridge.stream():
        ctx.monitor.mark_rx()
        if not was_connected:
            log.info("reconnect_resending_ui_state")
            await ctx.ui_state.resend_all()
        was_connected = ctx.monitor.is_connected

        handler = _HANDLERS.get(type(env))
        if handler is None:
            log.warning("unknown_envelope_type", type=type(env).__name__)
            continue

        result = handler(ctx, env)
        if asyncio.iscoroutine(result):
            await result


def _check_google_oauth_setup() -> None:
    """Log a hint if a Google OAuth client is configured but no token exists yet.

    Silent when both files are missing (user likely doesn't want Google
    integration); silent when token exists (happy path).
    """
    config_dir = Path("~/.config/deskstation").expanduser()
    client_path = config_dir / "google_client.json"
    token_path = config_dir / "google_token.json"
    if client_path.exists() and not token_path.exists():
        log.info("google_oauth_not_configured", hint="run `deskstation auth-google`")


async def _run() -> None:
    cfg = load_config()
    configure_logging(
        log_file=cfg.logging.file,
        pretty_console=cfg.logging.pretty_console,
        level=cfg.logging.level,
    )
    log.info("ready", serial_device=cfg.serial.device, bridge_mode=cfg.bridge.mode)
    _check_google_oauth_setup()

    bridge = _build_bridge(cfg)
    monitor = ConnectionMonitor(timeout_sec=cfg.heartbeat.timeout_sec)
    ui_state = UIState(bridge)

    pomodoro_store = PomodoroStore()

    secrets = load_secrets()
    cache = ApiCache()
    jira_client: JiraClient | None = None
    jira_poller: JiraPoller | None = None
    if secrets.jira is not None and cfg.jira.enabled and cfg.jira.project_key:
        jira_client = JiraClient(
            secrets.jira.base_url,
            secrets.jira.email,
            secrets.jira.api_token,
            cache,
        )
        jira_poller = JiraPoller(
            ui_state,
            jira_client,
            cfg.jira.project_key,
            interval_sec=cfg.jira.poll_interval_sec,
        )

    bitbucket_client: BitbucketClient | None = None
    bitbucket_poller: BitbucketPoller | None = None
    if (
        secrets.bitbucket is not None
        and cfg.bitbucket.enabled
        and cfg.bitbucket.workspace
        and cfg.bitbucket.repos
    ):
        bitbucket_client = BitbucketClient(
            secrets.bitbucket.workspace,
            secrets.bitbucket.email,
            secrets.bitbucket.api_token,
            cache,
        )
        # Prefer explicit username; fall back to email local-part for backwards compat.
        # If your Bitbucket nickname differs from your email's local-part, set
        # bitbucket.username in secrets.yaml.
        bb_username = secrets.bitbucket.username or secrets.bitbucket.email.split("@")[0]
        bitbucket_poller = BitbucketPoller(
            ui_state,
            bitbucket_client,
            bb_username,
            cfg.bitbucket.repos,
            interval_sec=cfg.bitbucket.poll_interval_sec,
        )

    # Load Google OAuth credentials once and share across Gmail + Chat
    # + Calendar. ``load_credentials()`` is cheap when a token file is
    # missing (returns None immediately).
    google_creds = None
    if cfg.gmail.enabled or cfg.gchat.enabled or cfg.calendar.enabled:
        google_creds = auth_google.load_credentials()

    # M5.5: single owner of the ``screen_2`` dispatch. Constructed before
    # the Gmail / Chat pollers and the dbus listener so they can route
    # their notifications through it instead of calling
    # ``ui_state.set_screen_2`` directly.
    screen2_merger = Screen2Merger(ui_state)

    gmail_poller: GmailPoller | None = None
    if google_creds is not None and cfg.gmail.enabled:
        gmail_client = GmailClient(google_creds, cache)
        gmail_poller = GmailPoller(
            ui_state,
            gmail_client,
            interval_sec=cfg.gmail.poll_interval_sec,
            merger=screen2_merger,
        )

    gchat_poller: GoogleChatPoller | None = None
    if google_creds is not None and cfg.gchat.enabled and cfg.gchat.my_email:
        gchat_client = GoogleChatClient(
            google_creds,
            cache,
            my_email=cfg.gchat.my_email,
        )
        gchat_poller = GoogleChatPoller(
            ui_state,
            gchat_client,
            my_email=cfg.gchat.my_email,
            interval_sec=cfg.gchat.poll_interval_sec,
            merger=screen2_merger,
        )

    # Calendar poller — drives screen_1.next_meeting. UIState.set_screen_1
    # now merges keyword args (M5.6 sentinel fix) so this can coexist with
    # the Jira poller without overwriting each other.
    calendar_client: GoogleCalendarClient | None = None
    calendar_poller: CalendarPoller | None = None
    if google_creds is not None and cfg.calendar.enabled:
        calendar_client = GoogleCalendarClient(google_creds, cache)
        calendar_poller = CalendarPoller(
            ui_state,
            calendar_client,
            near_interval_sec=cfg.calendar.near_interval_sec,
            far_interval_sec=cfg.calendar.far_interval_sec,
            near_window_sec=cfg.calendar.near_window_sec,
        )

    dbus_listener: DbusNotificationListener | None = None
    if cfg.dbus.enabled:
        dbus_listener = DbusNotificationListener(
            app_name_patterns=cfg.dbus.app_name_patterns,
            buffer_size=cfg.dbus.buffer_size,
        )
        try:
            await dbus_listener.start()
            log.info("dbus_listener_active", patterns=cfg.dbus.app_name_patterns)
        except Exception as exc:
            log.warning("dbus_listener_unavailable", error=str(exc))
            dbus_listener = None

    # M5.5: dbus is signal-driven (no tick loop), so to feed its buffered
    # notifications into the merger we run a tiny 1 Hz polling task that
    # reads ``snapshot()`` and pushes it. A snapshot is a small in-memory
    # deque copy — negligible cost. A proper callback-driven path can come
    # later if 1 Hz proves too coarse.
    #
    # ``dbus_listener`` is captured by closure and is guaranteed non-None
    # here because the task below is only scheduled inside the
    # ``if dbus_listener is not None`` branch, and the local is never
    # reassigned after task creation. So no None-guard is needed.
    async def _dbus_to_merger() -> None:
        assert dbus_listener is not None  # for mypy; see comment above
        while True:
            try:
                screen2_merger.update("dbus", dbus_listener.snapshot())
            except Exception as exc:
                log.warning("dbus_to_merger_failed", error=str(exc))
            await asyncio.sleep(1.0)

    pomodoro = PomodoroEngine(
        ui_state,
        pomodoro_store,
        task_index=jira_poller.lookup_summary if jira_poller is not None else None,
        worklog=jira_client.add_worklog if jira_client is not None else None,
    )

    # When real pollers are active, suppress the matching M2 mock pollers so
    # they don't overwrite real screen data with synthetic fixtures.
    skip: set[str] = set()
    if jira_poller is not None:
        skip.add("screen_1")
    if bitbucket_poller is not None:
        skip.add("screen_3")
    if gmail_poller is not None:
        skip.add("screen_2")
    if gchat_poller is not None:
        skip.add("screen_2")
    if dbus_listener is not None:
        skip.add("screen_2")
    if skip:
        log.info("mocks_skip_applied", skip=sorted(skip))

    mock_tasks: list[asyncio.Task[None]] = []
    if cfg.mock.enabled:
        log.info("starting_mock_pollers", interval_sec=cfg.mock.interval_sec)
        mock_tasks = start_all_mocks(
            ui_state,
            interval_sec=cfg.mock.interval_sec,
            skip=skip,
        )

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    dispatch_ctx = DispatchContext(
        bridge=bridge,
        monitor=monitor,
        ui_state=ui_state,
        pomodoro=pomodoro,
        merger=screen2_merger,
        calendar_poller=calendar_poller,
    )

    tasks = [
        asyncio.create_task(heartbeat_sender(bridge, interval_sec=cfg.heartbeat.interval_sec)),
        asyncio.create_task(_dispatch(dispatch_ctx)),
        asyncio.create_task(monitor.watchdog()),
        pomodoro.start(),
        *mock_tasks,
    ]
    if jira_poller is not None:
        tasks.append(asyncio.create_task(jira_poller.run_forever()))
    if bitbucket_poller is not None:
        tasks.append(asyncio.create_task(bitbucket_poller.run_forever()))
    if gmail_poller is not None:
        tasks.append(asyncio.create_task(gmail_poller.run_forever()))
    if gchat_poller is not None:
        tasks.append(asyncio.create_task(gchat_poller.run_forever()))
    if calendar_poller is not None:
        tasks.append(asyncio.create_task(calendar_poller.run_forever()))
    if dbus_listener is not None:
        tasks.append(asyncio.create_task(_dbus_to_merger()))

    await stop_event.wait()
    log.info("shutting_down")

    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    if jira_client is not None:
        await jira_client.aclose()
    if bitbucket_client is not None:
        await bitbucket_client.aclose()
    if calendar_client is not None:
        await calendar_client.aclose()
    if dbus_listener is not None:
        await dbus_listener.stop()
    pomodoro_store.close()
    cache.close()
    await bridge.close()
    log.info("shutdown_complete")


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
