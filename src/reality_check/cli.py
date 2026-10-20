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
    DEFAULT_ORIGIN,
    DEFAULT_TIMEOUT_SECONDS,
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
        ReasoningEffort | None, typer.Option("--reasoning-effort", help="high, or none for a model that takes none.")
    ] = None,
    timeout_seconds: Annotated[
        int, typer.Option("--timeout-seconds", min=0, help="How long the check may run; 0 for no limit.")
    ] = DEFAULT_TIMEOUT_SECONDS,
    images: Annotated[
        list[Path] | None, typer.Option("--image", help="An image shown to the agent with the request; repeatable.")
    ] = None,
    origin: Annotated[str, typer.Option("--origin", help="Who starts the check, such as app.")] = DEFAULT_ORIGIN,
    detach: Annotated[
        bool, typer.Option("--detach", help="Run the check in a process of its own; print its started event and exit.")
    ] = False,
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
                timeout_seconds=timeout_seconds or None,
                images=images,
                origin=origin,
                detach=detach,
            ),
            detach,
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
    origin: Annotated[str, typer.Option("--origin", help="Who sends the message, such as app.")] = DEFAULT_ORIGIN,
) -> None:
    """Send a message to a running check's agent. Deterministic."""
    lib.steer_check(check_id=check_id, message=message, checks_directory=checks_directory, origin=origin)


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
def read_check_activity(
    check_id: Annotated[str, typer.Option("--check-id", help="The check, running or ended.")],
    after: Annotated[
        int | None, typer.Option("--after", help="The cursor an earlier read returned; only what came after.")
    ] = None,
    tool_call_id: Annotated[
        str | None, typer.Option("--tool-call-id", help="Only this tool call and its result, in full.")
    ] = None,
    checks_directory: Annotated[
        Path, typer.Option("--checks-directory", help="Where checks are kept.")
    ] = DEFAULT_CHECKS_DIRECTORY,
) -> None:
    """Print a check's state and what its agent said, thought, and did, as JSON. Deterministic."""
    activity = lib.read_check_activity(
        check_id=check_id, after=after, tool_call_id=tool_call_id, checks_directory=checks_directory
    )
    typer.echo(activity.model_dump_json(indent=2))


@app.command()
def list_intelligence_models() -> None:
    """Print the models a check runs on and their reasoning efforts, as JSON. Deterministic."""
    typer.echo(lib.list_intelligence_models().model_dump_json(indent=2))


@app.command()
def install_computer_use() -> None:
    """Install, once, the cua-driver checks drive desktop apps with, and print it as JSON. Deterministic."""
    typer.echo(lib.install_computer_use().model_dump_json(indent=2))


@app.command()
def reaching_software_skill() -> None:
    """Print the skill for reaching software where it runs. Deterministic."""
    typer.echo(lib.reaching_software_skill())


@app.command()
def using_software_skill() -> None:
    """Print the skill for seeing and using software as a user. Deterministic."""
    typer.echo(lib.using_software_skill())


@app.command()
def using_computer_use_skill() -> None:
    """Print the skill for driving a desktop app's real UI through cua-driver. Deterministic."""
    typer.echo(lib.using_computer_use_skill())


@app.command()
def gathering_evidence_skill() -> None:
    """Print the skill for what evidence to gather and where to put it. Deterministic."""
    typer.echo(lib.gathering_evidence_skill())


async def _check(starting: Coroutine[Any, Any, lib.CheckRun], detach: bool) -> int:
    """Run a check to its end, one JSON line per event, and the exit code its end calls for.

    A detached check goes on in its own process, so only its `started` event is printed.
    """
    run = await starting
    if detach:
        async for event in run.events():
            _print_event(event)
            return 0
        return 1
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
    typer.echo(json.dumps(event.brief().model_dump(mode="json")))


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
