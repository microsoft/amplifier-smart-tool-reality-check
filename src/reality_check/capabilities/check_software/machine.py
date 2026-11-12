"""What this machine has free when a check starts, stated in one line of the agent's prompt."""

import contextlib
import os
from pathlib import Path
import sys

import psutil

from reality_check.capabilities.check_software.constants import MACHINE, MACHINE_WITH_ROOM

if sys.platform != "win32":
    import resource

CGROUPS = Path("/sys/fs/cgroup")
OWN_CGROUP = Path("/proc/self/cgroup")


def machine_text() -> str:
    """This machine's CPUs, free memory, and, where a limit applies, room for more processes and threads."""
    cpus = os.process_cpu_count() or 1
    memory = f"{psutil.virtual_memory().available / 2**30:.1f}"
    rooms = [*_cgroup_pids_rooms(), *_user_limit_rooms()]
    if not rooms:
        return MACHINE.substitute(cpus=cpus, memory=memory)
    return MACHINE_WITH_ROOM.substitute(cpus=cpus, memory=memory, room=f"{max(0, min(rooms)):,}")


def _cgroup_pids_rooms() -> list[int]:
    """How far below its `pids.max` each cgroup v2 group holding this process is, from its own group up."""
    if sys.platform != "linux":
        return []
    try:
        lines = OWN_CGROUP.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    group = next((CGROUPS / line[3:].lstrip("/") for line in lines if line.startswith("0::")), None)
    if group is None:
        return []
    rooms: list[int] = []
    for directory in [group, *group.parents]:
        if not directory.is_relative_to(CGROUPS):
            break
        with contextlib.suppress(OSError, ValueError):
            limit = (directory / "pids.max").read_text(encoding="utf-8").strip()
            if limit != "max":
                rooms.append(int(limit) - int((directory / "pids.current").read_text(encoding="utf-8")))
    return rooms


def _user_limit_rooms() -> list[int]:
    """Room under this user's process limit (`ulimit -u`), which counts threads too on Linux and binds no root."""
    if sys.platform == "win32" or os.geteuid() == 0:
        return []
    limit, _ = resource.getrlimit(resource.RLIMIT_NPROC)
    if limit == resource.RLIM_INFINITY:
        return []
    uid = os.getuid()
    used = 0
    for process in psutil.process_iter():
        with contextlib.suppress(psutil.Error), process.oneshot():
            if process.uids().real == uid:
                used += process.num_threads() if sys.platform == "linux" else 1
    return [limit - used]
