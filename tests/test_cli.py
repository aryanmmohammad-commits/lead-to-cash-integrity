from pathlib import Path

import pytest
from typer.main import get_command
from typer.testing import CliRunner

from l2c import cli

runner = CliRunner()
COMMANDS = [
    ["generate"],
    ["load"],
    ["build"],
    ["remember"],
    ["decisions", "import"],
    ["fixes", "propose"],
    ["fixes", "apply"],
    ["fixes", "rollback"],
    ["report"],
    ["slack"],
    ["show"],
    ["doctor"],
    ["pull", "hubspot"],
    ["pull", "younium"],
    ["run"],
]
MAPPING_COMMANDS = [
    ["generate"],
    ["load"],
    ["build"],
    ["doctor"],
    ["run"],
    ["pull", "hubspot"],
    ["pull", "younium"],
]


def test_root_help_lists_all_commands() -> None:
    result = runner.invoke(cli.app, ["--help"])
    assert result.exit_code == 0
    for command in {parts[0] for parts in COMMANDS}:
        assert command in result.output


@pytest.mark.parametrize(
    "command",
    [
        command
        for command in COMMANDS
        if command
        in (
            ["remember"],
            ["decisions", "import"],
            ["fixes", "apply"],
            ["fixes", "rollback"],
            ["doctor"],
            ["pull", "hubspot"],
            ["pull", "younium"],
        )
    ],
)
def test_v02_commands_point_to_the_roadmap_and_exit_one(command: list[str]) -> None:
    result = runner.invoke(cli.app, command)
    assert result.exit_code == 1
    assert result.output.strip() == "planned for v0.2 - see README roadmap"


@pytest.mark.parametrize("command", MAPPING_COMMANDS)
def test_source_commands_accept_mapping(command: list[str]) -> None:
    result = runner.invoke(cli.app, [*command, "--mapping", "custom mapping.yml"])
    assert result.exit_code == 1
    if command in (["generate"], ["load"], ["build"], ["run"]):
        assert "Cannot read configuration" in result.output
        assert "custom mapping.yml" in result.output
    else:
        assert result.output.strip() == "planned for v0.2 - see README roadmap"
    assert "--mapping" in runner.invoke(cli.app, [*command, "--help"]).output


def test_mapping_option_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    command = get_command(cli.app).commands["load"]

    def parsed_mapping(args: list[str]) -> Path:
        with command.make_context("load", args) as context:
            return Path(context.params["mapping"])

    monkeypatch.delenv("L2C_MAPPING", raising=False)
    assert parsed_mapping([]) == Path("config/mapping.yml")
    monkeypatch.setenv("L2C_MAPPING", "environment.yml")
    assert parsed_mapping([]) == Path("environment.yml")
    assert parsed_mapping(["--mapping", "explicit.yml"]) == Path("explicit.yml")
