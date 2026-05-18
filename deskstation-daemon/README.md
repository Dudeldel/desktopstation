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

M0 + M1 complete: scaffold + USB transport with heartbeat and reconnect. See `docs/superpowers/plans/2026-05-18-m0-m1-bootstrap-and-transport.md` and roadmap M2+ for what comes next.
