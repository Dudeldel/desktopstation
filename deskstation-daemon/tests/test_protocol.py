"""Test pydantic envelope models for serial protocol M1 + M2 types."""

import pytest
from pydantic import ValidationError

from deskstation.bridge.protocol import (
    AckData,
    AckMsg,
    Envelope,
    FullscreenData,
    FullscreenDismissData,
    FullscreenDismissMsg,
    FullscreenMsg,
    HeartbeatData,
    HeartbeatMsg,
    HelloData,
    HelloMsg,
    JiraTask,
    MacroTriggerData,
    MacroTriggerMsg,
    Notification,
    NotificationClickedData,
    NotificationClickedMsg,
    PomodoroActionData,
    PomodoroActionMsg,
    PomodoroStateData,
    PomodoroStateMsg,
    PrClickedData,
    PrClickedMsg,
    PullRequest,
    Screen1Data,
    Screen1Msg,
    Screen2Data,
    Screen2Msg,
    Screen3Data,
    Screen3Msg,
    Screen4Data,
    Screen4Msg,
    ScreenChangedData,
    ScreenChangedMsg,
    StandupItem,
    TaskClickedData,
    TaskClickedMsg,
    ToastData,
    ToastMsg,
    TodoClickedData,
    TodoClickedMsg,
    TodoItem,
    TopBarData,
    TopBarMsg,
    parse_envelope,
    serialize_envelope,
)


def test_parse_hello() -> None:
    line = (
        '{"v":1,"type":"hello",'
        '"data":{"firmware_version":"0.1.0","free_heap":152340,"psram_free":8123456}}'
    )
    env = parse_envelope(line)
    assert isinstance(env, HelloMsg)
    assert env.data.firmware_version == "0.1.0"
    assert env.data.free_heap == 152340
    assert env.data.psram_free == 8123456


def test_parse_heartbeat() -> None:
    line = '{"v":1,"type":"heartbeat","data":{}}'
    env = parse_envelope(line)
    assert isinstance(env, HeartbeatMsg)


def test_parse_toast() -> None:
    line = '{"v":1,"type":"toast","data":{"text":"hi","level":"warning"}}'
    env = parse_envelope(line)
    assert isinstance(env, ToastMsg)
    assert env.data.text == "hi"
    assert env.data.level == "warning"


def test_parse_toast_defaults_to_info() -> None:
    line = '{"v":1,"type":"toast","data":{"text":"hi"}}'
    env = parse_envelope(line)
    assert isinstance(env, ToastMsg)
    assert env.data.level == "info"


def test_parse_ack() -> None:
    line = '{"v":1,"type":"ack","data":{"of_type":"screen_1"}}'
    env = parse_envelope(line)
    assert isinstance(env, AckMsg)
    assert env.data.of_type == "screen_1"


def test_parse_screen_changed() -> None:
    line = '{"v":1,"type":"screen_changed","data":{"screen":2,"via":"swipe"}}'
    env = parse_envelope(line)
    assert isinstance(env, ScreenChangedMsg)
    assert env.data.screen == 2
    assert env.data.via == "swipe"


def test_serialize_roundtrip() -> None:
    envelopes: list[Envelope] = [
        HelloMsg(data=HelloData(firmware_version="0.1.0", free_heap=152340, psram_free=8123456)),
        HeartbeatMsg(data=HeartbeatData()),
        ToastMsg(data=ToastData(text="hello", level="error")),
        AckMsg(data=AckData(of_type="screen_1")),
        ScreenChangedMsg(data=ScreenChangedData(screen=2, via="dot_click")),
    ]
    for env in envelopes:
        line = serialize_envelope(env)
        assert not line.endswith("\n")  # serialize does not include newline
        parsed = parse_envelope(line)
        assert parsed.type == env.type
        assert parsed.data == env.data


def test_parse_rejects_unknown_type() -> None:
    line = '{"v":1,"type":"nonexistent_type","data":{}}'
    with pytest.raises(ValidationError):
        parse_envelope(line)


def test_parse_rejects_wrong_version() -> None:
    line = '{"v":2,"type":"heartbeat","data":{}}'
    with pytest.raises(ValidationError):
        parse_envelope(line)


def test_parse_rejects_malformed_json() -> None:
    line = "not json {{{"
    with pytest.raises(ValueError):
        parse_envelope(line)


