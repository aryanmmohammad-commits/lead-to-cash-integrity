from pathlib import Path
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from l2c import cli, pipeline
from l2c.paths import CONFIG_DIR

STEPS = ["generate_files", "load_files", "build_models", "propose_fixes", "write_report"]


@pytest.mark.parametrize("failure", [None, *STEPS])
def test_pipeline_order_mapping_run_id_and_first_failure(
    failure: str | None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, dict]] = []

    def fake(name: str):
        def execute(**kwargs):
            calls.append((name, kwargs))
            if name == failure:
                raise ValueError(f"synthetic failure in {name}")
            return Mock()

        return execute

    for name in STEPS:
        monkeypatch.setattr(pipeline, name, fake(name))
    monkeypatch.delenv("L2C_MAPPING", raising=False)
    kwargs = {"format_name": "de", "raw_dir": tmp_path / "raw", "output_dir": tmp_path / "out"}
    if failure:
        with pytest.raises(ValueError, match=f"synthetic failure in {failure}"):
            pipeline.run_pipeline(**kwargs)
        assert [name for name, _ in calls] == STEPS[: STEPS.index(failure) + 1]
    else:
        result = pipeline.run_pipeline(**kwargs)
        assert [name for name, _ in calls] == STEPS
        assert calls[-1][1]["run_id"] == result.run_id
    assert len({arguments["run_id"] for _, arguments in calls}) == 1
    for _, arguments in calls[:3]:
        assert arguments["mapping_path"] == CONFIG_DIR / "mapping.de.yml"


def test_pipeline_explicit_mapping_overrides_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mocks = {name: Mock() for name in STEPS}
    for name, mock in mocks.items():
        monkeypatch.setattr(pipeline, name, mock)
    monkeypatch.setenv("L2C_MAPPING", "environment.yml")
    pipeline.run_pipeline(mapping_path=tmp_path / "explicit.yml")
    assert mocks["generate_files"].call_args.kwargs["mapping_path"] == tmp_path / "explicit.yml"


def test_run_cli_reports_failure_and_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock = Mock(side_effect=ValueError("synthetic build failure"))
    monkeypatch.setattr(cli, "run_pipeline", mock)
    result = CliRunner().invoke(cli.app, ["run"])
    assert result.exit_code == 1 and "synthetic build failure" in result.output
    assert "Pipeline complete" not in result.output
    mock.side_effect = None
    result = CliRunner().invoke(cli.app, ["run", "--format", "de", "--output-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "Pipeline complete" in result.output
    assert mock.call_args.kwargs["format_name"] == "de"
    assert mock.call_args.kwargs["output_dir"] == tmp_path
