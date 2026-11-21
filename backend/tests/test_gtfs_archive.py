import zipfile

import pytest

from app.gtfs.archive import inspect_archive
from app.gtfs.errors import GtfsArchiveError
from tests.gtfs_factory import FILES, build_zip


def test_root_level_files_detected(tmp_path):
    a = inspect_archive(build_zip(tmp_path / "a.zip"))
    assert a.root == "" and a.members["stops.txt"] == "stops.txt"
    assert set(a.members) == {"stops.txt", "routes.txt", "trips.txt", "stop_times.txt", "calendar.txt", "calendar_dates.txt"}


def test_nested_directory_detected(tmp_path):
    a = inspect_archive(build_zip(tmp_path / "a.zip", nested=True))
    assert a.root == "feed_v1/" and a.members["trips.txt"] == "feed_v1/trips.txt"


def test_known_unimported_files_reported(tmp_path):
    # Phase 1 imports agency/shapes/feed_info, so the "recognised but not imported" list now holds only
    # GTFS files this version still skips (e.g. translations.txt).
    a = inspect_archive(build_zip(tmp_path / "a.zip", extra={"translations.txt": "table_name\nstops\n", "readme.md": "x"}))
    assert a.ignored_known_files == ("translations.txt",)
    assert a.unrecognised_files == ("readme.md",)
    assert "translations.txt" not in a.members


def test_macos_junk_ignored(tmp_path):
    a = inspect_archive(build_zip(tmp_path / "a.zip", extra={"__MACOSX/._stops.txt": "junk"}))
    assert a.root == ""


def test_missing_required_files_all_listed(tmp_path):
    with pytest.raises(GtfsArchiveError) as e:
        inspect_archive(build_zip(tmp_path / "a.zip", overrides={"stops.txt": None, "trips.txt": None}))
    msgs = " ".join(x["message"] for x in e.value.errors)
    assert "stops.txt" in msgs and "trips.txt" in msgs


def test_missing_both_calendars_rejected(tmp_path):
    with pytest.raises(GtfsArchiveError, match="calendar"):
        inspect_archive(build_zip(tmp_path / "a.zip", overrides={"calendar.txt": None, "calendar_dates.txt": None}))


def test_only_calendar_dates_is_acceptable(tmp_path):
    assert "calendar.txt" not in inspect_archive(build_zip(tmp_path / "a.zip", overrides={"calendar.txt": None})).members


def test_malformed_headers_reported(tmp_path):
    with pytest.raises(GtfsArchiveError) as e:
        inspect_archive(build_zip(tmp_path / "a.zip", overrides={
            "stops.txt": "stop_id,stop_name,stop_lat\nA,x,1\n",          # missing stop_lon
            "routes.txt": "route_id,route_id,route_short_name\nR,R,1\n",   # duplicate column
            "trips.txt": "",                                               # empty
        }))
    text = " ".join(x["message"] for x in e.value.errors)
    assert "stop_lon" in text and "duplicate" in text and "empty" in text


def test_routes_need_a_name_column(tmp_path):
    with pytest.raises(GtfsArchiveError, match="route_short_name"):
        inspect_archive(build_zip(tmp_path / "a.zip", overrides={"routes.txt": "route_id\nR1\n"}))


def test_bom_header_accepted(tmp_path):
    a = inspect_archive(build_zip(tmp_path / "a.zip", overrides={"stops.txt": "\ufeff" + FILES["stops.txt"]}))
    assert a.headers["stops.txt"][0] == "stop_id"


def test_ambiguous_nested_roots_rejected(tmp_path):
    p = tmp_path / "a.zip"
    with zipfile.ZipFile(p, "w") as zf:
        for folder in ("one", "two"):
            for n, c in FILES.items():
                zf.writestr(f"{folder}/{n}", c)
    with pytest.raises(GtfsArchiveError, match="Ambiguous"):
        inspect_archive(p)


def test_not_a_zip_and_missing_file(tmp_path):
    bad = tmp_path / "bad.zip"
    bad.write_text("nope")
    with pytest.raises(GtfsArchiveError, match="not a valid ZIP"):
        inspect_archive(bad)
    with pytest.raises(GtfsArchiveError, match="not found"):
        inspect_archive(tmp_path / "missing.zip")


def test_archive_without_gtfs_files(tmp_path):
    p = tmp_path / "a.zip"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("readme.txt", "hi")
    with pytest.raises(GtfsArchiveError, match="no GTFS files"):
        inspect_archive(p)
