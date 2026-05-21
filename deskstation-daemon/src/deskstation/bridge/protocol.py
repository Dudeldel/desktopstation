"""Pydantic models for the serial protocol envelope (M1 + M2 types).

Message types defined here: hello, heartbeat, toast, ack, screen_changed (M1)
and top_bar, screen_1..4, pomodoro_fullscreen, task_clicked, pr_clicked,
notification_clicked, todo_clicked, macro_trigger, pomodoro_action (M2).
Field shapes match `docs/spec/02-serial-protocol.md` (lines 334-471) exactly.
Additional types arrive in later milestones (M3+) and extend the per-type union.
"""

import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

MAX_LINE_BYTES = 4096


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


class HelloMsg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    v: Literal[1] = 1
    type: Literal["hello"] = "hello"
    data: HelloData


class HeartbeatMsg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    v: Literal[1] = 1
    type: Literal["heartbeat"] = "heartbeat"
    data: HeartbeatData


class ToastMsg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    v: Literal[1] = 1
    type: Literal["toast"] = "toast"
    data: ToastData


class AckMsg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    v: Literal[1] = 1
    type: Literal["ack"] = "ack"
    data: AckData


class ScreenChangedMsg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    v: Literal[1] = 1
    type: Literal["screen_changed"] = "screen_changed"
    data: ScreenChangedData


# ---- top_bar (host -> esp) ----


class TopBarData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    clock: str  # HH:MM
    date: str  # e.g. "pon 18.05"
    weather: str  # e.g. "18°C ☀"
    claude_usage: str  # e.g. "47%"
    pomodoro_counter: int  # completed pomodoros today
    macro_button_label: str = "MAKRO"


class TopBarMsg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    v: Literal[1] = 1
    type: Literal["top_bar"] = "top_bar"
    data: TopBarData


# ---- screen_1 (Jira) ----


class JiraTask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str  # e.g. "DEV-1234"
    summary: str
    status: str  # e.g. "In Progress"
    is_current: bool = False


