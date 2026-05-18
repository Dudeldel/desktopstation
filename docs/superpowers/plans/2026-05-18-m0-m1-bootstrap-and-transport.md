# M0 + M1 Bootstrap and Transport — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Postaw scaffold daemona Python i firmware ESP32, zaimplementuj minimalny ale niezawodny kanał USB CDC między nimi z heartbeat / reconnect / 5 typami wiadomości (M0+M1).

**Architecture:** Monorepo z dwoma subprojektami: `deskstation-daemon/` (Python asyncio, uv) i `deskstation-firmware/` (ESP-IDF v5.x + LVGL 8.x). Daemon TDD-style (pytest + mock_bridge), firmware compile-test + hardware-test. Protokół to newline-delimited JSON po `/dev/ttyACM0`. M0 = setup, M1 = transport żywy z toast/heartbeat/hello/screen_changed/ack.

**Tech Stack:** Python 3.11+ • uv • pydantic v2 • pyserial-asyncio • structlog • pytest-asyncio • ruff • mypy --strict • pre-commit • ESP-IDF v5.3 • LVGL 8.x (component manager) • TinyUSB CDC • cJSON • FreeRTOS.

**Spec reference:** `docs/superpowers/specs/2026-05-18-m0-m1-bootstrap-and-transport-design.md`

**Deviation from spec/03 (Waveshare BSP submodule):** Plan **nie używa** submodule Waveshare BSP. Zamiast tego: stock ESP-IDF drivers (`esp_lcd_panel_rgb`, `esp_lcd_touch_gt911`) + LVGL przez component manager + hardcoded piny z datasheetu Waveshare w `board.c`. Zalety: mniej deps, czystszy build, identyczne zachowanie. README linkuje do repo Waveshare jako referencji pinów.

---

## Phase A — Repo hygiene (M0 shared)

### Task 1: Top-level `.gitignore`

**Files:**
- Create: `/home/pc30/Desktop/desktopstation/.gitignore`

- [ ] **Step 1: Create `.gitignore`**

Treść (cały plik):

```gitignore
# Daemon (Python)
deskstation-daemon/.venv/
deskstation-daemon/__pycache__/
deskstation-daemon/**/__pycache__/
deskstation-daemon/*.egg-info/
deskstation-daemon/.pytest_cache/
deskstation-daemon/.mypy_cache/
deskstation-daemon/.ruff_cache/
deskstation-daemon/config.yaml
deskstation-daemon/.env

# Firmware (ESP-IDF)
deskstation-firmware/build/
deskstation-firmware/sdkconfig
deskstation-firmware/sdkconfig.old
deskstation-firmware/managed_components/
deskstation-firmware/dependencies.lock

# Logs
*.jsonl

# IDE / OS
.vscode/
.idea/
.DS_Store
```

- [ ] **Step 2: Verify**

Run: `cd /home/pc30/Desktop/desktopstation && git check-ignore -v deskstation-daemon/.venv/test 2>&1 || echo "ok (nothing to ignore yet)"`
Expected: ścieżka albo OK (nie istnieje jeszcze).

- [ ] **Step 3: Commit**

```bash
cd /home/pc30/Desktop/desktopstation
git add .gitignore
git commit -m "chore: add top-level .gitignore for daemon and firmware"
```

---

### Task 2: Konsolidacja docs do top-level + edycja spec/03

**Files:**
- Create: `docs/plan/`, `docs/spec/`, `docs/designs/` (kopia z `deskstation-daemon/docs/`)
- Delete: `deskstation-daemon/docs/`, `deskstation-firmware/docs/`
- Modify: `docs/spec/03-project-structure.md` (sekcja "Dwa osobne repozytoria")

- [ ] **Step 1: Verify obie kopie są identyczne**

Run: `cd /home/pc30/Desktop/desktopstation && diff -r deskstation-daemon/docs deskstation-firmware/docs && echo "IDENTICAL"`
Expected: `IDENTICAL` (bez output z diff).

- [ ] **Step 2: Move docs do top-level**

Run:
```bash
cd /home/pc30/Desktop/desktopstation
git mv deskstation-daemon/docs/plan docs/plan
git mv deskstation-daemon/docs/spec docs/spec
git mv deskstation-daemon/docs/designs docs/designs
git mv deskstation-daemon/docs/README.md docs/README.md
git rm -r deskstation-firmware/docs
```

- [ ] **Step 3: Edit `docs/spec/03-project-structure.md` — sekcja monorepo**

Find first paragraph:
```
Dwa osobne repozytoria, niezależne lifecycle, niezależne wersjonowanie.
```

Replace with:
```
Monorepo: jedno repo `github.com/Dudeldel/desktopstation` z dwoma subdir-ami `deskstation-daemon/` i `deskstation-firmware/` plus wspólnym `docs/` na top-level. Wcześniejsza decyzja "dwa osobne repo" odrzucona — atomiczność zmian protokołu (host i firmware muszą iść razem) ważniejsza niż niezależny lifecycle.
```

- [ ] **Step 4: Verify struktura**

Run: `cd /home/pc30/Desktop/desktopstation && ls docs/ && ls deskstation-daemon/ && ls deskstation-firmware/`
Expected: `docs/` zawiera `plan/ spec/ designs/ README.md superpowers/`. `deskstation-daemon/` i `deskstation-firmware/` puste (lub bez `docs/`).

- [ ] **Step 5: Commit**

```bash
cd /home/pc30/Desktop/desktopstation
git add -A
git commit -m "docs: consolidate duplicated daemon/firmware docs to top-level docs/

- Move from deskstation-{daemon,firmware}/docs/ to docs/
- Update spec/03-project-structure.md: \"two repos\" -> \"monorepo\""
```

---

## Phase B — Daemon scaffold + protocol + bridge (M0 + M1 daemon-side)

### Task 3: `uv` setup + `pyproject.toml` + tooling configs

**Files:**
- Create: `deskstation-daemon/pyproject.toml`
- Create: `deskstation-daemon/.python-version`
- Create: `deskstation-daemon/.pre-commit-config.yaml`
- Create: `deskstation-daemon/config.yaml.example`
- Create: `deskstation-daemon/.env.example`
- Create: `deskstation-daemon/src/deskstation/__init__.py` (empty)

- [ ] **Step 1: Verify `uv` jest zainstalowane**

Run: `uv --version`
Expected: wersja >= 0.4. Jeśli nie ma — `pipx install uv` lub `curl -LsSf https://astral.sh/uv/install.sh | sh`.

- [ ] **Step 2: Create `pyproject.toml`**

Path: `deskstation-daemon/pyproject.toml`

```toml
[project]
name = "deskstation"
version = "0.1.0"
description = "Deskstation host daemon — desktop work station for Jira/Bitbucket/Google + pomodoro"
requires-python = ">=3.11"
dependencies = [
    "pyserial-asyncio>=0.6",
    "pydantic>=2.5",
    "pydantic-settings>=2.0",
    "pyyaml>=6.0",
    "python-dotenv>=1.0",
    "structlog>=24.0",
]

[project.optional-dependencies]
dev = [
    "ruff>=0.4",
    "mypy>=1.10",
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pre-commit>=3.7",
    "types-PyYAML",
]

[project.scripts]
deskstation = "deskstation.__main__:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/deskstation"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "RUF"]

[tool.mypy]
strict = true
python_version = "3.11"
mypy_path = "src"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 3: Create `.python-version`**

Path: `deskstation-daemon/.python-version`
Content: `3.11`

- [ ] **Step 4: Create `.pre-commit-config.yaml`**

Path: `deskstation-daemon/.pre-commit-config.yaml`

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.4.10
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format

  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.10.0
    hooks:
      - id: mypy
        files: ^deskstation-daemon/src/
        additional_dependencies:
          - pydantic>=2.5
          - pydantic-settings>=2.0
          - structlog>=24.0
          - types-PyYAML
```

- [ ] **Step 5: Create `config.yaml.example`**

Path: `deskstation-daemon/config.yaml.example`

```yaml
# Copy to config.yaml and customize. config.yaml is gitignored.

serial:
  device: /dev/ttyACM0
  baudrate: 921600
  reconnect_interval_sec: 2

bridge:
  mode: serial  # alternatives: mock

heartbeat:
  interval_sec: 5.0
  timeout_sec: 15.0

logging:
  level: INFO
  file: ~/.local/share/deskstation/logs/daemon.jsonl
  pretty_console: false
```

- [ ] **Step 6: Create `.env.example`**

Path: `deskstation-daemon/.env.example`

```
# Secrets will appear here starting from M4 (Jira API token, Bitbucket app password, etc.)
# For M0+M1 this file is intentionally empty.
```

- [ ] **Step 7: Create empty package init**

Path: `deskstation-daemon/src/deskstation/__init__.py`
Content: `"""Deskstation host daemon."""\n`

- [ ] **Step 8: Run `uv sync` to install deps and create lockfile**

Run: `cd /home/pc30/Desktop/desktopstation/deskstation-daemon && uv sync --all-extras`
Expected: tworzy `.venv/` i `uv.lock`. Brak błędów.

- [ ] **Step 9: Verify tooling działa**

Run:
```bash
cd /home/pc30/Desktop/desktopstation/deskstation-daemon
uv run ruff check src/
uv run mypy src/
uv run pytest --collect-only
```
Expected: ruff/mypy puste output (nic nie ma do sprawdzenia jeszcze), pytest "no tests collected".

- [ ] **Step 10: Install pre-commit hooks**

Run: `cd /home/pc30/Desktop/desktopstation/deskstation-daemon && uv run pre-commit install`
Expected: `pre-commit installed at .git/hooks/pre-commit` (działa z root git dir).

- [ ] **Step 11: Commit**

```bash
cd /home/pc30/Desktop/desktopstation
git add deskstation-daemon/pyproject.toml deskstation-daemon/uv.lock deskstation-daemon/.python-version deskstation-daemon/.pre-commit-config.yaml deskstation-daemon/config.yaml.example deskstation-daemon/.env.example deskstation-daemon/src/deskstation/__init__.py
git commit -m "feat(daemon): scaffold Python project with uv, pyproject, ruff, mypy, pytest

- pyproject.toml with deps for M0+M1 transport (pyserial-asyncio, pydantic, structlog)
- pre-commit hooks: ruff + mypy --strict
- config.yaml.example with serial/bridge/heartbeat/logging sections"
```

---

### Task 4: Protocol pydantic models — TDD

**Files:**
- Create: `deskstation-daemon/src/deskstation/bridge/__init__.py` (empty)
- Create: `deskstation-daemon/src/deskstation/bridge/protocol.py`
- Create: `deskstation-daemon/tests/__init__.py` (empty)
- Create: `deskstation-daemon/tests/conftest.py`
- Create: `deskstation-daemon/tests/test_protocol.py`

- [ ] **Step 1: Write the failing test**

Path: `deskstation-daemon/tests/test_protocol.py`

