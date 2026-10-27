"""
Check and compile the app's frontend into the package, when the tools to do so are present.

The compiled MCP App view under `src/reality_check/capabilities/app/static/view/` and the browser host page under
`src/reality_check/capabilities/app/static/host/` are committed, so the tool installs and runs with no Node anywhere.
Node and pnpm are needed only to change the frontend; without them this script says so and exits 0, so
`prek run --all-files` passes for a Python-only contributor.

Arguments name the `app/package.json` scripts to run, so each precommit hook runs one step; with none it runs all.
"""

from pathlib import Path
import shutil
import subprocess
import sys

APP = Path(__file__).parent / "app"
ALL_SCRIPTS = ["lint", "format", "typecheck", "build", "build:view"]


def main() -> None:
    pnpm = shutil.which("pnpm")
    if pnpm is None:
        print(
            "pnpm not found; using the committed app build. "
            "Install Node 22+ and pnpm only to change the frontend (see docs/DEVELOPMENT.md)."
        )
        return
    for script in ("install --frozen-lockfile", *(sys.argv[1:] or ALL_SCRIPTS)):
        subprocess.run([pnpm, "--dir", str(APP), *script.split()], check=True)


if __name__ == "__main__":
    main()
