"""Command line entry point for Reality Check."""

import asyncio
from collections.abc import Callable, Coroutine, Iterator
import contextlib
import json
from pathlib import Path
import signal
from types import FrameType
from typing import Annotated, Any

import typer

# Typer 0.27 vendors Click, so a command that overrides Click's own hooks has to speak the vendored types.
from typer._click import Context, Parameter
from typer.core import TyperCommand, TyperOption
from typer.models import CommandFunctionType

from reality_check import lib
from reality_check.core.skill import DISTRIBUTION
from reality_check.schemas import (
    DEFAULT_CHECKS_DIRECTORY,
    DEFAULT_INTELLIGENCE_REASONING_EFFORT,
    AgentProvider,
    AskFirst,
    CheckEvent,
    RealityCheckError,
    ReasoningEffort,
)

# SIGHUP is the console closing on Linux and macOS, SIGBREAK on Windows, where Ctrl+Break and closing it raise it.
CANCELLING_SIGNALS = ("SIGINT", "SIGTERM", "SIGHUP", "SIGBREAK")


class CapabilityCommand(TyperCommand):
    """Every capability answers `-h` with the generated summary and `--help` with its skill from the library."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs["add_help_option"] = False
        super().__init__(*args, **kwargs)

    def get_params(self, ctx: Context) -> list[Parameter]:
        def short(ctx: Context, param: Parameter, value: bool) -> None:
            if value and not ctx.resilient_parsing:
                typer.echo(ctx.get_help())
                ctx.exit()

        def capability_skill(ctx: Context, param: Parameter, value: bool) -> None:
            if value and not ctx.resilient_parsing:
                typer.echo(lib.skill(self.name))
                ctx.exit()

        return [
            *super().get_params(ctx),
            TyperOption(
                param_decls=["-h"],
                is_flag=True,
                is_eager=True,
                expose_value=False,
                callback=short,
                help="Terse summary of this capability.",
            ),
            TyperOption(
                param_decls=["--help"],
                is_flag=True,
                is_eager=True,
                expose_value=False,
                callback=capability_skill,
                help="This capability's skill, for an agent about to call it.",
            ),
        ]


class SmartToolTyper(typer.Typer):
    """A Typer whose commands are CapabilityCommand by default, so a capability added later inherits the help split."""

    def command(
        self, *args: Any, cls: type[TyperCommand] = CapabilityCommand, **kwargs: Any
    ) -> Callable[[CommandFunctionType], CommandFunctionType]:
        return super().command(*args, cls=cls, **kwargs)


app = SmartToolTyper(
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
    # `-h` is the terse summary and `--help` is the skill, at both scopes. On the root, the callback's parameter
    # claims `--help` and Click drops a help option name a parameter already took, which leaves the generated
    # summary on `-h`; on a capability, CapabilityCommand splits the two itself.
    context_settings={"help_option_names": ["-h", "--help"]},
)


def _print_skill(value: bool) -> None:
    """Answer the root `--help` with the skill the library composes, leaving `-h` to Typer."""
    if value:
        typer.echo(lib.skill())
        raise typer.Exit()


def _print_version(value: bool) -> None:
    if value:
        typer.echo(f"{DISTRIBUTION} {lib.version()}")
        raise typer.Exit()


@app.callback()
def cli(
    version: Annotated[
        bool,
        typer.Option("--version", "-V", is_eager=True, callback=_print_version, help="Print the version and exit."),
    ] = False,
    help: Annotated[
        bool,
        typer.Option(
            "--help", is_eager=True, callback=_print_skill, help="This tool's skill, for an agent driving it."
        ),
    ] = False,
) -> None:
    """Checks that an app works the way a real user would experience it, on your machine, in a Digital Twin Universe, or in one it sets up for you, and returns evidence for every finding"""


@app.command()
def manifest() -> None:
    """Print the tool's manifest as JSON. Deterministic."""
    typer.echo(lib.load_manifest().model_dump_json(indent=2))


