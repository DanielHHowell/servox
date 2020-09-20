"""The `servo.utilities.subprocess` module provides support for asynchronous
execution of subprocesses with support for timeouts, streaming output, error
management, and logging.
"""
import asyncio
import time

from asyncio.streams import StreamReader
from datetime import timedelta
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, IO, List, NamedTuple, Optional, TypeVar, Union, cast
from loguru import logger

__all__ = (
    "OutputStreamCallback",
    "SubprocessResult",
    "Timeout",
    "stream_subprocess_exec",
    "run_subprocess_exec",
    "stream_subprocess_shell",
    "run_subprocess_shell",
    "stream_subprocess_output"
)


_DEFAULT_LIMIT = 2 ** 16  # 64 KiB


# Type definition for streaming output callbacks.
# Must accept a single string positional argument and returns nothing. Optionally asynchronous.
OutputStreamCallback = TypeVar("OutputStreamCallback", bound=Callable[[str], Union[None, Awaitable[None]]])

# Timeouts can be expressed as nummeric values in seconds or timedelta/Duration values
Timeout = Union[int, float, timedelta, None]


class SubprocessResult(NamedTuple):
    """
    An object that encapsulates the results of a subprocess execution.

    The `stdout` and `stderr` attributes will have a value of `None` when the corresponding 
    attribute of the parent subprocess is not a pipe.
    """
    return_code: int
    stdout: Optional[List[str]]
    stderr: Optional[List[str]]


async def stream_subprocess_exec(
    program: str,
    *args,
    cwd: Path = Path.cwd(), 
    env: Optional[Dict[str, str]] = None,
    timeout: Timeout = None,
    stdout_callback: Optional[OutputStreamCallback] = None,
    stderr_callback: Optional[OutputStreamCallback] = None,
    stdin: Union[int, IO[Any], None] = None,
    stdout: Union[int, IO[Any], None] = asyncio.subprocess.PIPE,
    stderr: Union[int, IO[Any], None] = asyncio.subprocess.PIPE,
    limit: int = _DEFAULT_LIMIT,
    **kwargs,
) -> int:
    """
    Run a program asynchronously in a subprocess and stream its output.

    :param program: The program to run.
    :param *args: A list of string arguments to supply to the executed program.
    :param cwd: The working directory to execute the subprocess in.
    :param env: An optional dictionary of environment variables to apply to the subprocess.
    :param timeout: An optional timeout in seconds for how long to read the streams before giving up.
    :param stdout_callback: An optional callable invoked with each line read from stdout. Must accept a single string positional argument and returns nothing.
    :param stderr_callback: An optional callable invoked with each line read from stderr. Must accept a single string positional argument and returns nothing.
    :param stdin: A file descriptor, IO stream, or None value to use as the standard input of the subprocess. Default is `None`.
    :param stdout: A file descriptor, IO stream, or None value to use as the standard output of the subprocess.
    :param stderr: A file descriptor, IO stream, or None value to use as the standard error of the subprocess.
    :param limit: The amount of memory to allocate for buffering subprocess data.

    :raises asyncio.TimeoutError: Raised if the timeout expires before the subprocess exits.
    :return: The exit status of the subprocess.
    """
    process = await asyncio.create_subprocess_exec(
        program,
        *args,
        cwd=cwd,
        env=env,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
        limit=limit,
        **kwargs,
    )
    return await stream_subprocess_output(
        process,
        timeout=timeout,
        stdout_callback=stdout_callback,
        stderr_callback=stderr_callback,
    )

