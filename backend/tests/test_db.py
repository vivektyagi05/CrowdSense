import sqlite3

import pytest

from app.db import DatabaseUnavailableError, connect, open_connection, transaction


def _make(path):
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE t(x INTEGER)")
    c.commit()
    c.close()


def test_missing_database_raises_and_is_not_created(tmp_path):
    p = tmp_path / "nope.sqlite3"
    with pytest.raises(DatabaseUnavailableError):
        connect(p)
    assert not p.exists()


def test_non_sqlite_file_is_unavailable(tmp_path):
    p = tmp_path / "junk.sqlite3"
    p.write_bytes(b"this is not a database" * 100)
    with pytest.raises(DatabaseUnavailableError):
        connect(p)


def test_connection_is_closed_by_context_manager(tmp_path):
    p = tmp_path / "d.sqlite3"
    _make(p)
    with open_connection(p) as conn:
        assert conn.execute("SELECT 1").fetchone()[0] == 1
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_pragmas_applied_and_read_only_blocks_writes(tmp_path):
    p = tmp_path / "d.sqlite3"
    _make(p)
    with open_connection(p, busy_timeout_ms=1234) as conn:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 1234
        assert conn.execute("PRAGMA query_only").fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("INSERT INTO t VALUES (1)")


def test_read_write_connection_uses_wal(tmp_path):
    p = tmp_path / "d.sqlite3"
    _make(p)
    with open_connection(p, read_only=False) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_transaction_commits_and_rolls_back(tmp_path):
    p = tmp_path / "d.sqlite3"
    _make(p)
    with open_connection(p, read_only=False) as conn:
        with transaction(conn):
            conn.execute("INSERT INTO t VALUES (1)")
        with pytest.raises(RuntimeError):
            with transaction(conn):
                conn.execute("INSERT INTO t VALUES (2)")
                raise RuntimeError("boom")
        assert not conn.in_transaction
        assert [r[0] for r in conn.execute("SELECT x FROM t")] == [1]


def test_path_with_spaces_works(tmp_path):
    d = tmp_path / "dir with space"
    d.mkdir()
    p = d / "d.sqlite3"
    _make(p)
    with open_connection(p) as conn:
        assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 0
