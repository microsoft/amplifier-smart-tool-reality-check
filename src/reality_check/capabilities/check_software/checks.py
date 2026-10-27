"""Every check on this machine, and one check in full with its evidence files."""

from datetime import UTC, datetime
import mimetypes
import os
from pathlib import Path, PurePosixPath
import re
import stat
from urllib.parse import quote

from pydantic import ValidationError

from reality_check.capabilities.check_software.record import (
    CHECK_ID_PATTERN,
    EVIDENCE,
    RECORD,
    REPORT,
    check_state,
    load_record,
    read_atomically,
)
from reality_check.capabilities.check_software.registry import project_root, registered_projects
from reality_check.schemas import (
    CheckDetail,
    CheckRecord,
    CheckReference,
    CheckSummary,
    EvidenceEntry,
    EvidenceFile,
    Project,
    RealityCheckError,
)

MAX_EVIDENCE_BYTES = 50 * 1024 * 1024
# Types a viewer would run rather than show, as are all `+xml` types; their text is evidence, their behavior is not.
ACTIVE_TYPES = {
    "text/html",
    "text/xml",
    "application/xml",
    "text/javascript",
    "application/javascript",
    "application/xhtml+xml",
    "image/svg+xml",
}
# One name in a path: no separator or drive of any platform, since a Windows path takes both from a POSIX-looking one.
PLAIN_NAME = re.compile(r"^[^\\/:\x00]+$")
# Where a path stops in Markdown or prose: whitespace, quotes, and the brackets that wrap links.
PATH_CHARACTERS = r"[^\s()\[\]<>\"'`]"
# The punctuation that ends a sentence after a path is not part of it.
PATH_END = r"[^\s()\[\]<>\"'`.,;:!?]"


def list_checks(checks_directory: Path | None = None) -> list[CheckSummary]:
    """Every check in `checks_directory`, or in every registered project when it is None, newest first."""
    projects = registered_projects() if checks_directory is None else [_project(checks_directory.resolve())]
    summaries = [
        _summary(record, project, project.checks_directory / record.check_id)
        for project in projects
        for record in _records(project.checks_directory)
    ]
    return sorted(summaries, key=lambda summary: summary.started_at, reverse=True)


def read_check(check_id: str, checks_directory: Path) -> CheckDetail:
    """One check as it stands: its record, its report with portable evidence links, and the evidence it has so far."""
    root = checks_directory.resolve()
    record = load_record(root, check_id)
    directory = root / check_id
    report_path = directory / REPORT
    # A report that is a link could name any file on the machine.
    readable = report_path.is_file() and not report_path.is_symlink()
    report = _portable(read_atomically(report_path), directory) if readable else None
    return CheckDetail(
        check=record,
        state=check_state(record),
        project=_project(root),
        directory=directory,
        report=report,
        evidence=_evidence(directory, report or ""),
        resumes=CheckReference(check_id=record.resume, checks_directory=root) if record.resume else None,
        previous_checks=[
            CheckReference(check_id=path.name, checks_directory=path.parent) for path in record.previous_checks or []
        ],
    )


