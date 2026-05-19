"""Asyncio entry point: wires bridge, heartbeat, message dispatch."""

import asyncio
import signal

import structlog

from deskstation.bridge.heartbeat import ConnectionMonitor, heartbeat_sender
from deskstation.bridge.interface import BridgeProtocol
from deskstation.bridge.mock_bridge import MockBridge
from deskstation.bridge.protocol import (
    AckMsg,
    FullscreenDismissMsg,
    HeartbeatMsg,
    HelloMsg,
    PomodoroActionMsg,
    ScreenChangedMsg,
    TaskClickedMsg,
    ToastMsg,
)
from deskstation.bridge.serial_bridge import SerialBridge, default_serial_factory
from deskstation.clients.bitbucket import BitbucketClient
from deskstation.clients.jira import JiraClient
from deskstation.config import Config, load_config
from deskstation.engines.pomodoro import PomodoroEngine
from deskstation.logging_setup import configure_logging
from deskstation.pollers.bitbucket import BitbucketPoller
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


async def _dispatch(
    bridge: BridgeProtocol,
    monitor: ConnectionMonitor,
    ui_state: UIState,
    pomodoro: PomodoroEngine,
) -> None:
    was_connected = monitor.is_connected
    async for env in bridge.stream():
        monitor.mark_rx()
        if not was_connected:
            log.info("reconnect_resending_ui_state")
            await ui_state.resend_all()
        was_connected = monitor.is_connected
        if isinstance(env, HelloMsg):
            log.info("hello_received", firmware_version=env.data.firmware_version)
        elif isinstance(env, HeartbeatMsg):
            log.debug("heartbeat_received")
        elif isinstance(env, ScreenChangedMsg):
            log.info("screen_changed_received", screen=env.data.screen)
        elif isinstance(env, AckMsg):
            log.debug("ack_received", of_type=env.data.of_type)
        elif isinstance(env, ToastMsg):
            log.warning("toast_from_esp_ignored", text=env.data.text)
        elif isinstance(env, TaskClickedMsg):
            # M3: start a pomodoro for the clicked task. task_summary lookup
            # arrives in M4 with the real Jira poller; for now we pass None.
            pomodoro.start_task(env.data.key)
        elif isinstance(env, PomodoroActionMsg):
            action = env.data.action
            if action == "pause":
                pomodoro.pause()
            elif action == "resume":
                pomodoro.resume()
            elif action == "stop_with_log":
                pomodoro.stop_with_log()
            elif action == "cancel":
                pomodoro.cancel()
            elif action == "start_loose":
                pomodoro.start_loose()
            elif action == "skip_break":
                pomodoro.skip_break()
        elif isinstance(env, FullscreenDismissMsg):
            # Dismissing a break overlay short-circuits the break (same as skip_break).
            log.info("fullscreen_dismissed", kind=env.data.kind)
            pomodoro.skip_break()
        else:
            log.warning("unknown_envelope_type")


async def _run() -> None:
    cfg = load_config()
    configure_logging(
        log_file=cfg.logging.file,
        pretty_console=cfg.logging.pretty_console,
        level=cfg.logging.level,
    )
    log.info("ready", serial_device=cfg.serial.device, bridge_mode=cfg.bridge.mode)

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

    pomodoro = PomodoroEngine(
        ui_state,
        pomodoro_store,
        task_index=jira_poller.lookup_summary if jira_poller is not None else None,
        worklog=jira_client.add_worklog if jira_client is not None else None,
    )

    mock_tasks: list[asyncio.Task[None]] = []
    if cfg.mock.enabled:
        log.info("starting_mock_pollers", interval_sec=cfg.mock.interval_sec)
        mock_tasks = start_all_mocks(ui_state, interval_sec=cfg.mock.interval_sec)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    tasks = [
        asyncio.create_task(heartbeat_sender(bridge, interval_sec=cfg.heartbeat.interval_sec)),
        asyncio.create_task(_dispatch(bridge, monitor, ui_state, pomodoro)),
        asyncio.create_task(monitor.watchdog()),
        pomodoro.start(),
        *mock_tasks,
    ]
    if jira_poller is not None:
        tasks.append(asyncio.create_task(jira_poller.run_forever()))
    if bitbucket_poller is not None:
        tasks.append(asyncio.create_task(bitbucket_poller.run_forever()))

    await stop_event.wait()
    log.info("shutting_down")

    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    if jira_client is not None:
        await jira_client.aclose()
    if bitbucket_client is not None:
        await bitbucket_client.aclose()
    pomodoro_store.close()
    await bridge.close()
    log.info("shutdown_complete")


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
