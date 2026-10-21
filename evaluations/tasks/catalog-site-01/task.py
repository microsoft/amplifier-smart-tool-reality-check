"""The Smart Tools catalog at its public URL, where one tool's Copy button copies the next tool's install command."""

from pathlib import Path
import subprocess

from common import capability, collect, environment, install, judge
from common.context import Criterion, EvaluationError, RunContext

TASK = Path(__file__).resolve().parent
IMAGE = "catalog-site:eval"
DESCRIPTION = (
    "The Amplifier Smart Tools catalog at a573c235, with an Install box added to each tool card. One box, Deep "
    "Research's, shows the right command but its Copy button copies Fact Check's. The site is served at its real "
    "URL, https://microsoft.github.io/amplifier-smart-tools-catalog/, through the environment's gateway, while the "
    "rest of the web, including the other family sites, is real. The agent gets no project and no target: it must "
    "go through all 22 tools and read what each Copy button actually puts on the clipboard."
)
REQUEST = (
    "We are about to share the Smart Tools catalog at https://microsoft.github.io/amplifier-smart-tools-catalog/ "
    "widely. Can you give it a check?"
)
TIMEOUT_SECONDS = 3600
RUBRIC = {
    "covered-every-tool": Criterion(
        weight=2, description="Lists each tool it checked, and the list covers every tool card in the catalog."
    ),
    "found-copy-defect": Criterion(
        weight=4,
        description="Reports that Deep Research's Copy button copies Fact Check's install command while the box "
        "shows the right one.",
    ),
    "clipboard-evidence": Criterion(
        weight=3,
        description="Shows the text Copy actually put on the clipboard, not only the visible text, for the defect "
        "and for the tools it says are fine.",
    ),
    "no-false-findings": Criterion(weight=1, description="Reports no defects that the evidence does not support."),
}


def run(context: RunContext) -> None:
    with context.step("build"):
        _build_image(context)
    with environment.launch(context, TASK / "environment") as env:
        with context.step("setup"):
            install.setup(env, context)
        with context.step("baseline"):
            baseline = collect.baseline(env, context)
        with context.step("capability"):
            result = capability.run(env, context, request=REQUEST, timeout_seconds=TIMEOUT_SECONDS)
        with context.step("collect"):
            collect.standard(env, context, result, baseline)
        with context.step("judge"):
            judge.grade(env, context, request=REQUEST, expected=TASK / "expected.md", rubric=RUBRIC, result=result)


def _build_image(context: RunContext) -> None:
    """Build the site's image with the host's Docker, where the profile's `catalog-site` service runs it."""
    log = context.directory / "logs" / "build.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8") as output:
        built = subprocess.run(
            ["docker", "build", "--tag", IMAGE, str(TASK / "image")], stdout=output, stderr=subprocess.STDOUT
        )
    if built.returncode != 0:
        raise EvaluationError(f"Building {IMAGE} failed; see {log}.")
