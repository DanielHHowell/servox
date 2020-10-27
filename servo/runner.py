from __future__ import annotations

import asyncio
import signal
from typing import Any, Dict, List, Optional

import backoff
import devtools
import httpx
import pydantic
import typer

import servo
import servo.api
import servo.utilities.key_paths
import servo.utilities.strings
from servo.types import Adjustment, Control, Description, Duration, Measurement

DEFAULT_CONTEXT = "__default__"

__all__ = [
    "AssemblyRunner",
    "ServoRunner"
]

class BackoffConfig:
    """BackoffConfig provides callables for runtime configuration of backoff decorators.

    This implementation relies upon the framework managed context variables to determine
    which servo is running and retrieve the configuration.
    """

    @staticmethod
    def max_time(context: str = DEFAULT_CONTEXT) -> Optional[int]:
        if servo.Servo.current():
            if servo_config := servo.Servo.current().config.servo:
                if backoff_config := servo_config.backoff.get(context, None):
                    if max_time := backoff_config.max_time:
                        return max_time.total_seconds()

        if max_time := BackoffConfig.max_time(DEFAULT_CONTEXT):
            return max_time

        raise AssertionError("max_time default should never be None")

    @staticmethod
    def max_tries(context: str = DEFAULT_CONTEXT) -> Optional[int]:
        if servo.Servo.current():
            if servo_config := servo.Servo.current().config.servo:
                if backoff_config := servo_config.backoff.get(context, None):
                    return backoff_config.max_tries

        return BackoffConfig.max_tries(DEFAULT_CONTEXT)