class MeetingBar(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    time: str  # e.g. "11:00-11:30"
    join_url: str | None = None
    in_minutes: int  # negative = ongoing


class Screen1Data(BaseModel):
    model_config = ConfigDict(extra="forbid")
    today_tasks: list[JiraTask] = Field(default_factory=list)
    queued_tasks: list[JiraTask] = Field(default_factory=list)
    next_meeting: MeetingBar | None = None


class Screen1Msg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    v: Literal[1] = 1
    type: Literal["screen_1"] = "screen_1"
    data: Screen1Data


# ---- screen_2 (Comms) ----


class Notification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["gmail", "chat", "messenger", "whatsapp", "system"]
    sender: str
    preview: str
    time_ago: str  # e.g. "3m ago"
    id: str


class Screen2Data(BaseModel):
    model_config = ConfigDict(extra="forbid")
    notifications: list[Notification] = Field(default_factory=list)


class Screen2Msg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    v: Literal[1] = 1
    type: Literal["screen_2"] = "screen_2"
    data: Screen2Data


# ---- screen_3 (Dev) ----


class PullRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str
    author: str
    repo: str
    status: Literal["open", "approved", "needs_review", "changes_requested"]
    ci: Literal["passing", "failing", "running", "unknown"]


class StandupItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str
    done: bool = False


class Screen3Data(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prs: list[PullRequest] = Field(default_factory=list)
    standup: list[StandupItem] = Field(default_factory=list)


class Screen3Msg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    v: Literal[1] = 1
    type: Literal["screen_3"] = "screen_3"
    data: Screen3Data


# ---- screen_4 (Todo) ----


class TodoItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    text: str
    done: bool = False


class Screen4Data(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[TodoItem] = Field(default_factory=list)


class Screen4Msg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    v: Literal[1] = 1
    type: Literal["screen_4"] = "screen_4"
    data: Screen4Data


# ---- pomodoro_state (host -> esp) ----


PomodoroStateName = Literal["idle", "active", "paused", "short_break", "long_break"]


class PomodoroStateData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: PomodoroStateName
    remaining_sec: int = 0
    total_sec: int = 0
    task_key: str | None = None
    task_summary: str | None = None
    pomodoro_number_today: int = 0


class PomodoroStateMsg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    v: Literal[1] = 1
    type: Literal["pomodoro_state"] = "pomodoro_state"
    data: PomodoroStateData


# ---- fullscreen (host -> esp): break / reminder overlay ----


FullscreenKind = Literal["break_short", "break_long", "water", "eyes", "standup"]
FullscreenActivity = Literal["water", "eyes", "stretch", "walk"]


class FullscreenData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: FullscreenKind
    title: str
    message: str = ""
    submessage: str = ""
    duration_sec: int = 0
    activities: list[FullscreenActivity] = Field(default_factory=list)
    dismissible: bool = True


class FullscreenMsg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    v: Literal[1] = 1
    type: Literal["fullscreen"] = "fullscreen"
    data: FullscreenData


# ---- lock_state (host -> esp): opaque overlay while host PC is locked ----


class LockStateData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    locked: bool


class LockStateMsg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    v: Literal[1] = 1
    type: Literal["lock_state"] = "lock_state"
    data: LockStateData


# ---- esp -> host events ----


class TaskClickedData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str


class TaskClickedMsg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    v: Literal[1] = 1
    type: Literal["task_clicked"] = "task_clicked"
    data: TaskClickedData


class PrClickedData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str


class PrClickedMsg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    v: Literal[1] = 1
    type: Literal["pr_clicked"] = "pr_clicked"
    data: PrClickedData


class NotificationClickedData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str


class NotificationClickedMsg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    v: Literal[1] = 1
    type: Literal["notification_clicked"] = "notification_clicked"
    data: NotificationClickedData


class MeetingJoinData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str


class MeetingJoinMsg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    v: Literal[1] = 1
    type: Literal["meeting_join"] = "meeting_join"
    data: MeetingJoinData


class NotificationActionData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str


class NotificationActionMsg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    v: Literal[1] = 1
    type: Literal["notification_action"] = "notification_action"
    data: NotificationActionData


class TodoClickedData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str


class TodoClickedMsg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    v: Literal[1] = 1
    type: Literal["todo_clicked"] = "todo_clicked"
    data: TodoClickedData


class MacroTriggerData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str


class MacroTriggerMsg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    v: Literal[1] = 1
    type: Literal["macro_trigger"] = "macro_trigger"
    data: MacroTriggerData


class StandupRequestData(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StandupRequestMsg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    v: Literal[1] = 1
    type: Literal["standup_request"] = "standup_request"
    data: StandupRequestData = Field(default_factory=StandupRequestData)


PomodoroAction = Literal["pause", "resume", "stop_with_log", "cancel", "start_loose", "skip_break"]


class PomodoroActionData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: PomodoroAction


class PomodoroActionMsg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    v: Literal[1] = 1
    type: Literal["pomodoro_action"] = "pomodoro_action"
    data: PomodoroActionData


class FullscreenDismissData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: FullscreenKind


class FullscreenDismissMsg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    v: Literal[1] = 1
    type: Literal["fullscreen_dismiss"] = "fullscreen_dismiss"
    data: FullscreenDismissData


Envelope = Annotated[
    HelloMsg
    | HeartbeatMsg
    | ToastMsg
    | AckMsg
    | ScreenChangedMsg
    | TopBarMsg
    | Screen1Msg
    | Screen2Msg
    | Screen3Msg
    | Screen4Msg
    | PomodoroStateMsg
    | FullscreenMsg
    | LockStateMsg
    | TaskClickedMsg
    | PrClickedMsg
    | NotificationClickedMsg
    | MeetingJoinMsg
    | NotificationActionMsg
    | TodoClickedMsg
    | MacroTriggerMsg
    | StandupRequestMsg
    | PomodoroActionMsg
    | FullscreenDismissMsg,
    Field(discriminator="type"),
]

_ENVELOPE_ADAPTER: TypeAdapter[Envelope] = TypeAdapter(Envelope)


def parse_envelope(line: str) -> Envelope:
    """Parse a single newline-delimited JSON line into an Envelope.

    Raises ValueError on malformed JSON or oversized line, ValidationError on schema mismatch.
    """
    if len(line.encode("utf-8")) > MAX_LINE_BYTES:
        raise ValueError(f"line too long: {len(line)} bytes (max {MAX_LINE_BYTES})")
    try:
        obj = json.loads(line)
    except json.JSONDecodeError as e:
        raise ValueError(f"malformed JSON: {e}") from e
    return _ENVELOPE_ADAPTER.validate_python(obj)


def serialize_envelope(envelope: Envelope) -> str:
    """Serialize an Envelope to a JSON string (no trailing newline)."""
    return envelope.model_dump_json()
