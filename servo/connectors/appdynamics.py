import asyncio
import datetime
import functools
import re
import enum
from typing import Dict, Iterable, List, Optional, Tuple

import httpcore._exceptions
import httpx
import pydantic

import servo

DEFAULT_BASE_URL = "http://localhost:8090"
API_PATH = "/controller/rest/"


class AppdynamicsMetric(servo.Metric):
    """AppdynamicsMetric objects describe metrics that can be measured by querying
    AppDynamics.
    """

    query: str
    """An AppD query that returns the value of the target metric.

    For details on AppDynamics, see the [AppDynamics
    Querying](https://docs.appdynamics.com/display/PRO45/Metric+and+Snapshot+API)
    documentation.
    """

    @property
    def query_escaped(self) -> str:
        # Not used as such, leaving for now in prom style
        return re.sub(r"\{(.*?)\}", r"{{\1}}", self.query)

    def __check__(self) -> servo.Check:
        return servo.Check(
            name=f"Check {self.name}",
            description=f'Run AppDynamics query "{self.query}"',
        )


class AppdynamicsConfiguration(servo.BaseConfiguration):
    """AppdynamicsConfiguration objects describe how AppdynamicsConnector objects
    capture measurements from the AppDynamics metrics server.
    """

    username: pydantic.SecretStr
    """The username for AppDynamics."""

    account: pydantic.SecretStr
    """The account name for AppDynamics."""

    password: pydantic.SecretStr
    """The API key for accessing the AppDynamics metrics API."""

    app_id: str
    """The Application ID for accessing the AppDynamics metrics API."""

    base_url: pydantic.AnyHttpUrl = DEFAULT_BASE_URL
    """The base URL for accessing the AppDynamics metrics API.

    The URL must point to the root of the AppDynamics deployment. Resource paths
    are computed as necessary for API requests.
    """

    metrics: List[AppdynamicsMetric]
    """The metrics to measure from AppDynamics.

    Metrics must include a valid query.
    """

    @classmethod
    def generate(cls, **kwargs) -> "AppdynamicsConfiguration":
        """Generates a default configuration for capturing measurements from the
        AppDynamics metrics server.

        Returns:
            A default configuration for AppdynamicsConnector objects.
        """
        return cls(
            description="Update the username, account, password, app_id, base_url and metrics to match your AppDynamics configuration",
            username='replace-me',
            account='replace-me',
            password='replace-me',
            app_id='replace-me',
            metrics=[
                AppdynamicsMetric(
                    "main_throughput",
                    servo.Unit.requests_per_minute,
                    query="Business Transaction Performance|Business Transactions|frontend-service|/payment|Individual Nodes|frontend|Calls per Minute",
                ),
                AppdynamicsMetric(
                    "main_error_rate",
                    servo.Unit.requests_per_minute,
                    query="Business Transaction Performance|Business Transactions|frontend-service|/payment|Individual Nodes|frontend|Errors per Minute",
                ),
                AppdynamicsMetric(
                    "main_latency",
                    servo.Unit.milliseconds,
                    query="Business Transaction Performance|Business Transactions|frontend-service|/payment|Individual Nodes|frontend|Average Response Time (ms)",
                ),
                AppdynamicsMetric(
                    "main_latency_normal",
                    servo.Unit.milliseconds,
                    query="Business Transaction Performance|Business Transactions|frontend-service|/payment|Individual Nodes|frontend|Normal Average Response Time (ms)",
                ),
                AppdynamicsMetric(
                    "main_latency_95th",
                    servo.Unit.milliseconds,
                    query="Business Transaction Performance|Business Transactions|frontend-service|/payment|Individual Nodes|frontend|95th Percentile Response Time (ms)",
                ),
                AppdynamicsMetric(
                    "main_slow_calls",
                    servo.Unit.requests_per_minute,
                    query="Business Transaction Performance|Business Transactions|frontend-service|/payment|Individual Nodes|frontend|Number of Slow Calls",
                ),
                AppdynamicsMetric(
                    "main_very_slow_calls",
                    servo.Unit.requests_per_minute,
                    query="Business Transaction Performance|Business Transactions|frontend-service|/payment|Individual Nodes|frontend|Number of Very Slow Calls",
                ),
                AppdynamicsMetric(
                    "main_stall",
                    servo.Unit.requests_per_minute,
                    query="Business Transaction Performance|Business Transactions|frontend-service|/payment|Individual Nodes|frontend|Stall Count",
                ),

                # Tuning instance metrics
                AppdynamicsMetric(
                    "tuning_throughput",
                    servo.Unit.requests_per_minute,
                    query="Business Transaction Performance|Business Transactions|frontend-service|/payment|Individual Nodes|frontend-service-tuning|Calls per Minute",
                ),
                AppdynamicsMetric(
                    "tuning_error_rate",
                    servo.Unit.requests_per_minute,
                    query="Business Transaction Performance|Business Transactions|frontend-service|/payment|Individual Nodes|frontend-service-tuning|Errors per Minute",
                ),
                AppdynamicsMetric(
                    "tuning_latency",
                    servo.Unit.milliseconds,
                    query="Business Transaction Performance|Business Transactions|frontend-service|/payment|Individual Nodes|frontend-service-tuning|Average Response Time (ms)",
                ),
                AppdynamicsMetric(
                    "tuning_latency_95th",
                    servo.Unit.milliseconds,
                    query="Business Transaction Performance|Business Transactions|frontend-service|/payment|Individual Nodes|frontend-service-tuning|95th Percentile Response Time (ms)",
                ),
                AppdynamicsMetric(
                    "tuning_latency_normal",
                    servo.Unit.milliseconds,
                    query="Business Transaction Performance|Business Transactions|frontend-service|/payment|Individual Nodes|frontend-service-tuning|Normal Average Response Time (ms)",
                ),
                AppdynamicsMetric(
                    "tuning_slow_calls",
                    servo.Unit.requests_per_minute,
                    query="Business Transaction Performance|Business Transactions|frontend-service|/payment|Individual Nodes|frontend-service-tuning|Number of Slow Calls",
                ),
                AppdynamicsMetric(
                    "tuning_very_slow_calls",
                    servo.Unit.requests_per_minute,
                    query="Business Transaction Performance|Business Transactions|frontend-service|/payment|Individual Nodes|frontend-service-tuning|Number of Very Slow Calls",
                ),
                AppdynamicsMetric(
                    "tuning_stall",
                    servo.Unit.requests_per_minute,
                    query="Business Transaction Performance|Business Transactions|frontend-service|/payment|Individual Nodes|frontend-service-tuning|Stall Count",
                )
            ],
            **kwargs,
        )

    @pydantic.validator("base_url")
    @classmethod
    def rstrip_base_url(cls, base_url):
        return base_url.rstrip("/")

    @property
    def api_url(self) -> str:
        return f"{self.base_url}{API_PATH}"