```python
"""Test pydantic envelope models for serial protocol M1 subset."""
import pytest
from pydantic import ValidationError

from deskstation.bridge.protocol import (
    AckMsg,
    Envelope,
    HeartbeatMsg,
    HelloMsg,
    ScreenChangedMsg,
    ToastMsg,
    parse_envelope,
    serialize_envelope,
)


def test_parse_hello() -> None:
    line = '{"v":1,"type":"hello","data":{"firmware_version":"0.1.0"}}'
    env = parse_envelope(line)
    assert isinstance(env, HelloMsg)
    assert env.data.firmware_version == "0.1.0"


def test_parse_heartbeat() -> None:
    line = '{"v":1,"type":"heartbeat","data":{}}'
    env = parse_envelope(line)
    assert isinstance(env, HeartbeatMsg)


def test_parse_toast() -> None:
    line = '{"v":1,"type":"toast","data":{"text":"hi","level":"warn"}}'
    env = parse_envelope(line)
    assert isinstance(env, ToastMsg)
    assert env.data.text == "hi"
    assert env.data.level == "warn"


def test_parse_toast_defaults_to_info() -> None:
    line = '{"v":1,"type":"toast","data":{"text":"hi"}}'
    env = parse_envelope(line)
    assert isinstance(env, ToastMsg)
    assert env.data.level == "info"


def test_parse_ack() -> None:
    line = '{"v":1,"type":"ack","data":{"ref":"abc-123"}}'
    env = parse_envelope(line)
    assert isinstance(env, AckMsg)
    assert env.data.ref == "abc-123"


def test_parse_screen_changed() -> None:
    line = '{"v":1,"type":"screen_changed","data":{"screen":"boot"}}'
    env = parse_envelope(line)
    assert isinstance(env, ScreenChangedMsg)
    assert env.data.screen == "boot"


def test_serialize_roundtrip() -> None:
    for env in [
        HelloMsg(data={"firmware_version": "0.1.0"}),
        HeartbeatMsg(data={}),
        ToastMsg(data={"text": "hello", "level": "error"}),
        AckMsg(data={"ref": "x"}),
        ScreenChangedMsg(data={"screen": "boot"}),
    ]:
        line = serialize_envelope(env)
        assert not line.endswith("\n")  # serialize does not include newline
        parsed = parse_envelope(line)
        assert parsed.type == env.type
        assert parsed.data == env.data


def test_parse_rejects_unknown_type() -> None:
    line = '{"v":1,"type":"top_bar","data":{}}'
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


def test_parse_rejects_oversized_line() -> None:
    big = '{"v":1,"type":"toast","data":{"text":"' + ("x" * 5000) + '"}}'
    assert len(big) > 4096
    with pytest.raises(ValueError, match="too long"):
        parse_envelope(big)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd deskstation-daemon && uv run pytest tests/test_protocol.py -v`
Expected: FAIL z `ImportError: No module named deskstation.bridge.protocol`.

- [ ] **Step 3: Create empty `bridge/__init__.py` and `tests/__init__.py`**

Path: `deskstation-daemon/src/deskstation/bridge/__init__.py` — content: `"""Serial bridge between host daemon and ESP32 firmware."""\n`
Path: `deskstation-daemon/tests/__init__.py` — content: empty.

- [ ] **Step 4: Create `conftest.py`**

Path: `deskstation-daemon/tests/conftest.py`

```python
"""Shared pytest fixtures."""
import pytest


@pytest.fixture
def example_hello_line() -> str:
    return '{"v":1,"type":"hello","data":{"firmware_version":"0.1.0"}}'
```

- [ ] **Step 5: Implement protocol models**

Path: `deskstation-daemon/src/deskstation/bridge/protocol.py`

```python
"""Pydantic models for the serial protocol envelope (M1 subset).

Only 5 message types are defined here: hello, heartbeat, toast, ack, screen_changed.
Additional types arrive in later milestones (M2+) and bump up the per-type union.
"""

import json
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

MAX_LINE_BYTES = 4096


class HelloData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    firmware_version: str


class HeartbeatData(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ToastData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str
    level: Literal["info", "warn", "error"] = "info"


class AckData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ref: str


class ScreenChangedData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    screen: str


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


Envelope = Annotated[
    Union[HelloMsg, HeartbeatMsg, ToastMsg, AckMsg, ScreenChangedMsg],
    Field(discriminator="type"),
]

_ENVELOPE_ADAPTER = TypeAdapter(Envelope)


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
```

- [ ] **Step 6: Run tests — verify pass**

Run: `cd deskstation-daemon && uv run pytest tests/test_protocol.py -v`
Expected: wszystkie 12 testów PASS.

- [ ] **Step 7: Run type check**

Run: `cd deskstation-daemon && uv run mypy src/`
Expected: `Success: no issues found`.

- [ ] **Step 8: Commit**

```bash
cd /home/pc30/Desktop/desktopstation
git add deskstation-daemon/src/deskstation/bridge/__init__.py deskstation-daemon/src/deskstation/bridge/protocol.py deskstation-daemon/tests/__init__.py deskstation-daemon/tests/conftest.py deskstation-daemon/tests/test_protocol.py
git commit -m "feat(daemon): pydantic models for M1 serial protocol envelope

- 5 message types: hello, heartbeat, toast, ack, screen_changed
- discriminated union via Field(discriminator=\"type\")
- parse_envelope() / serialize_envelope() with 4 KB line limit
- 12 tests covering happy path, defaults, validation rejects"
```

---

### Task 5: Bridge interface (`typing.Protocol`)

**Files:**
- Create: `deskstation-daemon/src/deskstation/bridge/interface.py`

- [ ] **Step 1: Create interface**

Path: `deskstation-daemon/src/deskstation/bridge/interface.py`

```python
"""Bridge interface — abstraction over USB serial / mock for testability."""
from collections.abc import AsyncIterator
from typing import Protocol

from deskstation.bridge.protocol import Envelope


class BridgeProtocol(Protocol):
    """Bidirectional channel for envelopes.

    Implementations: SerialBridge (USB CDC) and MockBridge (in-memory).
    """

    async def send(self, envelope: Envelope) -> None:
        """Send an envelope to the other end. Raises on permanent failure."""
        ...

    def stream(self) -> AsyncIterator[Envelope]:
        """Async iterator over incoming envelopes. Yields until closed."""
        ...

    async def close(self) -> None:
        """Close the bridge. After this, send() raises and stream() ends."""
        ...
```

- [ ] **Step 2: Verify mypy**

Run: `cd deskstation-daemon && uv run mypy src/`
Expected: `Success`.

- [ ] **Step 3: Commit**

```bash
cd /home/pc30/Desktop/desktopstation
git add deskstation-daemon/src/deskstation/bridge/interface.py
git commit -m "feat(daemon): bridge interface as typing.Protocol"
```

---

### Task 6: MockBridge + tests

**Files:**
- Create: `deskstation-daemon/src/deskstation/bridge/mock_bridge.py`
- Create: `deskstation-daemon/tests/test_mock_bridge.py`

- [ ] **Step 1: Write the failing test**

Path: `deskstation-daemon/tests/test_mock_bridge.py`

```python
"""Tests for the in-memory MockBridge."""
import asyncio

import pytest

from deskstation.bridge.mock_bridge import MockBridge
from deskstation.bridge.protocol import HeartbeatData, HeartbeatMsg, HelloData, HelloMsg


async def test_send_appears_in_outbound() -> None:
    bridge = MockBridge()
    msg = HeartbeatMsg(data=HeartbeatData())
    await bridge.send(msg)
    received = await bridge.received()
    assert received == msg
    await bridge.close()


async def test_injected_message_appears_in_stream() -> None:
    bridge = MockBridge()
    msg = HelloMsg(data=HelloData(firmware_version="0.1.0"))
    await bridge.inject(msg)
    async for env in bridge.stream():
        assert env == msg
        break
    await bridge.close()


async def test_send_after_close_raises() -> None:
    bridge = MockBridge()
    await bridge.close()
    with pytest.raises(RuntimeError, match="closed"):
        await bridge.send(HeartbeatMsg(data=HeartbeatData()))


async def test_stream_ends_after_close() -> None:
    bridge = MockBridge()
    await bridge.close()
    received = []
    async for env in bridge.stream():
        received.append(env)
    assert received == []
```

- [ ] **Step 2: Run tests — verify FAIL**

Run: `cd deskstation-daemon && uv run pytest tests/test_mock_bridge.py -v`
Expected: FAIL z ImportError.

- [ ] **Step 3: Implement MockBridge**

Path: `deskstation-daemon/src/deskstation/bridge/mock_bridge.py`

```python
"""In-memory bridge implementation for tests and dev-mode without ESP32."""
import asyncio
from collections.abc import AsyncIterator

from deskstation.bridge.protocol import Envelope


class MockBridge:
    """Two-queue in-memory bridge.

    - `send()` puts on outbound queue (test reads via `received()`)
    - `stream()` yields from inbound queue (test injects via `inject()`)
    """

    def __init__(self) -> None:
        self._inbound: asyncio.Queue[Envelope] = asyncio.Queue()
        self._outbound: asyncio.Queue[Envelope] = asyncio.Queue()
        self._closed = False

    async def send(self, envelope: Envelope) -> None:
        if self._closed:
            raise RuntimeError("bridge closed")
        await self._outbound.put(envelope)

    async def stream(self) -> AsyncIterator[Envelope]:
        while not self._closed:
            try:
                yield await asyncio.wait_for(self._inbound.get(), timeout=0.05)
            except asyncio.TimeoutError:
                continue

    async def close(self) -> None:
        self._closed = True

    # ---- test helpers ----

    async def inject(self, envelope: Envelope) -> None:
        """Inject an envelope as if it arrived from the other end."""
        await self._inbound.put(envelope)

    async def received(self) -> Envelope:
        """Pop the next envelope from the outbound queue (what daemon sent)."""
        return await self._outbound.get()
```

- [ ] **Step 4: Run tests — verify PASS**

Run: `cd deskstation-daemon && uv run pytest tests/test_mock_bridge.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Run mypy**

Run: `cd deskstation-daemon && uv run mypy src/`
Expected: `Success`.

- [ ] **Step 6: Commit**

```bash
cd /home/pc30/Desktop/desktopstation
git add deskstation-daemon/src/deskstation/bridge/mock_bridge.py deskstation-daemon/tests/test_mock_bridge.py
git commit -m "feat(daemon): MockBridge for headless tests and dev mode

- Two asyncio.Queue (inbound/outbound)
- inject() / received() test helpers
- 4 tests: send roundtrip, injected stream, send-after-close, stream-after-close"
```

---

### Task 7: SerialBridge — pyserial-asyncio + reconnect

**Files:**
- Create: `deskstation-daemon/src/deskstation/bridge/serial_bridge.py`
- Create: `deskstation-daemon/tests/test_serial_bridge.py`

- [ ] **Step 1: Write failing test**

Path: `deskstation-daemon/tests/test_serial_bridge.py`

Test używa fake reader/writer zamiast prawdziwego serial — SerialBridge zostanie zrefaktorowane żeby przyjmować reader/writer factory.

```python
"""Tests for SerialBridge with a fake stream pair."""
import asyncio
from typing import Optional

import pytest

from deskstation.bridge.protocol import HelloData, HeartbeatData, HeartbeatMsg, HelloMsg, ToastData, ToastMsg
from deskstation.bridge.serial_bridge import SerialBridge


class FakeStreamPair:
    """Bidirectional in-memory streams that look like asyncio.StreamReader/StreamWriter."""

    def __init__(self) -> None:
        self.host_to_device: asyncio.Queue[bytes] = asyncio.Queue()
        self.device_to_host: asyncio.Queue[bytes] = asyncio.Queue()
        self.closed = False
        self.eof_after_first_read = False
        self._buffer = b""

    # ---- writer-side (host writes) ----
    def write(self, data: bytes) -> None:
        self.host_to_device.put_nowait(data)

    async def drain(self) -> None:
        return

    def close(self) -> None:
        self.closed = True

    def is_closing(self) -> bool:
        return self.closed

    async def wait_closed(self) -> None:
        return

    # ---- reader-side (host reads from device) ----
    async def readline(self) -> bytes:
        if self.eof_after_first_read and self._buffer:
            data, self._buffer = self._buffer, b""
            self.eof_after_first_read = False
            return data
        if self.closed:
            return b""
        try:
            chunk = await asyncio.wait_for(self.device_to_host.get(), timeout=1.0)
        except asyncio.TimeoutError:
            return b""
        return chunk

    async def push_line(self, line: str) -> None:
        await self.device_to_host.put((line + "\n").encode("utf-8"))


@pytest.fixture
def fake_pair() -> FakeStreamPair:
    return FakeStreamPair()


@pytest.fixture
def bridge(fake_pair: FakeStreamPair) -> SerialBridge:
    async def factory() -> tuple[FakeStreamPair, FakeStreamPair]:
        return fake_pair, fake_pair

    return SerialBridge(connection_factory=factory, reconnect_interval_sec=0.01)  # type: ignore[arg-type]


