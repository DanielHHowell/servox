import asyncio
import pathlib
from typing import List, Optional

import httpx
import pytest
import statesman
import typer
import typer.testing


import servo
import servo.connectors.emulator
import tests.fake
    
@pytest.fixture
def fastapi_app() -> tests.fake.OpsaniAPI:
    return tests.fake.api

async def test_list(fakeapi_client: httpx.AsyncClient) -> None:
    response = await fakeapi_client.get("/")
    response.raise_for_status()
    
    servo.logger.info(f"Loaded data: {response.text}\n")
    assert response.status_code == 200

async def test_describe() -> None:
    connector = servo.connectors.emulator.EmulatorConnector(config=servo.BaseConfiguration())
    debug(connector)
    response = await connector.describe()
    debug(response)

async def test_metrics() -> None:
    ...

async def test_components() -> None:
    ...

async def test_measure() -> None:
    ...

async def test_adjust() -> None:
    ...

async def test_optimization(
    servo_runner: servo.runner.ServoRunner,
    fakeapi_url: str,
    fastapi_app: tests.fake.OpsaniAPI,
    event_loop: asyncio.AbstractEventLoop, 
) -> None:
    optimizer = tests.fake.SequencedOptimizer(
        id='dev.opsani.com/big-in-japan', 
        token='31337', 
        state=tests.fake.StateMachine.States.awaiting_description
    )
    fastapi_app.optimizer = optimizer
    servo_runner.servo.optimizer.base_url = fakeapi_url
    
    metric = servo.Metric(
        name="Some Metric",
        unit=servo.Unit.REQUESTS_PER_MINUTE,                        
    )
    adjustment = servo.Adjustment(component_name="web", setting_name="cpu", value=1.25)
    
    optimizer.sequence(
        optimizer.request_description(),
        optimizer.request_measurement(metrics=[metric], control=servo.Control()),
        optimizer.recommend_adjustments([adjustment]),
        optimizer.request_measurement(metrics=[metric], control=servo.Control()),
        optimizer.recommend_adjustments([adjustment]),
    )
    
    # TODO: Generalize (what about optimizer.terminal?)    
    for state in optimizer.get_states(tests.fake.StateMachine.States.done, tests.fake.StateMachine.States.failed):
        state.add_action(servo_runner.shutdown, statesman.Action.Types.entry)
    
    task = event_loop.create_task(servo_runner.run())
    servo.Servo.set_current(servo_runner.servo)
    
    await task


#################################################################


@pytest.fixture
def cli() -> typer.Typer:
    return servo.connectors.emulator.cli

@pytest.fixture
def token_path(tmp_path: pathlib.Path) -> pathlib.Path:
    path = tmp_path / "token"
    path.write_text("123456789")
    return path

def test_help(cli: typer.Typer, cli_runner: typer.testing.CliRunner) -> None:
    result = typer.testing.CliRunner().invoke(cli, "--help", catch_exceptions=False)
    assert result.exit_code == 0
    assert "servo [OPTIONS] COMMAND [ARGS]" in result.stdout

# def test_list_optimizers(cli: typer.Typer, token_path: pathlib.Path, cli_runner: typer.testing.CliRunner) -> None:
#     result = typer.testing.CliRunner().invoke(cli, f"-f {token_path} list-optimizers", catch_exceptions=False)
#     debug(result.stdout, result.stderr)
#     assert result.exit_code == 0
#     assert "servo [OPTIONS] COMMAND [ARGS]" in result.stdout

# def test_create_optimizers(cli: typer.Typer, token_path: pathlib.Path, cli_runner: typer.testing.CliRunner) -> None:
#     result = typer.testing.CliRunner().invoke(cli, f"-f {token_path} create-optimizers", catch_exceptions=False)
#     debug(result.stdout, result.stderr)
#     assert result.exit_code == 0
#     assert "servo [OPTIONS] COMMAND [ARGS]" in result.stdout

# def test_delete_optimizers(cli: typer.Typer, token_path: pathlib.Path, cli_runner: typer.testing.CliRunner) -> None:
#     result = typer.testing.CliRunner().invoke(cli, f"-f {token_path} delete-optimizers", catch_exceptions=False)
#     debug(result.stdout, result.stderr)
#     assert result.exit_code == 0
#     assert "servo [OPTIONS] COMMAND [ARGS]" in result.stdout

# def test_scale_optimizers(cli: typer.Typer, token_path: pathlib.Path, cli_runner: typer.testing.CliRunner) -> None:
#     result = typer.testing.CliRunner().invoke(cli, f"-f {token_path} scale-optimizers", catch_exceptions=False)
#     debug(result.stdout)
#     assert result.exit_code == 0
#     assert "servo [OPTIONS] COMMAND [ARGS]" in result.stdout

# def test_get_template(cli: typer.Typer, token_path: pathlib.Path, cli_runner: typer.testing.CliRunner) -> None:
#     result = typer.testing.CliRunner().invoke(cli, f"-f {token_path} get-template", catch_exceptions=False)
#     debug(result.stdout, result.stderr)
#     assert result.exit_code == 0
#     assert "servo [OPTIONS] COMMAND [ARGS]" in result.stdout
    