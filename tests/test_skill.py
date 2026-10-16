import pytest
import typer
from typer.testing import CliRunner

from reality_check import lib
from reality_check.cli import app
from reality_check.core.skill import CAPABILITIES, skill_directory
from reality_check.schemas import RealityCheckError

runner = CliRunner()


def test_skill_is_a_wrapped_document_naming_every_capability() -> None:
    document = lib.skill()

    assert document.startswith('<skill_content name="reality-check">')
    assert document.endswith("</skill_content>")
    assert "# reality-check" in document
    assert lib.load_manifest().body in document
    assert "Each has its own skill: `reality-check <capability> --help`." in document
    for capability in CAPABILITIES:
        kind = "model-backed" if capability.model_backed else "deterministic"
        assert f"- `{capability.name}` [{kind}] -- {capability.summary}" in document


def test_every_capability_ships_the_files_its_skill_names() -> None:
    root = skill_directory()

    for capability in CAPABILITIES:
        assert (root / capability.skill).is_file()
        for resource in capability.resources:
            assert (root / resource).is_file()


def test_an_unknown_capability_names_the_ones_that_exist() -> None:
    with pytest.raises(RealityCheckError) as failure:
        lib.skill("nope")

    for capability in CAPABILITIES:
        assert capability.name in str(failure.value)


def test_every_command_answers_help_with_its_own_skill() -> None:
    for capability in CAPABILITIES:
        result = runner.invoke(app, [capability.name, "--help"])

        assert result.exit_code == 0
        assert result.stdout.strip() == lib.skill(capability.name)


def test_the_cli_exposes_exactly_the_capabilities_the_skill_lists() -> None:
    commands = typer.main.get_group(app).commands

    assert set(commands) == {capability.name for capability in CAPABILITIES}


def test_every_capability_skill_documents_every_argument_the_cli_takes() -> None:
    commands = typer.main.get_group(app).commands

    for capability in CAPABILITIES:
        document = lib.skill(capability.name)
        for parameter in commands[capability.name].get_params(typer.Context(commands[capability.name])):
            names = [name for name in parameter.opts if name.startswith("-")]
            if not names:
                assert parameter.name is not None
                assert parameter.name.upper() in document
                continue
            if set(names) <= {"-h", "--help"}:
                continue
            for name in names:
                assert name in document