async def test_send_writes_to_serial(bridge: SerialBridge, fake_pair: FakeStreamPair) -> None:
    msg = ToastMsg(data=ToastData(text="hello"))
    await bridge.send(msg)
    raw = await fake_pair.host_to_device.get()
    assert raw == (msg.model_dump_json() + "\n").encode("utf-8")
    await bridge.close()


async def test_stream_yields_parsed_envelopes(bridge: SerialBridge, fake_pair: FakeStreamPair) -> None:
    await fake_pair.push_line('{"v":1,"type":"hello","data":{"firmware_version":"0.1.0"}}')
    async for env in bridge.stream():
        assert isinstance(env, HelloMsg)
        assert env.data.firmware_version == "0.1.0"
        break
    await bridge.close()


async def test_stream_skips_malformed_line(bridge: SerialBridge, fake_pair: FakeStreamPair) -> None:
    await fake_pair.push_line("garbage not json {{")
    await fake_pair.push_line('{"v":1,"type":"heartbeat","data":{}}')
    async for env in bridge.stream():
        assert isinstance(env, HeartbeatMsg)
        break
    await bridge.close()
```

- [ ] **Step 2: Run tests — verify FAIL**

Run: `cd deskstation-daemon && uv run pytest tests/test_serial_bridge.py -v`
Expected: FAIL z ImportError.

- [ ] **Step 3: Implement SerialBridge**

Path: `deskstation-daemon/src/deskstation/bridge/serial_bridge.py`

```python
"""USB CDC serial bridge with auto-reconnect.

Uses pyserial-asyncio under the hood, but takes a `connection_factory` for testability.
"""
import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import structlog

from deskstation.bridge.protocol import Envelope, parse_envelope, serialize_envelope

log = structlog.get_logger(__name__)

ConnectionFactory = Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]]


def default_serial_factory(device: str, baudrate: int) -> ConnectionFactory:
    """Wrap pyserial-asyncio.open_serial_connection in a zero-arg async factory."""
    import serial_asyncio

    async def factory() -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        return await serial_asyncio.open_serial_connection(url=device, baudrate=baudrate)

    return factory


class SerialBridge:
    """Async USB CDC bridge with reconnect loop."""

    def __init__(
        self,
        connection_factory: ConnectionFactory,
        reconnect_interval_sec: float = 2.0,
    ) -> None:
        self._factory = connection_factory
        self._reconnect_interval = reconnect_interval_sec
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()
        self._closed = False

    async def _connect(self) -> None:
        while not self._closed:
            try:
                self._reader, self._writer = await self._factory()
                log.info("serial_connected")
                return
            except OSError as e:
                log.warning("serial_connect_failed", error=str(e))
                await asyncio.sleep(self._reconnect_interval)

    async def send(self, envelope: Envelope) -> None:
        if self._closed:
            raise RuntimeError("bridge closed")
        async with self._lock:
            if self._writer is None or self._writer.is_closing():
                await self._connect()
            assert self._writer is not None
            line = serialize_envelope(envelope) + "\n"
            self._writer.write(line.encode("utf-8"))
            try:
                await self._writer.drain()
            except OSError as e:
                log.warning("serial_drain_failed", error=str(e))

    async def stream(self) -> AsyncIterator[Envelope]:
        if self._reader is None:
            await self._connect()
        while not self._closed:
            assert self._reader is not None
            try:
                raw = await self._reader.readline()
            except OSError as e:
                log.warning("serial_read_failed", error=str(e))
                await self._connect()
                continue
            if not raw:
                # EOF — port closed; reconnect
                log.warning("serial_eof")
                await self._connect()
                continue
            try:
                line = raw.decode("utf-8").rstrip("\n").rstrip("\r")
            except UnicodeDecodeError as e:
                log.warning("serial_decode_failed", error=str(e))
                continue
            try:
                yield parse_envelope(line)
            except ValueError as e:
                log.warning("malformed_line", error=str(e), line=line[:200])
                continue
            except Exception as e:
                log.warning("validation_failed", error=str(e), line=line[:200])
                continue

    async def close(self) -> None:
        self._closed = True
        if self._writer is not None:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
```

- [ ] **Step 4: Run tests — verify PASS**

Run: `cd deskstation-daemon && uv run pytest tests/test_serial_bridge.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Run mypy**

Run: `cd deskstation-daemon && uv run mypy src/`
Expected: `Success`.

- [ ] **Step 6: Commit**

```bash
cd /home/pc30/Desktop/desktopstation
git add deskstation-daemon/src/deskstation/bridge/serial_bridge.py deskstation-daemon/tests/test_serial_bridge.py
git commit -m "feat(daemon): SerialBridge with pyserial-asyncio + reconnect

- ConnectionFactory abstraction for testability
- Reconnect loop on OSError / EOF, infinite retries with config interval
- Malformed JSON / validation errors logged but do not crash stream
- 3 tests with fake stream pair: send, stream, skip-malformed"
```

---

### Task 8: Heartbeat task + ConnectionMonitor

**Files:**
- Create: `deskstation-daemon/src/deskstation/bridge/heartbeat.py`
- Create: `deskstation-daemon/tests/test_heartbeat.py`

- [ ] **Step 1: Write failing test**

Path: `deskstation-daemon/tests/test_heartbeat.py`

```python
"""Tests for heartbeat sender and connection monitor."""
import asyncio

import pytest

from deskstation.bridge.heartbeat import ConnectionMonitor, heartbeat_sender
from deskstation.bridge.mock_bridge import MockBridge
from deskstation.bridge.protocol import HeartbeatMsg


async def test_heartbeat_sender_emits_at_interval() -> None:
    bridge = MockBridge()
    task = asyncio.create_task(heartbeat_sender(bridge, interval_sec=0.05))
    await asyncio.sleep(0.17)  # at least 3 ticks
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    count = 0
    while not bridge._outbound.empty():
        env = bridge._outbound.get_nowait()
        assert isinstance(env, HeartbeatMsg)
        count += 1
    assert count >= 3
    await bridge.close()


async def test_connection_monitor_initially_connected() -> None:
    mon = ConnectionMonitor(timeout_sec=10.0)
    assert mon.is_connected is True


async def test_connection_monitor_detects_disconnect() -> None:
    mon = ConnectionMonitor(timeout_sec=0.1)
    task = asyncio.create_task(mon.watchdog(poll_interval_sec=0.02))
    await asyncio.sleep(0.18)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert mon.is_connected is False


async def test_connection_monitor_reconnects_on_rx() -> None:
    mon = ConnectionMonitor(timeout_sec=0.05)
    task = asyncio.create_task(mon.watchdog(poll_interval_sec=0.02))
    await asyncio.sleep(0.12)
    assert mon.is_connected is False
    mon.mark_rx()
    assert mon.is_connected is True
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
```

- [ ] **Step 2: Run — verify FAIL**

Run: `cd deskstation-daemon && uv run pytest tests/test_heartbeat.py -v`
Expected: FAIL z ImportError.

- [ ] **Step 3: Implement heartbeat module**

Path: `deskstation-daemon/src/deskstation/bridge/heartbeat.py`

```python
"""Heartbeat sender + ConnectionMonitor for disconnect detection."""
import asyncio
import time

import structlog

from deskstation.bridge.interface import BridgeProtocol
from deskstation.bridge.protocol import HeartbeatData, HeartbeatMsg

log = structlog.get_logger(__name__)


async def heartbeat_sender(bridge: BridgeProtocol, interval_sec: float = 5.0) -> None:
    """Push a heartbeat envelope every `interval_sec`. Runs until cancelled."""
    while True:
        try:
            await bridge.send(HeartbeatMsg(data=HeartbeatData()))
        except Exception as e:
            log.warning("heartbeat_send_failed", error=str(e))
        await asyncio.sleep(interval_sec)


class ConnectionMonitor:
    """Tracks last-received timestamp; flips state on timeout / recovery."""

    def __init__(self, timeout_sec: float = 15.0) -> None:
        self._timeout = timeout_sec
        self._last_rx = time.monotonic()
        self._connected = True

    @property
    def is_connected(self) -> bool:
        return self._connected

    def mark_rx(self) -> None:
        self._last_rx = time.monotonic()
        if not self._connected:
            log.info("reconnected")
            self._connected = True

    async def watchdog(self, poll_interval_sec: float = 1.0) -> None:
        """Loop: every `poll_interval_sec` check elapsed-since-rx; flip state on threshold."""
        while True:
            await asyncio.sleep(poll_interval_sec)
            elapsed = time.monotonic() - self._last_rx
            if elapsed > self._timeout and self._connected:
                log.warning("disconnected", elapsed_sec=elapsed)
                self._connected = False
```

- [ ] **Step 4: Run — verify PASS**

Run: `cd deskstation-daemon && uv run pytest tests/test_heartbeat.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Run mypy + ruff**

Run: `cd deskstation-daemon && uv run mypy src/ && uv run ruff check src/ tests/`
Expected: `Success` z mypy, brak issues z ruff.

- [ ] **Step 6: Commit**

```bash
cd /home/pc30/Desktop/desktopstation
git add deskstation-daemon/src/deskstation/bridge/heartbeat.py deskstation-daemon/tests/test_heartbeat.py
git commit -m "feat(daemon): heartbeat sender + ConnectionMonitor for disconnect detection

- heartbeat_sender(): fire-and-forget task pushing HeartbeatMsg every N seconds
- ConnectionMonitor: tracks last RX, flips is_connected on >timeout, logs on flip
- 4 tests with short intervals (50–180 ms) for fast feedback"
```

---

### Task 9: Logging setup (structlog JSON)

**Files:**
- Create: `deskstation-daemon/src/deskstation/logging_setup.py`

- [ ] **Step 1: Implement logging setup**

Path: `deskstation-daemon/src/deskstation/logging_setup.py`

```python
"""structlog configuration for the deskstation daemon.

JSON output to file + (optionally) pretty console output for dev.
"""
import logging
import logging.handlers
import sys
from pathlib import Path

import structlog