def test_parse_rejects_missing_data_field() -> None:
    line = '{"v":1,"type":"toast","data":{}}'  # toast wymaga text
    with pytest.raises(ValidationError):
        parse_envelope(line)


def test_parse_rejects_extra_fields_in_data() -> None:
    line = '{"v":1,"type":"heartbeat","data":{"surprise":"value"}}'
    with pytest.raises(ValidationError):
        parse_envelope(line)


def test_parse_rejects_invalid_toast_level() -> None:
    # "warn" is not valid — spec/02 uses "warning"
    line = '{"v":1,"type":"toast","data":{"text":"hi","level":"warn"}}'
    with pytest.raises(ValidationError):
        parse_envelope(line)


def test_parse_rejects_invalid_screen_changed_via() -> None:
    line = '{"v":1,"type":"screen_changed","data":{"screen":2,"via":"teleport"}}'
    with pytest.raises(ValidationError):
        parse_envelope(line)


def test_parse_rejects_oversized_line() -> None:
    big = '{"v":1,"type":"toast","data":{"text":"' + ("x" * 5000) + '"}}'
    assert len(big) > 4096
    with pytest.raises(ValueError, match="too long"):
        parse_envelope(big)


# ---------------------------------------------------------------------------
# M2 message types
# ---------------------------------------------------------------------------


def test_parse_top_bar() -> None:
    line = (
        '{"v":1,"type":"top_bar","data":{"clock":"14:32","date":"pon 18.05",'
        '"weather":"18\\u00b0C","claude_usage":"47%","pomodoro_counter":3}}'
    )
    env = parse_envelope(line)
    assert isinstance(env, TopBarMsg)
    assert env.data.clock == "14:32"
    assert env.data.date == "pon 18.05"
    assert env.data.pomodoro_counter == 3
    assert env.data.macro_button_label == "MAKRO"  # default


def test_top_bar_macro_button_label_override() -> None:
    line = (
        '{"v":1,"type":"top_bar","data":{"clock":"09:00","date":"wt 19.05",'
        '"weather":"10\\u00b0C","claude_usage":"12%","pomodoro_counter":0,'
        '"macro_button_label":"RUN"}}'
    )
    env = parse_envelope(line)
    assert isinstance(env, TopBarMsg)
    assert env.data.macro_button_label == "RUN"


def test_parse_screen_1_empty() -> None:
    line = '{"v":1,"type":"screen_1","data":{}}'
    env = parse_envelope(line)
    assert isinstance(env, Screen1Msg)
    assert env.data.today_tasks == []
    assert env.data.queued_tasks == []
    assert env.data.next_meeting is None


def test_parse_screen_1_with_tasks_and_meeting() -> None:
    line = (
        '{"v":1,"type":"screen_1","data":{"today_tasks":[{"key":"DEV-42",'
        '"summary":"Fix bug","status":"In Progress","is_current":true}],'
        '"queued_tasks":[],'
        '"next_meeting":{"title":"Standup","time":"10:00-10:15",'
        '"join_url":"https://meet.example.com/abc","in_minutes":5}}}'
    )
    env = parse_envelope(line)
    assert isinstance(env, Screen1Msg)
    assert len(env.data.today_tasks) == 1
    assert env.data.today_tasks[0].key == "DEV-42"
    assert env.data.today_tasks[0].is_current is True
    assert env.data.next_meeting is not None
    assert env.data.next_meeting.in_minutes == 5


def test_parse_screen_2() -> None:
    line = (
        '{"v":1,"type":"screen_2","data":{"notifications":[{"source":"gmail",'
        '"sender":"Jan Kowalski","preview":"Cześć, mam pytanie","time_ago":"3m ago",'
        '"id":"msg-001"}]}}'
    )
    env = parse_envelope(line)
    assert isinstance(env, Screen2Msg)
    assert len(env.data.notifications) == 1
    assert env.data.notifications[0].source == "gmail"
    assert env.data.notifications[0].id == "msg-001"


def test_parse_screen_3() -> None:
    line = (
        '{"v":1,"type":"screen_3","data":{"prs":[{"id":"pr-99","title":"Add feature",'
        '"author":"jdud","repo":"wfirma/api","status":"needs_review","ci":"passing"}],'
        '"standup":[{"text":"Skończyłem refactor","done":true}]}}'
    )
    env = parse_envelope(line)
    assert isinstance(env, Screen3Msg)
    assert len(env.data.prs) == 1
    assert env.data.prs[0].status == "needs_review"
    assert env.data.prs[0].ci == "passing"
    assert env.data.standup[0].done is True


