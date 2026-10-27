from pathlib import Path

import pytest

from reality_check.capabilities.check_software import check, registry
from reality_check.capabilities.computer_use.target import Unavailable


def computer_use_off(check_id: str, cache_directory: Path) -> Unavailable:
    return Unavailable("cua-driver 0.36.0 is not installed.", "Run `reality-check install-computer-use`.")


@pytest.fixture(autouse=True)
def no_computer_use(monkeypatch: pytest.MonkeyPatch) -> None:
    """Checks in tests never touch the machine's own cua-driver."""
    monkeypatch.setattr(check, "prepare_computer_use", computer_use_off)


@pytest.fixture(autouse=True)
def own_registry(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Checks in tests never add their projects to the machine's own registry."""
    path = tmp_path_factory.mktemp("home") / "projects.json"
    monkeypatch.setattr(registry, "REGISTRY", path)
    return path
