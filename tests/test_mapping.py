import datetime as dt
import sqlite3
import uuid

from src import ddl
from src.oracle_meta import Column, ForeignKey, Table
from src.turso_push import _upsert, _upload_row
from src.typemap import convert_value, is_uuid, sqlite_type, uuid_to_text


def test_type_mapping():
    assert sqlite_type("NUMBER", 10, 0) == "INTEGER"
    assert sqlite_type("NUMBER", 38, 0) == "NUMERIC"
    assert sqlite_type("NUMBER", None, None) == "NUMERIC"
    assert sqlite_type("BINARY_DOUBLE", None, None) == "REAL"
    assert sqlite_type("TIMESTAMP(6)", None, 6) == "TEXT"
    assert sqlite_type("CLOB", None, None) == "TEXT"


def test_raw16_is_uuid():
    u = uuid.uuid4()
    assert is_uuid("RAW", 16) and not is_uuid("RAW", 8)
    assert uuid_to_text(u.bytes) == str(u)


def test_value_conversion():
    assert convert_value(dt.datetime(2024, 1, 2, 3, 4, 5)) == "2024-01-02 03:04:05"
    assert convert_value(b"\x01\x02") == "AQI="
    assert convert_value(10**30) == str(10**30)


def test_ddl_runs_in_sqlite():
    parent = Table("P", [Column("ID", "RAW", 16, None, None, False)], pk=["ID"])
    child = Table(
        "C",
        [Column("ID", "NUMBER", 22, 10, 0, False), Column("PID", "RAW", 16, None, None, True),
         Column("N", "VARCHAR2", 10, None, None, True)],
        pk=["ID"], fks=[ForeignKey("FK", ["PID"], "P", ["ID"], "CASCADE")])
    db = sqlite3.connect(":memory:")
    db.execute(ddl.create_table_sql(parent))
    db.execute(ddl.create_table_sql(child))
    sql = ddl.upsert_sql(child)
    db.execute(sql, (1, None, "a"))
    db.execute(sql, (1, None, "b"))
    assert db.execute("SELECT N FROM C").fetchall() == [("b",)]


def test_turso_users_upload_maps_legacy_columns_and_null_admin():
    source = sqlite3.connect(":memory:")
    source.execute("CREATE TABLE USERS (ID TEXT PRIMARY KEY, CENTER_IDS TEXT, IS_ADMIN INTEGER)")
    source.execute("INSERT INTO USERS VALUES ('u1', '[1,2]', NULL)")
    target = sqlite3.connect(":memory:")
    target.execute(
        "CREATE TABLE users (id TEXT PRIMARY KEY, associated_centers TEXT, "
        "is_admin INTEGER NOT NULL DEFAULT 0)"
    )

    cols, pk, sql = _upsert(source, "USERS")
    row = source.execute("SELECT %s FROM USERS" % ", ".join(map(ddl.q, cols))).fetchone()
    target.execute(sql, _upload_row("USERS", cols, row))

    assert pk == ["ID"]
    assert target.execute(
        "SELECT associated_centers, is_admin FROM users WHERE id = 'u1'"
    ).fetchone() == ("[1,2]", 0)
