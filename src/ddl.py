"""Generate SQLite DDL from Oracle metadata."""
from .typemap import is_uuid, sqlite_type


def q(name):
    return '"%s"' % name.replace('"', '""')


def qlist(cols):
    return ", ".join(q(c) for c in cols)


def column_sqlite_type(col):
    if is_uuid(col.data_type, col.length):
        return "TEXT"
    return sqlite_type(col.data_type, col.precision, col.scale)


def create_table_sql(t):
    parts = []
    for c in t.columns:
        parts.append("%s %s%s" % (q(c.name), column_sqlite_type(c), "" if c.nullable else " NOT NULL"))
    if t.pk:
        parts.append("PRIMARY KEY (%s)" % qlist(t.pk))
    for u in t.uniques:
        parts.append("UNIQUE (%s)" % qlist(u))
    for fk in t.fks:
        action = {"CASCADE": " ON DELETE CASCADE", "SET NULL": " ON DELETE SET NULL"}.get(fk.on_delete, "")
        parts.append(
            "FOREIGN KEY (%s) REFERENCES %s (%s)%s"
            % (qlist(fk.columns), q(fk.ref_table), qlist(fk.ref_columns), action)
        )
    return "CREATE TABLE %s (\n  %s\n)" % (q(t.name), ",\n  ".join(parts))


def create_index_sql(t, idx):
    return "CREATE %sINDEX %s ON %s (%s)" % (
        "UNIQUE " if idx.unique else "", q(idx.name), q(t.name), qlist(idx.columns))


def create_view_sql(name, text):
    return "CREATE VIEW %s AS %s" % (q(name), text.strip())


def upsert_sql(t):
    cols = [c.name for c in t.columns]
    ins = "INSERT INTO %s (%s) VALUES (%s)" % (q(t.name), qlist(cols), ", ".join("?" * len(cols)))
    if not t.pk:
        return ins  # no key: caller truncates before reload
    non_pk = [c for c in cols if c not in t.pk]
    if non_pk:
        sets = ", ".join("%s = excluded.%s" % (q(c), q(c)) for c in non_pk)
        return "%s ON CONFLICT (%s) DO UPDATE SET %s" % (ins, qlist(t.pk), sets)
    return "%s ON CONFLICT (%s) DO NOTHING" % (ins, qlist(t.pk))