async def run_subprocess_exec(
    program: str,
    *args,
    cwd: Path = Path.cwd(), 
    env: Optional[Dict[str, str]] = None,
    timeout: Timeout = None,
    stdin: Union[int, IO[Any], None] = None,
    stdout: Union[int, IO[Any], None] = asyncio.subprocess.PIPE,
    stderr: Union[int, IO[Any], None] = asyncio.subprocess.PIPE,
    limit: int = _DEFAULT_LIMIT,
    **kwargs,
) -> SubprocessResult:
    """
    Run a program asynchronously in a subprocess and return the results.

    The standard input and output are configurable but generally do not need to be changed.
    Input via `stdin` is only necessary if dynamic content needs to be supplied via `stdin`.
    Output via `stdout` and `stderr` only need to be changed for unusual configurations like redirecting
    standard error onto the standard output stream.

    :param program: The program to run.
    :param *args: A list of string arguments to supply to the executed program.
    :param cwd: The working directory to execute the subprocess in.
    :param env: An optional dictionary of environment variables to apply to the subprocess.
    :param timeout: An optional timeout in seconds for how long to read the streams before giving up.
    :param stdin: A file descriptor, IO stream, or None value to use as the standard input of the subprocess. Default is `None`.
    :param stdout: A file descriptor, IO stream, or None value to use as the standard output of the subprocess.
    :param stderr: A file descriptor, IO stream, or None value to use as the standard error of the subprocess.
    :param limit: The amount of memory to allocate for buffering subprocess data.

    :raises asyncio.TimeoutError: Raised if the timeout expires before the subprocess exits.
    :return: A named tuple value of the exit status and two string lists of standard output and standard error.
    """
    stdout_list: List[str] = []
    stderr_list: List[str] = []
    return SubprocessResult(
        await stream_subprocess_exec(
            program,
            *args,
            cwd=cwd,
            env=env,
            timeout=timeout,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            limit=limit,
            stdout_callback=lambda m: stdout_list.append(m),
            stderr_callback=lambda m: stderr_list.append(m),
            **kwargs,
        ), 
        stdout_list, 
        stderr_list
    )

async def run_subprocess_shell(
    cmd: str,
    *,
    cwd: Path = Path.cwd(), 
    env: Optional[Dict[str, str]] = None,
    timeout: Timeout = None,
    stdin: Union[int, IO[Any], None] = None,
    stdout: Union[int, IO[Any], None] = asyncio.subprocess.PIPE,
    stderr: Union[int, IO[Any], None] = asyncio.subprocess.PIPE,
    limit: int = _DEFAULT_LIMIT,
    **kwargs,
) -> SubprocessResult:
    """
    Run a shell command asynchronously in a subprocess and return the results.

    The standard input and output are configurable but generally do not need to be changed.
    Input via `stdin` is only necessary if dynamic content needs to be supplied via `stdin`.
    Output via `stdout` and `stderr` only need to be changed for unusual configurations like redirecting
    standard error onto the standard output stream.

    :param cmd: The command to run.
    :param cwd: The working directory to execute the subprocess in.
    :param env: An optional dictionary of environment variables to apply to the subprocess.
    :param timeout: An optional timeout in seconds for how long to read the streams before giving up.
    :param stdin: A file descriptor, IO stream, or None value to use as the standard input of the subprocess. Default is `None`.
    :param stdout: A file descriptor, IO stream, or None value to use as the standard output of the subprocess.
    :param stderr: A file descriptor, IO stream, or None value to use as the standard error of the subprocess.
    :param limit: The amount of memory to allocate for buffering subprocess data.

    :raises asyncio.TimeoutError: Raised if the timeout expires before the subprocess exits.
    :return: A named tuple value of the exit status and two string lists of standard output and standard error.
    """
    stdout_list: List[str] = []
    stderr_list: List[str] = []
    return SubprocessResult(
        await stream_subprocess_shell(
            cmd,
            cwd=cwd,
            env=env,
            timeout=timeout,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            limit=limit,
            stdout_callback=lambda m: stdout_list.append(m),
            stderr_callback=lambda m: stderr_list.append(m),
            **kwargs,
        ), 
        stdout_list, 
        stderr_list
    )