class ServoRunner(servo.logging.Mixin, servo.api.Mixin):
    servo: servo.Servo
    connected: bool = False
    
    def __init__(self, servo_: servo) -> None: # noqa: D107
        self.servo = servo_

        # initialize default servo options if not configured
        if self.config.servo is None:
            self.config.servo = servo.ServoConfiguration()

        super().__init__()
    
    @property
    def optimizer(self) -> servo.Optimizer:
        return self.servo.optimizer
    
    @property
    def config(self) -> servo.BaseServoConfiguration:
        return self.servo.config
    
    @property
    def api_client_options(self) -> Dict[str, Any]:
        # FIXME: Support for proxies. This is messy. Needs to be cleaned up.
        # We have unnatural layering because proxies is on config but api is standalone.
        return self.servo.api_client_options

    async def describe(self) -> Description:
        self.logger.info("Describing...")

        aggregate_description = Description.construct()
        results: List[servo.EventResult] = await self.servo.dispatch_event(servo.Events.DESCRIBE)
        for result in results:
            description = result.value
            aggregate_description.components.extend(description.components)
            aggregate_description.metrics.extend(description.metrics)

        return aggregate_description

    async def measure(self, param: servo.MeasureParams) -> Measurement:
        servo.logger.info(f"Measuring... [metrics={', '.join(param.metrics)}]")
        servo.logger.trace(devtools.pformat(param))

        aggregate_measurement = Measurement.construct()
        results: List[servo.EventResult] = await self.servo.dispatch_event(
            servo.Events.MEASURE, metrics=param.metrics, control=param.control
        )
        for result in results:
            measurement = result.value
            aggregate_measurement.readings.extend(measurement.readings)
            aggregate_measurement.annotations.update(measurement.annotations)

        return aggregate_measurement

    async def adjust(
        self, adjustments: List[Adjustment], control: Control
    ) -> Description:
        summary = f"[{', '.join(list(map(str, adjustments)))}]"
        self.logger.info(f"Adjusting... {summary}")
        self.logger.trace(devtools.pformat(adjustments))

        aggregate_description = Description.construct()
        results = await self.servo.dispatch_event(servo.Events.ADJUST, adjustments)
        for result in results:
            description = result.value
            aggregate_description.components.extend(description.components)
            aggregate_description.metrics.extend(description.metrics)

        self.logger.info(f"Adjustment completed {summary}")
        return aggregate_description

    # backoff and retry for an hour on transient request failures
    @backoff.on_exception(
        backoff.expo, httpx.HTTPError, max_time=BackoffConfig.max_time
    )
    async def exec_command(self) -> servo.api.Status:
        cmd_response = await self._post_event(servo.api.Event.WHATS_NEXT, None)
        self.logger.info(f"What's Next? => {cmd_response.command}")
        self.logger.trace(devtools.pformat(cmd_response))

        if cmd_response.command == servo.api.Command.DESCRIBE:
            description = await self.describe()
            self.logger.info(
                f"Described: {len(description.components)} components, {len(description.metrics)} metrics"
            )
            self.logger.trace(devtools.pformat(description))

            param = dict(descriptor=description.__opsani_repr__(), status="ok")
            return await self._post_event(servo.api.Event.DESCRIPTION, param)

        elif cmd_response.command == servo.api.Command.MEASURE:
            measurement = await self.measure(cmd_response.param)
            self.logger.info(
                f"Measured: {len(measurement.readings)} readings, {len(measurement.annotations)} annotations"
            )
            self.logger.trace(devtools.pformat(measurement))
            param = measurement.__opsani_repr__()
            return await self._post_event(servo.api.Event.MEASUREMENT, param)

        elif cmd_response.command == servo.api.Command.ADJUST:
            adjustments = servo.api.descriptor_to_adjustments(cmd_response.param["state"])
            control = Control(**cmd_response.param.get("control", {}))
            description = await self.adjust(adjustments, control)

            reply = {"status": "ok", "state": description.__opsani_repr__()}

            components_count = len(description.components)
            settings_count = sum(
                len(component.settings) for component in description.components
            )
            self.logger.info(
                f"Adjusted: {components_count} components, {settings_count} settings"
            )

            return await self._post_event(servo.api.Event.ADJUSTMENT, reply)

        elif cmd_response.command == servo.api.Command.SLEEP:
            # TODO: Model this
            duration = Duration(cmd_response.param.get("duration", 120))
            status = servo.utilities.key_paths.value_for_key_path(cmd_response.param, "data.status", None)
            reason = servo.utilities.key_paths.value_for_key_path(
                cmd_response.param, "data.reason", "unknown reason"
            )
            msg = f"{status}: {reason}" if status else f"{reason}"
            self.logger.info(f"Sleeping for {duration} ({msg}).")
            await asyncio.sleep(duration.total_seconds())

            # Return a status so we have a simple API contract
            return servo.api.Status(status="slept", message=msg)
        else:
            raise ValueError(f"Unknown command '{cmd_response.command.value}'")

    # Main run loop for processing commands from the optimizer
    async def main_loop(self) -> None:
        while True:
            try:
                servo.servo.Servo.set_current(self.servo)
                status = await self.exec_command()
                if status.status == servo.api.UNEXPECTED_EVENT:
                    self.logger.warning(
                        f"server reported unexpected event: {status.reason}"
                    )
            except httpx.TimeoutException as error:
                self.logger.warning(f"ignoring HTTP timeout error: {error}")
            
            except httpx.HTTPStatusError as error:
                self.logger.warning(f"ignoring HTTP response error: {error}")
                
            except Exception as error:
                self.logger.exception(f"failed with unrecoverable error: {error}")
                raise error
            
    async def run(self) -> None:
        servo.servo.Servo.set_current(self.servo)
        self.logger.info(
            f"Servo started with {len(self.servo.connectors)} active connectors [{self.optimizer.id} @ {self.optimizer.url or self.optimizer.base_url}]"
        )

        async def giveup(details) -> None:
            loop = asyncio.get_event_loop()
            self.logger.critical("retries exhausted, giving up")
            asyncio.create_task(self.shutdown(loop))

        try:
            @backoff.on_exception(
                backoff.expo,
                httpx.HTTPError,
                max_time=lambda: BackoffConfig.max_time("connect"),
                on_giveup=giveup,
            )
            async def connect() -> None:
                self.logger.info("Saying HELLO.", end=" ")
                await self._post_event(servo.api.Event.HELLO, dict(agent=servo.api.USER_AGENT))
                self.connected = True

            self.logger.info("Dispatching startup event...")
            await self.servo.startup()

            self.logger.info(f"Connecting to Opsani Optimizer @ {self.optimizer.api_url}...")
            await connect()
        except:
            servo.logger.exception("exception encountered during connect")
            pass

        await asyncio.create_task(self.main_loop(), name="main loop")
    
    async def shutdown(self, *, reason: Optional[str] = None) -> None:
        """Shutdown the running servo."""
        try:
            if self.connected:
                await self._post_event(servo.api.Event.GOODBYE, dict(reason=reason))
        except Exception:
            self.logger.exception(f"Exception occurred during GOODBYE request")        

