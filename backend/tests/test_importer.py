import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from app.gtfs import importer
from app.gtfs.errors import GtfsArchiveError, GtfsDataError, GtfsImportError, ImportLockedError, PromotionError
from app.gtfs.importer import (import_gtfs, lock_path, previous_path, read_import_status, staging_path, status_path)
from tests.gtfs_factory import FILES, build_zip

EXPECTED = {"stops": 4, "routes": 2, "trips": 4, "stop_times": 10, "calendar": 1, "calendar_dates": 2}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def counts(db: Path) -> dict:
    c = sqlite3.connect(db)
    try:
        return {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in EXPECTED}
    finally:
        c.close()


def run(zip_path, db, **kw):
    return import_gtfs(zip_path, db, promote_retries=0, **kw)


def assert_clean(db: Path):
    assert not staging_path(db).exists() and not lock_path(db).exists()
    assert not list(db.parent.glob("*.staging*"))


def test_successful_import(tmp_path, feed_zip):
    db = tmp_path / "d" / "x.sqlite3"
    r = run(feed_zip, db)
    assert r.status == "success" and r.promoted and r.counts == EXPECTED and counts(db) == EXPECTED
    assert_clean(db)
    c = sqlite3.connect(db)
    assert c.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert c.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    meta = dict(c.execute("SELECT key, value FROM import_meta"))
    c.close()
    assert meta["source_sha256"] == sha(feed_zip) and json.loads(meta["counts"]) == EXPECTED
    st = read_import_status(db)
    assert st["status"] == "success" and st["finished_at"] and st["counts"] == EXPECTED


def test_nested_zip_imports(tmp_path):
    db = tmp_path / "x.sqlite3"
    r = run(build_zip(tmp_path / "n.zip", nested=True), db)
    assert r.gtfs_root == "feed_v1/" and counts(db) == EXPECTED


def test_calendar_dates_only_feed(tmp_path):
    db = tmp_path / "x.sqlite3"
    run(build_zip(tmp_path / "z.zip", overrides={"calendar.txt": None,
        "trips.txt": "route_id,service_id,trip_id\nR1,S2,T4\n",
        "stop_times.txt": "trip_id,arrival_time,departure_time,stop_id,stop_sequence\nT4,10:00:00,10:00:00,A,1\nT4,10:30:00,10:30:00,D,2\n"}), db)
    assert counts(db)["calendar"] == 0 and counts(db)["trips"] == 1


def test_short_hours_are_zero_padded(tmp_path):
    db = tmp_path / "x.sqlite3"
    run(build_zip(tmp_path / "z.zip", overrides={"stop_times.txt": FILES["stop_times.txt"].replace("T1,08:00:00,08:00:00", "T1,8:00:00,8:00:00")}), db)
    c = sqlite3.connect(db)
    assert c.execute("SELECT departure_time FROM stop_times WHERE trip_id='T1' AND stop_sequence=1").fetchone()[0] == "08:00:00"
    c.close()


def test_repeat_import_has_no_duplicates_and_keeps_previous(tmp_path, feed_zip):
    db = tmp_path / "x.sqlite3"
    run(feed_zip, db)
    first = sha(db)
    r = run(feed_zip, db)
    assert counts(db) == EXPECTED and r.previous_counts["stop_times"] == 10
    assert previous_path(db).exists() and sha(previous_path(db)) == first
    run(feed_zip, db)  # a third time: still exactly one generation kept
    assert counts(db) == EXPECTED and counts(previous_path(db)) == EXPECTED
    assert_clean(db)


BAD_FEEDS = {
    "bad_latitude": {"stops.txt": "stop_id,stop_name,stop_lat,stop_lon\nA,Alpha,99.5,77.2\n"},
    "duplicate_stop_id": {"stops.txt": FILES["stops.txt"] + "A,Again,28.6,77.2\n"},
    "duplicate_trip_sequence": {"stop_times.txt": FILES["stop_times.txt"] + "T1,08:30:00,08:30:00,D,3\n"},
    "orphan_stop_reference": {"stop_times.txt": FILES["stop_times.txt"] + "T1,08:30:00,08:30:00,ZZZ,9\n"},
    "orphan_trip_reference": {"stop_times.txt": FILES["stop_times.txt"] + "NOPE,08:30:00,08:30:00,A,1\n"},
    "orphan_route": {"trips.txt": FILES["trips.txt"] + "RX,S1,T9\n"},
    "orphan_service": {"trips.txt": FILES["trips.txt"] + "R1,SX,T9\n"},
    "bad_time": {"stop_times.txt": FILES["stop_times.txt"] + "T1,8am,08:30:00,D,9\n"},
    "bad_sequence": {"stop_times.txt": FILES["stop_times.txt"] + "T1,08:30:00,08:30:00,D,x\n"},
    "short_row": {"stop_times.txt": FILES["stop_times.txt"] + "T1,08:30:00\n"},
    "bad_calendar_day": {"calendar.txt": FILES["calendar.txt"].replace(",1,1,1,1,1,1,1,", ",1,1,1,1,1,1,2,")},
    "bad_exception_type": {"calendar_dates.txt": "service_id,date,exception_type\nS2,20261109,3\n"},
    "empty_stop_name": {"stops.txt": FILES["stops.txt"] + "E, ,28.6,77.2\n"},
}


