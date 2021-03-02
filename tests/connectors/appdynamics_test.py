import pytest
import datetime
import re

import httpx
import respx
import freezegun
import pydantic

import servo
from servo.types import *
from servo.connectors.appdynamics import (
    AppdynamicsChecks,
    AppdynamicsConfiguration,
    AppdynamicsMetric,
    AppdynamicsRequest,
    AppdynamicsConnector
)

class TestAppdynamicsMetric:

    # Query
    def test_query_required(self):
        try:
            AppdynamicsMetric(
                name="throughput", unit=Unit.requests_per_minute, query=None
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
        return AppdynamicsConfiguration(metrics=[],
                                        username='user',
                                        password='pass',
                                        account='acc',
                                        app_id='app')

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
            base_url="http://appdynamics.com/some/path/",
            metrics=[],
            username='user',
            password='pass',
            account='acc',
            app_id='app'
        )
        assert config.base_url == "http://appdynamics.com/some/path"

    def test_supports_localhost_url(self):
        config = AppdynamicsConfiguration(base_url="http://localhost:8090",
                                          metrics=[],
                                          username='user',
                                          password='pass',
                                          account='acc',
                                          app_id='app')
        assert config.base_url == "http://localhost:8090"

    def test_supports_cluster_url(self):
        config = AppdynamicsConfiguration(
            base_url="http://appdynamics.com:8090",
            metrics=[],
            username='user',
            password='pass',
            account='acc',
            app_id='app'
        )
        assert config.base_url == "http://appdynamics.com:8090"

    def test_rejects_invalid_url(self):
        try:
            AppdynamicsConfiguration(base_url="gopher://this-is-invalid",
                                     metrics=[],
                                     username='user',
                                     password='pass',
                                     account='acc',
                                     app_id='app')
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
            base_url="http://appdynamics.com:8090",
            metrics=[],
            username='user',
            password='pass',
            account='acc',
            app_id='app'
        )
        assert (
            config.api_url == "http://appdynamics.com:8090/controller/rest/"
        )

    # Metrics
    def test_metrics_required(self):
        try:
            AppdynamicsConfiguration(metrics=None,
                                     username='user',
                                     password='pass',
                                     account='acc',
                                     app_id='app')
        except pydantic.ValidationError as error:
            assert {
                "loc": ("metrics",),
                "msg": "none is not an allowed value",
                       "type": "type_error.none.not_allowed",
            } in error.errors()


class TestAppdynamicsRequest:
    @freezegun.freeze_time("2020-01-01")
    def test_url(self):
        request = AppdynamicsRequest(
            base_url="http://appdynamics.com",
            start=datetime.datetime.now(),
            end=datetime.datetime.now() + Duration("36h"),
            metric=AppdynamicsMetric(
                "throughput",
                servo.Unit.requests_per_minute,
                query='Overall Application Performance|Calls per Minute',
            ),
        )
        assert (
            request.endpoint
            == '?metric-path=Overall Application Performance|Calls per Minute&time-range-type=BETWEEN_TIMES&start-time=1577836800000&end-time=1577966400000&rollup=false&output=JSON'
        )


overall_application_performance_throughput = [{
    'frequency': 'ONE_MIN',
    'metricId': 11318904,
    'metricName': 'BTM|Application Summary|Calls per Minute',
    'metricPath': 'Overall Application Performance|Calls per Minute',
    'metricValues': [{'count': 5,
                      'current': 2098,
                      'max': 1119,
                      'min': 12,
                      'occurrences': 1,
                      'standardDeviation': 0,
                      'startTimeInMillis': 1614647040000,
                      'sum': 2098,
                      'useRange': False,
                      'value': 2098},
                     {'count': 5,
                      'current': 1249,
                      'max': 615,
                      'min': 12,
                      'occurrences': 1,
                      'standardDeviation': 0,
                      'startTimeInMillis': 1614647100000,
                      'sum': 1249,
                      'useRange': False,
                      'value': 1249},
                     {'count': 5,
                      'current': 1659,
                      'max': 959,
                      'min': 12,
                      'occurrences': 1,
                      'standardDeviation': 0,
                      'startTimeInMillis': 1614647160000,
                      'sum': 1659,
                      'useRange': False,
                      'value': 1659},
                     {'count': 5,
                      'current': 1696,
                      'max': 861,
                      'min': 12,
                      'occurrences': 1,
                      'standardDeviation': 0,
                      'startTimeInMillis': 1614647220000,
                      'sum': 1696,
                      'useRange': False,
                      'value': 1696},
                     {'count': 5,
                      'current': 2549,
                      'max': 1315,
                      'min': 12,
                      'occurrences': 1,
                      'standardDeviation': 0,
                      'startTimeInMillis': 1614647280000,
                      'sum': 2549,
                      'useRange': False,
                      'value': 2549},
                     {'count': 5,
                      'current': 2474,
                      'max': 1380,
                      'min': 12,
                      'occurrences': 1,
                      'standardDeviation': 0,
                      'startTimeInMillis': 1614647340000,
                      'sum': 2474,
                      'useRange': False,
                      'value': 2474},
                     {'count': 5,
                      'current': 1603,
                      'max': 792,
                      'min': 12,
                      'occurrences': 1,
                      'standardDeviation': 0,
                      'startTimeInMillis': 1614647400000,
                      'sum': 1603,
                      'useRange': False,
                      'value': 1603},
                     {'count': 5,
                      'current': 1909,
                      'max': 1103,
                      'min': 12,
                      'occurrences': 1,
                      'standardDeviation': 0,
                      'startTimeInMillis': 1614647460000,
                      'sum': 1909,
                      'useRange': False,
                      'value': 1909},
                     {'count': 5,
                      'current': 2241,
                      'max': 1270,
                      'min': 12,
                      'occurrences': 1,
                      'standardDeviation': 0,
                      'startTimeInMillis': 1614647520000,
                      'sum': 2241,
                      'useRange': False,
                      'value': 2241},
                     {'count': 5,
                      'current': 2665,
                      'max': 1491,
                      'min': 12,
                      'occurrences': 1,
                      'standardDeviation': 0,
                      'startTimeInMillis': 1614647580000,
                      'sum': 2665,
                      'useRange': False,
                      'value': 2665}]
}]


