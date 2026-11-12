from pathlib import Path
import re
import sys

import pytest

from reality_check.capabilities.check_software import machine

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="cgroups and threads counted toward ulimit are Linux's")


def cgroups(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, groups: dict[str, tuple[str, int]]) -> None:
    """A cgroup v2 tree under `tmp_path` holding this process in its deepest group, with each group's pids limits."""
    root = tmp_path / "cgroup"
    for name, (limit, current) in groups.items():
        directory = root / name
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "pids.max").write_text(f"{limit}\n", encoding="utf-8")
        (directory / "pids.current").write_text(f"{current}\n", encoding="utf-8")
    own = tmp_path / "own"
    own.write_text(f"0::/{max(groups, key=len)}\n", encoding="utf-8")
    monkeypatch.setattr(machine, "CGROUPS", root)
    monkeypatch.setattr(machine, "OWN_CGROUP", own)
    monkeypatch.setattr(machine, "_user_limit_rooms", list)


def test_the_room_is_the_least_any_group_holding_the_process_has_left(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cgroups(
        tmp_path,
        monkeypatch,
        {"user.slice": ("10000", 9000), "user.slice/agent.scope": ("4096", 1200), "other.slice": ("10", 9)},
    )

    assert machine.machine_text().endswith("and room for 1,000 more processes and threads.")


def test_without_a_limit_the_line_states_only_cpus_and_memory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cgroups(tmp_path, monkeypatch, {"user.slice": ("max", 50)})

    assert re.fullmatch(
        r"When this check started, this machine had \d+ CPUs and \d+\.\d GB of memory free\.", machine.machine_text()
    )
