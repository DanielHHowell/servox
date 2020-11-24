import datetime
import re

import httpx
import pytest
import respx
import freezegun
import pydantic

from servo.connectors.appdynamics import AppdynamicsChecks, AppdynamicsConfiguration, AppdynamicsMetric, AppdynamicsRequest, AppdynamicsConnector
from servo.types import *


class TestAppdynamicsMetric:

    # Query
    def test_query_required(self):
        try:
            AppdynamicsMetric(
                name="throughput", unit=Unit.REQUESTS_PER_MINUTE, query=None
            )
        except pydantic.ValidationError as error:
            assert {
                "loc": ("query",),
                "msg": "none is not an allowed value",
                       "type": "type_error.none.not_allowed",
            } in error.errors()


class TestAppdynamicsConfiguration:

    @pytest.fixture()
    def appdynamics_config(self) -> AppdynamicsConfiguration:
        return AppdynamicsConfiguration(base_url="http://localhost:8090", metrics=[], api_key="abcd12345")

    def test_url_required(self, appdynamics_config):
        try:
            appdynamics_config
        except pydantic.ValidationError as error:
            assert {
                "loc": ("base_url",),
                "msg": "none is not an allowed value",
                       "type": "type_error.none.not_allowed",
            } in error.errors()

    def test_base_url_is_rstripped(self):
        config = AppdynamicsConfiguration(
            base_url="http://appdynamics.com/some/path/", metrics=[], api_key="abcd12345"
        )
        assert config.base_url == "http://appdynamics.com/some/path"

    def test_supports_localhost_url(self):
        config = AppdynamicsConfiguration(base_url="http://localhost:8090", metrics=[], api_key="abcd12345")
        assert config.base_url == "http://localhost:8090"

    def test_supports_cluster_url(self):
        config = AppdynamicsConfiguration(
            base_url="http://appdynamics.com:8090", metrics=[], api_key="abcd12345"
        )
        assert config.base_url == "http://appdynamics.com:8090"

    def test_rejects_invalid_url(self):
        try:
            AppdynamicsConfiguration(base_url="gopher://this-is-invalid", api_key="abcd12345")
        except pydantic.ValidationError as error:
            assert {
                "loc": ("base_url",),
                "msg": "URL scheme not permitted",
                       "type": "value_error.url.scheme",
                       "ctx": {
                           "allowed_schemes": {
                               "http",
                               "https",
                           },
                },
            } in error.errors()

    def test_api_url(self):
        config = AppdynamicsConfiguration(
            base_url="http://appdynamics.com:8090", metrics=[], api_key='abc12345', app_id='demo-app'
        )
        assert (
            config.api_url == "http://appdynamics.com:8090/controller/rest/"
        )

    # Metrics
    def test_metrics_required(self):
        try:
            AppdynamicsConfiguration(metrics=None, api_key='abc12345', app_id='demo-app')
        except pydantic.ValidationError as error:
            assert {
                "loc": ("metrics",),
                "msg": "none is not an allowed value",
                       "type": "type_error.none.not_allowed",
            } in error.errors()

    # Generation
    def test_generate_default_config(self):
        config = AppdynamicsConfiguration.generate()
        assert config.yaml() == (
            "description: Update the api_key, base_url and metrics to match your Appdynamics configuration\n"
            "api_key: '**********'\n"
            "app_id: demo-app\n"
            "base_url: http://appdynamics.com:8090\n"
            "metrics:\n"
            "- name: throughput\n"
            "  unit: rpm\n"
            "  query: avg(ts(appdynamics.apm.overall.calls_per_min, env=foo and app=my-app))\n"
            "  granularity: m\n"
            "  summarized_by: LAST\n"
            "- name: error_rate\n"
            "  unit: count\n"
            "  query: avg(ts(appdynamics.apm.transactions.errors_per_min, env=foo and app=my-app))\n"
            "  granularity: m\n"
            "  summarized_by: LAST\n"
        )