def read_check_evidence(check_id: str, path: str, checks_directory: Path) -> EvidenceFile:
    """One file from a check's evidence folder; nothing outside that folder, and no link out of it, is read."""
    root = checks_directory.resolve()
    load_record(root, check_id)
    evidence = root / check_id / EVIDENCE
    relative = PurePosixPath(path)
    names = relative.parts[1:]
    if relative.parts[:1] != (EVIDENCE,) or not names or any(_unsafe(name) for name in names):
        raise _not_evidence(check_id, path, "is not a path inside the check's evidence folder")
    candidate = evidence.joinpath(*names)
    if not _unlinked(candidate):
        raise _not_evidence(check_id, path, "is not a file in the check's evidence folder, or is reached by a link")
    # Opened once, without following a link in its last step, and checked again through the open file, so a link
    # put in its place after the check above is not read.
    try:
        descriptor = os.open(candidate, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
    except OSError:
        raise _not_evidence(check_id, path, "is not a file in the check's evidence folder") from None
    with os.fdopen(descriptor, "rb") as file:
        status = os.fstat(file.fileno())
        if (
            not stat.S_ISREG(status.st_mode)
            or not _unlinked(candidate)
            or not os.path.samestat(status, candidate.lstat())
        ):
            raise _not_evidence(check_id, path, "is not a file in the check's evidence folder, or is reached by a link")
        if status.st_size > MAX_EVIDENCE_BYTES:
            raise RealityCheckError(
                code="evidence-too-large",
                message=f"{path} in check {check_id} is {status.st_size} bytes, more than the {MAX_EVIDENCE_BYTES} "
                "read at once.",
                remedy=f"Open it from {candidate} directly.",
            )
        content = file.read(MAX_EVIDENCE_BYTES + 1)
    return EvidenceFile(path=path, media_type=_media_type(candidate), content=content)


def _project(checks_directory: Path) -> Project:
    for project in registered_projects():
        if os.path.normcase(project.checks_directory) == os.path.normcase(checks_directory):
            return project
    return Project(root=project_root(checks_directory), checks_directory=checks_directory)


def _records(checks_directory: Path) -> list[CheckRecord]:
    records = []
    for path in checks_directory.glob(f"*/{RECORD}"):
        if not CHECK_ID_PATTERN.match(path.parent.name):
            continue
        try:
            records.append(CheckRecord.model_validate_json(read_atomically(path)))
        except (OSError, ValidationError):
            # A record being written for the first time, or one this version cannot read, is left out of the list.
            continue
    return records


def _summary(record: CheckRecord, project: Project, directory: Path) -> CheckSummary:
    return CheckSummary(
        check_id=record.check_id,
        project=project,
        request=record.request,
        target=record.target,
        state=check_state(record),
        started_at=record.started_at,
        ended_at=record.ended_at,
        agent_provider=record.agent_provider,
        model=record.model,
        origin=record.origin,
        resume=record.resume,
        has_report=(directory / REPORT).is_file(),
    )


def _portable(report: str, directory: Path) -> str:
    """The report with every path into this check's evidence folder, absolute or not, written as `evidence/<name>`."""
    # Angle-bracket Markdown destinations can contain spaces, unlike paths in ordinary prose.
    report = re.sub(
        rf"(?<=<)[^<>\r\n]*?{re.escape(directory.name)}[\\/]{EVIDENCE}((?:[\\/][^<>\r\n]*)?)(?=>)",
        lambda match: f"{EVIDENCE}{match.group(1).replace(chr(92), '/')}",
        report,
    )
    # Anchored to where a path starts, so each run of path characters is scanned once, however long.
    folder = rf"(?<!{PATH_CHARACTERS}){PATH_CHARACTERS}*?[\\/]?{re.escape(directory.name)}[\\/]{EVIDENCE}"
    report = re.sub(
        rf"{folder}[\\/]({PATH_CHARACTERS}*{PATH_END})",
        lambda match: f"{EVIDENCE}/{match.group(1).replace(chr(92), '/')}",
        report,
    )
    return re.sub(rf"{folder}[\\/]?(?!{PATH_CHARACTERS})", f"{EVIDENCE}/", report)


def _cited(relative: str, report: str) -> bool:
    """Whether the report names the file by its path in the check, or by its path inside the evidence folder alone."""
    inside = relative.removeprefix(f"{EVIDENCE}/")
    return any(
        re.search(rf"(?<![\w./-]){re.escape(name)}(?![\w/-])", report)
        for name in {relative, quote(relative), inside, quote(inside)}
    )


def _evidence(directory: Path, report: str) -> list[EvidenceEntry]:
    evidence = directory / EVIDENCE
    if not evidence.is_dir() or evidence.is_symlink():
        return []
    entries = []
    # rglob does not walk into linked folders, so a link can only be the file itself.
    for path in sorted(evidence.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        relative = path.relative_to(directory).as_posix()
        stat = path.stat()
        entries.append(
            EvidenceEntry(
                path=relative,
                media_type=_media_type(path),
                size=stat.st_size,
                modified_at=datetime.fromtimestamp(stat.st_mtime, UTC),
                referenced=_cited(relative, report),
            )
        )
    return entries


def _media_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    if guessed is None:
        return "application/octet-stream"
    if guessed in ACTIVE_TYPES or guessed.endswith("+xml"):
        return "text/plain"
    return guessed


def _unsafe(name: str) -> bool:
    return name in {".", ".."} or not PLAIN_NAME.match(name)


def _unlinked(path: Path) -> bool:
    """Whether `path` is a file reached through no link or junction, since resolving follows every one of them."""
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        return False
    return os.path.normcase(resolved) == os.path.normcase(path) and resolved.is_file()


def _not_evidence(check_id: str, path: str, why: str) -> RealityCheckError:
    return RealityCheckError(
        code="not-evidence",
        message=f"{path!r} {why}.",
        remedy=f"Name a path from the `evidence` list of `reality-check read-check --check-id {check_id}`.",
    )
