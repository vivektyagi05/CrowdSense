"""Pre-import GTFS archive inspection and validation.

Nothing here touches the database. The goal is to reject a bad archive cheaply
and with a complete list of problems, before any import work starts, and to tell
the operator exactly which files and columns will (and will not) be imported.
"""

from __future__ import annotations

import csv
import io
import posixpath
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from app.gtfs.errors import GtfsArchiveError
from app.gtfs.spec import (
    RECOGNISED_UNIMPORTED_FILES,
    REQUIRED_SPECS,
    SERVICE_SPECS,
    SPEC_BY_FILE,
    TABLE_SPECS,
    TableSpec,
)

# Guard against decompression bombs / wrong files. Delhi feed is ~130 MB uncompressed.
MAX_UNCOMPRESSED_BYTES = 8 * 1024**3
PHASE = "archive_validation"


@dataclass(frozen=True)
class GtfsArchive:
    zip_path: Path
    root: str  # "" for root-level files, else "folder/"
    members: dict[str, str]  # GTFS filename -> exact member name inside the ZIP (supported files that are present)
    headers: dict[str, tuple[str, ...]]  # GTFS filename -> header columns
    # Phase 0 name, kept: GTFS-defined files that are recognised but intentionally not imported.
    ignored_known_files: tuple[str, ...] = ()
    warnings: tuple[str, ...] = field(default_factory=tuple)
    uncompressed_bytes: int = 0
    missing_optional_files: tuple[str, ...] = ()  # supported optional files that the feed does not contain
    unrecognised_files: tuple[str, ...] = ()  # files in the GTFS folder that are not part of GTFS Schedule
    # filename -> {"standard": [...], "extension_stored": [...], "unsupported": [...]}
    column_report: dict[str, dict[str, list[str]]] = field(default_factory=dict)


def _normalise(name: str) -> str:
    return name.replace("\\", "/")


def _is_junk(name: str) -> bool:
    base = posixpath.basename(name)
    return name.startswith("__MACOSX/") or base.startswith("._") or base == ".DS_Store" or base == "Thumbs.db"


def read_header(zf: zipfile.ZipFile, member: str) -> tuple[str, ...]:
    """Return the stripped header row of a CSV member (raises ValueError if empty)."""
    with zf.open(member) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
        reader = csv.reader(text)
        try:
            header = next(reader)
        except StopIteration:
            raise ValueError("file is empty (no header row)") from None
    return tuple(cell.strip() for cell in header)


def iter_rows(zf: zipfile.ZipFile, member: str) -> Iterator[tuple[int, list[str]]]:
    """Yield ``(line_number, row)`` for every data row, skipping fully blank lines.

    Streams from the ZIP; never materialises the file.
    """
    with zf.open(member) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
        reader = csv.reader(text)
        next(reader, None)  # header
        for row in reader:
            if not row:
                continue
            yield reader.line_num, row


def inspect_archive(zip_path: Path) -> GtfsArchive:
    """Validate ``zip_path`` and locate the GTFS files inside it.

    Accepts files at the ZIP root *or* inside a single nested directory (the
    layout of the Delhi feed). Raises :class:`GtfsArchiveError` listing every
    problem found.
    """
    if not zip_path.is_file():
        raise GtfsArchiveError(f"GTFS ZIP not found: {zip_path}", phase=PHASE,
                               errors=[{"file": zip_path.name, "message": "file does not exist"}])
    if not zipfile.is_zipfile(zip_path):
        raise GtfsArchiveError(f"{zip_path.name} is not a valid ZIP archive", phase=PHASE,
                               errors=[{"file": zip_path.name, "message": "not a ZIP archive"}])

    try:
        with zipfile.ZipFile(zip_path) as zf:
            bad = zf.testzip()  # verifies CRCs of every member
            if bad is not None:
                raise GtfsArchiveError(f"ZIP is corrupt: bad CRC in {bad}", phase=PHASE,
                                       errors=[{"file": bad, "message": "CRC check failed"}])
            infos = [i for i in zf.infolist() if not i.is_dir() and not _is_junk(_normalise(i.filename))]
            total = sum(i.file_size for i in infos)
            if total > MAX_UNCOMPRESSED_BYTES:
                raise GtfsArchiveError(
                    f"Archive expands to {total:,} bytes, above the {MAX_UNCOMPRESSED_BYTES:,} byte safety limit",
                    phase=PHASE, errors=[{"file": zip_path.name, "message": "uncompressed size too large"}])
            return _inspect_members(zf, zip_path, infos, total)
    except zipfile.BadZipFile as exc:
        raise GtfsArchiveError(f"{zip_path.name} is not a readable ZIP archive: {exc}", phase=PHASE,
                               errors=[{"file": zip_path.name, "message": str(exc)}]) from exc


