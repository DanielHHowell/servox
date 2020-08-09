from __future__ import annotations
import asyncio
import functools
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Any, Callable, Dict, Optional, Set, Union, cast
from weakref import WeakSet

import loguru
from loguru import logger
from servo.events import EventContext, _event_context_var
from servo.types import Duration

__all__ = (
    "Mixin",
    "Filter",
    "ProgressHandler",
    "Logger",
    "logger",
    "log_execution",
    "log_execution_time",
    "reset_to_defaults",
    "set_level"
)


class Mixin:
    @property
    def logger(self) -> loguru.Logger:
        """Returns a contextualized logger"""
        return loguru.logger.bind(connector=self)


class Filter:
    """
    NOTE: The level on the sink needs to be set to 0.
    """

    def __init__(self, level = "INFO") -> None:
        self.level = level

    def __call__(self, record) -> bool:        
        levelno = logger.level(self.level).no
        return record["level"].no >= levelno


class ProgressHandler:
    """
    The ProgressHandler class provides transparent integration between logging events and
    API based reporting to Opsani. Log messages annotated with a "progress" attribute are
    automatically picked up by the handler and reported back to the API via a callback.

    NOTE: We call the logger re-entrantly for misconfigured progress logging attempts. The
        `progress` should must be excluded on logger calls to avoid recursion.
    """
    def __init__(self, 
        progress_reporter: Callable[[Dict[Any, Any]], Union[None, Awaitable[None]]], 
        error_reporter: Callable[[str], Union[None, Awaitable[None]]],
    ) -> None:
        self._progress_reporter = progress_reporter
        self._error_reporter = error_reporter
        self._tasks = WeakSet()
    
    @property
    def tasks(self) -> Set[asyncio.Task]:
        return cast(Set[asyncio.Task], self._tasks.copy())
    
    async def sink(self, message: loguru.Message) -> None:
        """
        An asynchronous loguru sink handling the progress reporting.
        Implemented as a sink versus a `logging.Handler` because the Python stdlib logging package isn't async.
        """
        record = message.record
        extra = record["extra"]
        progress = extra.get("progress", None)
        if not progress:
            return

        connector = extra.get("connector", None)
        if not connector:
            return await self._report_error("declining request to report progress for record without a connector attribute", record)

        event_context: Optional[EventContext] = _event_context_var.get()
        operation = extra.get("operation", None)
        if not operation:
            if not event_context:
                return await self._report_error("declining request to report progress for record without an operation parameter or inferrable value from event context", record)
            operation = event_context.operation()

        started_at = extra.get("started_at", None)
        if not started_at:
            if event_context:
                started_at = event_context.created_at
            else:
                return await self._report_error("declining request to report progress for record without a started_at parameter or inferrable value from event context", record)

        return await self._report_progress(
            operation=operation,
            progress=progress,
            connector=connector.name,
            event_context=event_context,
            started_at=started_at,
            message=message
        )
    
    async def _report_progress(self, **kwargs) -> None:
        """
        Report progress about a log message that was processed.
        """
        if self._progress_reporter:
            if asyncio.iscoroutinefunction(self._progress_reporter):
                self._tasks.add(asyncio.create_task(self._progress_reporter(**kwargs)))
            else:
                self._progress_reporter(**kwargs)

    async def _report_error(self, message: str, record) -> None:
        """
        Report an error message about rocessing a log message annotated with a `progress` attribute.
        """
        message = f"!!! WARNING: {record['name']}:{record['file'].name}:{record['line']} | servo.logging.ProgressHandler - {message}"
        if self._error_reporter:
            if asyncio.iscoroutinefunction(self._error_reporter):
                self._tasks.add(asyncio.create_task(self._error_reporter(message)))
            else:
                self._error_reporter(message)


DEFAULT_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | <magenta>{extra[component]}</magenta> - <level>{message}</level>"
    "{extra[traceback]}"
)


def _format(record: dict) -> str:
    """
    Formats a log message with contextual information from the servo assembly.
    """
    extra = record["extra"]

    # Add optional traceback
    if extra.get("with_traceback", False):
        extra["traceback"] = "\n" + "".join(traceback.format_stack())
    else:
        extra["traceback"] = ""

    # Respect an explicit component 
    if not "component" in record["extra"]:        
        if connector := extra.get("connector", None):
            component = connector.name
        else:
            component = "servo"
        
        # Append event context if available
        if event_context := _event_context_var.get():
            component += f"[{event_context}]"
        
        extra["component"] = component

    return DEFAULT_FORMAT + "\n"


DEFAULT_FILTER = Filter("INFO")
DEFAULT_FORMATTER = _format


DEFAULT_STDERR_HANDLER = {
    "sink": sys.stderr,
    "colorize": True,
    "filter": DEFAULT_FILTER,
    "level": 0,
    "format": DEFAULT_FORMATTER,
    "backtrace": True,
    "diagnose": True,
}


# Persistent disk logging to logs/
root_path = Path(__file__).parents[1]
logs_path = root_path / "logs" / f"servo.log"


DEFAULT_FILE_HANDLER = {
    "sink": logs_path,
    "colorize": False,
    "filter": DEFAULT_FILTER,
    "level": 0,
    "format": DEFAULT_FORMATTER,
    "backtrace": True,
    "diagnose": False,
}

DEFAULT_HANDLERS = [
    DEFAULT_STDERR_HANDLER,
    DEFAULT_FILE_HANDLER,
]

def set_level(level: str) -> None:
    """
    Sets the logging threshold to the given level for all log handlers.
    """
    DEFAULT_FILTER.level = level

def reset_to_defaults() -> loguru.Logger:
    """
    Resets the logging subsystem to the default configuration and returns the logger instance.
    """
    logger = loguru.logger
    logger.remove()
    logger.configure(handlers=DEFAULT_HANDLERS)
    DEFAULT_FILTER.level = "INFO"
    return logger

def friendly_decorator(f):
    """
    A "decorator decorator" that wraps a decorator function such that it can be invoked
    with or without parentheses such as:
   
        @decorator(with, arguments, and=kwargs)
        or
        @decorator
    """
    @functools.wraps(f)
    def decorator(*args, **kwargs):
        if len(args) == 1 and len(kwargs) == 0 and callable(args[0]):
            # actual decorated function
            return f(args[0])
        else:
            # decorator arguments
            return lambda realf: f(realf, *args, **kwargs)

    return decorator

@friendly_decorator
def log_execution(func, *, entry=True, exit=True, level="DEBUG"):
    """
    Log the execution of the decorated function.
    """
    @functools.wraps(func)
    def wrapped(*args, **kwargs):
        name = func.__name__
        logger_ = logger.opt(depth=1)
        if entry:
            logger_.log(level, f"Entering '{name}' (args={args}, kwargs={kwargs})")
        result = func(*args, **kwargs)
        if exit:
            logger_.log(level, f"Exiting '{name}' (result={result})")
        return result

    return wrapped

@friendly_decorator
def log_execution_time(func, *, level="DEBUG"):
    """
    Log the execution time upon exit from the decorated function.
    """
    @functools.wraps(func)
    def wrapped(*args, **kwargs):
        name = func.__name__
        logger_ = logger.opt(depth=1)

        start = time.time()
        result = func(*args, **kwargs)
        end = time.time()

        duration = Duration(end - start)
        logger_.log(level, f"Function '{name}' executed in {duration}")
        return result

    return wrapped

# Alias the loguru logger to hide implementation details
logger = reset_to_defaults()