class TestAppdynamicsRequest:
    @freezegun.freeze_time("2020-01-01")
    def test_url(self):
        request = AppdynamicsRequest(
            base_url="http://appdynamics.com:8090",
            start=datetime.datetime.now(),
            end=datetime.datetime.now() + Duration("36h"),
            metric=AppdynamicsMetric(
                "throughput",
                servo.Unit.REQUESTS_PER_MINUTE,
                query='rate(ts("heapster.node.network.tx", cluster="idps-preprod-west2.cluster.k8s.local"))',
            ),
        )
        assert (
            request.endpoint
            == 'metric-path=rate(ts("heapster.node.network.tx", cluster="idps-preprod-west2.cluster.k8s.local"))&time-range-type=BETWEEN_TIMESstart-time=1577836800.0&end-time=1577966400.0'
        )


heapster_node_network_tx = {
    'granularity': 60,
    'name': 'rate(ts("heapster.node.network.tx", '
            'cluster="idps-preprod-west2.cluster.k8s.local"))',
    'query': 'rate(ts("heapster.node.network.tx", '
             'cluster="idps-preprod-west2.cluster.k8s.local"))',
    'stats': {'buffer_keys': 154,
              'cached_compacted_keys': 0,
              'compacted_keys': 24,
              'compacted_points': 12440,
              'cpu_ns': 36609718,
              'distributions': 0,
              'dropped_distributions': 0,
              'dropped_edges': 0,
              'dropped_metrics': 0,
              'dropped_spans': 0,
              'edges': 0,
              'keys': 168,
              'latency': 11,
              'metrics': 12584,
              'points': 12584,
              'queries': 108,
              'query_tasks': 0,
              's3_keys': 0,
              'skipped_compacted_keys': 22,
              'spans': 0,
              'summaries': 12584},
    'timeseries': [
        {'data': [[1604626020, 68441.23333333334],
                  [1604626080, 75125.6],
                  [1604626140, 59805.666666666664]],
         'host': 'ip-10-131-115-108.us-west-2.compute.internal',
         'label': 'heapster.node.network.tx',
         'tags': {'cluster': 'idps-preprod-west2.cluster.k8s.local',
                  'label.beta.kubernetes.io/arch': 'amd64',
                  'label.beta.kubernetes.io/instance-type': 'm5.2xlarge',
                  'label.beta.kubernetes.io/os': 'linux',
                  'label.failure-domain.beta.kubernetes.io/region': 'us-west-2',
                  'label.failure-domain.beta.kubernetes.io/zone': 'us-west-2b',
                  'label.kops.k8s.io/instancegroup': 'iks-system',
                  'label.kubernetes.io/arch': 'amd64',
                  'label.kubernetes.io/hostname': 'ip-10-131-115-108.us-west-2.compute.internal',
                  'label.kubernetes.io/os': 'linux',
                  'label.kubernetes.io/role': 'node',
                  'label.node.kubernetes.io/instance-type': 'm5.2xlarge',
                  'label.topology.kubernetes.io/region': 'us-west-2',
                  'label.topology.kubernetes.io/zone': 'us-west-2b',
                  'nodename': 'ip-10-131-115-108.us-west-2.compute.internal',
                  'type': 'node'}},
        {'data': [[1604626020, 33849.583333333336],
                  [1604626080, 48680.51666666667],
                  [1604626140, 34244.1]],
         'host': 'ip-10-131-115-88.us-west-2.compute.internal',
         'label': 'heapster.node.network.tx',
         'tags': {'cluster': 'idps-preprod-west2.cluster.k8s.local',
                  'label.beta.kubernetes.io/arch': 'amd64',
                  'label.beta.kubernetes.io/instance-type': 'm5.2xlarge',
                  'label.beta.kubernetes.io/os': 'linux',
                  'label.failure-domain.beta.kubernetes.io/region': 'us-west-2',
                  'label.failure-domain.beta.kubernetes.io/zone': 'us-west-2b',
                  'label.kops.k8s.io/instancegroup': 'iks-system',
                  'label.kubernetes.io/arch': 'amd64',
                  'label.kubernetes.io/hostname': 'ip-10-131-115-88.us-west-2.compute.internal',
                  'label.kubernetes.io/os': 'linux',
                  'label.kubernetes.io/role': 'node',
                  'label.node.kubernetes.io/instance-type': 'm5.2xlarge',
                  'label.topology.kubernetes.io/region': 'us-west-2',
                  'label.topology.kubernetes.io/zone': 'us-west-2b',
                  'nodename': 'ip-10-131-115-88.us-west-2.compute.internal',
                  'type': 'node'}}],
    'traceDimensions': []
}