def _check_header(spec: TableSpec, header: tuple[str, ...]) -> list[dict[str, str]]:
    problems: list[dict[str, str]] = []
    duplicates = sorted({c for c in header if header.count(c) > 1})
    if duplicates:
        problems.append({"file": spec.filename, "message": f"duplicate header column(s): {', '.join(duplicates)}"})
    if any(not c for c in header):
        problems.append({"file": spec.filename, "message": "header contains an empty column name"})
    if spec.needs_one_of and not set(spec.needs_one_of) & set(header):
        problems.append({"file": spec.filename,
                         "message": f"needs at least one of {' / '.join(spec.needs_one_of)} columns"})
    missing = [c for c in spec.required_columns if c not in header]
    if missing:
        problems.append({"file": spec.filename, "message": f"missing required column(s): {', '.join(missing)}"})
    return problems


def _inspect_members(zf: zipfile.ZipFile, zip_path: Path, infos: list[zipfile.ZipInfo], total: int) -> GtfsArchive:
    by_dir: dict[str, dict[str, str]] = {}
    for info in infos:
        norm = _normalise(info.filename)
        directory = posixpath.dirname(norm)
        by_dir.setdefault(directory, {})[posixpath.basename(norm)] = info.filename

    required_names = [spec.filename for spec in REQUIRED_SPECS]
    candidates = [d for d, files in by_dir.items() if all(n in files for n in required_names)]
    warnings: list[str] = []

    if not candidates:
        problems = _describe_missing(by_dir, required_names)
        raise GtfsArchiveError("GTFS archive is incomplete: " + "; ".join(e["message"] for e in problems),
                               phase=PHASE, errors=problems)
    if "" in candidates:
        directory = ""
        others = [d for d in candidates if d]
        if others:
            warnings.append(f"GTFS files also found in nested folder(s) {others}; using the ZIP root")
    elif len(candidates) == 1:
        directory = candidates[0]
    else:
        raise GtfsArchiveError(
            f"Ambiguous archive: complete GTFS file sets found in multiple folders: {sorted(candidates)}",
            phase=PHASE, errors=[{"file": zip_path.name, "message": f"multiple GTFS roots: {sorted(candidates)}"}])

    files = by_dir[directory]
    present_service = [spec for spec in SERVICE_SPECS if spec.filename in files]
    if not present_service:
        raise GtfsArchiveError(
            "GTFS archive needs calendar.txt and/or calendar_dates.txt (service calendars are required)",
            phase=PHASE, errors=[{"file": "calendar.txt", "message": "neither calendar.txt nor calendar_dates.txt present"}])

    # Every supported file that is present gets its header validated, required or not.
    specs: list[TableSpec] = [spec for spec in TABLE_SPECS if spec.filename in files]
    headers: dict[str, tuple[str, ...]] = {}
    problems: list[dict[str, str]] = []
    column_report: dict[str, dict[str, list[str]]] = {}
    for spec in specs:
        member = files[spec.filename]
        try:
            header = read_header(zf, member)
        except ValueError as exc:
            problems.append({"file": spec.filename, "message": str(exc)})
            continue
        except UnicodeDecodeError:
            problems.append({"file": spec.filename, "message": "file is not valid UTF-8"})
            continue
        except csv.Error as exc:
            problems.append({"file": spec.filename, "message": f"malformed CSV header: {exc}"})
            continue
        problems.extend(_check_header(spec, header))
        headers[spec.filename] = header
        known = set(spec.column_names)
        column_report[spec.filename] = {
            "standard": [c for c in header if c in set(spec.standard_columns)],
            "extension_stored": [c for c in header if c in set(spec.extension_columns)],
            "unsupported": [c for c in header if c and c not in known],
        }

    if problems:
        raise GtfsArchiveError("GTFS header validation failed: " +
                               "; ".join(f"{p['file']}: {p['message']}" for p in problems),
                               phase=PHASE, errors=problems)

    members = {spec.filename: files[spec.filename] for spec in specs}
    ignored = tuple(sorted(n for n in files if n in RECOGNISED_UNIMPORTED_FILES))
    unrecognised = tuple(sorted(n for n in files if n not in SPEC_BY_FILE and n not in RECOGNISED_UNIMPORTED_FILES))
    missing_optional = tuple(spec.filename for spec in TABLE_SPECS
                             if not spec.required_file and spec.filename not in files)
    return GtfsArchive(zip_path=zip_path, root=f"{directory}/" if directory else "", members=members, headers=headers,
                       ignored_known_files=ignored, warnings=tuple(warnings), uncompressed_bytes=total,
                       missing_optional_files=missing_optional, unrecognised_files=unrecognised,
                       column_report=column_report)


def _describe_missing(by_dir: dict[str, dict[str, str]], required_names: list[str]) -> list[dict[str, str]]:
    if not by_dir or not any(n in files for files in by_dir.values() for n in required_names):
        return [{"file": ", ".join(required_names), "message": "no GTFS files found in archive"}]
    # Report against the folder that holds the most required files (the likely intended root).
    best = max(by_dir, key=lambda d: (sum(n in by_dir[d] for n in required_names), -len(d)))
    return [{"file": name, "message": f"missing required file {name}" + (f" in {best}/" if best else "")}
            for name in required_names if name not in by_dir[best]]