class AppdynamicsRequest(pydantic.BaseModel):
    base_url: pydantic.AnyHttpUrl
    metric: AppdynamicsMetric
    start: datetime.datetime
    end: datetime.datetime

    @property
    def query(self) -> str:
        return self.metric.query

    @property
    def params(self) -> dict:
        return {"metric-path": f"{self.query}",
                "time-range-type": "BETWEEN_TIMES",  # Should remain non-configurable
                "start-time": f"{int(self.start.timestamp()*1000)}",
                "end-time": f"{int(self.end.timestamp()*1000)}",
                "rollup": "false",  # Prevents aggregation/summarization
                "output": "JSON"
                }

    @property
    def endpoint(self) -> str:
        return "".join(f"?metric-path={self.query}"
                       + f"&time-range-type=BETWEEN_TIMES"  # Should remain non-configurable
                       + f"&start-time={int(self.start.timestamp()*1000)}"
                       + f"&end-time={int(self.end.timestamp()*1000)}"
                       + f"&rollup=false"  # Prevents aggregation/summarization
                       + f"&output=JSON"
                       )


class AppdynamicsChecks(servo.BaseChecks):
    """AppdynamicsChecks objects check the state of a AppdynamicsConfiguration to
    determine if it is ready for use in an optimization run.
    """

    config: AppdynamicsConfiguration

    @servo.multicheck('Run query "{item.query_escaped}"')
    async def check_queries(self) -> Tuple[Iterable, servo.CheckHandler]:
        """Checks that all metrics have valid, well-formed WQL queries."""

        async def query_for_metric(metric: AppdynamicsMetric) -> str:
            start, end = (
                datetime.datetime.now() - datetime.timedelta(minutes=10),
                datetime.datetime.now(),
            )
            appdynamics_request = AppdynamicsRequest(
                base_url=self.config.api_url, metric=metric, start=start, end=end
            )

            self.logger.trace(
                f"Querying Appdynamics (`{metric.query}`): {appdynamics_request.endpoint}"
            )
            async with httpx.AsyncClient(
                base_url=self.config.api_url,
                params=appdynamics_request.params,
            ) as client:
                try:
                    response = await client.get(f"applications/{self.config.app_id}/metric-data",
                                                auth=(f"{self.config.username.get_secret_value()}@"
                                                      f"{self.config.account.get_secret_value()}",
                                                      self.config.password.get_secret_value()))
                    response.raise_for_status()
                    result = response.json()[0]
                    return f"returned {len(result)} results"
                except (httpx.HTTPError, httpcore._exceptions.ReadTimeout, httpcore._exceptions.ConnectError) as error:
                    self.logger.trace(f"HTTP error encountered during GET {appdynamics_request.endpoint}: {error}")
                    raise

        return self.config.metrics, query_for_metric


