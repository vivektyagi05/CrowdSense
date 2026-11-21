"""Phase 1 ingestion: every supported file, optional/missing files, validation findings, safety."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from app.gtfs.archive import inspect_archive
from app.gtfs.errors import GtfsArchiveError, GtfsDataError
from app.gtfs.importer import import_gtfs, read_import_status
from app.gtfs.loader import RowError, make_parser, normalise_time
from app.gtfs.schema import GTFS_TABLES, SCHEMA_VERSION, TABLES_DDL
from app.gtfs.spec import SPEC_BY_FILE, SPEC_BY_TABLE, TABLE_SPECS
from tests.gtfs_factory import FILES, build_zip
from tests.gtfs_full import FULL_COUNTS, FULL_FILES


def run(zip_path, db, **kw):
    return import_gtfs(zip_path, db, promote_retries=0, **kw)


def rows(db: Path, sql: str, *params):
    c = sqlite3.connect(db)
    try:
        return c.execute(sql, params).fetchall()
    finally:
        c.close()


def codes(report, severity: str) -> set[str]:
    return {f["code"] for f in report.data_quality["findings"] if f["severity"] == severity}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# --- schema <-> spec consistency ---------------------------------------------------------------

def test_every_spec_column_exists_in_the_ddl_and_vice_versa():
    c = sqlite3.connect(":memory:")
    for stmt in TABLES_DDL.split(";"):
        if stmt.strip():
            c.execute(stmt)
    for spec in TABLE_SPECS:
        ddl_columns = [r[1] for r in c.execute(f"PRAGMA table_info({spec.table})")]
        assert set(spec.column_names) <= set(ddl_columns), spec.table  # every parsed column has a home
        # the only DDL column without a spec column is feed_info's surrogate row id
        assert set(ddl_columns) - set(spec.column_names) <= {"feed_info_id"}, spec.table
    tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert set(GTFS_TABLES) <= tables and "import_meta" in tables


def test_all_gtfs_files_have_unique_specs():
    assert len(SPEC_BY_FILE) == len(TABLE_SPECS) == len(SPEC_BY_TABLE)


# --- row parsers, one per file --------------------------------------------------------------------

PARSER_CASES = {
    "agency": ("agency_id,agency_name,agency_url,agency_timezone", ["X", "Name", "https://a.example", "Asia/Kolkata"], ["agency_url"]),
    "stops": ("stop_id,stop_name,stop_lat,stop_lon", ["S", "Name", "28.5", "77.5"], ["stop_lat"]),
    "routes": ("route_id,route_short_name,route_type", ["R", "1", "3"], ["route_type"]),
    "trips": ("route_id,service_id,trip_id,direction_id", ["R", "S", "T", "1"], ["direction_id"]),
    "stop_times": ("trip_id,arrival_time,departure_time,stop_id,stop_sequence", ["T", "25:10:00", "25:11:00", "S", "4"], ["stop_sequence"]),
    "calendar": ("service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date",
                 ["S", "1", "1", "1", "1", "1", "0", "0", "20250101", "20251231"], ["start_date"]),
    "calendar_dates": ("service_id,date,exception_type", ["S", "20250105", "1"], ["exception_type"]),
    "shape_points": ("shape_id,shape_pt_lat,shape_pt_lon,shape_pt_sequence", ["SH", "28.1", "77.1", "1"], ["shape_pt_lon"]),
    "feed_info": ("feed_publisher_name,feed_publisher_url,feed_lang", ["P", "https://p.example", "en"], ["feed_lang"]),
    "frequencies": ("trip_id,start_time,end_time,headway_secs", ["T", "6:00:00", "9:00:00", "300"], ["headway_secs"]),
    "transfers": ("from_stop_id,to_stop_id,transfer_type", ["A", "B", "2"], ["transfer_type"]),
    "levels": ("level_id,level_index", ["L", "-1"], ["level_index"]),
    "pathways": ("pathway_id,from_stop_id,to_stop_id,pathway_mode,is_bidirectional", ["P", "A", "B", "1", "0"], ["pathway_mode"]),
    "attributions": ("organization_name,is_operator", ["Org", "1"], ["is_operator"]),
    "fare_attributes": ("fare_id,price,currency_type,payment_method", ["F", "12.5", "INR", "1"], ["payment_method"]),
    "fare_rules": ("fare_id", ["F"], []),
}


@pytest.mark.parametrize("table", sorted(PARSER_CASES))
def test_each_parser_accepts_a_valid_row_and_rejects_a_corrupted_one(table):
    header_text, row, corruptible = PARSER_CASES[table]
    header = header_text.split(",")
    parse = make_parser(SPEC_BY_TABLE[table], header)
    out = parse(row)
    assert len(out) == len(SPEC_BY_TABLE[table].columns)
    for column in corruptible:  # replace one value by garbage; the parser must refuse it
        bad = list(row)
        bad[header.index(column)] = "garbage"
        with pytest.raises(RowError, match=column):
            make_parser(SPEC_BY_TABLE[table], header)(bad)


def test_identifiers_stay_strings_and_sequences_stay_integers():
    parse = make_parser(SPEC_BY_TABLE["stop_times"], ["trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence"])
    trip, _, _, stop, seq, *_ = parse(["007", "08:00:00", "08:00:00", "0012", "3"])
    assert (trip, stop, seq) == ("007", "0012", 3) and isinstance(seq, int)  # leading zeros preserved


def test_coordinates_keep_double_precision():
    parse = make_parser(SPEC_BY_TABLE["stops"], ["stop_id", "stop_name", "stop_lat", "stop_lon"])
    out = dict(zip(SPEC_BY_TABLE["stops"].column_names, parse(["S", "n", "28.71797103184126", "77.06389993096785"])))
    assert (out["stop_lat"], out["stop_lon"]) == (28.71797103184126, 77.06389993096785)


@pytest.mark.parametrize("raw,expected", [("08:00:00", "08:00:00"), ("8:05:09", "08:05:09"), ("24:00:00", "24:00:00"),
                                          ("27:59:59", "27:59:59"), ("", None)])
def test_times_beyond_24_hours_are_preserved(raw, expected):
    assert normalise_time(raw, "t") == expected


@pytest.mark.parametrize("raw", ["8am", "08:60:00", "08:00", "-1:00:00", "08:00:61"])
def test_invalid_times_are_rejected(raw):
    with pytest.raises(RowError):
        normalise_time(raw, "arrival_time")


def test_overnight_times_survive_the_import(tmp_path):
    db = tmp_path / "x.sqlite3"
    run(build_zip(tmp_path / "z.zip", base=FULL_FILES), db)
    assert rows(db, "SELECT arrival_time, departure_time FROM stop_times WHERE trip_id='T3' AND stop_sequence=2") == [("24:10:00", "24:10:00")]


# --- full feed import --------------------------------------------------------------------------------

def test_full_feed_imports_every_table(tmp_path, full_zip):
    db = tmp_path / "x.sqlite3"
    r = run(full_zip, db)
    assert r.status == "success" and r.table_counts == FULL_COUNTS and r.schema_version == SCHEMA_VERSION
    assert r.counts == {"stops": 4, "routes": 2, "trips": 4, "stop_times": 10, "calendar": 1, "calendar_dates": 2}
    assert [d["file"] for d in r.file_details] == [s.filename for s in TABLE_SPECS if s.filename in FULL_FILES]
    assert all(d["rows_rejected"] == 0 and d["rows_read"] == d["rows_imported"] for d in r.file_details)
    assert rows(db, "PRAGMA user_version") == [(SCHEMA_VERSION,)]
    assert rows(db, "SELECT agency_id, agency_name, agency_timezone FROM agency ORDER BY 1")[0] == ("AG1", "Alpha Transit", "Asia/Kolkata")
    assert rows(db, "SELECT feed_version FROM feed_info") == [("v7",)]
    assert rows(db, "SELECT start_time, end_time, headway_secs FROM frequencies") == [("08:00:00", "10:00:00", 600)]
    assert rows(db, "SELECT from_stop_id, to_stop_id, transfer_type, min_transfer_time FROM transfers") == [("B", "C", 2, 120)]
    assert rows(db, "SELECT currency_type, transfers FROM fare_attributes") == [("INR", None)]  # empty transfers = unlimited, kept NULL
    assert rows(db, "SELECT stop_code, level_id FROM stops WHERE stop_id='A'") == [("CA", "L0")]
    assert rows(db, "SELECT fare_stage FROM stop_times WHERE trip_id='T1' ORDER BY stop_sequence") == [(0,), (1,), (1,)]


def test_shapes_are_stored_in_sequence_order_with_a_derived_summary(tmp_path, full_zip):
    db = tmp_path / "x.sqlite3"
    run(full_zip, db)
    pts = rows(db, "SELECT shape_pt_sequence, shape_pt_lat FROM shape_points WHERE shape_id='SH1' ORDER BY shape_pt_sequence")
    assert pts == [(1, 28.60), (2, 28.61), (3, 28.62)]
    assert rows(db, "SELECT point_count, min_lat, max_lat, max_dist_traveled FROM shapes WHERE shape_id='SH1'") == [(3, 28.60, 28.62, 2500.5)]
    assert rows(db, "SELECT sql FROM sqlite_master WHERE name='idx_shape_points_seq'")[0][0].startswith("CREATE UNIQUE INDEX")


def test_nested_full_feed(tmp_path):
    r = run(build_zip(tmp_path / "n.zip", nested=True, base=FULL_FILES), tmp_path / "x.sqlite3")
    assert r.gtfs_root == "feed_v1/" and r.table_counts == FULL_COUNTS


def test_repeated_full_imports_never_duplicate_rows(tmp_path, full_zip):
    db = tmp_path / "x.sqlite3"
    first = run(full_zip, db)
    second = run(full_zip, db)
    third = run(full_zip, db)
    assert first.table_counts == second.table_counts == third.table_counts == FULL_COUNTS
    assert rows(db, "SELECT COUNT(*) FROM shape_points") == [(5,)]


# --- missing optional files / extensions ------------------------------------------------------------

def test_base_feed_without_optional_files_imports_and_says_so(tmp_path, feed_zip):
    r = run(feed_zip, tmp_path / "x.sqlite3")
    assert r.status == "success"
    assert {"agency.txt", "shapes.txt", "feed_info.txt", "frequencies.txt"} <= set(r.missing_optional_files)
    assert r.table_counts["agency"] == 0 and r.table_counts["shapes"] == 0 and r.table_counts["feed_info"] == 0
    assert "agency_file_missing" in codes(r, "warning") and "optional_file_absent" in codes(r, "info")
    assert "shapes_absent" in codes(r, "info")  # and no geometry was invented


def test_feed_info_with_several_rows_warns_and_keeps_all(tmp_path):
    two = FULL_FILES["feed_info.txt"] + "Second,https://s.example/,en,20250101,20401231,v7\n"
    r = run(build_zip(tmp_path / "z.zip", base=FULL_FILES, overrides={"feed_info.txt": two}), tmp_path / "x.sqlite3")
    assert r.table_counts["feed_info"] == 2 and "feed_info_multiple_rows" in codes(r, "warning")
    assert r.feed_info["feed_publisher_name"] == "Example Publisher"  # first row = identity


def test_extension_columns_are_stored_and_unknown_columns_reported_not_stored(tmp_path):
    stops = "stop_id,stop_name,stop_lat,stop_lon,vendor_flag\nA,Alpha Stop,28.60,77.20,x\nB,Beta Stop,28.61,77.21,y\n" \
            "C,Gamma,28.62,77.22,\nD,Delta,28.63,77.23,\n"
    r = run(build_zip(tmp_path / "z.zip", base=FULL_FILES, overrides={"stops.txt": stops},
                      extra={"notes.csv": "x\n", "translations.txt": "table_name\n"}), tmp_path / "x.sqlite3")
    assert "unsupported_columns" in codes(r, "warning") and "unrecognised_file" in codes(r, "warning")
    assert "recognised_file_not_imported" in codes(r, "warning") and "extension_column_stored" in codes(r, "info")
    assert not any(row[1] == "vendor_flag" for row in rows(tmp_path / "x.sqlite3", "PRAGMA table_info(stops)"))
    detail = next(d for d in r.file_details if d["file"] == "stops.txt")
    assert detail["columns"]["unsupported"] == ["vendor_flag"]
    stop_times = next(d for d in r.file_details if d["file"] == "stop_times.txt")
    assert stop_times["columns"]["extension_stored"] == ["fare_stage"]


def test_missing_required_columns_of_optional_files_are_fatal_archive_errors(tmp_path):
    with pytest.raises(GtfsArchiveError) as e:
        inspect_archive(build_zip(tmp_path / "z.zip", base=FULL_FILES, overrides={"shapes.txt": "shape_id,shape_pt_lat\nSH1,1\n"}))
    assert "shapes.txt" in e.value.message and "shape_pt_lon" in e.value.message


def test_archive_reports_present_and_missing_files(tmp_path):
    a = inspect_archive(build_zip(tmp_path / "z.zip", base=FULL_FILES))
    assert a.missing_optional_files == () and set(a.members) == {s.filename for s in TABLE_SPECS if s.filename in FULL_FILES}


# --- fatal errors: nothing is imported and the live database survives -------------------------------------

def _swap(file: str, old: str, new: str) -> dict[str, str]:
    assert old in FULL_FILES[file], (file, old)
    return {file: FULL_FILES[file].replace(old, new)}


FATAL_CASES = {
    "shape_bad_latitude": (_swap("shapes.txt", "SH2,28.63,77.23", "SH2,98.63,77.23"), "shape_pt_lat"),
    "shape_duplicate_sequence": ({"shapes.txt": FULL_FILES["shapes.txt"] + "SH1,28.6,77.2,2,1\n"}, "duplicate_shape_point_sequence"),
    "shape_distance_decreasing": (_swap("shapes.txt", "SH1,28.61,77.21,2,1200.25", "SH1,28.61,77.21,2,3000"), "shape_point_dist_decreasing"),
    "trip_references_unknown_shape": (_swap("trips.txt", "R1,S2,T4,Delta,0,SH2", "R1,S2,T4,Delta,0,SHX"), "trip_shape_missing"),
    "agency_bad_url": (_swap("agency.txt", "https://alpha.example/", "ftp://alpha"), "agency_url"),
    "agency_timezones_differ": (_swap("agency.txt", "AG2,Beta Transit,https://beta.example/,Asia/Kolkata", "AG2,Beta Transit,https://beta.example/,Asia/Tokyo"), "agency_timezone_consistent"),
    "route_unknown_agency": (_swap("routes.txt", "R1,AG1", "R1,AGX"), "route_agency_missing"),
    "route_needs_agency_when_several": (_swap("routes.txt", "R2,AG2", "R2,"), "route_agency_required"),
    "route_bad_colour": ({"routes.txt": "route_id,agency_id,route_short_name,route_type,route_color\nR1,AG1,1,3,ZZZ\nR2,AG2,N,3,\n"}, "route_color"),
    "feed_info_dates_reversed": (_swap("feed_info.txt", "20250101,20401231", "20401231,20250101"), "feed_info_date_order"),
    "frequency_end_before_start": (_swap("frequencies.txt", "8:00:00,10:00:00", "10:00:00,8:00:00"), "end_time"),
    "frequency_unknown_trip": (_swap("frequencies.txt", "T1,", "TX,"), "frequency_trip_missing"),
    "transfer_without_stops": (_swap("transfers.txt", "B,C,2", ",,2"), "from_stop_id and to_stop_id"),
    "transfer_unknown_stop": (_swap("transfers.txt", "B,C", "B,ZZ"), "transfer_to_stop_missing"),
    "attribution_without_role": (_swap("attributions.txt", "Example Org,1", "Example Org,0"), "at least one of"),
    "fare_rule_unknown_fare": (_swap("fare_rules.txt", "F1,R1", "F9,R1"), "fare_rule_fare_missing"),
    "pathway_unknown_stop": (_swap("pathways.txt", "P1,A,B", "P1,A,QQ"), "pathway_to_stop_missing"),
    "stop_unknown_level": (_swap("stops.txt", ",L0", ",L9"), "stop_level_missing"),
    "stop_unknown_parent": ({"stops.txt": "stop_id,stop_name,stop_lat,stop_lon,parent_station\nA,Alpha,28.6,77.2,NOPE\nB,Beta,28.61,77.21,\nC,G,28.62,77.22,\nD,D,28.63,77.23,\n"}, "stop_parent_missing"),
    "entrance_needs_parent": ({"stops.txt": "stop_id,stop_name,stop_lat,stop_lon,location_type\nA,Alpha,28.6,77.2,0\nB,B,28.61,77.21,0\nC,C,28.62,77.22,0\nD,D,28.63,77.23,2\n"}, "stop_parent_required"),
    "departure_before_arrival": (_swap("stop_times.txt", "T1,08:10:00,08:10:00", "T1,08:10:00,08:05:00"), "departure_before_arrival"),
    "time_runs_backwards": (_swap("stop_times.txt", "T1,08:10:00,08:10:00,B", "T1,07:10:00,07:10:00,B"), "time_travel"),
    "last_stop_without_time": (_swap("stop_times.txt", "T1,08:20:00,08:20:00,C,3", "T1,,,C,3"), "trip_edge_time_missing"),
    "invalid_pickup_type": (_swap("stop_times.txt", "T1,08:00:00,08:00:00,A,1,0", "T1,08:00:00,08:00:00,A,1,7"), "pickup_type"),
    "negative_stop_sequence": (_swap("stop_times.txt", "T4,10:00:00,10:00:00,A,1", "T4,10:00:00,10:00:00,A,-1"), "stop_sequence"),
    "malformed_row_length": ({"shapes.txt": FULL_FILES["shapes.txt"] + "SH2,28.7\n"}, "expected 5 columns"),
    "calendar_start_after_end": ({"calendar.txt": FILES["calendar.txt"].replace("20250101,20401231", "20401231,20250101")}, "start_date"),
}


@pytest.mark.parametrize("name", sorted(FATAL_CASES))
def test_fatal_findings_abort_the_import_and_preserve_the_live_database(tmp_path, full_zip, name):
    overrides, expected = FATAL_CASES[name]
    db = tmp_path / "x.sqlite3"
    run(full_zip, db)
    before = sha(db)
    with pytest.raises(GtfsDataError) as e:
        run(build_zip(tmp_path / "bad.zip", base=FULL_FILES, overrides=overrides), db)
    text = " | ".join(f"{r.get('code', '')} {r['message']}" for r in e.value.errors)
    assert expected in text, text
    assert sha(db) == before and rows(db, "SELECT COUNT(*) FROM shape_points") == [(5,)]
    assert e.value.report.status == "failed" and e.value.report.error_count >= 1
    assert read_import_status(db)["status"] == "failed"
    assert not list(db.parent.glob("*.staging*"))


def test_failed_quality_check_keeps_the_full_findings_on_the_failed_report(tmp_path):
    with pytest.raises(GtfsDataError) as e:
        run(build_zip(tmp_path / "bad.zip", base=FULL_FILES, overrides=FATAL_CASES["route_unknown_agency"][0]), tmp_path / "x.sqlite3")
    dq = e.value.report.data_quality
    assert dq["status"] == "fail" and dq["error_count"] >= 1
    failed = [c for c in dq["integrity_checks"] if c["status"] == "failed"]
    assert any(c["code"] == "route_agency_missing" and c["violations"] == 1 for c in failed)


# --- warnings do not block the import -------------------------------------------------------------------------

def test_schedule_oddities_are_warnings_not_errors(tmp_path):
    stop_times = FULL_FILES["stop_times.txt"] + "T1,08:25:00,08:25:00,C,4,,1,1\n" + "T5,12:00:00,12:00:00,A,1,,1,0\n"
    trips = FULL_FILES["trips.txt"] + "R1,S1,T5,X,0,SH1\n"
    stops = FULL_FILES["stops.txt"] + "E,CE,Lonely Stop,28.7,77.3,\n"
    r = run(build_zip(tmp_path / "z.zip", base=FULL_FILES, overrides={"stop_times.txt": stop_times, "trips.txt": trips, "stops.txt": stops}),
            tmp_path / "x.sqlite3")
    assert r.status == "success" and r.data_quality["status"] == "pass_with_warnings"
    assert {"consecutive_duplicate_stop", "trip_too_short", "unused_stops", "trips_without_shape"} <= codes(r, "warning")
    assert any("fewer than 2 stop_times" in w for w in r.warnings)  # Phase 0 wording is preserved


def test_clean_feed_reports_every_check_that_ran(tmp_path, full_zip):
    r = run(full_zip, tmp_path / "x.sqlite3")
    by_code = {c["code"]: c for c in r.data_quality["integrity_checks"]}
    for code in ("trip_route_missing", "stop_time_trip_missing", "stop_time_stop_missing", "trip_shape_missing",
                 "route_agency_missing", "trip_service_missing", "duplicate_stop_time_sequence", "time_travel"):
        assert by_code[code]["status"] == "passed", code
    assert by_code["pathway_from_stop_missing"]["status"] == "passed"
    assert r.data_quality["error_count"] == 0
    assert "overnight_service" in codes(r, "info") and "calendar_span" in codes(r, "info")


def test_report_is_persisted_inside_the_database_and_in_the_status_file(tmp_path, full_zip):
    db = tmp_path / "x.sqlite3"
    r = run(full_zip, db)
    meta = dict(rows(db, "SELECT key, value FROM import_meta"))
    stored = json.loads(meta["import_report"])
    assert stored["data_quality"]["status"] == r.data_quality["status"]
    assert json.loads(meta["table_counts"]) == FULL_COUNTS and meta["schema_version"] == str(SCHEMA_VERSION)
    status = read_import_status(db)
    assert status["status"] == "success" and status["data_quality"]["status"] == r.data_quality["status"]
    assert status["table_counts"] == FULL_COUNTS and status["duration_seconds"] >= 0