def configure_logging(
    log_file: Path | None = None,
    pretty_console: bool = False,
    level: str = "INFO",
) -> None:
    """Configure structlog for the daemon.

    - JSON renderer writes to `log_file` (one event per line) if provided.
    - `pretty_console=True` enables a human-readable renderer on stderr.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    # File handler (JSON)
    handlers: list[logging.Handler] = []
    if log_file is not None:
        log_file = log_file.expanduser()
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=10 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(
            logging.Formatter(fmt="%(message)s")
        )
        handlers.append(file_handler)

    # Console handler
    if pretty_console:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setFormatter(logging.Formatter(fmt="%(message)s"))
        handlers.append(console_handler)

    logging.basicConfig(level=log_level, handlers=handlers, force=True)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Set up the actual renderer per-handler
    renderer_json = structlog.processors.JSONRenderer()
    renderer_pretty = structlog.dev.ConsoleRenderer(colors=True)

    for h in handlers:
        if isinstance(h, logging.StreamHandler) and not isinstance(
            h, logging.handlers.RotatingFileHandler
        ):
            h.setFormatter(
                structlog.stdlib.ProcessorFormatter(
                    foreign_pre_chain=shared_processors,
                    processors=[
                        structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                        renderer_pretty,
                    ],
                )
            )
        else:
            h.setFormatter(
                structlog.stdlib.ProcessorFormatter(
                    foreign_pre_chain=shared_processors,
                    processors=[
                        structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                        renderer_json,
                    ],
                )
            )
```

- [ ] **Step 2: Run mypy**

Run: `cd deskstation-daemon && uv run mypy src/`
Expected: `Success`.

- [ ] **Step 3: Commit**

```bash
cd /home/pc30/Desktop/desktopstation
git add deskstation-daemon/src/deskstation/logging_setup.py
git commit -m "feat(daemon): structlog setup with JSON file rotation + pretty console"
```

---

### Task 10: Config module (pydantic-settings)

**Files:**
- Create: `deskstation-daemon/src/deskstation/config.py`

- [ ] **Step 1: Implement config**

Path: `deskstation-daemon/src/deskstation/config.py`

```python
"""Daemon configuration loaded from YAML + env."""
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field


class SerialConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device: str = "/dev/ttyACM0"
    baudrate: int = 921600
    reconnect_interval_sec: float = 2.0


class BridgeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["serial", "mock"] = "serial"


class HeartbeatConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    interval_sec: float = 5.0
    timeout_sec: float = 15.0


class LoggingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    file: Path = Field(default=Path("~/.local/share/deskstation/logs/daemon.jsonl"))
    pretty_console: bool = False


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")
    serial: SerialConfig = Field(default_factory=SerialConfig)
    bridge: BridgeConfig = Field(default_factory=BridgeConfig)
    heartbeat: HeartbeatConfig = Field(default_factory=HeartbeatConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


def load_config(path: Path | None = None) -> Config:
    """Load config from YAML file, falling back to defaults if file missing.

    Resolution order:
    1. Explicit `path` argument
    2. `./config.yaml` in cwd
    3. `~/.config/deskstation/config.yaml`
    4. all defaults
    """
    candidates: list[Path] = []
    if path is not None:
        candidates.append(path)
    candidates.append(Path("config.yaml"))
    candidates.append(Path("~/.config/deskstation/config.yaml").expanduser())

    for candidate in candidates:
        if candidate.exists():
            with candidate.open() as f:
                data = yaml.safe_load(f) or {}
            return Config.model_validate(data)

    return Config()
```

- [ ] **Step 2: Run mypy**

Run: `cd deskstation-daemon && uv run mypy src/`
Expected: `Success`.

- [ ] **Step 3: Commit**

```bash
cd /home/pc30/Desktop/desktopstation
git add deskstation-daemon/src/deskstation/config.py
git commit -m "feat(daemon): pydantic config loader with YAML + sane defaults"
```

---

### Task 11: Main entry — wire bridge + heartbeat + signals

**Files:**
- Create: `deskstation-daemon/src/deskstation/main.py`
- Create: `deskstation-daemon/src/deskstation/__main__.py`

- [ ] **Step 1: Implement `main.py`**

Path: `deskstation-daemon/src/deskstation/main.py`

```python
"""Asyncio entry point: wires bridge, heartbeat, message dispatch."""
import asyncio
import signal

import structlog

from deskstation.bridge.heartbeat import ConnectionMonitor, heartbeat_sender
from deskstation.bridge.interface import BridgeProtocol
from deskstation.bridge.mock_bridge import MockBridge
from deskstation.bridge.protocol import (
    AckMsg,
    HeartbeatMsg,
    HelloMsg,
    ScreenChangedMsg,
    ToastMsg,
)
from deskstation.bridge.serial_bridge import SerialBridge, default_serial_factory
from deskstation.config import Config, load_config
from deskstation.logging_setup import configure_logging

log = structlog.get_logger(__name__)


def _build_bridge(cfg: Config) -> BridgeProtocol:
    if cfg.bridge.mode == "mock":
        log.info("bridge_mode_mock")
        return MockBridge()
    factory = default_serial_factory(cfg.serial.device, cfg.serial.baudrate)
    return SerialBridge(factory, reconnect_interval_sec=cfg.serial.reconnect_interval_sec)


async def _dispatch(bridge: BridgeProtocol, monitor: ConnectionMonitor) -> None:
    async for env in bridge.stream():
        monitor.mark_rx()
        if isinstance(env, HelloMsg):
            log.info("hello_received", firmware_version=env.data.firmware_version)
        elif isinstance(env, HeartbeatMsg):
            log.debug("heartbeat_received")
        elif isinstance(env, ScreenChangedMsg):
            log.info("screen_changed_received", screen=env.data.screen)
        elif isinstance(env, AckMsg):
            log.debug("ack_received", ref=env.data.ref)
        elif isinstance(env, ToastMsg):
            log.warning("toast_from_esp_ignored", text=env.data.text)
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

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    tasks = [
        asyncio.create_task(heartbeat_sender(bridge, interval_sec=cfg.heartbeat.interval_sec)),
        asyncio.create_task(_dispatch(bridge, monitor)),
        asyncio.create_task(monitor.watchdog()),
    ]

    await stop_event.wait()
    log.info("shutting_down")

    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await bridge.close()
    log.info("shutdown_complete")


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Implement `__main__.py`**

Path: `deskstation-daemon/src/deskstation/__main__.py`

```python
"""Entry point for `python -m deskstation`."""
from deskstation.main import main

if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Smoke test (mock mode)**

Run:
```bash
cd deskstation-daemon
cp config.yaml.example config.yaml
sed -i 's/mode: serial/mode: mock/' config.yaml
timeout 3 uv run python -m deskstation || true
cat ~/.local/share/deskstation/logs/daemon.jsonl | tail -5
```
Expected: w logu są wpisy `ready`, `bridge_mode_mock`, brak crash.

Cleanup: `rm deskstation-daemon/config.yaml`.

- [ ] **Step 4: Run mypy + ruff**

Run: `cd deskstation-daemon && uv run mypy src/ && uv run ruff check src/`
Expected: `Success`, brak issues.

- [ ] **Step 5: Commit**

```bash
cd /home/pc30/Desktop/desktopstation
git add deskstation-daemon/src/deskstation/main.py deskstation-daemon/src/deskstation/__main__.py
git commit -m "feat(daemon): wire bridge + heartbeat + dispatch + signal handlers in main

- Builds bridge per config.bridge.mode (serial|mock)
- Runs heartbeat_sender, _dispatch loop, ConnectionMonitor.watchdog as tasks
- Graceful shutdown on SIGINT/SIGTERM via stop_event"
```

---

### Task 12: Daemon `README.md`

**Files:**
- Create: `deskstation-daemon/README.md`

- [ ] **Step 1: Create README**

Path: `deskstation-daemon/README.md`

```markdown
# deskstation-daemon

Python asyncio daemon — host side of the Deskstation system. Talks to ESP32 firmware over USB CDC (`/dev/ttyACM0`).

## Quick start

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/) (one-time: `pipx install uv` or `curl -LsSf https://astral.sh/uv/install.sh | sh`).

```bash
cd deskstation-daemon

# Install deps and create venv
uv sync --all-extras

# Run tests
uv run pytest -v

# Type check + lint
uv run mypy src/
uv run ruff check src/ tests/

# Run the daemon (requires ESP32 plugged into /dev/ttyACM0)
cp config.yaml.example config.yaml
uv run deskstation
```

For development without a connected ESP32:

```bash
# Switch to mock bridge in config.yaml: bridge.mode = mock
uv run deskstation
```

## Logs

`~/.local/share/deskstation/logs/daemon.jsonl` (one JSON event per line, rotated at 10 MB × 3).

## Layout

- `src/deskstation/bridge/` — serial transport, protocol models, heartbeat
- `src/deskstation/main.py` — asyncio entry, wires it all
- `tests/` — pytest, headless (no ESP needed thanks to MockBridge)

## Status

M0 + M1 complete: scaffold + USB transport with heartbeat and reconnect. See `docs/superpowers/specs/2026-05-18-m0-m1-bootstrap-and-transport-design.md` and roadmap M2+ for what comes next.
```

- [ ] **Step 2: Commit**

```bash
cd /home/pc30/Desktop/desktopstation
git add deskstation-daemon/README.md
git commit -m "docs(daemon): README with quick start and layout"
```

---

## Phase C — Firmware scaffold + transport (M0 + M1 firmware-side)

### Task 13: `install_esp_idf.sh` script

**Files:**
- Create: `deskstation-firmware/tools/install_esp_idf.sh`

- [ ] **Step 1: Create install script**

Path: `deskstation-firmware/tools/install_esp_idf.sh`

```bash
#!/usr/bin/env bash
# One-shot installer for ESP-IDF v5.3 on Linux.
# Idempotent: re-running is safe.
set -euo pipefail

IDF_VERSION="v5.3"
IDF_DIR="${HOME}/esp/esp-idf"
TARGETS="esp32s3"

if [[ "$(uname)" != "Linux" ]]; then
    echo "ERROR: this script is for Linux only (you're on $(uname))."
    exit 1
fi

mkdir -p "${HOME}/esp"

if [[ -d "${IDF_DIR}/.git" ]]; then
    echo "ESP-IDF already cloned at ${IDF_DIR}, fetching ${IDF_VERSION}..."
    cd "${IDF_DIR}"
    git fetch origin
    git checkout "${IDF_VERSION}"
    git submodule update --init --recursive
else
    echo "Cloning ESP-IDF ${IDF_VERSION} into ${IDF_DIR}..."
    git clone --branch "${IDF_VERSION}" --recursive https://github.com/espressif/esp-idf.git "${IDF_DIR}"
fi

echo "Running ESP-IDF installer for targets: ${TARGETS}"
cd "${IDF_DIR}"
./install.sh "${TARGETS}"

echo ""
echo "==============================================================="
echo "ESP-IDF ${IDF_VERSION} installed at ${IDF_DIR}"
echo ""
echo "To activate, run in each new shell:"
echo "    . ${IDF_DIR}/export.sh"
echo ""
echo "Or add to ~/.bashrc:"
echo "    alias get_idf='. ${IDF_DIR}/export.sh'"
echo ""
echo "Verify with: idf.py --version"
echo "==============================================================="
```

- [ ] **Step 2: Make executable**

Run: `chmod +x deskstation-firmware/tools/install_esp_idf.sh`

- [ ] **Step 3: Commit**

```bash
cd /home/pc30/Desktop/desktopstation
git add deskstation-firmware/tools/install_esp_idf.sh
git commit -m "feat(firmware): one-shot ESP-IDF v5.3 installer script"
```

- [ ] **Step 4: USER runs installer (manual, ~10–20 min)**

This step is for the human / Claude-Code-in-charge to execute interactively, since it requires `apt` deps and downloads ~600 MB:

Run: `bash deskstation-firmware/tools/install_esp_idf.sh`
Expected: ESP-IDF v5.3 zainstalowane w `~/esp/esp-idf/`, `idf.py --version` po `. ~/esp/esp-idf/export.sh` zwraca `ESP-IDF v5.3.x`.

---

### Task 14: ESP-IDF project skeleton

**Files:**
- Create: `deskstation-firmware/CMakeLists.txt`
- Create: `deskstation-firmware/sdkconfig.defaults`
- Create: `deskstation-firmware/partitions.csv`
- Create: `deskstation-firmware/main/CMakeLists.txt`
- Create: `deskstation-firmware/main/idf_component.yml`

- [ ] **Step 1: Top-level `CMakeLists.txt`**

Path: `deskstation-firmware/CMakeLists.txt`

```cmake
cmake_minimum_required(VERSION 3.16)
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(deskstation)
```

- [ ] **Step 2: `sdkconfig.defaults`**

Path: `deskstation-firmware/sdkconfig.defaults`

```
# Target
CONFIG_IDF_TARGET="esp32s3"

# USB CDC via TinyUSB
CONFIG_TINYUSB_CDC_ENABLED=y
CONFIG_TINYUSB_CDC_RX_BUFSIZE=2048
CONFIG_TINYUSB_CDC_TX_BUFSIZE=2048

# PSRAM (octal, 8 MB on ESP32-S3-N16R8)
CONFIG_SPIRAM=y
CONFIG_SPIRAM_MODE_OCT=y
CONFIG_SPIRAM_SPEED_80M=y
CONFIG_SPIRAM_USE_MALLOC=y
CONFIG_SPIRAM_MALLOC_ALWAYSINTERNAL=16384

# FreeRTOS
CONFIG_FREERTOS_HZ=1000
CONFIG_ESP_TASK_WDT_TIMEOUT_S=10

# LVGL color depth 16 bpp
CONFIG_LV_COLOR_DEPTH_16=y

# Flash size (16 MB)
CONFIG_ESPTOOLPY_FLASHSIZE_16MB=y
CONFIG_PARTITION_TABLE_CUSTOM=y
CONFIG_PARTITION_TABLE_CUSTOM_FILENAME="partitions.csv"

# Console — logs go to JTAG/UART debug port (NOT USB CDC, which is reserved for our protocol)
CONFIG_ESP_CONSOLE_UART_DEFAULT=y
```

- [ ] **Step 3: `partitions.csv`**

Path: `deskstation-firmware/partitions.csv`

```
# Name,   Type, SubType, Offset,  Size,    Flags
nvs,      data, nvs,     0x9000,  0x6000,
phy_init, data, phy,     0xf000,  0x1000,
factory,  app,  factory, 0x10000, 4M,
```

- [ ] **Step 4: `main/CMakeLists.txt`**

Path: `deskstation-firmware/main/CMakeLists.txt`

```cmake
idf_component_register(
    SRCS
        "main.c"
        "board.c"
        "usb_cdc.c"
        "protocol.c"
        "ui_state.c"
        "ui/ui.c"
        "ui/toast.c"
    INCLUDE_DIRS
        "."
        "ui"
    REQUIRES
        json
        esp_lcd
        esp_lcd_touch_gt911
        esp_tinyusb
        lvgl
        driver
        nvs_flash
)
```

- [ ] **Step 5: `main/idf_component.yml`**

Path: `deskstation-firmware/main/idf_component.yml`

```yaml
dependencies:
  idf:
    version: ">=5.3"
  lvgl/lvgl:
    version: "^8.4.0"
  espressif/esp_lcd_touch_gt911:
    version: "^1.0"
  espressif/esp_tinyusb:
    version: "^1.4"
```

- [ ] **Step 6: Commit (NIE budujemy jeszcze — wymaga source files)**

```bash
cd /home/pc30/Desktop/desktopstation
git add deskstation-firmware/CMakeLists.txt deskstation-firmware/sdkconfig.defaults deskstation-firmware/partitions.csv deskstation-firmware/main/CMakeLists.txt deskstation-firmware/main/idf_component.yml
git commit -m "feat(firmware): ESP-IDF v5.3 project skeleton

- Top-level CMakeLists, sdkconfig.defaults, partitions.csv (16 MB flash)
- main/CMakeLists.txt with REQUIRES: json, esp_lcd, esp_lcd_touch_gt911, esp_tinyusb, lvgl
- main/idf_component.yml: pins LVGL 8.4.x and stock ESP-IDF drivers (no Waveshare BSP submodule)"
```

---

### Task 15: Board init — RGB LCD + GT911 touch

**Files:**
- Create: `deskstation-firmware/main/board.h`
- Create: `deskstation-firmware/main/board.c`

Notatka: piny i timingi pochodzą z datasheetu Waveshare ESP32-S3-Touch-LCD-7. Wartości poniżej są szablonowe — przed flashem zweryfikuj z dokumentacją Waveshare ([repo referencyjne](https://github.com/waveshareteam/Waveshare-ESP32-S3-Touch-LCD-7)).

- [ ] **Step 1: `board.h`**

Path: `deskstation-firmware/main/board.h`

```c
#pragma once

#include "esp_err.h"
#include "esp_lcd_panel_ops.h"
#include "esp_lcd_touch.h"

#define BOARD_LCD_WIDTH  800
#define BOARD_LCD_HEIGHT 480

// Initialize PSRAM-aware heap, RGB LCD panel, and GT911 touch controller.
// On success, populates *out_panel and *out_touch with handles.
esp_err_t board_init(esp_lcd_panel_handle_t *out_panel,
                     esp_lcd_touch_handle_t *out_touch);
```

- [ ] **Step 2: `board.c`** (RGB panel + GT911 init — stock ESP-IDF drivers)

Path: `deskstation-firmware/main/board.c`

```c
#include "board.h"

#include "driver/i2c.h"
#include "esp_check.h"
#include "esp_lcd_panel_rgb.h"
#include "esp_lcd_touch_gt911.h"
#include "esp_log.h"

static const char *TAG = "board";

// --- Pin definitions (Waveshare ESP32-S3-Touch-LCD-7, verify against datasheet) ---

// RGB LCD pins (16-bit RGB565)
#define LCD_PIN_HSYNC 46
#define LCD_PIN_VSYNC 3
#define LCD_PIN_DE    5
#define LCD_PIN_PCLK  7
#define LCD_PIN_DISP  -1

#define LCD_PIN_R0 1
#define LCD_PIN_R1 2
#define LCD_PIN_R2 42
#define LCD_PIN_R3 41
#define LCD_PIN_R4 40
#define LCD_PIN_G0 39
#define LCD_PIN_G1 0
#define LCD_PIN_G2 45
#define LCD_PIN_G3 48
#define LCD_PIN_G4 47
#define LCD_PIN_G5 21
#define LCD_PIN_B0 14
#define LCD_PIN_B1 38
#define LCD_PIN_B2 18
#define LCD_PIN_B3 17
#define LCD_PIN_B4 10

// Touch I2C pins
#define TOUCH_I2C_PORT  I2C_NUM_0
#define TOUCH_PIN_SDA   8
#define TOUCH_PIN_SCL   9
#define TOUCH_PIN_INT   4
#define TOUCH_PIN_RESET -1  // shared with LCD reset on this board

static esp_err_t init_rgb_panel(esp_lcd_panel_handle_t *out_panel)
{
    esp_lcd_rgb_panel_config_t panel_config = {
        .data_width = 16,
        .psram_trans_align = 64,
        .num_fbs = 2,
        .clk_src = LCD_CLK_SRC_DEFAULT,
        .disp_gpio_num = LCD_PIN_DISP,
        .pclk_gpio_num = LCD_PIN_PCLK,
        .vsync_gpio_num = LCD_PIN_VSYNC,
        .hsync_gpio_num = LCD_PIN_HSYNC,
        .de_gpio_num = LCD_PIN_DE,
        .data_gpio_nums = {
            LCD_PIN_B0, LCD_PIN_B1, LCD_PIN_B2, LCD_PIN_B3, LCD_PIN_B4,
            LCD_PIN_G0, LCD_PIN_G1, LCD_PIN_G2, LCD_PIN_G3, LCD_PIN_G4, LCD_PIN_G5,
            LCD_PIN_R0, LCD_PIN_R1, LCD_PIN_R2, LCD_PIN_R3, LCD_PIN_R4,
        },
        .timings = {
            .pclk_hz = 16 * 1000 * 1000,
            .h_res = BOARD_LCD_WIDTH,
            .v_res = BOARD_LCD_HEIGHT,
            .hsync_pulse_width = 4,
            .hsync_back_porch = 8,
            .hsync_front_porch = 8,
            .vsync_pulse_width = 4,
            .vsync_back_porch = 8,
            .vsync_front_porch = 8,
            .flags.pclk_active_neg = 1,
        },
        .flags.fb_in_psram = 1,
    };
    ESP_RETURN_ON_ERROR(
        esp_lcd_new_rgb_panel(&panel_config, out_panel),
        TAG, "create RGB panel"
    );
    ESP_RETURN_ON_ERROR(esp_lcd_panel_init(*out_panel), TAG, "init panel");
    ESP_LOGI(TAG, "RGB panel initialized: %dx%d", BOARD_LCD_WIDTH, BOARD_LCD_HEIGHT);
    return ESP_OK;
}

static esp_err_t init_touch(esp_lcd_touch_handle_t *out_touch)
{
    i2c_config_t i2c_conf = {
        .mode = I2C_MODE_MASTER,
        .sda_io_num = TOUCH_PIN_SDA,
        .scl_io_num = TOUCH_PIN_SCL,
        .sda_pullup_en = GPIO_PULLUP_ENABLE,
        .scl_pullup_en = GPIO_PULLUP_ENABLE,
        .master.clk_speed = 400000,
    };
    ESP_RETURN_ON_ERROR(i2c_param_config(TOUCH_I2C_PORT, &i2c_conf), TAG, "i2c cfg");
    ESP_RETURN_ON_ERROR(i2c_driver_install(TOUCH_I2C_PORT, I2C_MODE_MASTER, 0, 0, 0), TAG, "i2c drv");

    esp_lcd_panel_io_handle_t touch_io = NULL;
    esp_lcd_panel_io_i2c_config_t tp_io_config = ESP_LCD_TOUCH_IO_I2C_GT911_CONFIG();
    ESP_RETURN_ON_ERROR(
        esp_lcd_new_panel_io_i2c((esp_lcd_i2c_bus_handle_t)TOUCH_I2C_PORT, &tp_io_config, &touch_io),
        TAG, "touch io"
    );

    esp_lcd_touch_config_t tp_cfg = {
        .x_max = BOARD_LCD_WIDTH,
        .y_max = BOARD_LCD_HEIGHT,
        .rst_gpio_num = TOUCH_PIN_RESET,
        .int_gpio_num = TOUCH_PIN_INT,
        .flags = {.swap_xy = 0, .mirror_x = 0, .mirror_y = 0},
    };
    ESP_RETURN_ON_ERROR(esp_lcd_touch_new_i2c_gt911(touch_io, &tp_cfg, out_touch), TAG, "gt911");
    ESP_LOGI(TAG, "GT911 touch initialized");
    return ESP_OK;
}

esp_err_t board_init(esp_lcd_panel_handle_t *out_panel,
                     esp_lcd_touch_handle_t *out_touch)
{
    ESP_RETURN_ON_ERROR(init_rgb_panel(out_panel), TAG, "rgb panel");
    ESP_RETURN_ON_ERROR(init_touch(out_touch), TAG, "touch");
    return ESP_OK;
}
```

- [ ] **Step 3: Commit (jeszcze nie buduje — brakuje innych modułów)**

```bash
cd /home/pc30/Desktop/desktopstation
git add deskstation-firmware/main/board.h deskstation-firmware/main/board.c
git commit -m "feat(firmware): board init for RGB LCD (800x480) + GT911 touch via stock drivers"
```

---

### Task 16: USB CDC reader/writer + queues

**Files:**
- Create: `deskstation-firmware/main/usb_cdc.h`
- Create: `deskstation-firmware/main/usb_cdc.c`

- [ ] **Step 1: `usb_cdc.h`**

Path: `deskstation-firmware/main/usb_cdc.h`

```c
#pragma once

#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include <stdbool.h>
#include <stddef.h>

#define USB_LINE_MAX_LEN 4096

typedef struct {
    char data[USB_LINE_MAX_LEN];
    size_t len;
} usb_line_t;

// Initialize TinyUSB CDC and create RX/TX queues (each capacity 16 lines).
esp_err_t usb_cdc_init(void);

// Get queue handles (used by tasks).
QueueHandle_t usb_cdc_rx_queue(void);
QueueHandle_t usb_cdc_tx_queue(void);

// Start the FreeRTOS reader and writer tasks (must be called once after init).
esp_err_t usb_cdc_start_tasks(void);
```

- [ ] **Step 2: `usb_cdc.c`**

Path: `deskstation-firmware/main/usb_cdc.c`

```c
#include "usb_cdc.h"

#include "esp_log.h"
#include "freertos/task.h"
#include "tinyusb.h"
#include "tusb_cdc_acm.h"

#include <string.h>

static const char *TAG = "usb_cdc";

#define USB_QUEUE_LEN 16

static QueueHandle_t s_rx_queue;
static QueueHandle_t s_tx_queue;
static char s_rx_buf[USB_LINE_MAX_LEN];
static size_t s_rx_len;

static void on_cdc_rx(int itf, cdcacm_event_t *event)
{
    (void)itf;
    (void)event;
    uint8_t chunk[64];
    size_t got = 0;
    while (tinyusb_cdcacm_read(TINYUSB_CDC_ACM_0, chunk, sizeof(chunk), &got) == ESP_OK && got > 0) {
        for (size_t i = 0; i < got; ++i) {
            char c = (char)chunk[i];
            if (c == '\n') {
                if (s_rx_len > 0 && s_rx_buf[s_rx_len - 1] == '\r') s_rx_len--;
                usb_line_t line;
                memcpy(line.data, s_rx_buf, s_rx_len);
                line.data[s_rx_len] = '\0';
                line.len = s_rx_len;
                if (xQueueSend(s_rx_queue, &line, 0) != pdTRUE) {
                    ESP_LOGW(TAG, "rx queue full, dropped line");
                }
                s_rx_len = 0;
            } else if (s_rx_len < USB_LINE_MAX_LEN - 1) {
                s_rx_buf[s_rx_len++] = c;
            } else {
                ESP_LOGW(TAG, "rx line overflow, dropping buffer");
                s_rx_len = 0;
            }
        }
    }
}

static void tx_task(void *arg)
{
    (void)arg;
    usb_line_t line;
    while (1) {
        if (xQueueReceive(s_tx_queue, &line, portMAX_DELAY) == pdTRUE) {
            tinyusb_cdcacm_write_queue(TINYUSB_CDC_ACM_0, (const uint8_t *)line.data, line.len);
            const char nl = '\n';
            tinyusb_cdcacm_write_queue(TINYUSB_CDC_ACM_0, (const uint8_t *)&nl, 1);
            tinyusb_cdcacm_write_flush(TINYUSB_CDC_ACM_0, 0);
        }
    }
}

esp_err_t usb_cdc_init(void)
{
    s_rx_queue = xQueueCreate(USB_QUEUE_LEN, sizeof(usb_line_t));
    s_tx_queue = xQueueCreate(USB_QUEUE_LEN, sizeof(usb_line_t));
    if (!s_rx_queue || !s_tx_queue) return ESP_ERR_NO_MEM;

    const tinyusb_config_t tusb_cfg = {0};
    ESP_ERROR_CHECK(tinyusb_driver_install(&tusb_cfg));

    tinyusb_config_cdcacm_t acm_cfg = {
        .usb_dev = TINYUSB_USBDEV_0,
        .cdc_port = TINYUSB_CDC_ACM_0,
        .rx_unread_buf_sz = 1024,
        .callback_rx = &on_cdc_rx,
        .callback_rx_wanted_char = NULL,
        .callback_line_state_changed = NULL,
        .callback_line_coding_changed = NULL,
    };
    ESP_ERROR_CHECK(tusb_cdc_acm_init(&acm_cfg));

    ESP_LOGI(TAG, "USB CDC initialized");
    return ESP_OK;
}

QueueHandle_t usb_cdc_rx_queue(void) { return s_rx_queue; }
QueueHandle_t usb_cdc_tx_queue(void) { return s_tx_queue; }

esp_err_t usb_cdc_start_tasks(void)
{
    if (xTaskCreatePinnedToCore(tx_task, "usb_tx", 4096, NULL, 5, NULL, 0) != pdPASS) {
        return ESP_FAIL;
    }
    return ESP_OK;
}
```

- [ ] **Step 3: Commit**

```bash
cd /home/pc30/Desktop/desktopstation
git add deskstation-firmware/main/usb_cdc.h deskstation-firmware/main/usb_cdc.c
git commit -m "feat(firmware): USB CDC reader (callback) + tx task with 16-line queues"
```

---

### Task 17: Protocol — cJSON parse / serialize

**Files:**
- Create: `deskstation-firmware/main/protocol.h`
- Create: `deskstation-firmware/main/protocol.c`

- [ ] **Step 1: `protocol.h`**

Path: `deskstation-firmware/main/protocol.h`

```c
#pragma once

#include <stdbool.h>
#include <stddef.h>

typedef enum {
    MSG_HELLO,
    MSG_HEARTBEAT,
    MSG_TOAST,
    MSG_ACK,
    MSG_SCREEN_CHANGED,
    MSG_UNKNOWN,
} msg_type_t;

#define TEXT_MAX 256

typedef struct {
    char text[TEXT_MAX];
    char level[8];  // info, warn, error
} toast_payload_t;

typedef struct {
    char ref[64];
} ack_payload_t;

typedef struct {
    msg_type_t type;
    union {
        toast_payload_t toast;
        ack_payload_t ack;
    } data;
} parsed_msg_t;

// Parse a single line (NUL-terminated, no trailing newline).
// Returns true if parsed successfully, false on error (caller logs).
bool protocol_parse(const char *line, parsed_msg_t *out);

// Serialize outgoing messages. Each writes into `buf` (size `cap`), returns bytes written or -1.

int protocol_serialize_hello(char *buf, size_t cap, const char *firmware_version);
int protocol_serialize_heartbeat(char *buf, size_t cap);
int protocol_serialize_screen_changed(char *buf, size_t cap, const char *screen);
```

- [ ] **Step 2: `protocol.c`**

Path: `deskstation-firmware/main/protocol.c`

```c
#include "protocol.h"

#include "cJSON.h"
#include "esp_log.h"
#include <stdio.h>
#include <string.h>

static const char *TAG = "protocol";

static msg_type_t parse_type(const char *t)
{
    if (!t) return MSG_UNKNOWN;
    if (strcmp(t, "hello") == 0) return MSG_HELLO;
    if (strcmp(t, "heartbeat") == 0) return MSG_HEARTBEAT;
    if (strcmp(t, "toast") == 0) return MSG_TOAST;
    if (strcmp(t, "ack") == 0) return MSG_ACK;
    if (strcmp(t, "screen_changed") == 0) return MSG_SCREEN_CHANGED;
    return MSG_UNKNOWN;
}

bool protocol_parse(const char *line, parsed_msg_t *out)
{
    cJSON *root = cJSON_Parse(line);
    if (!root) {
        ESP_LOGW(TAG, "malformed JSON");
        return false;
    }

    bool ok = false;
    cJSON *v = cJSON_GetObjectItem(root, "v");
    if (!cJSON_IsNumber(v) || v->valueint != 1) {
        ESP_LOGW(TAG, "wrong version: %d", v ? v->valueint : -1);
        goto done;
    }

    cJSON *type = cJSON_GetObjectItem(root, "type");
    if (!cJSON_IsString(type)) {
        ESP_LOGW(TAG, "missing type");
        goto done;
    }
    out->type = parse_type(type->valuestring);
    if (out->type == MSG_UNKNOWN) {
        ESP_LOGW(TAG, "unknown type: %s", type->valuestring);
        goto done;
    }

    cJSON *data = cJSON_GetObjectItem(root, "data");
    if (!cJSON_IsObject(data)) {
        ESP_LOGW(TAG, "missing data");
        goto done;
    }

    if (out->type == MSG_TOAST) {
        cJSON *text = cJSON_GetObjectItem(data, "text");
        cJSON *level = cJSON_GetObjectItem(data, "level");
        if (!cJSON_IsString(text)) {
            ESP_LOGW(TAG, "toast missing text");
            goto done;
        }
        strncpy(out->data.toast.text, text->valuestring, TEXT_MAX - 1);
        out->data.toast.text[TEXT_MAX - 1] = '\0';
        const char *lvl = (cJSON_IsString(level)) ? level->valuestring : "info";
        strncpy(out->data.toast.level, lvl, sizeof(out->data.toast.level) - 1);
        out->data.toast.level[sizeof(out->data.toast.level) - 1] = '\0';
    } else if (out->type == MSG_ACK) {
        cJSON *ref = cJSON_GetObjectItem(data, "ref");
        if (!cJSON_IsString(ref)) {
            ESP_LOGW(TAG, "ack missing ref");
            goto done;
        }
        strncpy(out->data.ack.ref, ref->valuestring, sizeof(out->data.ack.ref) - 1);
        out->data.ack.ref[sizeof(out->data.ack.ref) - 1] = '\0';
    }
    // heartbeat — no data needed
    // hello / screen_changed — incoming would be ignored (these are ESP→host directions)

    ok = true;
done:
    cJSON_Delete(root);
    return ok;
}

int protocol_serialize_hello(char *buf, size_t cap, const char *firmware_version)
{
    return snprintf(buf, cap,
        "{\"v\":1,\"type\":\"hello\",\"data\":{\"firmware_version\":\"%s\"}}",
        firmware_version);
}

int protocol_serialize_heartbeat(char *buf, size_t cap)
{
    return snprintf(buf, cap, "{\"v\":1,\"type\":\"heartbeat\",\"data\":{}}");
}

int protocol_serialize_screen_changed(char *buf, size_t cap, const char *screen)
{
    return snprintf(buf, cap,
        "{\"v\":1,\"type\":\"screen_changed\",\"data\":{\"screen\":\"%s\"}}",
        screen);
}
```

- [ ] **Step 3: Commit**

```bash
cd /home/pc30/Desktop/desktopstation
git add deskstation-firmware/main/protocol.h deskstation-firmware/main/protocol.c
git commit -m "feat(firmware): cJSON parser/serializer for M1 envelope subset"
```

---

### Task 18: UI state + LVGL hello + toast widget

**Files:**
- Create: `deskstation-firmware/main/ui_state.h`
- Create: `deskstation-firmware/main/ui_state.c`
- Create: `deskstation-firmware/main/ui/ui.h`
- Create: `deskstation-firmware/main/ui/ui.c`
- Create: `deskstation-firmware/main/ui/toast.h`
- Create: `deskstation-firmware/main/ui/toast.c`

- [ ] **Step 1: `ui_state.h`**

Path: `deskstation-firmware/main/ui_state.h`

```c
#pragma once

#include <stdbool.h>

typedef struct {
    bool connected;
    char last_toast[256];
} ui_state_t;

ui_state_t *ui_state_get(void);
void ui_state_set_connected(bool connected);
```

- [ ] **Step 2: `ui_state.c`**

Path: `deskstation-firmware/main/ui_state.c`

```c
#include "ui_state.h"

#include <string.h>

static ui_state_t s_state = {.connected = true};

ui_state_t *ui_state_get(void) { return &s_state; }

void ui_state_set_connected(bool connected) { s_state.connected = connected; }
```

- [ ] **Step 3: `ui/ui.h`**

Path: `deskstation-firmware/main/ui/ui.h`

```c
#pragma once

#include "esp_err.h"
#include "esp_lcd_panel_ops.h"
#include "esp_lcd_touch.h"

// Initialize LVGL on top of the RGB panel and touch handles.
// Spawns the LVGL tick + handler task on core 1.
esp_err_t ui_init(esp_lcd_panel_handle_t panel, esp_lcd_touch_handle_t touch);

// Build the M0+M1 placeholder screen (full-screen "Hello, Deskstation. M0+M1.").
void ui_build_hello_screen(void);
```

- [ ] **Step 4: `ui/ui.c`**

Path: `deskstation-firmware/main/ui/ui.c`

```c
#include "ui.h"
#include "toast.h"

#include "esp_log.h"
#include "esp_lcd_panel_io.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "lvgl.h"

static const char *TAG = "ui";

#define LVGL_TICK_PERIOD_MS 5
#define LVGL_TASK_STACK 8192
#define LVGL_TASK_PRIO 2
#define LVGL_TASK_CORE 1

static lv_disp_drv_t s_disp_drv;
static lv_disp_draw_buf_t s_draw_buf;
static esp_lcd_panel_handle_t s_panel;
static esp_lcd_touch_handle_t s_touch;

static void flush_cb(lv_disp_drv_t *drv, const lv_area_t *area, lv_color_t *color_map)
{
    esp_lcd_panel_draw_bitmap(s_panel,
                              area->x1, area->y1,
                              area->x2 + 1, area->y2 + 1,
                              color_map);
    lv_disp_flush_ready(drv);
}

static void touch_read_cb(lv_indev_drv_t *drv, lv_indev_data_t *data)
{
    (void)drv;
    uint16_t x[1] = {0};
    uint16_t y[1] = {0};
    uint16_t strength[1] = {0};
    uint8_t count = 0;
    esp_lcd_touch_read_data(s_touch);
    bool pressed = esp_lcd_touch_get_coordinates(s_touch, x, y, strength, &count, 1);
    data->state = (pressed && count > 0) ? LV_INDEV_STATE_PR : LV_INDEV_STATE_REL;
    if (pressed && count > 0) {
        data->point.x = x[0];
        data->point.y = y[0];
    }
}

static void tick_cb(void *arg) { (void)arg; lv_tick_inc(LVGL_TICK_PERIOD_MS); }

static void lvgl_task(void *arg)
{
    (void)arg;
    while (1) {
        lv_timer_handler();
        vTaskDelay(pdMS_TO_TICKS(LVGL_TICK_PERIOD_MS));
    }
}

esp_err_t ui_init(esp_lcd_panel_handle_t panel, esp_lcd_touch_handle_t touch)
{
    s_panel = panel;
    s_touch = touch;

    lv_init();

    const size_t buf_pixels = 800 * 60;
    lv_color_t *buf1 = heap_caps_malloc(buf_pixels * sizeof(lv_color_t), MALLOC_CAP_SPIRAM);
    lv_color_t *buf2 = heap_caps_malloc(buf_pixels * sizeof(lv_color_t), MALLOC_CAP_SPIRAM);
    lv_disp_draw_buf_init(&s_draw_buf, buf1, buf2, buf_pixels);

    lv_disp_drv_init(&s_disp_drv);
    s_disp_drv.hor_res = 800;
    s_disp_drv.ver_res = 480;
    s_disp_drv.flush_cb = flush_cb;
    s_disp_drv.draw_buf = &s_draw_buf;
    lv_disp_drv_register(&s_disp_drv);

    static lv_indev_drv_t indev_drv;
    lv_indev_drv_init(&indev_drv);
    indev_drv.type = LV_INDEV_TYPE_POINTER;
    indev_drv.read_cb = touch_read_cb;
    lv_indev_drv_register(&indev_drv);

    const esp_timer_create_args_t tick_args = {
        .callback = &tick_cb, .name = "lv_tick",
    };
    esp_timer_handle_t tick_handle;
    esp_timer_create(&tick_args, &tick_handle);
    esp_timer_start_periodic(tick_handle, LVGL_TICK_PERIOD_MS * 1000);

    if (xTaskCreatePinnedToCore(lvgl_task, "lvgl", LVGL_TASK_STACK, NULL,
                                LVGL_TASK_PRIO, NULL, LVGL_TASK_CORE) != pdPASS) {
        return ESP_FAIL;
    }

    ESP_LOGI(TAG, "LVGL initialized");
    return ESP_OK;
}

void ui_build_hello_screen(void)
{
    lv_obj_t *scr = lv_scr_act();
    lv_obj_set_style_bg_color(scr, lv_color_black(), 0);

    lv_obj_t *label = lv_label_create(scr);
    lv_label_set_text(label, "Hello, Deskstation. M0+M1.");
    lv_obj_set_style_text_color(label, lv_color_white(), 0);
    lv_obj_align(label, LV_ALIGN_CENTER, 0, 0);

    toast_init(scr);
}
```

- [ ] **Step 5: `ui/toast.h`**

Path: `deskstation-firmware/main/ui/toast.h`

```c
#pragma once

#include "lvgl.h"

// Build the toast widget on the given parent (typically lv_scr_act()).
void toast_init(lv_obj_t *parent);

// Show a toast at the top with the given text. `level` is one of "info", "warn", "error".
// Fades out after 3 seconds.
void toast_show(const char *text, const char *level);
```

- [ ] **Step 6: `ui/toast.c`**

Path: `deskstation-firmware/main/ui/toast.c`

```c
#include "toast.h"

#include <string.h>

static lv_obj_t *s_toast;
static lv_obj_t *s_label;
static lv_timer_t *s_hide_timer;

static void hide_timer_cb(lv_timer_t *t)
{
    (void)t;
    lv_obj_add_flag(s_toast, LV_OBJ_FLAG_HIDDEN);
}

void toast_init(lv_obj_t *parent)
{
    s_toast = lv_obj_create(parent);
    lv_obj_set_size(s_toast, 600, 60);
    lv_obj_align(s_toast, LV_ALIGN_TOP_MID, 0, 20);
    lv_obj_add_flag(s_toast, LV_OBJ_FLAG_HIDDEN);

    s_label = lv_label_create(s_toast);
    lv_obj_center(s_label);
}

static lv_color_t color_for_level(const char *level)
{
    if (strcmp(level, "warn") == 0) return lv_palette_main(LV_PALETTE_YELLOW);
    if (strcmp(level, "error") == 0) return lv_palette_main(LV_PALETTE_RED);
    return lv_palette_main(LV_PALETTE_BLUE);
}

void toast_show(const char *text, const char *level)
{
    lv_label_set_text(s_label, text);
    lv_obj_set_style_bg_color(s_toast, color_for_level(level), 0);
    lv_obj_set_style_text_color(s_label, lv_color_white(), 0);
    lv_obj_clear_flag(s_toast, LV_OBJ_FLAG_HIDDEN);

    if (s_hide_timer) lv_timer_del(s_hide_timer);
    s_hide_timer = lv_timer_create(hide_timer_cb, 3000, NULL);
    lv_timer_set_repeat_count(s_hide_timer, 1);
}
```

- [ ] **Step 7: Commit**

```bash
cd /home/pc30/Desktop/desktopstation
git add deskstation-firmware/main/ui_state.h deskstation-firmware/main/ui_state.c deskstation-firmware/main/ui/ui.h deskstation-firmware/main/ui/ui.c deskstation-firmware/main/ui/toast.h deskstation-firmware/main/ui/toast.c
git commit -m "feat(firmware): LVGL init + hello placeholder + toast widget"
```

---

### Task 19: `main.c` — boot sequence, FreeRTOS tasks, heartbeat

**Files:**
- Create: `deskstation-firmware/main/main.c`

- [ ] **Step 1: `main.c`**

Path: `deskstation-firmware/main/main.c`

```c
#include "board.h"
#include "protocol.h"
#include "ui.h"
#include "ui_state.h"
#include "usb_cdc.h"

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "lvgl.h"

#include <string.h>

static const char *TAG = "main";

#define FIRMWARE_VERSION "0.1.0"
#define HEARTBEAT_INTERVAL_MS 5000
#define HEARTBEAT_TIMEOUT_MS  15000

static int64_t s_last_rx_ms = 0;

static int64_t now_ms(void)
{
    return (int64_t)xTaskGetTickCount() * portTICK_PERIOD_MS;
}

static void send_line(const char *line)
{
    usb_line_t out;
    size_t len = strlen(line);
    if (len >= sizeof(out.data)) {
        ESP_LOGE(TAG, "outgoing line too long");
        return;
    }
    memcpy(out.data, line, len);
    out.len = len;
    xQueueSend(usb_cdc_tx_queue(), &out, portMAX_DELAY);
}

static void ui_dispatch_task(void *arg)
{
    (void)arg;
    usb_line_t line;
    while (1) {
        if (xQueueReceive(usb_cdc_rx_queue(), &line, portMAX_DELAY) != pdTRUE) continue;

        parsed_msg_t msg;
        if (!protocol_parse(line.data, &msg)) continue;

        s_last_rx_ms = now_ms();
        if (!ui_state_get()->connected) {
            ESP_LOGI(TAG, "reconnected — sending hello");
            char buf[128];
            int n = protocol_serialize_hello(buf, sizeof(buf), FIRMWARE_VERSION);
            if (n > 0) send_line(buf);
            ui_state_set_connected(true);
        }

        switch (msg.type) {
            case MSG_TOAST:
                toast_show(msg.data.toast.text, msg.data.toast.level);
                break;
            case MSG_ACK:
                ESP_LOGI(TAG, "ack ref=%s", msg.data.ack.ref);
                break;
            case MSG_HEARTBEAT:
                ESP_LOGD(TAG, "heartbeat from host");
                break;
            case MSG_HELLO:
            case MSG_SCREEN_CHANGED:
            case MSG_UNKNOWN:
            default:
                ESP_LOGW(TAG, "ignored type=%d", msg.type);
                break;
        }
    }
}

static void heartbeat_task(void *arg)
{
    (void)arg;
    char buf[64];
    while (1) {
        int n = protocol_serialize_heartbeat(buf, sizeof(buf));
        if (n > 0) send_line(buf);

        int64_t elapsed = now_ms() - s_last_rx_ms;
        if (elapsed > HEARTBEAT_TIMEOUT_MS && ui_state_get()->connected) {
            ESP_LOGW(TAG, "disconnected — no heartbeat for %lld ms", elapsed);
            ui_state_set_connected(false);
            toast_show("Disconnected", "error");
        }

        vTaskDelay(pdMS_TO_TICKS(HEARTBEAT_INTERVAL_MS));
    }
}

void app_main(void)
{
    ESP_LOGI(TAG, "boot, firmware v%s", FIRMWARE_VERSION);

    esp_lcd_panel_handle_t panel = NULL;
    esp_lcd_touch_handle_t touch = NULL;
    ESP_ERROR_CHECK(board_init(&panel, &touch));
    ESP_ERROR_CHECK(ui_init(panel, touch));

    ui_build_hello_screen();

    ESP_ERROR_CHECK(usb_cdc_init());
    ESP_ERROR_CHECK(usb_cdc_start_tasks());

    xTaskCreatePinnedToCore(ui_dispatch_task, "ui_dispatch", 4096, NULL, 3, NULL, 0);
    xTaskCreatePinnedToCore(heartbeat_task, "heartbeat", 4096, NULL, 4, NULL, 0);

    s_last_rx_ms = now_ms();

    // Send initial hello + screen_changed
    char buf[128];
    int n = protocol_serialize_hello(buf, sizeof(buf), FIRMWARE_VERSION);
    if (n > 0) send_line(buf);

    n = protocol_serialize_screen_changed(buf, sizeof(buf), "boot");
    if (n > 0) send_line(buf);

    ESP_LOGI(TAG, "boot complete");
}
```

- [ ] **Step 2: Compile-check (z aktywnym ESP-IDF)**

Run (z aktywnym `. ~/esp/esp-idf/export.sh`):
```bash
cd /home/pc30/Desktop/desktopstation/deskstation-firmware
idf.py set-target esp32s3
idf.py build
```
Expected: build success. Warnings na poziomie info OK; ERRORs naprawiaj iteracyjnie. Najczęstsze issue:
- Brakujący include w `usb_cdc.c` dla `tinyusb.h` / `tusb_cdc_acm.h` — sprawdź czy `esp_tinyusb` jest pobrany przez component manager (`ls managed_components/`).
- `cJSON.h` not found — `REQUIRES json` w `main/CMakeLists.txt` (już jest).
- Niezgodne piny GPIO — niektóre piny na ESP32-S3 nie obsługują wymaganej funkcji; w razie czego dostosuj w `board.c` z datasheetu Waveshare.

- [ ] **Step 3: Commit (po przejściu build)**

```bash
cd /home/pc30/Desktop/desktopstation
git add deskstation-firmware/main/main.c
git commit -m "feat(firmware): app_main with 4 FreeRTOS tasks, boot hello, heartbeat loop"
```

---

### Task 20: `flash.sh` + firmware `README.md`

**Files:**
- Create: `deskstation-firmware/tools/flash.sh`
- Create: `deskstation-firmware/README.md`

- [ ] **Step 1: `flash.sh`**

Path: `deskstation-firmware/tools/flash.sh`

```bash
#!/usr/bin/env bash
# Convenience: build + flash + monitor.
# Usage: bash tools/flash.sh [/dev/ttyACM0]
set -euo pipefail

PORT="${1:-/dev/ttyACM0}"

if ! command -v idf.py >/dev/null 2>&1; then
    echo "ERROR: idf.py not found. Did you source ESP-IDF export.sh?"
    echo "  . ~/esp/esp-idf/export.sh"
    exit 1
fi

idf.py -p "${PORT}" build flash monitor
```

Run: `chmod +x deskstation-firmware/tools/flash.sh`

- [ ] **Step 2: `README.md`**

Path: `deskstation-firmware/README.md`

```markdown
# deskstation-firmware

ESP32-S3 firmware for the Deskstation hardware (Waveshare ESP32-S3-Touch-LCD-7). LVGL UI, USB CDC transport. Behaves as a dumb terminal — all state lives on the host daemon.

## One-time setup

### 1. Install ESP-IDF v5.3

```bash
bash tools/install_esp_idf.sh
```

This clones ESP-IDF v5.3 into `~/esp/esp-idf/` and runs the official installer. Takes ~10–20 min.

Add to your `~/.bashrc` or `~/.zshrc`:

```bash
alias get_idf='. $HOME/esp/esp-idf/export.sh'
```

Then source it in each terminal:

```bash
get_idf
idf.py --version    # should print v5.3.x
```

### 2. Verify the target

```bash
cd deskstation-firmware
idf.py set-target esp32s3
```

### 3. Plug in the board

```bash
ls /dev/ttyACM*       # find your device (typically /dev/ttyACM0)
dmesg | tail -10      # confirms it shows up after plug
```

## Build, flash, run

```bash
get_idf
bash tools/flash.sh /dev/ttyACM0
# or manually:
idf.py -p /dev/ttyACM0 build flash monitor
```

The serial monitor is on a different channel than the USB CDC protocol used by the daemon — the latter is `/dev/ttyACM0`, the former is over JTAG/UART.

## Hardware reference

This firmware targets the Waveshare ESP32-S3-Touch-LCD-7. Pin assignments and timings live in `main/board.c`. See [waveshareteam/Waveshare-ESP32-S3-Touch-LCD-7](https://github.com/waveshareteam/Waveshare-ESP32-S3-Touch-LCD-7) for the datasheet and reference designs.

## Layout

- `main/main.c` — app_main: init board → LVGL → USB CDC → spawn 4 FreeRTOS tasks
- `main/board.{h,c}` — RGB LCD + GT911 touch init using stock ESP-IDF drivers
- `main/usb_cdc.{h,c}` — TinyUSB CDC + RX/TX queues
- `main/protocol.{h,c}` — cJSON envelope parser + outgoing message serializers
- `main/ui/` — LVGL screen + toast widget

## Status

M0 + M1 complete: scaffold + USB transport with heartbeat and reconnect. UI is a placeholder screen ("Hello, Deskstation. M0+M1.") + toast widget. The full UI (top bar, 4 carousel screens) starts in M2.
```

- [ ] **Step 3: Commit**

```bash
cd /home/pc30/Desktop/desktopstation
git add deskstation-firmware/tools/flash.sh deskstation-firmware/README.md
git commit -m "docs(firmware): README with setup, flash, layout"
```

---

## Phase D — Final wiring + DoD

### Task 21: Update top-level `README.md`

**Files:**
- Modify: `/home/pc30/Desktop/desktopstation/README.md`

- [ ] **Step 1: Read current README**

Run: `cat /home/pc30/Desktop/desktopstation/README.md`
The existing file describes the project at high level.

- [ ] **Step 2: Append "Quick start" section**

Use Edit tool. After the existing "Stack" section, append:

```markdown

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
```

- [ ] **Step 3: Commit**

```bash
cd /home/pc30/Desktop/desktopstation
git add README.md
git commit -m "docs: add Quick start section to top-level README"
```

---

### Task 22: Update `CLAUDE.md`

**Files:**
- Modify: `/home/pc30/Desktop/desktopstation/CLAUDE.md`

- [ ] **Step 1: Replace "Repository state" section**

Open `/home/pc30/Desktop/desktopstation/CLAUDE.md`.

Find sekcja zaczynająca:
```
## Repository state

This repo currently contains **only specification and design documents**
```

Replace całą sekcję (do następnego `##`) z:

```markdown
## Repository state

M0 + M1 complete: daemon scaffold (Python asyncio, uv, pytest, structlog) i firmware scaffold (ESP-IDF v5.3 + LVGL 8.x). Transport USB CDC działa z heartbeat / reconnect / 5 typami wiadomości.

**Build / test / run commands:**

| Co | Komenda |
|---|---|
| Daemon tests | `cd deskstation-daemon && uv run pytest -v` |
| Daemon mypy + ruff | `cd deskstation-daemon && uv run mypy src/ && uv run ruff check src/ tests/` |
| Daemon run (live) | `cd deskstation-daemon && uv run deskstation` |
| Daemon run (mock bridge) | `bridge.mode: mock` w `config.yaml`, potem `uv run deskstation` |
| Firmware build | `cd deskstation-firmware && idf.py build` (po `. ~/esp/esp-idf/export.sh`) |
| Firmware flash + monitor | `cd deskstation-firmware && bash tools/flash.sh /dev/ttyACM0` |

**Logs:** `~/.local/share/deskstation/logs/daemon.jsonl` (rotating, 10 MB × 3).

The top-level `docs/` is the single source of truth for plan/spec/designs. Per-milestone specs and plans go to `docs/superpowers/{specs,plans}/`.
```

- [ ] **Step 2: Commit**

```bash
cd /home/pc30/Desktop/desktopstation
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md after M0+M1 — add build/test/run commands"
```

---

### Task 23: Run full daemon test suite + lint gates

**Files:** none (verification only)

- [ ] **Step 1: pytest**

Run: `cd deskstation-daemon && uv run pytest -v`
Expected: wszystkie testy z task 4, 6, 7, 8 PASS. Total ~25+ testów, <2 s.

- [ ] **Step 2: mypy**

Run: `cd deskstation-daemon && uv run mypy src/`
Expected: `Success: no issues found`.

- [ ] **Step 3: ruff**

Run: `cd deskstation-daemon && uv run ruff check src/ tests/`
Expected: brak issues.

- [ ] **Step 4: pre-commit run on all files**

Run: `cd deskstation-daemon && uv run pre-commit run --all-files`
Expected: wszystkie hooki PASS (po ewentualnych auto-fix).

- [ ] **Step 5: Firmware compile**

Run (z aktywnym ESP-IDF):
```bash
cd deskstation-firmware
idf.py build
```
Expected: success, brak ERRORs.

- [ ] **Step 6: Commit jeśli były jakiekolwiek auto-fixy**

```bash
cd /home/pc30/Desktop/desktopstation
git status
# Jeśli coś się zmieniło:
git add -A
git commit -m "chore: pre-commit auto-fixes"
```

---

### Task 24: Hardware test checklist (manualnie po podłączeniu ESP)

**Files:** none — to robi user po podłączeniu płytki.

Te punkty są definicją done po stronie sprzętu. Wykonaj wszystkie, każdy zhaczkowany = M0+M1 done.

- [ ] **Step 1: Flash i pierwszy display**

Run:
```bash
cd deskstation-firmware
. ~/esp/esp-idf/export.sh
bash tools/flash.sh /dev/ttyACM0
```
Expected:
- Build success
- Flash success
- Monitor pokazuje boot log: `I (xxx) main: boot, firmware v0.1.0`, potem `I (xxx) board: RGB panel initialized: 800x480`, `I (xxx) board: GT911 touch initialized`, `I (xxx) ui: LVGL initialized`, `I (xxx) main: boot complete`.
- LCD wyświetla "Hello, Deskstation. M0+M1." (biały tekst na czarnym tle, środek).

Wyłącz monitor: `Ctrl+]`.

- [ ] **Step 2: Daemon startuje**

W drugim terminalu:
```bash
cd deskstation-daemon
cp config.yaml.example config.yaml
uv run deskstation &
sleep 3
tail -20 ~/.local/share/deskstation/logs/daemon.jsonl
```
Expected: log `event=ready`, log `event=serial_connected`.

- [ ] **Step 3: Hello + screen_changed odebrane**

`tail -f ~/.local/share/deskstation/logs/daemon.jsonl` (osobny terminal). Spodziewane wpisy w pierwszej minucie:
- `event=hello_received` z `firmware_version=0.1.0`
- `event=screen_changed_received` z `screen=boot`

- [ ] **Step 4: Heartbeat działa**

Po 30 sekundach od startu w logach daemon spodziewamy `event=heartbeat_received` lub `event=ready` ale w logach DEBUG. Sprawdź też output monitora ESP: brak warnings o disconnect.

- [ ] **Step 5: Toast z hosta**

W osobnym terminalu pokaz dev REPL:
```bash
cd deskstation-daemon
uv run python -c "
import asyncio
from deskstation.bridge.serial_bridge import SerialBridge, default_serial_factory
from deskstation.bridge.protocol import ToastMsg, ToastData

async def main():
    f = default_serial_factory('/dev/ttyACM0', 921600)
    bridge = SerialBridge(f)
    await bridge.send(ToastMsg(data=ToastData(text='hello from host', level='info')))
    await asyncio.sleep(1)
    await bridge.close()

asyncio.run(main())
"
```
**Note:** to wymaga zatrzymania głównego daemon (jeden proces ma `/dev/ttyACM0` na raz). Najpierw `kill %1` (lub `pkill -f deskstation`), potem powyższy snippet.

Expected: na ESP pojawia się niebieski toast "hello from host" u góry, znika po 3 sekundach.

- [ ] **Step 6: Disconnect detection**

Restart daemon: `uv run deskstation &`
Następnie wyciągnij kabel USB.
Expected w ciągu 15 sekund:
- W logu daemon: `event=disconnected`, potem `event=serial_eof` / `event=serial_connect_failed`
- Na ESP: pojawia się czerwony toast "Disconnected"

- [ ] **Step 7: Reconnect**

Podłącz kabel z powrotem.
Expected w ciągu 5–10 sekund:
- W logu daemon: `event=serial_connected`, potem `event=hello_received` (ESP wysyła hello automatycznie po reconnect — logika w `ui_dispatch_task` w `main.c`: pierwsza przychodząca wiadomość po `connected=false` triggeruje wysłanie `hello`).
- Na ESP: toast "Disconnected" zniknął (po 3 s fade-out), normalna praca.

- [ ] **Step 8: 30-minutowy soak test**

Zostaw oba uruchomione. Po 30 minutach sprawdź:
- `wc -l ~/.local/share/deskstation/logs/daemon.jsonl` — rośnie liniowo (heartbeat co 5s).
- `idf.py monitor` strona ESP — brak rosnącego heap usage między bootem a teraz (sprawdź `esp_get_free_heap_size()` jeśli chcesz ręcznie; alternatywnie po prostu brak crashy).
- Brak ERROR'ów w żadnym logu.

Jeśli wszystkie 8 zhaczkowane → **M0+M1 DONE**.

---

## Self-Review checklist

Przed zakończeniem planu wykonane:

**Spec coverage** — każdy punkt sekcji ze specu (1: repo layout → Task 1+2; 2: daemon scaffold → Task 3–12; 3: firmware scaffold → Task 13–20; 4: protocol M1 → Task 4 + Task 17; 5: testing → Task 4, 6, 7, 8 + Task 24; 6: DoD → Task 23 + Task 24; 7: file inventory → wszystkie task; 8: poza scope → expicit w each task by what is NOT done) — pokryte.

**Placeholders** — żaden krok nie zawiera "TBD" / "TODO" / "fill in details". Każdy krok ma realny kod lub komendę.

**Type consistency** — pydantic models: `HelloMsg`, `HeartbeatMsg`, `ToastMsg`, `AckMsg`, `ScreenChangedMsg` (single naming convention) używane konsekwentnie w Task 4, Task 6, Task 7, Task 8, Task 11. Bridge protocol method names: `send`, `stream`, `close` używane konsekwentnie (Task 5, 6, 7, 11). Firmware: `msg_type_t` enum konsekwentnie używany w Task 17, 19.

**Deviation called out** — Waveshare BSP submodule odrzucone na rzecz stock ESP-IDF drivers (header planu, Task 14, Task 15).

---

## Execution

Plan complete and saved to `docs/superpowers/plans/2026-05-18-m0-m1-bootstrap-and-transport.md`.

Two execution options:

**1. Subagent-Driven (recommended)** — Dispatch fresh subagent per task, two-stage review between tasks. Fast iteration, isolated context per task.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch with review checkpoints.
