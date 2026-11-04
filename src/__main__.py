"""CLI: python -m src {export|verify|upload|all}"""
import argparse
import logging
import os
import sys

from dotenv import load_dotenv

from . import export as exp
from . import prompt
from .oracle_meta import connect
from .turso_push import push


def upload(sqlite_path, db_name):
    push(sqlite_path, db_name)


def main(argv=None):
    p = argparse.ArgumentParser(prog="saidbtransport")
    p.add_argument("command", choices=["export", "verify", "upload", "all"])
    p.add_argument("--tables", nargs="*", help="restrict to these tables (skips views)")
    p.add_argument("--sqlite", help="output SQLite file (default $SQLITE_PATH or export.db)")
    p.add_argument("--turso-db", help="Turso database name (default $TURSO_DB_NAME)")
    p.add_argument("-y", "--yes", action="store_true", help="answer yes to every per-table prompt")
    p.add_argument("-v", "--verbose", action="store_true")
    a = p.parse_args(argv)
    prompt.ASSUME_YES = a.yes
    load_dotenv()
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO, format="%(message)s")
    path = a.sqlite or os.environ.get("SQLITE_PATH", "export.db")
    rc = 0

    if a.command in ("export", "verify", "all"):
        conn = connect()
        owner = (os.environ.get("ORACLE_SCHEMA") or os.environ["ORACLE_USER"]).upper()
        names = None
        if a.command in ("export", "all"):
            names, skipped = exp.export(conn, owner, path, a.tables)
            if skipped:
                logging.warning("Skipped views: %s", ", ".join(skipped))
        else:
            from .oracle_meta import load_tables
            names = [n for n in load_tables(conn, owner) if not a.tables or n in {t.upper() for t in a.tables}]
        if a.command in ("verify", "all"):
            rc = 1 if exp.verify(conn, owner, path, names, ask=a.command == "verify") else 0
        conn.close()

    if a.command in ("upload", "all") and rc == 0:
        name = a.turso_db or os.environ.get("TURSO_DB_NAME")
        if not name:
            sys.exit("Set --turso-db or TURSO_DB_NAME")
        upload(path, name)
    return rc


if __name__ == "__main__":
    sys.exit(main())