class TestAppdynamicsChecks:

    @pytest.fixture
    def metric(self) -> AppdynamicsMetric:
        return AppdynamicsMetric(
            name="test",
            unit=Unit.REQUESTS_PER_MINUTE,
            query='rate(ts("heapster.node.network.tx", cluster="idps-preprod-west2.cluster.k8s.local"))',
        )

    @pytest.fixture
    def heapster_node_network_tx(self) -> dict:
        return {
            'granularity': 60,
            'name': 'rate(ts("heapster.node.network.tx", '
                    'cluster="idps-preprod-west2.cluster.k8s.local"))',
            'query': 'rate(ts("heapster.node.network.tx", '
                     'cluster="idps-preprod-west2.cluster.k8s.local"))',
            'stats': {'buffer_keys': 154,
                      'cached_compacted_keys': 0,
                      'compacted_keys': 24,
                      'compacted_points': 12440,
                      'cpu_ns': 36609718,
                      'distributions': 0,
                      'dropped_distributions': 0,
                      'dropped_edges': 0,
                      'dropped_metrics': 0,
                      'dropped_spans': 0,
                      'edges': 0,
                      'keys': 168,
                      'latency': 11,
                      'metrics': 12584,
                      'points': 12584,
                      'queries': 108,
                      'query_tasks': 0,
                      's3_keys': 0,
                      'skipped_compacted_keys': 22,
                      'spans': 0,
                      'summaries': 12584},
            'timeseries': [
                {'data': [[1604626020, 68441.23333333334],
                          [1604626080, 75125.6],
                          [1604626140, 59805.666666666664]],
                 'host': 'ip-10-131-115-108.us-west-2.compute.internal',
                 'label': 'heapster.node.network.tx',
                 'tags': {'cluster': 'idps-preprod-west2.cluster.k8s.local',
                          'label.beta.kubernetes.io/arch': 'amd64',
                          'label.beta.kubernetes.io/instance-type': 'm5.2xlarge',
                          'label.beta.kubernetes.io/os': 'linux',
                          'label.failure-domain.beta.kubernetes.io/region': 'us-west-2',
                          'label.failure-domain.beta.kubernetes.io/zone': 'us-west-2b',
                          'label.kops.k8s.io/instancegroup': 'iks-system',
                          'label.kubernetes.io/arch': 'amd64',
                          'label.kubernetes.io/hostname': 'ip-10-131-115-108.us-west-2.compute.internal',
                          'label.kubernetes.io/os': 'linux',
                          'label.kubernetes.io/role': 'node',
                          'label.node.kubernetes.io/instance-type': 'm5.2xlarge',
                          'label.topology.kubernetes.io/region': 'us-west-2',
                          'label.topology.kubernetes.io/zone': 'us-west-2b',
                          'nodename': 'ip-10-131-115-108.us-west-2.compute.internal',
                          'type': 'node'}},
                {'data': [[1604626020, 33849.583333333336],
                          [1604626080, 48680.51666666667],
                          [1604626140, 34244.1]],
                 'host': 'ip-10-131-115-88.us-west-2.compute.internal',
                 'label': 'heapster.node.network.tx',
                 'tags': {'cluster': 'idps-preprod-west2.cluster.k8s.local',
                          'label.beta.kubernetes.io/arch': 'amd64',
                          'label.beta.kubernetes.io/instance-type': 'm5.2xlarge',
                          'label.beta.kubernetes.io/os': 'linux',
                          'label.failure-domain.beta.kubernetes.io/region': 'us-west-2',
                          'label.failure-domain.beta.kubernetes.io/zone': 'us-west-2b',
                          'label.kops.k8s.io/instancegroup': 'iks-system',
                          'label.kubernetes.io/arch': 'amd64',
                          'label.kubernetes.io/hostname': 'ip-10-131-115-88.us-west-2.compute.internal',
                          'label.kubernetes.io/os': 'linux',
                          'label.kubernetes.io/role': 'node',
                          'label.node.kubernetes.io/instance-type': 'm5.2xlarge',
                          'label.topology.kubernetes.io/region': 'us-west-2',
                          'label.topology.kubernetes.io/zone': 'us-west-2b',
                          'nodename': 'ip-10-131-115-88.us-west-2.compute.internal',
                          'type': 'node'}}],
            'traceDimensions': []
        }

    @pytest.fixture
    def mocked_api(self, heapster_node_network_tx):
        with respx.mock(
                base_url="http://localhost:8090", assert_all_called=False
        ) as respx_mock:
            respx_mock.get(
                re.compile(r"/controller/rest/.+"),
                name="query"
            ).mock(httpx.Response(200, json=heapster_node_network_tx))
            yield respx_mock

    @pytest.fixture
    def checks(self, metric) -> AppdynamicsChecks:
        config = AppdynamicsConfiguration(
            base_url="http://localhost:8090", metrics=[metric], api_key='abc12345'
        )
        return AppdynamicsChecks(config=config)

    @respx.mock
    async def test_check_queries(self, mocked_api, checks) -> None:
        request = mocked_api["query"]
        multichecks = await checks._expand_multichecks()
        check = await multichecks[0]()
        assert request.called
        assert check
        assert check.name == r'Run query "rate(ts("heapster.node.network.tx", cluster="idps-preprod-west2.cluster.k8s.local"))"'
        assert check.id == "check_queries_item_0"
        assert not check.critical
        assert check.success
        assert check.message == "returned 2 results"


