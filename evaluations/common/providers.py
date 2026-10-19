"""What each agent provider needs in the evaluation environment, and where it keeps what it did."""

import os
import shutil
import subprocess
from typing import NamedTuple

from common.context import EvaluationError

from reality_check.schemas import AgentProvider


class Provider(NamedTuple):
    """An agent provider's setup in the environment, as its user would do it, and where its records are."""

    extra: str  # the reality-check extra that installs the provider's SDK
    credentials: tuple[str, ...]  # host environment variables the environment profile passes into the twin
    setup: str  # shell run in the twin before reality-check is installed: the prerequisites the tool's README names
    sessions: str  # directory in the twin holding one directory per session id
    logs: tuple[str, ...]  # directories in the twin with the provider's own process logs


# https://github.com/cli/cli/blob/trunk/docs/install_linux.md, the gh install the manifest points a user to.
GH_INSTALL = """sudo mkdir -p -m 755 /etc/apt/keyrings \
&& curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
| sudo tee /etc/apt/keyrings/githubcli-archive-keyring.gpg > /dev/null \
&& echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] \
https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
&& sudo apt-get update -qq && sudo apt-get install -y -qq gh"""

PROVIDERS: dict[AgentProvider, Provider] = {
    "copilot": Provider(
        extra="copilot",
        credentials=("GH_TOKEN",),
        setup=GH_INSTALL,
        sessions="~/.copilot/session-state",
        logs=("~/.copilot/logs",),
    ),
}


def provider(name: AgentProvider) -> Provider:
    """The named provider, or a failure naming the ones the evaluations can set up."""
    if name not in PROVIDERS:
        raise EvaluationError(f"The evaluations cannot set up {name}; it can set up: {', '.join(PROVIDERS)}.")
    return PROVIDERS[name]


def export_credentials(name: AgentProvider) -> None:
    """Put the provider's credentials in this process's environment, where the environment's launch reads them.

    Called once, before any run starts, since every run's launch shares this process's environment.
    """
    for variable in provider(name).credentials:
        if os.environ.get(variable):
            continue
        if variable == "GH_TOKEN" and shutil.which("gh") is not None:
            minted = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True)
            if minted.returncode == 0:
                os.environ[variable] = minted.stdout.strip()
                continue
        raise EvaluationError(f"{name} needs {variable} set, or for GH_TOKEN, `gh auth login` on this machine.")
