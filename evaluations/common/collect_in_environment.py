"""Runs inside the evaluation environment after the capability, as root, with the system Python's standard library.

`collect_in_environment.py CONFIG` gathers, into one directory, everything that shows what the agent did: its
record, its session and logs, every file it made or changed since the baseline, what is installed now, and the
containers on the nested Docker daemon. `collect.py` on the host imports PACKAGE_LISTS and `installed_diff` from
here, so the baseline needs no file in the environment.
"""

import difflib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

WORK = Path("/var/lib/evaluation")
USER = "user"
HOME = Path("/home/user")
# Never part of what the agent did: kernel and runtime views, the nested daemon's data, and the evaluation's own files.
SKIPPED = {Path("/proc"), Path("/sys"), Path("/dev"), Path("/run"), Path("/var/lib/docker"), WORK}
# Mount points other than the root that hold files a person or agent writes.
WALKED_MOUNTS = {Path("/tmp")}
# Changes under these are installs and caches: listed, never copied.
BULK = (
    "/usr/",
    "/opt/",
    "/var/lib/apt/",
    "/var/lib/dpkg/",
    "/var/cache/",
    "/var/log/",
    f"{HOME}/.cache/",
    f"{HOME}/.local/share/uv/",
    f"{HOME}/.npm/",
)
BULK_PARTS = ("node_modules", "site-packages", "__pycache__", ".git")
# Installs the agent made inside its own directories; changes.json still lists every file in them.
IGNORED_IN_COPIES = shutil.ignore_patterns(*BULK_PARTS, ".venv", "*-venv", "ms-playwright")
FILE_LIMIT_BYTES = 5 * 1024**2
TOTAL_LIMIT_BYTES = 1024**3
CONTAINER_LIMIT_BYTES = 200 * 1024**2
# What a person would check to see what they installed; a command that is missing records that.
PACKAGE_LISTS = {
    "dpkg.txt": ["dpkg-query", "-W", "-f", "${Package} ${Version}\n"],
    "uv-tools.txt": ["runuser", "-u", USER, "--", "sh", "-lc", "uv tool list --show-paths"],
    "pip-user.txt": ["runuser", "-u", USER, "--", "sh", "-lc", "python3 -m pip list --user 2>&1"],
    "npm-global.txt": ["runuser", "-u", USER, "--", "sh", "-lc", "npm ls -g --depth=0 2>&1"],
    "playwright-browsers.txt": ["runuser", "-u", USER, "--", "sh", "-lc", "ls -1 ~/.cache/ms-playwright 2>&1"],
}


def collect(config_path: Path) -> None:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    out = Path(config["out"])
    out.mkdir(parents=True, exist_ok=True)
    since = float(config["since"])

    check = config.get("check_directory")
    if check and Path(check).is_dir():
        shutil.copytree(check, out / "check", symlinks=True, ignore=IGNORED_IN_COPIES)
        session_id = json.loads((Path(check) / "check.json").read_text(encoding="utf-8")).get("session_id")
        # A check keeps its session in its record; one resumed from a check made before that leaves it where the
        # agent provider keeps its sessions.
        kept = Path(check) / "session"
        session = kept if kept.is_dir() else Path(config["sessions"]) / str(session_id)
        if session_id and session.is_dir():
            shutil.copytree(session, out / "session", symlinks=True, ignore=IGNORED_IN_COPIES)
    for logs in config.get("logs", []):
        if Path(logs).is_dir():
            shutil.copytree(logs, out / "logs" / "harness" / Path(logs).name, symlinks=True)

    _package_lists(out / "packages" / "after")
    _changes(since, out)
    _containers(out / "logs" / "docker")
    state = HOME / ".digital-twin-universe"
    if state.is_dir():
        _copy_tree_limited(state, out / "logs" / "dtu-state")


