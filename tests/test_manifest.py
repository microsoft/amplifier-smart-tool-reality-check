from importlib.metadata import version
import json
from pathlib import Path
import re

import pytest

from reality_check.core.manifest import MANIFEST_PATH
from reality_check.lib import load_manifest

DISTRIBUTION_ROOT = Path(__file__).parents[1]
SKILL_PATH = DISTRIBUTION_ROOT / "skills" / "reality-check" / "SKILL.md"


def test_manifest_matches_the_descriptor_and_package() -> None:
    manifest = load_manifest()
    descriptor = json.loads((DISTRIBUTION_ROOT / "smart-tool.json").read_text(encoding="utf-8"))

    assert DISTRIBUTION_ROOT / descriptor["manifest"] == MANIFEST_PATH
    assert manifest.name == descriptor["cli_argv"][0]
    assert manifest.version == version("reality-check")


@pytest.mark.parametrize("document", [DISTRIBUTION_ROOT / "README.md", SKILL_PATH, MANIFEST_PATH])
def test_install_commands_pin_the_package_version(document: Path) -> None:
    pins = re.findall(r"amplifier-smart-tool-reality-check[@#]v(\d+(?:\.\w+)*)", document.read_text(encoding="utf-8"))

    assert pins
    assert set(pins) == {version("reality-check")}
