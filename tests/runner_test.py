import asyncio
import pathlib

import pytest

import servo
import servo.connectors.prometheus
import tests


pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest.fixture()
def assembly(servo_yaml: pathlib.Path) -> servo.assembly.Assembly:
    config_model = servo.assembly._create_config_model_from_routes(
        {
            "prometheus": servo.connectors.prometheus.PrometheusConnector,
            "adjust": tests.test_helpers.AdjustConnector,
        }
    )
    config = config_model.generate()
    servo_yaml.write_text(config.yaml())

    optimizer = servo.configuration.Optimizer(
        id="dev.opsani.com/blake-ignite",
        token="bfcf94a6e302222eed3c73a5594badcfd53fef4b6d6a703ed32604",
    )
    assembly_ = servo.assembly.Assembly.assemble(
        config_file=servo_yaml, optimizer=optimizer
    )
    return assembly_


@pytest.fixture
def runner(assembly) -> servo.runner.AssemblyRunner:
    return servo.runner.AssemblyRunner(assembly)


async def test_test_out_of_order_operations(runner) -> None:
    await runner.servo.startup()
    response = await runner._post_event(
        servo.api.Event.HELLO, dict(agent=servo.api.USER_AGENT)
    )
    debug(response)
    assert response.status == "ok"

    response = await runner._post_event(servo.api.Event.WHATS_NEXT, None)
    debug(response)
    assert response.command == servo.api.Command.DESCRIBE

    description = await runner.describe()

    param = dict(descriptor=description.__opsani_repr__(), status="ok")
    debug(param)
    response = await runner._post_event(servo.api.Event.DESCRIPTION, param)
    debug(response)

    response = await runner._post_event(servo.api.Event.WHATS_NEXT, None)
    debug(response)
    assert response.command == servo.api.Command.MEASURE

    # Send out of order adjust
    reply = {"status": "ok"}
    response = await runner._post_event(servo.api.Event.ADJUSTMENT, reply)
    debug(response)

    assert response.status == "unexpected-event"
    assert (
        response.reason
        == 'Out of order event "ADJUSTMENT", expected "MEASUREMENT"; ignoring'
    )

    runner.logger.info("test logging", operation="ADJUST", progress=55)

    await asyncio.sleep(5)


async def test_hello(runner) -> None:
    response = await runner._post_event(
        servo.api.Event.HELLO, dict(agent=servo.api.USER_AGENT)
    )
    assert response.status == "ok"


# async def test_describe() -> None:
#     pass

# async def test_measure() -> None:
#     pass

# async def test_adjust() -> None:
#     pass

# async def test_whats_next() -> None:
#     pass

# async def test_sleep() -> None:
#     pass

# async def test_goodbye() -> None:
#     pass
# @pytest.mark.integration
# @pytest.mark.parametrize(
#     ("proxies"),
#     [
#         "http://localhost:1234",
#         {"all://": "http://localhost:1234"},
#         {"https://": "http://localhost:1234"},
#         {"https://api.opsani.com": "http://localhost:1234"},
#         {"https://*.opsani.com": "http://localhost:1234"},
#     ]
# )
# async def test_proxies_support() -> None:
#     ...
#     # fire up runner.run and check .run, etc.


# TODO: This doesn't need to be integration test
#
async def test_adjustment_rejected(mocker, runner) -> None:
    connector = runner.servo.get_connector("adjust")
    with servo.utilities.pydantic.extra(connector):
        on_handler = connector.get_event_handlers("adjust", servo.events.Preposition.ON)[0]
        mock = mocker.patch.object(on_handler, "handler")
        mock.side_effect = servo.errors.AdjustmentRejectedError()
        await runner.servo.startup()
        with pytest.raises(servo.errors.AdjustmentRejectedError):
            await runner.adjust([], servo.Control())
