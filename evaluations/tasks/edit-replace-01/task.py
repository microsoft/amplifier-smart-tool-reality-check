"""Microsoft Edit in the user's project, where Replace All undoes one replacement at a time and misplaces the cursor."""

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from common import capability, collect, environment, install, judge
from common.context import Criterion, EvaluationError, RunContext
from common.environment import PROJECT

TASK = Path(__file__).resolve().parent
CACHE = TASK / ".cache"
PATCH = TASK / "patches" / "replace-all.patch"
EDIT_REPOSITORY = "https://github.com/microsoft/edit"
# main on 2026-10-12.
EDIT_COMMIT = "cb6de0a8966aecd01d19a3541dab1829d0e679ca"
DESCRIPTION = (
    "Microsoft Edit, the Rust terminal text editor, at main cb6de0a8 with patches/replace-all.patch applied, placed "
    "in ~/project as a repository of one commit, so the patch shows in no diff. Nothing is built or installed: the "
    "agent installs Rust, and ICU for search, itself. The patch adds two defects to Replace All: each replacement "
    "is its own undo step, so one Ctrl+Z undoes only the last one, and the cursor afterward lands one column right "
    "of the end of the last replacement for each wide character, such as CJK or emoji, before it on that line. It "
    "also adds assets/highlighting-tests/wide-chars.txt, a sample with wide characters. The agent must build the "
    "editor, drive it in a terminal, and notice both."
)
REQUEST = (
    "Can you check that Replace All in edit holds up in real use, for people writing in any language, including "
    "fixing a replace they did not mean?"
)
TIMEOUT_SECONDS = 3600
RUBRIC = {
    "built-from-source": Criterion(
        weight=1,
        description="Built the project's own code in ~/project and checked that build, not a released edit.",
    ),
    "found-undo": Criterion(
        weight=4,
        description="Reports that after Replace All, one Ctrl+Z undoes only the last replacement, not all of them.",
    ),
    "found-wide-char-cursor": Criterion(
        weight=4,
        description="Reports that after Replace All on a line with wide characters, such as CJK or emoji, the cursor "
        "lands to the right of the end of the last replacement, while on an ASCII line it lands right after it.",
    ),
    "terminal-evidence": Criterion(
        weight=3,
        description="Each finding cites terminal captures that show it as a user would see it. A claim about the "
        "cursor needs the status bar's line and column, the cursor position from the terminal, or an image that "
        "draws the cursor. A claim about how wide characters or emoji look needs an image with their real glyphs. "
        "A capture that cannot show what it is cited for counts as no evidence.",
    ),
    "no-false-findings": Criterion(
        weight=1,
        description='Reports nothing the evidence does not support. The answer key\'s "Not defects" are not findings.',
    ),
    "did-not-use-upstream": Criterion(
        weight=1,
        description="Found the defects by using the editor, not by fetching the upstream project, its GitHub "
        "repository, a release, or a crate, to compare against the project's code. 100 when the session shows no "
        "such fetch or comparison, 0 when it does.",
    ),
}


def run(context: RunContext) -> None:
    with context.step("build"):
        checkout = _checkout()
    with environment.launch(context, TASK / "environment") as env:
        with context.step("setup"):
            install.setup(env, context)
        with context.step("place"):
            # `push` into an existing directory nests the source in it, so the checkout lands beside the project
            # and its contents are moved in.
            staged = f"/var/tmp/{checkout.name}"
            env.push(checkout, staged)
            env.run_checked("place-project", f"cp -a {staged}/. {PROJECT}/ && rm -rf {staged}")
        with context.step("baseline"):
            baseline = collect.baseline(env, context)
        with context.step("capability"):
            result = capability.run(env, context, request=REQUEST, timeout_seconds=TIMEOUT_SECONDS)
        with context.step("collect"):
            collect.standard(env, context, result, baseline)
        with context.step("judge"):
            judge.grade(env, context, request=REQUEST, expected=TASK / "expected.md", rubric=RUBRIC, result=result)


def _checkout() -> Path:
    """Edit at EDIT_COMMIT with the patch applied, as a repository of one commit on `main`.

    Kept in the cache under the commit and the patch's hash. The history is dropped so the patch shows in no diff.
    """
    patch = hashlib.sha256(PATCH.read_bytes()).hexdigest()[:12]
    checkout = CACHE / f"edit-{EDIT_COMMIT[:12]}-{patch}"
    if checkout.is_dir():
        return checkout
    CACHE.mkdir(exist_ok=True)
    scratch = Path(tempfile.mkdtemp(dir=CACHE))
    try:
        source = scratch / "edit"
        source.mkdir()
        _git(source, "init", "-q")
        _git(source, "fetch", "-q", "--depth", "1", EDIT_REPOSITORY, EDIT_COMMIT)
        _git(source, "checkout", "-q", "FETCH_HEAD")
        subject = _git(source, "log", "-1", "--format=%s")
        applied = subprocess.run(["git", "-C", str(source), "apply", str(PATCH)], capture_output=True, text=True)
        if applied.returncode != 0:
            raise EvaluationError(
                f"{PATCH.relative_to(TASK)} does not apply to {EDIT_REPOSITORY} at {EDIT_COMMIT}.\n"
                f"{applied.stderr.strip()}"
            )
        shutil.rmtree(source / ".git")
        _git(source, "init", "-q", "--initial-branch", "main")
        _git(source, "add", "--all", "--force")
        _git(source, "commit", "-q", "-m", subject)
        # A run building the same checkout at the same time may have moved its own into place first.
        try:
            source.rename(checkout)
        except OSError:
            if not checkout.is_dir():
                raise
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return checkout


def _git(directory: Path, *arguments: str) -> str:
    # A fixed identity and date make the commit the same on every build.
    identity = {
        "GIT_AUTHOR_NAME": "edit",
        "GIT_AUTHOR_EMAIL": "main@edit.invalid",
        "GIT_AUTHOR_DATE": "2026-10-12T00:00:00Z",
        "GIT_COMMITTER_NAME": "edit",
        "GIT_COMMITTER_EMAIL": "main@edit.invalid",
        "GIT_COMMITTER_DATE": "2026-10-12T00:00:00Z",
    }
    done = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "-C", str(directory), *arguments],
        capture_output=True,
        text=True,
        env=os.environ | identity,
    )
    if done.returncode != 0:
        raise EvaluationError(f"git {' '.join(arguments)} failed: {done.stderr.strip()}")
    return done.stdout.strip()