class TestAppdynamicsChecks:

    @pytest.fixture
    def metric(self) -> AppdynamicsMetric:
        return AppdynamicsMetric(
            name="throughput",
            unit=Unit.requests_per_minute,
            query='Overall Application Performance|Calls per Minute',
        )

    @pytest.fixture
    def overall_application_performance_throughput(self) -> List[dict]:
        return [{
            'frequency': 'ONE_MIN',
            'metricId': 11318904,
            'metricName': 'BTM|Application Summary|Calls per Minute',
            'metricPath': 'Overall Application Performance|Calls per Minute',
            'metricValues': [{'count': 5,
                              'current': 2098,
                              'max': 1119,
                              'min': 12,
                              'occurrences': 1,
                              'standardDeviation': 0,
                              'startTimeInMillis': 1614647040000,
                              'sum': 2098,
                              'useRange': False,
                              'value': 2098},
                             {'count': 5,
                              'current': 1249,
                              'max': 615,
                              'min': 12,
                              'occurrences': 1,
                              'standardDeviation': 0,
                              'startTimeInMillis': 1614647100000,
                              'sum': 1249,
                              'useRange': False,
                              'value': 1249},
                             {'count': 5,
                              'current': 1659,
                              'max': 959,
                              'min': 12,
                              'occurrences': 1,
                              'standardDeviation': 0,
                              'startTimeInMillis': 1614647160000,
                              'sum': 1659,
                              'useRange': False,
                              'value': 1659},
                             {'count': 5,
                              'current': 1696,
                              'max': 861,
                              'min': 12,
                              'occurrences': 1,
                              'standardDeviation': 0,
                              'startTimeInMillis': 1614647220000,
                              'sum': 1696,
                              'useRange': False,
                              'value': 1696},
                             {'count': 5,
                              'current': 2549,
                              'max': 1315,
                              'min': 12,
                              'occurrences': 1,
                              'standardDeviation': 0,
                              'startTimeInMillis': 1614647280000,
                              'sum': 2549,
                              'useRange': False,
                              'value': 2549},
                             {'count': 5,
                              'current': 2474,
                              'max': 1380,
                              'min': 12,
                              'occurrences': 1,
                              'standardDeviation': 0,
                              'startTimeInMillis': 1614647340000,
                              'sum': 2474,
                              'useRange': False,
                              'value': 2474},
                             {'count': 5,
                              'current': 1603,
                              'max': 792,
                              'min': 12,
                              'occurrences': 1,
                              'standardDeviation': 0,
                              'startTimeInMillis': 1614647400000,
                              'sum': 1603,
                              'useRange': False,
                              'value': 1603},
                             {'count': 5,
                              'current': 1909,
                              'max': 1103,
                              'min': 12,
                              'occurrences': 1,
                              'standardDeviation': 0,
                              'startTimeInMillis': 1614647460000,
                              'sum': 1909,
                              'useRange': False,
                              'value': 1909},
                             {'count': 5,
                              'current': 2241,
                              'max': 1270,
                              'min': 12,
                              'occurrences': 1,
                              'standardDeviation': 0,
                              'startTimeInMillis': 1614647520000,
                              'sum': 2241,
                              'useRange': False,
                              'value': 2241},
                             {'count': 5,
                              'current': 2665,
                              'max': 1491,
                              'min': 12,
                              'occurrences': 1,
                              'standardDeviation': 0,
                              'startTimeInMillis': 1614647580000,
                              'sum': 2665,
                              'useRange': False,
                              'value': 2665}]
        }]

    @pytest.fixture
    def mocked_api(self, overall_application_performance_throughput):
        with respx.mock(
                base_url="http://localhost:8090", assert_all_called=False
        ) as respx_mock:
            respx_mock.get(
                re.compile(r"/controller/rest/.+"),
                name="query"
            ).mock(httpx.Response(200, json=overall_application_performance_throughput))
            yield respx_mock

    @pytest.fixture
    def checks(self, metric) -> AppdynamicsChecks:
        config = AppdynamicsConfiguration(
            base_url="http://localhost:8090",
            metrics=[metric],
            username='user',
            password='pass',
            account='acc',
            app_id='app'
        )
        return AppdynamicsChecks(config=config)

    @respx.mock
    async def test_check_queries(self, mocked_api, checks) -> None:
        request = mocked_api["query"]
        multichecks = await checks._expand_multichecks()
        check = await multichecks[0]()
        assert request.called
        assert check
        assert check.name == r'Run query "Overall Application Performance|Calls per Minute"'
        assert check.id == "check_queries_item_0"
        assert not check.critical
        assert check.success
        assert check.message == "returned 5 results"