async def stream_subprocess_shell(
    cmd: str,
    *,
    cwd: Path = Path.cwd(), 
    env: Optional[Dict[str, str]] = None,
    timeout: Timeout = None,
    stdout_callback: Optional[OutputStreamCallback] = None,
    stderr_callback: Optional[OutputStreamCallback] = None,
    stdin: Union[int, IO[Any], None] = None,
    stdout: Union[int, IO[Any], None] = asyncio.subprocess.PIPE,
    stderr: Union[int, IO[Any], None] = asyncio.subprocess.PIPE,
    limit: int = _DEFAULT_LIMIT,
    **kwargs,
) -> int:
    """
    Run a shell command asynchronously in a subprocess and stream its output.

    :param cmd: The command to run.
    :param cwd: The working directory to execute the subprocess in.
    :param env: An optional dictionary of environment variables to apply to the subprocess.
    :param timeout: An optional timeout in seconds for how long to read the streams before giving up.
    :param stdout_callback: An optional callable invoked with each line read from stdout. Must accept a single string positional argument and returns nothing.
    :param stderr_callback: An optional callable invoked with each line read from stderr. Must accept a single string positional argument and returns nothing.
    :param stdin: A file descriptor, IO stream, or None value to use as the standard input of the subprocess. Default is `None`.
    :param stdout: A file descriptor, IO stream, or None value to use as the standard output of the subprocess.
    :param stderr: A file descriptor, IO stream, or None value to use as the standard error of the subprocess.
    :param limit: The amount of memory to allocate for buffering subprocess data.

    :raises asyncio.TimeoutError: Raised if the timeout expires before the subprocess exits.
    :return: The exit status of the subprocess.
    """                    
    process = await asyncio.create_subprocess_shell(
        cmd,
        cwd=cwd,
        env=env,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
        limit=limit,
        **kwargs,
    )    
    from servo.types import Duration
    try:
        start = time.time()
        timeout_note = f" ({Duration(timeout)} timeout)" if timeout else ""
        logger.info(f"Running subprocess command `{cmd}`{timeout_note}")
        result = await stream_subprocess_output(
            process,
            timeout=timeout,
            stdout_callback=stdout_callback,
            stderr_callback=stderr_callback,
        )
        end = time.time()
        duration = Duration(end - start)
        logger.info(f"Subprocess finished with return code {result} in {duration} (`{cmd}`)")
        return result
    except asyncio.TimeoutError as error:
        logger.warning(f"timeout expired waiting for subprocess to complete: {error}")
        raise error
    

async def stream_subprocess_output(
    process: asyncio.subprocess.Process,
    *,
    timeout: Timeout = None,
    stdout_callback: Optional[OutputStreamCallback] = None,
    stderr_callback: Optional[OutputStreamCallback] = None,
) -> int:
    """
    Asynchronously read the stdout and stderr output streams of a subprocess and 
    and optionally invoke a callback with each line of text read.

    :param process: An asyncio subprocess created with `create_subprocess_exec` or `create_subprocess_shell`.
    :param timeout: An optional timeout in seconds for how long to read the streams before giving up.
    :param stdout_callback: An optional callable invoked with each line read from stdout. Must accept a single string positional argument and returns nothing.
    :param stderr_callback: An optional callable invoked with each line read from stderr. Must accept a single string positional argument and returns nothing.

    :raises asyncio.TimeoutError: Raised if the timeout expires before the subprocess exits.
    :return: The exit status of the subprocess.
    """
    tasks = []
    if process.stdout:
        tasks.append(asyncio.create_task(_read_lines_from_output_stream(process.stdout, stdout_callback)))
    if process.stderr:
        tasks.append(asyncio.create_task(_read_lines_from_output_stream(process.stderr, stderr_callback)))

    if timeout is None:
        await asyncio.wait([process.wait(), *tasks])
    else:
        timeout_in_seconds = timeout.total_seconds() if isinstance(timeout, timedelta) else timeout
        try:
            await asyncio.wait_for(process.wait(), timeout=timeout_in_seconds)
            await asyncio.wait(tasks)
        except asyncio.TimeoutError as timeout:
            process.kill()
            [task.cancel() for task in tasks]
            raise timeout

    return cast(int, process.returncode)


async def _read_lines_from_output_stream(
    stream: StreamReader, 
    callback: Optional[OutputStreamCallback],
    *,
    encoding: str = 'utf-8'
) -> None:
    """
    Asynchronouysly read a subprocess output stream line by line,
    optionally invoking a callback with each line as it is read.

    :param stream: An IO stream reader linked to the stdout or stderr of a subprocess.
    :param callback: An optionally async callable that accepts a single string positional argument and returns nothing.
    :param encoding: The encoding to use when decoding from bytes to string (default is utf-8).
    """
    while True:
        line = await stream.readline()
        if line:
            line = line.decode(encoding).rstrip()
            if callback:
                if asyncio.iscoroutinefunction(callback):
                    await callback(line)
                else:
                    callback(line)
        else:
            break
        