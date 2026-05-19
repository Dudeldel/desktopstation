"""Entry point for `python -m deskstation` and the `deskstation` console script.

Dispatches subcommands:
  - ``deskstation`` (no args) → run the asyncio daemon.
  - ``deskstation auth-google`` → run the one-shot Google OAuth2 setup flow.

The auth-google branch lazy-imports the Google libraries so the daemon's cold
start stays fast when no one is running the helper.
"""

from __future__ import annotations

import sys

from deskstation.main import main as run_daemon


def main() -> None:
    if len(sys.argv) >= 2 and sys.argv[1] == "auth-google":
        from deskstation.auth_google import run_oauth_flow

        run_oauth_flow()
        return
    run_daemon()


if __name__ == "__main__":
    main()
