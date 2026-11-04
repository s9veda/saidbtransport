"""Export Oracle schema + data into a local SQLite file, and verify it."""
import logging
import sqlite3

from . import ddl
from .oracle_meta import load_tables, load_views
from .prompt import confirm
from .typemap import convert_value, is_uuid, select_expr, uuid_to_text

log = logging.getLogger("saidbtransport")
BATCH = 5000


def _converters(t):
    return [uuid_to_text if is_uuid(c.data_type, c.length) else convert_value for c in t.columns]


def _create_schema(db, tables, views):
    for t in tables.values():
        db.execute(ddl.create_table_sql(t).replace("CREATE TABLE", "CREATE TABLE IF NOT EXISTS", 1))
        for idx in t.indexes:
            db.execute(ddl.create_index_sql(t, idx).replace(" INDEX", " INDEX IF NOT EXISTS", 1))
    skipped = []
    for name, text in views:
        try:
            db.execute("DROP VIEW IF EXISTS %s" % ddl.q(name))
            db.execute(ddl.create_view_sql(name, text))
        except sqlite3.Error as e:
            log.warning("View %s skipped (Oracle SQL not valid in SQLite): %s", name, e)
            skipped.append(name)
    return skipped


def export(conn, owner, sqlite_path, only=None):
    tables = load_tables(conn, owner)
    if only:
        wanted = {n.upper() for n in only}
        tables = {k: v for k, v in tables.items() if k in wanted}
    tables = {k: v for k, v in tables.items() if confirm("Export", k)}
    views = [] if only else load_views(conn, owner)
    db = sqlite3.connect(sqlite_path)
    db.execute("PRAGMA foreign_keys = OFF")  # load order is arbitrary
    _create_schema(db, tables, [])
    cur = conn.cursor()
    cur.arraysize = BATCH
    for t in tables.values():
        if not t.columns:
            continue
        if not t.pk:
            db.execute("DELETE FROM %s" % ddl.q(t.name))
        sql = "SELECT %s FROM %s.%s t" % (
            ", ".join(select_expr(c.name, c.data_type) for c in t.columns),
            ddl.q(owner), ddl.q(t.name))
        insert = ddl.upsert_sql(t)
        convs = _converters(t)
        cur.execute(sql)
        total = 0
        while True:
            rows = cur.fetchmany(BATCH)
            if not rows:
                break
            db.executemany(insert, [tuple(f(v) for f, v in zip(convs, r)) for r in rows])
            total += len(rows)
        db.commit()
        log.info("%s: %d rows", t.name, total)
    skipped = _create_schema(db, {}, views)
    db.commit()
    db.close()
    return list(tables), skipped


def verify(conn, owner, sqlite_path, table_names, ask=True):
    """Compare row counts; returns list of mismatches."""
    db = sqlite3.connect(sqlite_path)
    cur = conn.cursor()
    bad = []
    for name in table_names:
        if ask and not confirm("Verify", name):
            continue
        cur.execute("SELECT COUNT(*) FROM %s.%s" % (ddl.q(owner), ddl.q(name)))
        src = cur.fetchone()[0]
        dst = db.execute("SELECT COUNT(*) FROM %s" % ddl.q(name)).fetchone()[0]
        status = "OK" if src == dst else "MISMATCH"
        log.info("%-40s oracle=%d sqlite=%d %s", name, src, dst, status)
        if src != dst:
            bad.append((name, src, dst))
    db.close()
    return bad