class TestAppdynamicsConnector:

    @pytest.fixture
    def metric(self) -> AppdynamicsMetric:
        return AppdynamicsMetric(
            name="test",
            unit=Unit.requests_per_minute,
            query='Overall Application Performance|Calls per Minute',
        )

    @pytest.fixture
    def overall_application_performance_throughput(self) -> List[dict]:
        return [{
            'frequency': 'ONE_MIN',
            'metricId': 11318904,
            'metricName': 'BTM|Application Summary|Calls per Minute',
            'metricPath': 'Overall Application Performance|Calls per Minute',
            'metricValues': [{'count': 5,
                              'current': 2098,
                              'max': 1119,
                              'min': 12,
                              'occurrences': 1,
                              'standardDeviation': 0,
                              'startTimeInMillis': 1614647040000,
                              'sum': 2098,
                              'useRange': False,
                              'value': 2098},
                             {'count': 5,
                              'current': 1249,
                              'max': 615,
                              'min': 12,
                              'occurrences': 1,
                              'standardDeviation': 0,
                              'startTimeInMillis': 1614647100000,
                              'sum': 1249,
                              'useRange': False,
                              'value': 1249},
                             {'count': 5,
                              'current': 1659,
                              'max': 959,
                              'min': 12,
                              'occurrences': 1,
                              'standardDeviation': 0,
                              'startTimeInMillis': 1614647160000,
                              'sum': 1659,
                              'useRange': False,
                              'value': 1659},
                             {'count': 5,
                              'current': 1696,
                              'max': 861,
                              'min': 12,
                              'occurrences': 1,
                              'standardDeviation': 0,
                              'startTimeInMillis': 1614647220000,
                              'sum': 1696,
                              'useRange': False,
                              'value': 1696},
                             {'count': 5,
                              'current': 2549,
                              'max': 1315,
                              'min': 12,
                              'occurrences': 1,
                              'standardDeviation': 0,
                              'startTimeInMillis': 1614647280000,
                              'sum': 2549,
                              'useRange': False,
                              'value': 2549},
                             {'count': 5,
                              'current': 2474,
                              'max': 1380,
                              'min': 12,
                              'occurrences': 1,
                              'standardDeviation': 0,
                              'startTimeInMillis': 1614647340000,
                              'sum': 2474,
                              'useRange': False,
                              'value': 2474},
                             {'count': 5,
                              'current': 1603,
                              'max': 792,
                              'min': 12,
                              'occurrences': 1,
                              'standardDeviation': 0,
                              'startTimeInMillis': 1614647400000,
                              'sum': 1603,
                              'useRange': False,
                              'value': 1603},
                             {'count': 5,
                              'current': 1909,
                              'max': 1103,
                              'min': 12,
                              'occurrences': 1,
                              'standardDeviation': 0,
                              'startTimeInMillis': 1614647460000,
                              'sum': 1909,
                              'useRange': False,
                              'value': 1909},
                             {'count': 5,
                              'current': 2241,
                              'max': 1270,
                              'min': 12,
                              'occurrences': 1,
                              'standardDeviation': 0,
                              'startTimeInMillis': 1614647520000,
                              'sum': 2241,
                              'useRange': False,
                              'value': 2241},
                             {'count': 5,
                              'current': 2665,
                              'max': 1491,
                              'min': 12,
                              'occurrences': 1,
                              'standardDeviation': 0,
                              'startTimeInMillis': 1614647580000,
                              'sum': 2665,
                              'useRange': False,
                              'value': 2665}]
        }]

    @pytest.fixture
    def mocked_api(self, overall_application_performance_throughput):
        with respx.mock(
            base_url="http://localhost:8090", assert_all_called=False
        ) as respx_mock:
            respx_mock.get(
                re.compile(r"/controller/rest/.+"),
                name="query",
            ).mock(httpx.Response(200, json=overall_application_performance_throughput))
            yield respx_mock

    @pytest.fixture
    def connector(self, metric) -> AppdynamicsConnector:
        config = AppdynamicsConfiguration(
            base_url="http://localhost:8090",
            metrics=[metric],
            username='user',
            password='pass',
            account='acc',
            app_id='app'
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
        print(measurements.readings[0].data_points[0][1])
        assert measurements.readings[0].data_points[0][1] == overall_application_performance_throughput[0]["metricValues"][0]["value"]