def test_parse_screen_4() -> None:
    line = (
        '{"v":1,"type":"screen_4","data":{"items":[{"id":"t1","text":"Napisać testy",'
        '"done":false},{"id":"t2","text":"Code review","done":true}]}}'
    )
    env = parse_envelope(line)
    assert isinstance(env, Screen4Msg)
    assert len(env.data.items) == 2
    assert env.data.items[0].id == "t1"
    assert env.data.items[1].done is True


def test_parse_pomodoro_state_active() -> None:
    line = (
        '{"v":1,"type":"pomodoro_state","data":{"state":"active",'
        '"remaining_sec":847,"total_sec":1500,"task_key":"DEV-1234",'
        '"task_summary":"Refactor auth","pomodoro_number_today":4}}'
    )
    env = parse_envelope(line)
    assert isinstance(env, PomodoroStateMsg)
    assert env.data.state == "active"
    assert env.data.remaining_sec == 847
    assert env.data.total_sec == 1500
    assert env.data.task_key == "DEV-1234"
    assert env.data.task_summary == "Refactor auth"
    assert env.data.pomodoro_number_today == 4


def test_parse_pomodoro_state_idle_defaults() -> None:
    line = '{"v":1,"type":"pomodoro_state","data":{"state":"idle"}}'
    env = parse_envelope(line)
    assert isinstance(env, PomodoroStateMsg)
    assert env.data.state == "idle"
    assert env.data.remaining_sec == 0
    assert env.data.task_key is None
    assert env.data.task_summary is None
    assert env.data.pomodoro_number_today == 0


def test_parse_pomodoro_state_rejects_invalid_state() -> None:
    line = '{"v":1,"type":"pomodoro_state","data":{"state":"running"}}'
    with pytest.raises(ValidationError):
        parse_envelope(line)


def test_parse_fullscreen_break_short() -> None:
    line = (
        '{"v":1,"type":"fullscreen","data":{"kind":"break_short","title":"Krótka przerwa",'
        '"message":"Wstań i napij się wody","submessage":"Spójrz w dal",'
        '"duration_sec":300,"activities":["water","eyes"],"dismissible":true}}'
    )
    env = parse_envelope(line)
    assert isinstance(env, FullscreenMsg)
    assert env.data.kind == "break_short"
    assert env.data.duration_sec == 300
    assert env.data.activities == ["water", "eyes"]
    assert env.data.dismissible is True


def test_parse_fullscreen_dismiss() -> None:
    line = '{"v":1,"type":"fullscreen_dismiss","data":{"kind":"break_short"}}'
    env = parse_envelope(line)
    assert isinstance(env, FullscreenDismissMsg)
    assert env.data.kind == "break_short"


def test_parse_task_clicked() -> None:
    line = '{"v":1,"type":"task_clicked","data":{"key":"DEV-99"}}'
    env = parse_envelope(line)
    assert isinstance(env, TaskClickedMsg)
    assert env.data.key == "DEV-99"


def test_parse_pr_clicked() -> None:
    line = '{"v":1,"type":"pr_clicked","data":{"id":"pr-42"}}'
    env = parse_envelope(line)
    assert isinstance(env, PrClickedMsg)
    assert env.data.id == "pr-42"


def test_parse_notification_clicked() -> None:
    line = '{"v":1,"type":"notification_clicked","data":{"id":"msg-001"}}'
    env = parse_envelope(line)
    assert isinstance(env, NotificationClickedMsg)
    assert env.data.id == "msg-001"


def test_parse_meeting_join() -> None:
    from deskstation.bridge.protocol import MeetingJoinMsg

    line = '{"v":1,"type":"meeting_join","data":{"id":"ev-42"}}'
    env = parse_envelope(line)
    assert isinstance(env, MeetingJoinMsg)
    assert env.data.id == "ev-42"


def test_parse_notification_action() -> None:
    from deskstation.bridge.protocol import NotificationActionMsg

    line = '{"v":1,"type":"notification_action","data":{"id":"n2"}}'
    env = parse_envelope(line)
    assert isinstance(env, NotificationActionMsg)
    assert env.data.id == "n2"


def test_parse_todo_clicked() -> None:
    line = '{"v":1,"type":"todo_clicked","data":{"id":"t1"}}'
    env = parse_envelope(line)
    assert isinstance(env, TodoClickedMsg)
    assert env.data.id == "t1"


