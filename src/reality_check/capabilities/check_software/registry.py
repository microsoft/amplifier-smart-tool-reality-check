"""The projects checks were started from on this machine, so every check can be found without knowing where it is kept."""

import os
from pathlib import Path

from filelock import FileLock
from pydantic import BaseModel, ValidationError

from reality_check.capabilities.check_software.record import read_atomically, write_atomically
from reality_check.schemas import Project, RealityCheckError

# In the home directory rather than a project's, because it is the one place that knows every project.
REGISTRY = Path.home() / ".agents" / "reality-check" / "projects.json"
LOCK_TIMEOUT_SECONDS = 60
# A checks directory at a project's default place names its project; one kept anywhere else names only itself.
DEFAULT_PLACE = (".agents", "reality-check")


class Registry(BaseModel):
    projects: list[Project] = []


def register_project(checks_directory: Path, root: Path | None = None) -> Project:
    """Add the project whose checks are kept in `checks_directory` to the registry, once.

    `root` is the directory checks there were started from; without it, the project the checks directory belongs to.
    """
    checks_directory = checks_directory.resolve()
    project = Project(root=(root or project_root(checks_directory)).resolve(), checks_directory=checks_directory)
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    # Held across the read and the write, because checks started at once each add their project.
    with FileLock(REGISTRY.with_name(f"{REGISTRY.name}.lock"), timeout=LOCK_TIMEOUT_SECONDS):
        registry = _read()
        if any(_same(known.checks_directory, checks_directory) for known in registry.projects):
            return project
        registry.projects.append(project)
        write_atomically(REGISTRY, registry.model_dump_json(indent=2))
    return project


def registered_projects() -> list[Project]:
    """Every registered project, in the order each was first registered."""
    return _read().projects


def project_root(checks_directory: Path) -> Path:
    """The project a checks directory belongs to, when no record says where its checks were started from."""
    resolved = checks_directory.resolve()
    if resolved.parts[-2:] == DEFAULT_PLACE:
        return resolved.parents[1]
    return resolved


def _read() -> Registry:
    if not REGISTRY.is_file():
        return Registry()
    try:
        return Registry.model_validate_json(read_atomically(REGISTRY))
    except ValidationError as error:
        raise RealityCheckError(
            code="bad-registry",
            message=f"{REGISTRY} is not a list of projects: {error.errors()[0]['msg']}.",
            remedy="Fix the file, or delete it; checks started after that add their projects again.",
        ) from None


def _same(one: Path, other: Path) -> bool:
    # Windows paths differ only in case for the same directory.
    return os.path.normcase(one) == os.path.normcase(other)
