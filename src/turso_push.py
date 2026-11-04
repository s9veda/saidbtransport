"""Push a local SQLite export into an existing Turso database (create-if-missing + upsert)."""
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request

from .prompt import confirm

log = logging.getLogger("saidbtransport")
MAX_STMTS = 500
MAX_BYTES = 2_000_000


def q(name):
    return '"%s"' % name.replace('"', '""')


def _cli(*args):
    if not shutil.which("turso"):
        sys.exit("Turso CLI not found. Install from https://docs.turso.tech/cli/installation "
                 "or set TURSO_DATABASE_URL and TURSO_AUTH_TOKEN")
    return subprocess.run(["turso", *args], capture_output=True, text=True, check=True).stdout.strip()


def resolve_target(db_name):
    url = os.environ.get("TURSO_DATABASE_URL") or _cli("db", "show", db_name, "--url")
    token = os.environ.get("TURSO_AUTH_TOKEN") or _cli("db", "tokens", "create", db_name)
    return url.replace("libsql://", "https://", 1).rstrip("/"), token


def _arg(v):
    if v is None:
        return {"type": "null"}
    if isinstance(v, bool):
        return {"type": "integer", "value": str(int(v))}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    return {"type": "text", "value": str(v)}


class Turso:
    def __init__(self, url, token):
        self.url, self.token = url, token

    def run(self, stmts):
        """stmts: list of (sql, params). Executed in order on one connection."""
        reqs = [{"type": "execute", "stmt": {"sql": "PRAGMA foreign_keys = OFF"}}]
        for sql, params in stmts:
            st = {"sql": sql}
            if params:
                st["args"] = [_arg(p) for p in params]
            reqs.append({"type": "execute", "stmt": st})
        reqs.append({"type": "close"})
        body = json.dumps({"requests": reqs}).encode()
        req = urllib.request.Request(
            self.url + "/v2/pipeline", data=body, method="POST",
            headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                out = json.load(r)
        except urllib.error.HTTPError as e:
            raise RuntimeError("Turso HTTP %s: %s" % (e.code, e.read().decode(errors="replace")))
        for i, res in enumerate(out["results"][:-1]):
            if res["type"] == "error":
                sql = reqs[i]["stmt"]["sql"][:200]
                raise RuntimeError("Turso error: %s\nSQL: %s" % (res["error"]["message"], sql))


def _order_tables(db, names):
    deps = {n: {r[2] for r in db.execute("PRAGMA foreign_key_list(%s)" % q(n)) if r[2] in names and r[2] != n}
            for n in names}
    ordered = []
    while deps:
        ready = [n for n, d in deps.items() if d.issubset(set(ordered))] or list(deps)
        for n in sorted(ready):
            ordered.append(n)
            del deps[n]
    return ordered


def _upsert(db, table):
    info = db.execute("PRAGMA table_info(%s)" % q(table)).fetchall()
    cols = [r[1] for r in info]
    pk = [r[1] for r in sorted((r for r in info if r[5]), key=lambda r: r[5])]
    sql = "INSERT INTO %s (%s) VALUES (%s)" % (
        q(table), ", ".join(map(q, cols)), ", ".join("?" * len(cols)))
    if pk:
        rest = [c for c in cols if c not in pk]
        sql += " ON CONFLICT (%s) " % ", ".join(map(q, pk))
        sql += ("DO UPDATE SET " + ", ".join("%s = excluded.%s" % (q(c), q(c)) for c in rest)) if rest else "DO NOTHING"
    return cols, pk, sql


def push(sqlite_path, db_name):
    target = Turso(*resolve_target(db_name))
    db = sqlite3.connect(sqlite_path)
    schema = db.execute("SELECT type, name, tbl_name, sql FROM sqlite_master WHERE sql IS NOT NULL "
                        "AND name NOT LIKE 'sqlite_%'").fetchall()
    tables = [r[1] for r in schema if r[0] == "table" and "$" not in r[1]]
    selected = set()
    for name in _order_tables(db, set(tables)):
        n = db.execute("SELECT COUNT(*) FROM %s" % q(name)).fetchone()[0]
        if confirm("Upload", name, "%d rows" % n):
            selected.add(name)

    ddl = []
    for t, name, _, sql in schema:
        if t == "table" and name in selected:
            ddl.append((sql.replace("CREATE TABLE", "CREATE TABLE IF NOT EXISTS", 1), None))
    for t, name, tbl, sql in schema:
        if t == "index" and tbl in selected:
            ddl.append((sql.replace("INDEX", "INDEX IF NOT EXISTS", 1), None))
    if ddl:
        target.run(ddl)
    log.info("Schema ensured on Turso '%s' (%d tables)", db_name, len(selected))

    for name in _order_tables(db, selected):
        cols, pk, sql = _upsert(db, name)
        if not pk:
            target.run([("DELETE FROM %s" % q(name), None)])
        total, batch, size = 0, [], 0
        for row in db.execute("SELECT %s FROM %s" % (", ".join(map(q, cols)), q(name))):
            batch.append((sql, row))
            size += sum(len(v) if isinstance(v, str) else 16 for v in row if v is not None)
            if len(batch) >= MAX_STMTS or size >= MAX_BYTES:
                target.run(batch)
                total += len(batch)
                batch, size = [], 0
                log.info("%s: %d rows pushed so far", name, total)
        if batch:
            target.run(batch)
            total += len(batch)
        log.info("%s: %d rows pushed", name, total)

    views = [(r[1], r[3]) for r in schema if r[0] == "view"]
    for name, sql in views:
        target.run([("DROP VIEW IF EXISTS %s" % q(name), None), (sql, None)])
    db.close()
