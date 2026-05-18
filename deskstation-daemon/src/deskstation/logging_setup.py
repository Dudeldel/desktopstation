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
        file_handler.setFormatter(logging.Formatter(fmt="%(message)s"))
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
