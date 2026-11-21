"""Command-line GTFS import (safe, staged, repeatable).

    python -m scripts.import_gtfs                      # import GTFS_ZIP into DATABASE_PATH
    python -m scripts.import_gtfs --validate-only      # full validation, database untouched
    python -m scripts.import_gtfs --zip X.zip --database Y.sqlite3

Exit codes: 0 success, 1 import/validation failure, 2 bad configuration or arguments.
The existing database is replaced only after the new one is fully validated; if
anything fails it is left exactly as it was.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.config import ConfigError, Settings
from app.gtfs.errors import GtfsImportError
from app.gtfs.importer import ImportReport, import_gtfs, previous_path, status_path
from app.logging_config import configure_logging


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m scripts.import_gtfs", description=__doc__.split("\n\n")[0])
    parser.add_argument("--zip", type=Path, help="GTFS ZIP to import (default: GTFS_ZIP setting)")
    parser.add_argument("--database", type=Path, help="Target SQLite file (default: DATABASE_PATH setting)")
    parser.add_argument("--validate-only", action="store_true",
                        help="Validate and build a throw-away database, but do not replace the live one")
    parser.add_argument("--json", action="store_true", help="Print the final report as JSON")
    return parser.parse_args(argv)


def _print_report(report: ImportReport, *, failed: bool) -> None:
    line = "-" * 64
    print(line)
    print(f"GTFS IMPORT {report.status.upper()}")
    print(line)
    if report.message:
        print(report.message)
    print(f"Source   : {report.source_zip}")
    print(f"Database : {report.database}")
    if report.gtfs_root:
        print(f"GTFS root: {report.gtfs_root}")
    if report.table_counts:
        print("Imported rows per table:")
        for table, count in report.table_counts.items():
            print(f"  {table:<16}{count:>12,}")
    elif report.counts:
        print("Imported rows:")
        for table, count in report.counts.items():
            print(f"  {table:<15}{count:>12,}")
    for detail in report.file_details:
        rejected = f", {detail['rows_rejected']:,} REJECTED" if detail["rows_rejected"] else ""
        extra = detail["columns"].get("extension_stored") or []
        print(f"  file {detail['file']:<22}{detail['rows_imported']:>12,} rows{rejected}"
              + (f"  [non-GTFS columns stored: {', '.join(extra)}]" if extra else ""))
    if report.missing_optional_files:
        print("Optional files not in the feed: " + ", ".join(report.missing_optional_files))
    quality = report.data_quality
    if quality:
        checks = quality["integrity_checks"]
        by_status = {k: sum(c["status"] == k for c in checks) for k in ("passed", "failed", "skipped")}
        print(f"Data quality: {quality['status'].upper()}  ({quality['error_count']} errors, {quality['warning_count']} "
              f"warnings, {quality['info_count']} info)")
        print(f"Integrity checks: {by_status['passed']} passed, {by_status['failed']} reported a finding, "
              f"{by_status['skipped']} skipped (nothing to check: optional table is empty)")
        for finding in quality["findings"]:
            if finding["severity"] == "info":
                print(f"INFO: {finding['message']}")
    if report.previous_counts:
        print("Previous database rows: " + ", ".join(f"{t}={c:,}" for t, c in report.previous_counts.items()))
    if report.promoted and report.previous_database:
        print(f"Previous database kept as: {report.previous_database}")
    for warning in report.warnings:
        print(f"WARNING: {warning}")
    if failed:
        print(f"Failed during phase: {report.phase}")
        print(f"Problems found: {report.error_count:,} (showing {len(report.errors)})")
        for record in report.errors:
            where = record.get("file", "")
            if record.get("line"):
                where += f":{record['line']}"
            print(f"  - {where}: {record.get('message')}")
        print("The existing database (if any) was NOT modified.")
    print(f"Duration : {report.duration_seconds:.1f}s")
    print(line)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    configure_logging(settings.log_level)

    zip_path = (args.zip or settings.gtfs_zip).resolve()
    database = (args.database or settings.database_path).resolve()
    try:
        report = import_gtfs(zip_path, database, validate_only=args.validate_only)
    except GtfsImportError as exc:
        if args.json and exc.report:
            print(json.dumps(exc.report.to_dict(), indent=2))
        elif exc.report:
            _print_report(exc.report, failed=True)
        else:  # e.g. lock held by another import: no report exists
            print(f"Import not started: {exc.message}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        _print_report(report, failed=False)
        print(f"Status file: {status_path(database).name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