@app.command()
def check_software(
    request: Annotated[str, typer.Option("--request", help="What to check, in plain words.")],
    target: Annotated[
        str | None, typer.Option("--target", help="Where the software is; omit when the request says.")
    ] = None,
    resume: Annotated[str | None, typer.Option("--resume", help="An earlier check_id to continue.")] = None,
    previous_checks: Annotated[
        list[Path] | None,
        typer.Option(
            "--previous-checks", help="An earlier check's directory, for the request to refer to; repeatable."
        ),
    ] = None,
    ask_first: Annotated[
        AskFirst, typer.Option("--ask-first", help="When to stop and ask before the work starts.")
    ] = "when-off",
    keep_running: Annotated[
        bool, typer.Option("--keep-running", help="Leave running what this check started, for later checks.")
    ] = False,
    checks_directory: Annotated[
        Path, typer.Option("--checks-directory", help="Where checks are kept.")
    ] = DEFAULT_CHECKS_DIRECTORY,
    agent_provider: Annotated[
        AgentProvider | None, typer.Option("--agent-provider", help="The first installed when omitted.")
    ] = None,
    model: Annotated[str | None, typer.Option("--model", help="The agent provider's default when omitted.")] = None,
    reasoning_effort: Annotated[
        ReasoningEffort, typer.Option("--reasoning-effort")
    ] = DEFAULT_INTELLIGENCE_REASONING_EFFORT,
    timeout_seconds: Annotated[int, typer.Option("--timeout-seconds", min=1)] = 3600,
) -> None:
    """Check software as a user would, printing each event as a JSON line. Model-backed."""
    code = asyncio.run(
        _check(
            lib.check_software(
                request=request,
                target=target,
                resume=resume,
                previous_checks=previous_checks,
                ask_first=ask_first,
                keep_running=keep_running,
                checks_directory=checks_directory,
                agent_provider=agent_provider,
                model=model,
                reasoning_effort=reasoning_effort,
                timeout_seconds=timeout_seconds,
            )
        )
    )
    raise typer.Exit(code)


@app.command()
def steer_check(
    check_id: Annotated[str, typer.Option("--check-id", help="The running check.")],
    message: Annotated[str, typer.Option("--message", help="What to tell its agent.")],
    checks_directory: Annotated[
        Path, typer.Option("--checks-directory", help="Where checks are kept.")
    ] = DEFAULT_CHECKS_DIRECTORY,
) -> None:
    """Send a message to a running check's agent. Deterministic."""
    lib.steer_check(check_id=check_id, message=message, checks_directory=checks_directory)


@app.command()
def cancel_check(
    check_id: Annotated[str, typer.Option("--check-id", help="The running check.")],
    checks_directory: Annotated[
        Path, typer.Option("--checks-directory", help="Where checks are kept.")
    ] = DEFAULT_CHECKS_DIRECTORY,
) -> None:
    """Cancel a running check; its session can still be resumed. Deterministic."""
    lib.cancel_check(check_id=check_id, checks_directory=checks_directory)


@app.command()
def reaching_software_skill() -> None:
    """Print the skill for reaching software where it runs. Deterministic."""
    typer.echo(lib.reaching_software_skill())


@app.command()
def using_software_skill() -> None:
    """Print the skill for seeing and using software as a user. Deterministic."""
    typer.echo(lib.using_software_skill())


@app.command()
def gathering_evidence_skill() -> None:
    """Print the skill for what evidence to gather and where to put it. Deterministic."""
    typer.echo(lib.gathering_evidence_skill())


async def _check(starting: Coroutine[Any, Any, lib.CheckRun]) -> int:
    """Run a check to its end, one JSON line per event, and the exit code its end calls for."""
    run = await starting
    with _cancelled_by_signals(run):
        async for event in run.events():
            _print_event(event)
        try:
            result = await run.result()
        except RealityCheckError as error:
            typer.echo(error, err=True)
            return 1
    return 0 if result.status == "done" else 1


def _print_event(event: CheckEvent) -> None:
    # ASCII-escaped JSON is UTF-8 on any console encoding, and echo writes the line in one call and flushes it.
    typer.echo(json.dumps(event.model_dump(mode="json")))


@contextlib.contextmanager
def _cancelled_by_signals(run: lib.CheckRun) -> Iterator[None]:
    """Cancel the check on every signal that ends the process, so its session is drained and can be resumed."""
    loop = asyncio.get_running_loop()
    cancelling: set[asyncio.Task[None]] = set()

    def cancel() -> None:
        task = asyncio.ensure_future(run.cancel())
        cancelling.add(task)
        task.add_done_callback(cancelling.discard)

    def handler(signum: int, frame: FrameType | None) -> None:
        loop.call_soon_threadsafe(cancel)

    previous: dict[signal.Signals, Any] = {}
    for name in CANCELLING_SIGNALS:
        number = getattr(signal, name, None)
        if isinstance(number, signal.Signals):
            previous[number] = signal.signal(number, handler)
    try:
        yield
    finally:
        for number, original in previous.items():
            signal.signal(number, original)


def main() -> int:
    try:
        app()
    except RealityCheckError as error:
        typer.echo(error, err=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
