"""The process a detached check runs in, with its agent faked by the fake in fakes.py named as its first argument."""

from pathlib import Path
import sys

import fakes

from reality_check.capabilities.check_software import background, check


def command(name: str, skills_cache: Path) -> list[str]:
    """What runs a detached check with its agent faked by `name`, in place of `check.BACKGROUND_COMMAND`."""
    return [sys.executable, str(Path(__file__)), name, str(skills_cache)]


if __name__ == "__main__":
    check.POLL_SECONDS = 0.01
    check.SKILLS_CACHE_DIRECTORY = Path(sys.argv[2])
    raise SystemExit(background.main(fakes.intelligence(sys.argv[1])))