class AssemblyRunner(pydantic.BaseModel, servo.logging.Mixin):
    assembly: servo.Assembly
    runners: List[ServoRunner] = []
    progress_handler: Optional[servo.logging.ProgressHandler] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    def __init__(self, assembly: servo.Assembly, **kwargs) -> None:
        super().__init__(assembly=assembly, **kwargs)
    
    def _runner_for_servo(self, servo: servo.Servo) -> ServoRunner:
        for runner in self.runners:
            if runner.servo == servo:
                return runner
        
        raise KeyError(f"no runner was found for the servo: \"{servo}\"")
    
    def run(self) -> None:
        """Asynchronously run all servos active within the assembly.
        
        Running the assembly takes over the current event loop and schedules a `ServoRunner` instance for each servo active in the assembly.
        """
        loop = asyncio.get_event_loop()

        # Setup signal handling
        signals = (signal.SIGHUP, signal.SIGTERM, signal.SIGINT, signal.SIGUSR1)
        for s in signals:
            loop.add_signal_handler(
                s, lambda s=s: asyncio.create_task(self._shutdown(loop, signal=s))
            )

        loop.set_exception_handler(self._handle_exception)
        
        # Setup logging
        # TODO: encapsulate all this shit
        async def report_progress(self, **kwargs) -> None:
            # Forward to the active servo...
            await servo.Servo.current().report_progress(**kwargs)
            
        def handle_progress_exception(error: Exception) -> None:
            # FIXME: This needs to be made multi-servo aware
            # Restart the main event loop if we get out of sync with the server
            if isinstance(error, servo.api.UnexpectedEventError):
                self.logger.error(
                    "servo has lost synchronization with the optimizer: restarting operations"
                )

                tasks = [
                    t for t in asyncio.all_tasks() if t is not asyncio.current_task()
                ]
                self.logger.info(f"Canceling {len(tasks)} outstanding tasks")
                [task.cancel() for task in tasks]

                # Restart a fresh main loop
                runner = self._runner_for_servo(servo.Servo.current())
                asyncio.create_task(runner.main_loop(), name="main loop")
        
        self.progress_handler = servo.logging.ProgressHandler(
            report_progress, self.logger.warning, handle_progress_exception
        )
        self.logger.add(self.progress_handler.sink, catch=True)

        self._display_banner()

        try:
            for servo_ in self.assembly.servos:
                servo_runner = ServoRunner(servo_)
                loop.create_task(servo_runner.run())
                self.runners.append(servo_runner)
            
            loop.run_forever()
            
        finally:
            loop.close()
    
    def _display_banner(self) -> None:
        banner = "\n".join([
            r"   _____                      _  __",
            r"  / ___/___  ______   ______ | |/ /",
            r"  \__ \/ _ \/ ___/ | / / __ \|   /",
            r" ___/ /  __/ /   | |/ / /_/ /   |",
            r"/____/\___/_/    |___/\____/_/|_|",
        ])
        typer.secho(banner, fg=typer.colors.BRIGHT_BLUE, bold=True)
        types = servo.Assembly.all_connector_types()
        types.remove(servo.Servo)

        names = []
        for c in types:
            name = typer.style(
                servo.utilities.strings.commandify(c.__default_name__), fg=typer.colors.CYAN, bold=False
            )
            version = typer.style(str(c.version), fg=typer.colors.WHITE, bold=True)
            names.append(f"{name}-{version}")

        version = typer.style(f"v{servo.__version__}", fg=typer.colors.WHITE, bold=True)
        codename = typer.style(servo.__cryptonym__, fg=typer.colors.MAGENTA, bold=False)
        initialized = typer.style(
            "initialized", fg=typer.colors.BRIGHT_GREEN, bold=True
        )

        typer.secho(f'{version} "{codename}" {initialized}')
        typer.secho()
        typer.secho(f"connectors:  {', '.join(sorted(names))}")
        typer.secho(
            f"config file: {typer.style(str(self.assembly.config_file), bold=True, fg=typer.colors.YELLOW)}"
        )
        
        if len(self.assembly.servos) == 1:
            servo_ = self.assembly.servos[0]
            optimizer = servo_.optimizer
            
            id = typer.style(optimizer.id, bold=True, fg=typer.colors.WHITE)
            typer.secho(f"optimizer:   {id}")
            if optimizer.base_url != "https://api.opsani.com/":
                base_url = typer.style(
                    f"{optimizer.base_url}", bold=True, fg=typer.colors.RED
                )
                typer.secho(f"base url: {base_url}")
            
            if servo_.config.servo and servo_.config.servo.proxies:
                proxies = typer.style(
                    f"{devtools.pformat(servo_.config.servo.proxies)}",
                    bold=True,
                    fg=typer.colors.CYAN,
                )
                typer.secho(f"proxies: {proxies}")
        else:
            servo_count = typer.style(str(len(self.assembly.servos)), bold=True, fg=typer.colors.WHITE)
            typer.secho(f"servos:   {servo_count}")
            
        typer.secho()
    
    async def _shutdown(self, loop, signal=None):
        if signal:
            self.logger.info(f"Received exit signal {signal.name}...")
        
        reason = signal.name if signal else "shutdown"
        self.logger.info(f"Shutting down {len(self.runners)} running servos...")
        for runner in self.runners:
            await runner.shutdown(reason=reason)

        self.logger.info("Dispatching shutdown event...")
        await self.assembly.shutdown()
        await self.progress_handler.shutdown()

        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]

        [task.cancel() for task in tasks]        

        self.logger.info(f"Canceling {len(tasks)} outstanding tasks")
        await asyncio.gather(*tasks, return_exceptions=True)

        self.logger.info("Servo shutdown complete.")
        await self.logger.complete()

        loop.stop()

    def _handle_exception(self, loop: asyncio.AbstractEventLoop, context: dict) -> None:
        self.logger.error(f"asyncio exception handler triggered with context: {context}")

        self.logger.critical(
            "Shutting down due to unhandled exception in asyncio event loop..."
        )
        asyncio.create_task(self._shutdown(loop))