@pytest.mark.parametrize("name", sorted(BAD_FEEDS))
def test_failed_import_preserves_previous_database(tmp_path, feed_zip, name):
    db = tmp_path / "x.sqlite3"
    run(feed_zip, db)
    before = sha(db)
    bad = build_zip(tmp_path / "bad.zip", overrides=BAD_FEEDS[name])
    with pytest.raises(GtfsDataError) as e:
        run(bad, db)
    assert sha(db) == before and counts(db) == EXPECTED
    assert e.value.report.status == "failed" and e.value.report.error_count >= 1 and e.value.errors
    st = read_import_status(db)
    assert st["status"] == "failed" and st["error_count"] >= 1
    assert_clean(db)


def test_bad_row_errors_carry_file_and_line(tmp_path):
    bad = build_zip(tmp_path / "bad.zip", overrides=BAD_FEEDS["bad_latitude"])
    with pytest.raises(GtfsDataError) as e:
        run(bad, tmp_path / "x.sqlite3")
    rec = e.value.errors[0]
    assert rec["file"] == "stops.txt" and rec["line"] == 2 and "stop_lat" in rec["message"]
    assert not (tmp_path / "x.sqlite3").exists()  # nothing was ever created


def test_archive_failure_preserves_database(tmp_path, feed_zip):
    db = tmp_path / "x.sqlite3"
    run(feed_zip, db)
    before = sha(db)
    with pytest.raises(GtfsArchiveError):
        run(build_zip(tmp_path / "b.zip", overrides={"stops.txt": None}), db)
    assert sha(db) == before and read_import_status(db)["phase"] == "archive_validation"


def test_validate_only_never_touches_database(tmp_path, feed_zip):
    db = tmp_path / "x.sqlite3"
    r = run(feed_zip, db, validate_only=True)
    assert r.status == "validated" and not r.promoted and not db.exists()
    run(feed_zip, db)
    before = sha(db)
    run(feed_zip, db, validate_only=True)
    assert sha(db) == before and not previous_path(db).exists()
    assert_clean(db)


def test_small_batches_cross_boundaries(tmp_path, feed_zip):
    db = tmp_path / "x.sqlite3"
    run(feed_zip, db, batch_size=3)
    assert counts(db) == EXPECTED


def test_concurrent_import_is_refused(tmp_path, feed_zip):
    db = tmp_path / "x.sqlite3"
    lock_path(db).write_text('{"pid": 1}')
    with pytest.raises(ImportLockedError):
        run(feed_zip, db)
    assert lock_path(db).exists()  # the other import's lock is not removed
    assert not db.exists()


def test_database_in_use_blocks_promotion_and_keeps_old(tmp_path, feed_zip):
    db = tmp_path / "x.sqlite3"
    run(feed_zip, db)
    before = sha(db)
    holder = sqlite3.connect(db)
    holder.execute("SELECT COUNT(*) FROM stops").fetchone()  # keeps -wal/-shm alive
    try:
        with pytest.raises(PromotionError) as e:
            run(feed_zip, db)
    finally:
        holder.close()
    assert "in use" in e.value.message and sha(db) == before
    assert_clean(db)
    run(feed_zip, db)  # works once the holder is gone
    assert counts(db) == EXPECTED


def test_stale_wal_sidecars_are_not_carried_to_new_database(tmp_path, feed_zip):
    live = tmp_path / "live.sqlite3"
    run(feed_zip, live)
    # Simulate a crash: a database whose newest data exists only in its WAL.
    writer = sqlite3.connect(live)
    writer.execute("PRAGMA wal_autocheckpoint=0")
    writer.execute("INSERT INTO stops(stop_id, stop_name) VALUES ('WALONLY', 'Only in WAL')")
    writer.commit()
    crashed = tmp_path / "crashed.sqlite3"
    for suffix in ("", "-wal", "-shm"):
        src = Path(str(live) + suffix)
        if src.exists():
            shutil.copy(src, str(crashed) + suffix)
    writer.close()
    assert Path(str(crashed) + "-wal").stat().st_size > 0

    r = run(feed_zip, crashed)
    assert r.status == "success" and counts(crashed) == EXPECTED
    assert not Path(str(crashed) + "-wal").exists() or Path(str(crashed) + "-wal").stat().st_size == 0
    c = sqlite3.connect(crashed)
    assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert c.execute("SELECT COUNT(*) FROM stops WHERE stop_id='WALONLY'").fetchone()[0] == 0
    c.close()
    # the WAL-only row was recovered into the preserved previous database, not lost
    p = sqlite3.connect(previous_path(crashed))
    assert p.execute("SELECT COUNT(*) FROM stops WHERE stop_id='WALONLY'").fetchone()[0] == 1
    p.close()


def test_failed_post_promotion_verification_restores_previous(tmp_path, feed_zip, monkeypatch):
    db = tmp_path / "x.sqlite3"
    run(feed_zip, db)
    before = sha(db)

    def boom(*a, **k):
        raise PromotionError("forced", phase="promotion")
    monkeypatch.setattr(importer, "_verify_promoted", boom)
    with pytest.raises(PromotionError):
        run(feed_zip, db)
    assert sha(db) == before and counts(db) == EXPECTED
    assert_clean(db)


def test_unexpected_error_is_wrapped_and_database_preserved(tmp_path, feed_zip, monkeypatch):
    db = tmp_path / "x.sqlite3"
    run(feed_zip, db)
    before = sha(db)
    monkeypatch.setattr(importer, "_build_staging", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("secret internals")))
    with pytest.raises(GtfsImportError) as e:
        run(feed_zip, db)
    assert "secret internals" not in e.value.message and sha(db) == before
    assert read_import_status(db)["status"] == "failed"
    assert_clean(db)


def test_import_into_existing_empty_dir_creates_parents(tmp_path, feed_zip):
    db = tmp_path / "a" / "b" / "x.sqlite3"
    run(feed_zip, db)
    assert db.exists() and status_path(db).exists()
