"""Excalidraw with a bound arrow that jumps inside its shape after a drag, behind a profile in the user's project."""

from pathlib import Path
import subprocess
import tempfile

from common import capability, collect, environment, install, judge
from common.context import Criterion, EvaluationError, RunContext
from common.environment import PROJECT

TASK = Path(__file__).resolve().parent
IMAGE = "excalidraw-app:0.18.1"
DESCRIPTION = (
    "Excalidraw v0.18.1, the open-source whiteboard, built from source with one bug added: once a shape that an "
    "arrow is connected to is dragged, the arrow's end jumps about 20px inside the shape. When the arrow is first "
    "drawn, its end is placed correctly. The image is built outside the evaluation environment, so the agent sees "
    "only a Digital Twin Universe profile that runs it, as a user with their own custom build would. The agent must "
    "launch it, find a way to use it in a browser, and notice where the arrow ends sit after a shape moves."
)
REQUEST = (
    "I have a custom version of excalidraw available in a DTU in .agents/digital-twin-universe/excalidraw. "
    "Can you please check that drawing shapes, moving them, and connecting them all work as expected?"
)
TARGET = ".agents/digital-twin-universe/excalidraw"
TIMEOUT_SECONDS = 3600
RUBRIC = {
    "found-the-defect": Criterion(
        weight=4,
        description="Reports that the end of an arrow bound to a shape moves inside the shape after a bound shape "
        "is dragged.",
    ),
    "drawn-vs-dragged": Criterion(
        weight=2,
        description="Says that the arrow end is placed correctly when the arrow is drawn and wrongly only after a "
        "drag.",
    ),
    "evidence": Criterion(weight=3, description="Each finding cites screenshots or recordings that actually show it."),
    "no-false-findings": Criterion(weight=1, description="Reports no defects that the evidence does not support."),
}


def run(context: RunContext) -> None:
    with tempfile.TemporaryDirectory() as scratch:
        with context.step("build"):
            archive = _build_image(context, Path(scratch))
        with environment.launch(context, TASK / "environment") as env:
            with context.step("setup"):
                install.setup(env, context)
            with context.step("place"):
                env.run_checked("place-profile", f"mkdir -p {PROJECT}/.agents/digital-twin-universe")
                env.push(TASK / "profile", f"{PROJECT}/{TARGET}")
                env.load_images(archive)
            with context.step("baseline"):
                baseline = collect.baseline(env, context)
            with context.step("capability"):
                result = capability.run(env, context, request=REQUEST, target=TARGET, timeout_seconds=TIMEOUT_SECONDS)
            with context.step("collect"):
                collect.standard(env, context, result, baseline)
            with context.step("judge"):
                judge.grade(
                    env,
                    context,
                    request=REQUEST,
                    expected=TASK / "expected.md",
                    rubric=RUBRIC,
                    result=result,
                    target=TARGET,
                )


def _build_image(context: RunContext, destination: Path) -> Path:
    """Build the image with the host's Docker, whose build cache makes every run after the first fast, and save it.

    Built on the host, so neither the patched source nor its build cache enters the environment.
    """
    log = context.directory / "logs" / "build.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8") as output:
        built = subprocess.run(
            ["docker", "build", "--tag", IMAGE, str(TASK / "image")], stdout=output, stderr=subprocess.STDOUT
        )
    if built.returncode != 0:
        raise EvaluationError(f"Building {IMAGE} failed; see {log}.")
    archive = destination / "images.tar"
    saved = subprocess.run(["docker", "save", "--output", str(archive), IMAGE], capture_output=True, text=True)
    if saved.returncode != 0:
        raise EvaluationError(f"Saving {IMAGE} failed: {saved.stderr.strip()}")
    return archive