def _package_lists(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name, command in PACKAGE_LISTS.items():
        try:
            listed = subprocess.run(command, capture_output=True, text=True).stdout
        except FileNotFoundError:
            listed = f"{command[0]} is not installed\n"
        (directory / name).write_text(listed, encoding="utf-8")


def installed_diff(before: Path, after: Path, destination: Path) -> None:
    lines: list[str] = []
    for name in PACKAGE_LISTS:
        old = (before / name).read_text(encoding="utf-8").splitlines(keepends=True)
        new = (after / name).read_text(encoding="utf-8").splitlines(keepends=True)
        lines.extend(difflib.unified_diff(old, new, f"before/{name}", f"after/{name}"))
    destination.write_text("".join(lines), encoding="utf-8")


def _changes(since: float, out: Path) -> None:
    """Every file and link made or changed since the baseline, listed; the small ones outside BULK copied."""
    changes: list[dict] = []
    copied_bytes = 0
    for top in [Path("/"), *WALKED_MOUNTS]:
        for directory, subdirectories, files in os.walk(top):
            here = Path(directory)
            # Another mount is either one of WALKED_MOUNTS, walked from its own top, or not the machine's disk.
            subdirectories[:] = [
                name for name in subdirectories if here / name not in SKIPPED and not os.path.ismount(here / name)
            ]
            for name in files:
                path = here / name
                try:
                    status = path.lstat()
                except OSError:
                    continue
                if max(status.st_mtime, status.st_ctime) <= since:
                    continue
                entry: dict = {"path": str(path), "bytes": status.st_size, "copied": False}
                if path.is_symlink():
                    entry["link"] = str(path.readlink())
                elif _copyable(path, status.st_size) and copied_bytes + status.st_size <= TOTAL_LIMIT_BYTES:
                    target = out / "changes" / path.relative_to("/")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        shutil.copy2(path, target)
                        entry["copied"] = True
                        copied_bytes += status.st_size
                    except OSError:
                        pass
                changes.append(entry)
    changes.sort(key=lambda each: each["path"])
    (out / "changes.json").write_text(json.dumps(changes, indent=1), encoding="utf-8")


def _copyable(path: Path, size: int) -> bool:
    text = str(path)
    return size <= FILE_LIMIT_BYTES and not text.startswith(BULK) and not set(path.parts) & set(BULK_PARTS)


def _containers(out: Path) -> None:
    """Logs, configuration, and changed files of every container on the nested daemon, stopped ones included."""
    out.mkdir(parents=True, exist_ok=True)
    listed = subprocess.run(["docker", "ps", "-a", "--format", "{{json .}}"], capture_output=True, text=True)
    containers = [json.loads(line) for line in listed.stdout.splitlines() if line.strip()]
    (out / "containers.json").write_text(json.dumps(containers, indent=1), encoding="utf-8")
    for container in containers:
        name = container["Names"]
        directory = out / name
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / "logs.txt").open("w", encoding="utf-8") as logs:
            subprocess.run(["docker", "logs", "--timestamps", name], stdout=logs, stderr=subprocess.STDOUT)
        inspected = subprocess.run(["docker", "inspect", name], capture_output=True, text=True).stdout
        (directory / "inspect.json").write_text(inspected, encoding="utf-8")
        diff = subprocess.run(["docker", "diff", name], capture_output=True, text=True).stdout
        (directory / "diff.txt").write_text(diff, encoding="utf-8")
        changed = sorted(line[2:] for line in diff.splitlines() if line[:1] in ("A", "C"))
        # Only the deepest paths, so a changed directory does not pull in everything under it.
        leaves = [
            path
            for index, path in enumerate(changed)
            if not any(other.startswith(path + "/") for other in changed[index + 1 :])
        ]
        copied = 0
        for path in leaves:
            if copied > CONTAINER_LIMIT_BYTES or not _copyable(Path(path), 0):
                continue
            target = directory / "files" / path.lstrip("/")
            target.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["docker", "cp", f"{name}:{path}", str(target)], capture_output=True)
            if target.is_file():
                copied += target.stat().st_size


def _copy_tree_limited(source: Path, destination: Path) -> None:
    for path in source.rglob("*"):
        if path.is_file() and not path.is_symlink() and path.stat().st_size <= FILE_LIMIT_BYTES:
            target = destination / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


if __name__ == "__main__":
    match sys.argv[1:]:
        case [config]:
            collect(Path(config))
        case _:
            sys.exit("usage: collect.py CONFIG")
