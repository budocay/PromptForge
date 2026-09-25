"""
Structured logging configuration for PromptForge.
Provides consistent, configurable logging across all modules.
"""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


class StructuredFormatter(logging.Formatter):
    """
    Custom formatter that outputs structured JSON logs.
    Useful for log aggregation and analysis.
    """

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add extra fields if present
        for key, value in record.__dict__.items():
            if key not in (
                "name",
                "msg",
                "args",
                "created",
                "filename",
                "funcName",
                "levelname",
                "levelno",
                "lineno",
                "module",
                "msecs",
                "pathname",
                "process",
                "processName",
                "relativeCreated",
                "stack_info",
                "exc_info",
                "exc_text",
                "thread",
                "threadName",
                "message",
                "asctime",
            ):
                log_data[key] = value

        return json.dumps(log_data, default=str)


class ColoredConsoleFormatter(logging.Formatter):
    """
    Console formatter with colors for better readability.
    """

    COLORS = {
        "DEBUG": "\033[36m",  # Cyan
        "INFO": "\033[32m",  # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",  # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, self.RESET)
        timestamp = datetime.now().strftime("%H:%M:%S")

        # Format: [TIME] LEVEL module:line - message
        formatted = f"{color}[{timestamp}] {record.levelname:8}{self.RESET} {record.name}:{record.lineno} - {record.getMessage()}"

        if record.exc_info:
            formatted += f"\n{self.formatException(record.exc_info)}"

        return formatted


class PromptForgeLogger:
    """
    Centralized logging configuration for PromptForge.
    Supports console and file logging with structured output.
    """

    _instance: Optional["PromptForgeLogger"] = None
    _initialized: bool = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self.root_logger = logging.getLogger("promptforge")
        self.root_logger.setLevel(logging.DEBUG)

        # Prevent propagation to root logger
        self.root_logger.propagate = False

        # Remove any existing handlers
        self.root_logger.handlers.clear()

        # Add default console handler
        self._add_console_handler()

    def _add_console_handler(self, level: int = logging.INFO):
        """Add colored console handler."""
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(level)
        console_handler.setFormatter(ColoredConsoleFormatter())
        self.root_logger.addHandler(console_handler)

    def add_file_handler(self, log_path: Path, level: int = logging.DEBUG, structured: bool = True):
        """
        Add file handler for persistent logging.

        Args:
            log_path: Path to log file
            level: Minimum log level for this handler
            structured: Use JSON structured format if True
        """
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setLevel(level)

        if structured:
            file_handler.setFormatter(StructuredFormatter())
        else:
            file_handler.setFormatter(
                logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
            )

        self.root_logger.addHandler(file_handler)

    def set_level(self, level: int):
        """Set the root logger level."""
        self.root_logger.setLevel(level)

    def set_console_level(self, level: int):
        """Set console handler level."""
        for handler in self.root_logger.handlers:
            if isinstance(handler, logging.StreamHandler) and handler.stream == sys.stderr:
                handler.setLevel(level)

    def get_logger(self, name: str) -> logging.Logger:
        """
        Get a logger for a specific module.

        Args:
            name: Module name (typically __name__)

        Returns:
            Configured logger instance
        """
        if name.startswith("promptforge."):
            return logging.getLogger(name)
        return logging.getLogger(f"promptforge.{name}")


# Global singleton instance
_logger_instance: PromptForgeLogger | None = None


def init_logging(
    level: int = logging.INFO, log_file: Path | None = None, structured_file: bool = True
) -> PromptForgeLogger:
    """
    Initialize the PromptForge logging system.

    Args:
        level: Console log level
        log_file: Optional path to log file
        structured_file: Use JSON format for file logs

    Returns:
        PromptForgeLogger instance
    """
    global _logger_instance
    _logger_instance = PromptForgeLogger()
    _logger_instance.set_console_level(level)

    if log_file:
        _logger_instance.add_file_handler(log_file, structured=structured_file)

    return _logger_instance


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger for a module.

    Args:
        name: Module name (typically __name__)

    Returns:
        Configured logger instance
    """
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = PromptForgeLogger()
    return _logger_instance.get_logger(name)


# Convenience function for quick debug logging
def log_debug(message: str, **kwargs):
    """Quick debug log."""
    logger = get_logger("debug")
    logger.debug(message, extra=kwargs)


def log_info(message: str, **kwargs):
    """Quick info log."""
    logger = get_logger("info")
    logger.info(message, extra=kwargs)


def log_warning(message: str, **kwargs):
    """Quick warning log."""
    logger = get_logger("warning")
    logger.warning(message, extra=kwargs)


def log_error(message: str, **kwargs):
    """Quick error log."""
    logger = get_logger("error")
    logger.error(message, extra=kwargs)