def test_parse_macro_trigger() -> None:
    line = '{"v":1,"type":"macro_trigger","data":{"name":"git_status"}}'
    env = parse_envelope(line)
    assert isinstance(env, MacroTriggerMsg)
    assert env.data.name == "git_status"


def test_parse_standup_request() -> None:
    env = parse_envelope('{"v":1,"type":"standup_request","data":{}}')
    assert env.type == "standup_request"


def test_parse_pomodoro_action_all_variants() -> None:
    for action in ("pause", "resume", "stop_with_log", "cancel", "start_loose", "skip_break"):
        line = f'{{"v":1,"type":"pomodoro_action","data":{{"action":"{action}"}}}}'
        env = parse_envelope(line)
        assert isinstance(env, PomodoroActionMsg)
        assert env.data.action == action


def test_parse_pomodoro_action_rejects_invalid() -> None:
    line = '{"v":1,"type":"pomodoro_action","data":{"action":"stop"}}'
    with pytest.raises(ValidationError):
        parse_envelope(line)


def test_top_bar_rejects_extra_fields() -> None:
    line = (
        '{"v":1,"type":"top_bar","data":{"clock":"14:32","date":"pon 18.05",'
        '"weather":"18C","claude_usage":"47%","pomodoro_counter":3,"extra":"bad"}}'
    )
    with pytest.raises(ValidationError):
        parse_envelope(line)


def test_screen_2_rejects_invalid_source() -> None:
    line = (
        '{"v":1,"type":"screen_2","data":{"notifications":[{"source":"twitter",'
        '"sender":"x","preview":"y","time_ago":"1m","id":"z"}]}}'
    )
    with pytest.raises(ValidationError):
        parse_envelope(line)


def test_screen_1_rejects_missing_task_key() -> None:
    # JiraTask requires 'key' and 'summary' and 'status'
    line = '{"v":1,"type":"screen_1","data":{"today_tasks":[{"summary":"no key","status":"Open"}]}}'
    with pytest.raises(ValidationError):
        parse_envelope(line)


def test_m2_serialize_roundtrip() -> None:
    envelopes: list[Envelope] = [
        TopBarMsg(
            data=TopBarData(
                clock="14:32",
                date="pon 18.05",
                weather="18C",
                claude_usage="47%",
                pomodoro_counter=2,
            )
        ),
        Screen1Msg(
            data=Screen1Data(
                today_tasks=[JiraTask(key="DEV-1", summary="Task", status="Open")],
            )
        ),
        Screen2Msg(
            data=Screen2Data(
                notifications=[
                    Notification(
                        source="gmail", sender="Jan", preview="Cześć", time_ago="5m ago", id="x1"
                    )
                ],
            )
        ),
        Screen3Msg(
            data=Screen3Data(
                prs=[
                    PullRequest(
                        id="pr-1",
                        title="PR",
                        author="jdud",
                        repo="wf/api",
                        status="open",
                        ci="passing",
                    )
                ],
                standup=[StandupItem(text="Zrobiłem X", done=False)],
            )
        ),
        Screen4Msg(data=Screen4Data(items=[TodoItem(id="t1", text="Todo", done=False)])),
        PomodoroStateMsg(
            data=PomodoroStateData(
                state="active",
                remaining_sec=847,
                total_sec=1500,
                task_key="DEV-1",
                task_summary="Task",
                pomodoro_number_today=2,
            )
        ),
        FullscreenMsg(
            data=FullscreenData(
                kind="break_short",
                title="Krótka przerwa",
                message="Wstań",
                duration_sec=300,
                activities=["water"],
            )
        ),
        TaskClickedMsg(data=TaskClickedData(key="DEV-1")),
        PrClickedMsg(data=PrClickedData(id="pr-1")),
        NotificationClickedMsg(data=NotificationClickedData(id="x1")),
        TodoClickedMsg(data=TodoClickedData(id="t1")),
        MacroTriggerMsg(data=MacroTriggerData(name="open_terminal")),
        PomodoroActionMsg(data=PomodoroActionData(action="stop_with_log")),
        FullscreenDismissMsg(data=FullscreenDismissData(kind="break_short")),
    ]
    for env in envelopes:
        line = serialize_envelope(env)
        parsed = parse_envelope(line)
        assert parsed.type == env.type
        assert parsed.data == env.data