@servo.metadata(
    description="AppDynamics Connector for Opsani",
    version="0.0.1",
    homepage="https://github.com/opsani/servox",
    license=servo.License.apache2,
    maturity=servo.Maturity.stable,
)
class AppdynamicsConnector(servo.BaseConnector):
    """AppdynamicsConnector objects enable servo assemblies to capture
    measurements from the [AppDynamics](https://appdynamics.io/) metrics server.
    """

    config: AppdynamicsConfiguration

    @servo.on_event()
    async def check(
        self,
        matching: Optional[servo.CheckFilter] = None,
        halt_on: Optional[servo.ErrorSeverity] = servo.ErrorSeverity.critical,
    ) -> List[servo.Check]:
        """Checks that the configuration is valid and the connector can capture
        measurements from AppDynamics.

        Checks are implemented in the AppdynamicsChecks class.

        Args:
            matching (Optional[Filter], optional): A filter for limiting the
                checks that are run. Defaults to None.
            halt_on (Severity, optional): When to halt running checks.
                Defaults to Severity.critical.

        Returns:
            List[Check]: A list of check objects that report the outcomes of the
                checks that were run.
        """
        return await AppdynamicsChecks.run(
            self.config, matching=matching, halt_on=halt_on
        )

    @servo.on_event()
    def describe(self) -> servo.Description:
        """Describes the current state of Metrics measured by querying AppDynamics.

        Returns:
            Description: An object describing the current state of metrics
                queried from AppDynamics.
        """
        return servo.Description(metrics=self.config.metrics)

    @servo.on_event()
    def metrics(self) -> List[servo.Metric]:
        """Returns the list of Metrics measured through AppDynamics queries.

        Returns:
            List[Metric]: The list of metrics to be queried.
        """
        return self.config.metrics

    @servo.on_event()
    async def measure(
            self, *, metrics: List[str] = None, control: servo.Control = servo.Control()
    ) -> servo.Measurement:
        """Queries AppDynamics for metrics as time series values and returns a
        Measurement object that aggregates the readings for processing by the
        optimizer.

        Args:
            metrics (List[str], optional): A list of the metric names to measure.
                When None, all configured metrics are measured. Defaults to None.
            control (Control, optional): A control descriptor that describes how
                the measurement is to be captured. Defaults to Control().

        Returns:
            Measurement: An object that aggregates the state of the metrics
            queried from AppDynamics.
        """
        if metrics:
            metrics__ = list(filter(lambda m: m.name in metrics, self.metrics()))
        else:
            metrics__ = self.metrics()
        measuring_names = list(map(lambda m: m.name, metrics__))
        self.logger.info(
            f"Starting measurement of {len(metrics__)} metrics: {servo.utilities.join_to_series(measuring_names)}"
        )

        start = datetime.datetime.now() + control.warmup
        end = start + control.duration

        sleep_duration = servo.Duration(control.warmup + control.duration)
        self.logger.info(
            f"Waiting {sleep_duration} during metrics collection ({control.warmup} warmup + {control.duration} duration)..."
        )

        progress = servo.DurationProgress(sleep_duration)

        def notifier(p):
            return self.logger.info(
                p.annotate(f"waiting {sleep_duration} during metrics collection...", False),
                progress=p.progress,
            )

        await progress.watch(notifier)
        self.logger.info(
            f"Done waiting {sleep_duration} for metrics collection, resuming optimization."
        )

        # Capture the measurements
        self.logger.info(f"Querying AppDynamics for {len(metrics__)} metrics...")
        readings = await asyncio.gather(
            *list(map(lambda m: self._query_appd(m, start, end), metrics__))
        )
        all_readings = (
            functools.reduce(lambda x, y: x + y, readings) if readings else []
        )
        measurement = servo.Measurement(readings=all_readings)
        return measurement

    async def _query_appd(
            self, metric: AppdynamicsMetric, start: datetime, end: datetime
    ) -> List[servo.TimeSeries]:
        appdynamics_request = AppdynamicsRequest(
            base_url=self.config.api_url, metric=metric, start=start, end=end
        )

        # Collect node information for optimization service
        # self.logger.trace(
        #     f"Querying AppDynamics nodes"
        # )
        #
        # async with httpx.AsyncClient(
        #         base_url=self.config.api_url,
        # ) as client:
        #     try:
        #         response = await client.get(f"applications/{self.config.app_id}/tiers/{self.config.tier}/nodes",
        #                                     auth=(f"{self.config.user_auth}", self.config.password))
        #         response.raise_for_status()
        #     except (httpx.HTTPError, httpcore._exceptions.ReadTimeout, httpcore._exceptions.ConnectError) as error:
        #         self.logger.trace(f"HTTP error encountered during GET {response.url}: {error}")
        #         raise
        #
        # data = response.json()
        # nodes = [node['name'] for node in data]
        #
        # self.logger.trace(f"Retrieved nodes for tier {self.config.tier}: {nodes}")

        self.logger.trace(
            f"Querying AppDynamics (`{metric.query}`): {appdynamics_request.endpoint}"
        )
        async with httpx.AsyncClient(
                base_url=self.config.api_url,
                params=appdynamics_request.params,
        ) as client:
            try:
                response = await client.get(f"applications/{self.config.app_id}/metric-data",
                                            auth=(f"{self.config.username.get_secret_value()}@"
                                                  f"{self.config.account.get_secret_value()}",
                                                  self.config.password.get_secret_value()))
                response.raise_for_status()
            except (httpx.HTTPError, httpcore._exceptions.ReadTimeout, httpcore._exceptions.ConnectError) as error:
                self.logger.trace(f"HTTP error encountered during GET {appdynamics_request.endpoint}: {error}")
                raise

        data = response.json()[0]
        self.logger.trace(f"Got response data for metric {metric}: {data}")

        readings = []

        # TEMP: just to see output
        for result_dict in data["metricValues"]:
            self.logger.info(
                f"Captured {result_dict['value']} at {result_dict['startTimeInMillis']} for {metric}"
            )

        metric_path = data["metricPath"]  # e.g. "Business Transaction Performance|Business Transactions|frontend-service|/payment|Calls per Minute"
        metric_name = data["metricName"]  # e.g. "BTM|BTs|BT:270723|Component:8435|Calls per Minute"

        for result_dict in data["metricValues"]:

            data_points: List[servo.DataPoint] = [servo.DataPoint(
                metric, result_dict['startTimeInMillis'], float(result_dict['value'])
            )]

            readings.append(
                servo.TimeSeries(
                    metric,
                    data_points,
                    id=f"{{metric_path={metric_path}, metric_name={metric_name}}}",
                )
            )

        return readings
