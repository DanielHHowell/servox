import asyncio
import datetime
import importlib.metadata
import functools
import re
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

    tier: str
    """The AppDynamics tier that the service to optimize is running on."""

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
            description="Update the app_id, base_url and metrics to match your AppDynamics configuration. Additional credential parameters of username, account and password are handled via K8s secrets in deployment",
            app_id='app-replace',
            tier='tier-replace',
            base_url='url-replace',
            metrics=[
                # Main metrics (for aggregation)
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
                except (httpx.HTTPError, httpx.ReadTimeout, httpx.ConnectError) as error:
                    self.logger.trace(f"HTTP error encountered during GET {appdynamics_request.endpoint}: {error}")
                    raise

        return self.config.metrics, query_for_metric


@servo.metadata(
    description="AppDynamics Connector for Opsani",
    version="0.7.1",
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

        # Separate instance_count metrics away from all_metrics
        all_metrics = list(filter(lambda m: 'instance_count' not in m.name, metrics__))
        #main_instance_metric = next(iter(filter(lambda m: 'main_instance_count' in m.name, metrics__)))
        #tuning_instance_metric = next(iter(filter(lambda m: 'tuning_instance_count' in m.name, metrics__)))

        # Capture the measurements
        self.logger.info(f"Querying AppDynamics for {len(metrics__)} metrics...")

        # Parse active nodes and metrics between main and tuning
        # Collect nodes
        nodes = await self._query_nodes()

        # Main set
        main_nodes = list(filter(lambda x: 'tuning' not in x, nodes))
        aggregate_metrics = list(filter(lambda m: 'main' in m.name, all_metrics))
        all_main_nodes_response = await asyncio.gather(
            *list(map(lambda m: self._query_appd_active_nodes(m, aggregate_metrics[0], start, end), main_nodes))
        )
        active_main_nodes = list(filter(lambda x: x is not None, all_main_nodes_response))
        self.logger.info(f"Found {len(active_main_nodes)} active nodes: {active_main_nodes}")

        # Capture measurements that require aggregation
        #main_instance_readings = await asyncio.gather(self._query_instance_count(main_instance_metric, start, end, active_main_nodes))
        aggregate_readings = await asyncio.gather(
            *list(map(lambda m: self._query_appd_aggregate(m, start, end, active_main_nodes), aggregate_metrics))
        )

        # Tuning set
        tuning_nodes = list(filter(lambda x: 'tuning' in x, nodes))
        tuning_metrics = list(filter(lambda m: 'tuning' in m.name, all_metrics))
        tuning_nodes_response = await asyncio.gather(
            *list(map(lambda m: self._query_appd_active_nodes(m, tuning_metrics[0], start, end), tuning_nodes))
        )
        active_tuning_node = next(iter(filter(lambda x: x is not None, tuning_nodes_response)), None)

        # Capture tuning measurements directly that do not require aggregation/processing
        if not active_tuning_node:

            self.logger.info(f"No active tuning node, returning empty readings and will retry before aborting current adjustment")
            direct_readings = []

        elif active_tuning_node:

            self.logger.info(f"Found active tuning node: {active_tuning_node}")
            # tuning_instance_readings = await asyncio.gather(
            #     self._query_instance_count(tuning_instance_metric, start, end, [active_tuning_node]))
            direct_readings = await asyncio.gather(
                *list(map(lambda m: self._appd_node_response(active_tuning_node, m, start, end), tuning_metrics))
            )

        # Combine and clean
        readings = direct_readings + aggregate_readings #+ main_instance_readings + tuning_instance_readings

        all_readings = (
            functools.reduce(lambda x, y: x + y, readings) if readings else []
        )
        measurement = servo.Measurement(readings=all_readings)
        return measurement

    async def _query_nodes(self) -> List[str]:
        """Queries AppDynamics for a list of all nodes under a given tier (specified in the config), both actively
        reporting and shutdown nodes, to be subsequently filtered for status.

        Returns:
            nodes: A list of all nodes within the specified tier.
        """

        self.logger.trace(
            f"Querying AppDynamics nodes for tier: {self.config.tier}"
        )

        params = {'output': 'JSON'}

        async with httpx.AsyncClient(
                base_url=self.config.api_url,
                params=params
        ) as client:
            try:
                response = await client.get(f"applications/{self.config.app_id}/tiers/{self.config.tier}/nodes",
                                            auth=(f"{self.config.username.get_secret_value()}@"
                                                  f"{self.config.account.get_secret_value()}",
                                                  self.config.password.get_secret_value()))
                response.raise_for_status()
            except (httpx.HTTPError, httpcore._exceptions.ReadTimeout, httpcore._exceptions.ConnectError) as error:
                self.logger.trace(f"HTTP error encountered during GET {response.url}: {error}")
                raise

        data = response.json()
        nodes = [node['name'] for node in data]

        self.logger.trace(f"Retrieved nodes for tier {self.config.tier}: {nodes}")

        return nodes

    async def _query_appd_active_nodes(
            self, individual_node: str, metric: AppdynamicsMetric, start: datetime, end: datetime
    ) -> Optional[str]:
        """Queries AppDynamics to see if a given node is actively reporting.

        Args:
            individual_node (str, required): The node to query.
            metric (AppdynamicsMetric, required): The metric to query for.
            start (datetime, required): Metric start time.
            end (datetime, required). Metric end time.

        Returns:
            Optional[str]. The node name if actively reporting, otherwise None.
        """

        appdynamics_request = AppdynamicsRequest(
            base_url=self.config.api_url, metric=metric, start=start, end=end
        )

        metric_head = '|'.join(metric.query.split('|')[:-2])
        metric_tail = metric.query.split('|')[-1] # TODO: rationalize having this available - throughput (below) should always suffice
        metric_path_substitution = f"{metric_head}|{individual_node}|Calls per Minute"

        self.logger.trace(
            f"Querying AppDynamics (`{metric_path_substitution}`): {appdynamics_request.endpoint}"
        )

        params = appdynamics_request.params
        params.update({'metric-path': metric_path_substitution})

        async with httpx.AsyncClient(
                base_url=self.config.api_url,
                params=params,
        ) as client:
            try:
                response = await client.get(f"applications/{self.config.app_id}/metric-data",
                                            auth=(f"{self.config.username.get_secret_value()}@"
                                                  f"{self.config.account.get_secret_value()}",
                                                  self.config.password.get_secret_value()))
                response.raise_for_status()
            except (httpx.HTTPError, httpx.ReadTimeout, httpx.ConnectError) as error:
                self.logger.trace(f"HTTP error encountered during GET {appdynamics_request.endpoint}: {error}")
                raise

        # AppDynamics API can confusingly either present no response or an empty response
        # TODO: improve this conditional handling?

        node_data = response.json()
        if not node_data:

            self.logger.trace(f"Found inactive node: {individual_node}")
            return None

        if not node_data[0]["metricValues"]:

            self.logger.trace(f"Found inactive node: {individual_node}")
            return None

        elif node_data[0]["metricValues"]:

            self.logger.trace(f"Verified active node: {individual_node}")
            return individual_node


    async def _query_appd_aggregate(
            self, metric: AppdynamicsMetric, start: datetime, end: datetime, active_nodes: List[str]
    ):
        """Queries AppDynamics for measurements that need to be aggregated across multiple AppD nodes/K8s pods.
        Individual node responses are gathered via _appd_node_response(), transposed to synchronize reading times,
        and computed via either sum or average.

        Args:
            metric (AppdynamicsMetric, required): The metric to query for.
            start (datetime, required): Metric start time.
            end (datetime, required). Metric end time.
            active_nodes (List[str], required): The list of actively reporting nodes to aggregate on

        Returns:
            Readings: A list of TimeSeries with metric readings.
        """

        # Begin metric collection and aggregation for active nodes
        node_readings = await asyncio.gather(
            *list(map(lambda m: self._appd_node_response(m, metric, start, end), active_nodes))
        )

        aggregate_readings = []

        # Transpose node readings from [nodes[readings]] to [readings[nodes]] for computed aggregation
        transposed_node_readings = list(map(list, zip(*node_readings)))

        for node_reading in transposed_node_readings:
            aggregate_data_points = []

            for time_series in node_reading:
                aggregate_data_points.append(time_series.data_points[0].value)

            # Main aggregation logic
            if metric.unit == 'rpm':
                computed_aggregate = sum(aggregate_data_points)

                self.logger.trace(f"Aggregating values {aggregate_data_points} for {metric.unit} via sum into {computed_aggregate}")
                aggregate_readings.append(computed_aggregate)

            elif metric.unit == 'ms':
                computed_aggregate = sum(aggregate_data_points) / len(aggregate_data_points)

                self.logger.trace(f"Aggregating values {aggregate_data_points} for {metric.unit} via average into {computed_aggregate}")
                aggregate_readings.append(computed_aggregate)


        # Reading from first node retrieved for time information with aggregation value data substituted from individual retrievals above
        appdynamics_request = AppdynamicsRequest(
            base_url=self.config.api_url, metric=metric, start=start, end=end
        )

        self.logger.trace(
            f"Querying AppDynamics (`{metric.query}`): {appdynamics_request.endpoint}"
        )

        metric_head = '|'.join(metric.query.split('|')[:-2])
        metric_tail = metric.query.split('|')[-1]
        metric_path_substitution = f"{metric_head}|{active_nodes[0]}|{metric_tail}"

        params = appdynamics_request.params
        params.update({'metric-path': metric_path_substitution})

        async with httpx.AsyncClient(
                base_url=self.config.api_url,
                params=params,
        ) as client:
            try:
                response = await client.get(f"applications/{self.config.app_id}/metric-data",
                                            auth=(f"{self.config.username.get_secret_value()}@"
                                                  f"{self.config.account.get_secret_value()}",
                                                  self.config.password.get_secret_value()))
                response.raise_for_status()
            except (httpx.HTTPError, httpx.ReadTimeout, httpx.ConnectError) as error:
                self.logger.trace(f"HTTP error encountered during GET {appdynamics_request.endpoint}: {error}")
                raise

        data = response.json()[0]

        readings = []

        for result_dict in zip(aggregate_readings, data["metricValues"]):
            self.logger.trace(
                f"Captured {result_dict[0]} at {result_dict[1]['startTimeInMillis']} for aggregate metric: {metric}"
            )

        metric_path = data["metricPath"]  # e.g. "Business Transaction Performance|Business Transactions|frontend-service|/payment|Calls per Minute"
        metric_name = data["metricName"]  # e.g. "BTM|BTs|BT:270723|Component:8435|Calls per Minute"


        for result_dict in zip(aggregate_readings, data["metricValues"]):

            data_points: List[servo.DataPoint] = [servo.DataPoint(
                metric, result_dict[1]['startTimeInMillis'], float(result_dict[0])
            )]

            readings.append(
                servo.TimeSeries(
                    metric,
                    data_points,
                    id=f"{{metric_path={metric_path}, metric_name={metric_name}}}",
                )
            )

        return readings

    async def _query_instance_count(
            self, metric: AppdynamicsMetric, start: datetime, end: datetime, active_nodes: List[str]
    ):
        """Queries AppDynamics for instances count. Individual node responses are gathered via _appd_node_response(),
        transposed to synchronize reading times, and computed via either sum or average.

        Args:
            metric (AppdynamicsMetric, required): The metric to query for.
            start (datetime, required): Metric start time.
            end (datetime, required). Metric end time.
            active_nodes (List[str], required): The list of actively reporting nodes to aggregate on

        Returns:
            Readings: A list of TimeSeries with metric readings.
        """

        # Begin metric collection and aggregation for active nodes

        # TODO: Cleanup this conditional handling for singleton instance counting

        if len(active_nodes) > 1:
            node_readings = await asyncio.gather(
                *list(map(lambda m: self._appd_node_response(m, metric, start, end), active_nodes))
            )

            instance_count_readings = []

            # Transpose node readings from [nodes[readings]] to [readings[nodes]] for computed aggregation
            transposed_node_readings = list(map(list, zip(*node_readings)))

            for node_reading in transposed_node_readings:

                instant_instance_count = len(node_reading)
                instance_count_readings.append(instant_instance_count)

                self.logger.trace(f"Found instance count {instant_instance_count} at time {node_reading[0].data_points[0].time}")

        elif len(active_nodes) == 1:

            node_readings = await asyncio.gather(self._appd_node_response(active_nodes[0], metric, start, end))
            instance_count_readings = [float(1) for reading in node_readings]

            for reading in node_readings:
                self.logger.trace(
                    f"Found single instance count at time {reading[0].data_points[0].time}")

        # Reading from first node retrieved for time information with aggregation value data substituted from individual retrievals above
        appdynamics_request = AppdynamicsRequest(
            base_url=self.config.api_url, metric=metric, start=start, end=end
        )

        self.logger.trace(
            f"Querying AppDynamics (`{metric.query}`): {appdynamics_request.endpoint}"
        )

        metric_head = '|'.join(metric.query.split('|')[:-2])
        metric_tail = metric.query.split('|')[-1]
        metric_path_substitution = f"{metric_head}|{active_nodes[0]}|Calls per Minute"

        params = appdynamics_request.params
        params.update({'metric-path': metric_path_substitution})

        async with httpx.AsyncClient(
                base_url=self.config.api_url,
                params=params,
        ) as client:
            try:
                response = await client.get(f"applications/{self.config.app_id}/metric-data",
                                            auth=(f"{self.config.username.get_secret_value()}@"
                                                  f"{self.config.account.get_secret_value()}",
                                                  self.config.password.get_secret_value()))
                response.raise_for_status()
            except (httpx.HTTPError, httpx.ReadTimeout, httpx.ConnectError) as error:
                self.logger.trace(f"HTTP error encountered during GET {appdynamics_request.endpoint}: {error}")
                raise

        data = response.json()[0]

        readings = []

        for result_dict in zip(instance_count_readings, data["metricValues"]):
            self.logger.trace(
                f"Captured {result_dict[0]} at {result_dict[1]['startTimeInMillis']} for instance count"
            )

        metric_path = data["metricPath"]  # e.g. "Business Transaction Performance|Business Transactions|frontend-service|/payment|Calls per Minute"
        metric_name = data["metricName"]  # e.g. "BTM|BTs|BT:270723|Component:8435|Calls per Minute"


        for result_dict in zip(instance_count_readings, data["metricValues"]):

            data_points: List[servo.DataPoint] = [servo.DataPoint(
                metric, result_dict[1]['startTimeInMillis'], float(result_dict[0])
            )]

            readings.append(
                servo.TimeSeries(
                    metric,
                    data_points,
                    id=f"{{metric_path={metric_path}, metric_name={metric_name}}}",
                )
            )

        return readings


    async def _appd_node_response(
            self, individual_node: str, metric: AppdynamicsMetric, start: datetime, end: datetime
    ):
        """Queries AppDynamics for measurements either used directly or in aggregation when a dynamic node is being read
        that requires the metric endpoint to be substituted from the config. Substitutes the metric path with the
        individual nodes endpoint, as well as substitutes reading values of 0 when the response is empty from a metric
        that does always report (calls per minute) to synchronize timestamps and number of readings.

        Args:
            individual_node (str, required): The active node to be queried.
            metric (AppdynamicsMetric, required): The metric to query for.
            start (datetime, required): Metric start time.
            end (datetime, required). Metric end time.

        Returns:
            Readings: A list of TimeSeries with metric readings.
        """

        appdynamics_request = AppdynamicsRequest(
            base_url=self.config.api_url, metric=metric, start=start, end=end
        )

        metric_head = '|'.join(metric.query.split('|')[:-2])
        metric_tail = metric.query.split('|')[-1]
        metric_path_substitution = f"{metric_head}|{individual_node}|{metric_tail}"

        self.logger.trace(
            f"Querying AppDynamics (`{metric_path_substitution}`): {appdynamics_request.endpoint}"
        )

        params = appdynamics_request.params
        params.update({'metric-path': metric_path_substitution})

        async with httpx.AsyncClient(
                base_url=self.config.api_url,
                params=params,
        ) as client:
            try:
                response = await client.get(f"applications/{self.config.app_id}/metric-data",
                                            auth=(f"{self.config.username.get_secret_value()}@"
                                                  f"{self.config.account.get_secret_value()}",
                                                  self.config.password.get_secret_value()))
                response.raise_for_status()
            except (httpx.HTTPError, httpx.ReadTimeout, httpx.ConnectError) as error:
                self.logger.trace(f"HTTP error encountered during GET {appdynamics_request.endpoint}: {error}")
                raise

        node_data = response.json()[0]
        self.logger.trace(f"Got response data for metric {metric_path_substitution}: {node_data}")

        node_readings = []

        # If the metric data isn't consistently above 0, sometimes no data is returned
        # This requires a substitution with a working call to sync timestamps and number of readings
        # This function is only called for just-verified active nodes

        if not node_data["metricValues"]:

            # Calls per Minute is an always-reporting metric that is good to substitute
            metric_path_substitution = f"{metric_head}|{individual_node}|Calls per Minute"

            self.logger.trace(
                f"Metric {metric_tail} failed for individual node: {individual_node}, substituting for Calls per Minute"
            )

            params = appdynamics_request.params
            params.update({'metric-path': metric_path_substitution})

            async with httpx.AsyncClient(
                    base_url=self.config.api_url,
                    params=params,
            ) as client:
                try:
                    response = await client.get(f"applications/{self.config.app_id}/metric-data",
                                                auth=(f"{self.config.username.get_secret_value()}@"
                                                      f"{self.config.account.get_secret_value()}",
                                                      self.config.password.get_secret_value()))
                    response.raise_for_status()
                except (httpx.HTTPError, httpx.ReadTimeout, httpx.ConnectError) as error:
                    self.logger.trace(f"HTTP error encountered during GET {appdynamics_request.endpoint}: {error}")
                    raise

            node_data = response.json()[0]
            self.logger.trace(f"Got substitute data for {metric_tail} on node: {individual_node}")

            # Substitute in 0's for the actual metric values
            for result_dict in node_data["metricValues"]:
                data_points: List[servo.DataPoint] = [servo.DataPoint(
                    metric, result_dict['startTimeInMillis'], float(0)
                )]

                node_readings.append(
                    servo.TimeSeries(
                        metric,
                        data_points,
                    )
                )

        # Main capture logic

        for result_dict in node_data["metricValues"]:
            self.logger.trace(
                f"Captured {result_dict['value']} at {result_dict['startTimeInMillis']} for {metric_path_substitution}"
            )

        for result_dict in node_data["metricValues"]:

            data_points: List[servo.DataPoint] = [servo.DataPoint(
                metric, result_dict['startTimeInMillis'], float(result_dict['value'])
            )]

            node_readings.append(
                servo.TimeSeries(
                    metric,
                    data_points,
                )
            )

        return node_readings

    async def _query_appd_direct(
            self, metric: AppdynamicsMetric, start: datetime, end: datetime
    ) -> List[servo.TimeSeries]:
        """Queries AppDynamics for measurements that are taken from a metric exactly as defined in the config, e.g.
        from nodes that are not dynamic and remain consistent. Currently not utilized in the main/tuning workflow as
        both of these utilize a dynamic node naming.

        Args:
            metric (AppdynamicsMetric, required): The metric to query for.
            start (datetime, required): Metric start time.
            end (datetime, required). Metric end time.

        Returns:
            Readings: A list of TimeSeries with metric readings.
        """

        appdynamics_request = AppdynamicsRequest(
            base_url=self.config.api_url, metric=metric, start=start, end=end
        )

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

        for result_dict in data["metricValues"]:
            self.logger.trace(
                f"Captured {result_dict['value']} at {result_dict['startTimeInMillis']} for {metric}"
            )

        metric_path = data["metricPath"]  # e.g. "Business Transaction Performance|Business Transactions|frontend-service|/payment|Individual Nodes|frontend-tuning|Calls per Minute"
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
