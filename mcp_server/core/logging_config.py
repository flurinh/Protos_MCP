"""Structured logging configuration for Protos MCP server.

Provides consistent, production-ready logging with optional JSON output
for integration with log aggregation systems.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from typing import Any, Dict, Optional

# Module-level logger instance
_logger: Optional[logging.Logger] = None


class JSONFormatter(logging.Formatter):
    """JSON formatter for structured log output."""

    def format(self, record: logging.LogRecord) -> str:
        import json

        log_entry: Dict[str, Any] = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Include extra fields if present
        if hasattr(record, "extra") and record.extra:
            log_entry["context"] = record.extra

        # Include exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, default=str)


class ContextAdapter(logging.LoggerAdapter):
    """Logger adapter that supports extra context in log calls."""

    def process(self, msg: str, kwargs: Dict[str, Any]) -> tuple:
        # Merge extra context
        extra = kwargs.get("extra", {})
        if self.extra:
            extra = {**self.extra, **extra}
        kwargs["extra"] = extra

        # Store extra on the record for JSONFormatter
        return msg, kwargs


def setup_logging(
    level: Optional[str] = None,
    json_format: Optional[bool] = None,
    name: str = "protos_mcp",
) -> logging.Logger:
    """Configure structured logging for MCP server.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR). Defaults to INFO.
               Can be overridden via PROTOS_LOG_LEVEL env var.
        json_format: If True, output JSON-formatted logs. Defaults to False.
                     Can be overridden via PROTOS_LOG_JSON env var.
        name: Logger name. Defaults to 'protos_mcp'.

    Returns:
        Configured logger instance.
    """
    global _logger

    # Check environment overrides
    if level is None:
        level = os.environ.get("PROTOS_LOG_LEVEL", "INFO")
    if json_format is None:
        json_format = os.environ.get("PROTOS_LOG_JSON", "false").lower() == "true"

    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove existing handlers to avoid duplicates
    logger.handlers.clear()

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(logger.level)

    if json_format:
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )

    logger.addHandler(handler)

    # Prevent propagation to root logger
    logger.propagate = False

    _logger = logger
    return logger


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Get the configured logger instance.

    Args:
        name: Optional child logger name. If provided, returns a child logger.

    Returns:
        Logger instance.
    """
    global _logger

    if _logger is None:
        _logger = setup_logging()

    if name:
        return _logger.getChild(name)

    return _logger


def log_tool_call(
    tool_name: str,
    params: Optional[Dict[str, Any]] = None,
    result_status: Optional[str] = None,
    execution_time_ms: Optional[int] = None,
    error: Optional[str] = None,
) -> None:
    """Log a tool call with structured context.

    Args:
        tool_name: Name of the tool being called.
        params: Tool parameters (sensitive values should be redacted).
        result_status: 'success' or 'error'.
        execution_time_ms: Execution time in milliseconds.
        error: Error message if failed.
    """
    logger = get_logger("tools")

    context = {
        "tool": tool_name,
        "execution_time_ms": execution_time_ms,
    }

    if params:
        # Redact potentially sensitive parameters
        safe_params = {
            k: v if k not in ("password", "token", "secret", "key") else "[REDACTED]"
            for k, v in params.items()
        }
        context["params"] = safe_params

    if error:
        context["error"] = error
        logger.error(f"Tool {tool_name} failed", extra={"extra": context})
    else:
        context["status"] = result_status or "success"
        logger.info(f"Tool {tool_name} completed", extra={"extra": context})


def log_server_event(
    event: str,
    **context: Any,
) -> None:
    """Log a server lifecycle event.

    Args:
        event: Event name (startup, shutdown, error, etc.).
        **context: Additional context to include.
    """
    logger = get_logger("server")
    logger.info(f"Server event: {event}", extra={"extra": {"event": event, **context}})