class TestAppdynamicsConnector:

    @pytest.fixture
    def metric(self) -> AppdynamicsMetric:
        return AppdynamicsMetric(
            name="test",
            unit=Unit.REQUESTS_PER_MINUTE,
            query='rate(ts("heapster.node.network.tx", cluster="idps-preprod-west2.cluster.k8s.local"))',
        )

    @pytest.fixture
    def heapster_node_network_tx(self) -> dict:
        return {
            'granularity': 60,
            'name': 'rate(ts("heapster.node.network.tx", '
                    'cluster="idps-preprod-west2.cluster.k8s.local"))',
            'query': 'rate(ts("heapster.node.network.tx", '
                     'cluster="idps-preprod-west2.cluster.k8s.local"))',
            'stats': {'buffer_keys': 154,
                      'cached_compacted_keys': 0,
                      'compacted_keys': 24,
                      'compacted_points': 12440,
                      'cpu_ns': 36609718,
                      'distributions': 0,
                      'dropped_distributions': 0,
                      'dropped_edges': 0,
                      'dropped_metrics': 0,
                      'dropped_spans': 0,
                      'edges': 0,
                      'keys': 168,
                      'latency': 11,
                      'metrics': 12584,
                      'points': 12584,
                      'queries': 108,
                      'query_tasks': 0,
                      's3_keys': 0,
                      'skipped_compacted_keys': 22,
                      'spans': 0,
                      'summaries': 12584},
            'timeseries': [
                {'data': [[1604626020, 68441.23333333334],
                          [1604626080, 75125.6],
                          [1604626140, 59805.666666666664]],
                 'host': 'ip-10-131-115-108.us-west-2.compute.internal',
                 'label': 'heapster.node.network.tx',
                 'tags': {'cluster': 'idps-preprod-west2.cluster.k8s.local',
                          'label.beta.kubernetes.io/arch': 'amd64',
                          'label.beta.kubernetes.io/instance-type': 'm5.2xlarge',
                          'label.beta.kubernetes.io/os': 'linux',
                          'label.failure-domain.beta.kubernetes.io/region': 'us-west-2',
                          'label.failure-domain.beta.kubernetes.io/zone': 'us-west-2b',
                          'label.kops.k8s.io/instancegroup': 'iks-system',
                          'label.kubernetes.io/arch': 'amd64',
                          'label.kubernetes.io/hostname': 'ip-10-131-115-108.us-west-2.compute.internal',
                          'label.kubernetes.io/os': 'linux',
                          'label.kubernetes.io/role': 'node',
                          'label.node.kubernetes.io/instance-type': 'm5.2xlarge',
                          'label.topology.kubernetes.io/region': 'us-west-2',
                          'label.topology.kubernetes.io/zone': 'us-west-2b',
                          'nodename': 'ip-10-131-115-108.us-west-2.compute.internal',
                          'type': 'node'}},
                {'data': [[1604626020, 33849.583333333336],
                          [1604626080, 48680.51666666667],
                          [1604626140, 34244.1]],
                 'host': 'ip-10-131-115-88.us-west-2.compute.internal',
                 'label': 'heapster.node.network.tx',
                 'tags': {'cluster': 'idps-preprod-west2.cluster.k8s.local',
                          'label.beta.kubernetes.io/arch': 'amd64',
                          'label.beta.kubernetes.io/instance-type': 'm5.2xlarge',
                          'label.beta.kubernetes.io/os': 'linux',
                          'label.failure-domain.beta.kubernetes.io/region': 'us-west-2',
                          'label.failure-domain.beta.kubernetes.io/zone': 'us-west-2b',
                          'label.kops.k8s.io/instancegroup': 'iks-system',
                          'label.kubernetes.io/arch': 'amd64',
                          'label.kubernetes.io/hostname': 'ip-10-131-115-88.us-west-2.compute.internal',
                          'label.kubernetes.io/os': 'linux',
                          'label.kubernetes.io/role': 'node',
                          'label.node.kubernetes.io/instance-type': 'm5.2xlarge',
                          'label.topology.kubernetes.io/region': 'us-west-2',
                          'label.topology.kubernetes.io/zone': 'us-west-2b',
                          'nodename': 'ip-10-131-115-88.us-west-2.compute.internal',
                          'type': 'node'}}],
            'traceDimensions': []
        }

    @pytest.fixture
    def mocked_api(self, heapster_node_network_tx):
        with respx.mock(
            base_url="http://localhost:8090", assert_all_called=False
        ) as respx_mock:
            respx_mock.get(
                re.compile(r"/api/v2/.+"),
                name="query",
            ).mock(httpx.Response(200, json=heapster_node_network_tx))
            yield respx_mock

    @pytest.fixture
    def connector(self, metric) -> AppdynamicsConnector:
        config = AppdynamicsConfiguration(
            base_url="http://localhost:8090", metrics=[metric], api_key='abc12345'
        )
        return AppdynamicsConnector(config=config)

    async def test_describe(self, connector) -> None:
        described = connector.describe()
        assert described.metrics == connector.metrics()

    @respx.mock
    async def test_measure(self, mocked_api, connector) -> None:
        request = mocked_api["query"]
        measurements = await connector.measure()
        assert request.called
        # Assert float values are the same (for first entry from first reading)
        assert measurements.readings[0].values[0][1] == heapster_node_network_tx["timeseries"][0]["data"][0][1]
