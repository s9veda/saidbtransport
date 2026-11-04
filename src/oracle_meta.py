"""Read table/constraint/index/view metadata from Oracle dictionary views."""
from __future__ import annotations

import os
from collections import defaultdict
from dataclasses import dataclass, field

import oracledb


@dataclass
class Column:
    name: str
    data_type: str
    length: int
    precision: int | None
    scale: int | None
    nullable: bool


@dataclass
class ForeignKey:
    name: str
    columns: list
    ref_table: str
    ref_columns: list
    on_delete: str


@dataclass
class Index:
    name: str
    unique: bool
    columns: list


@dataclass
class Table:
    name: str
    columns: list = field(default_factory=list)
    pk: list = field(default_factory=list)
    uniques: list = field(default_factory=list)
    fks: list = field(default_factory=list)
    indexes: list = field(default_factory=list)


def connect():
    oracledb.defaults.fetch_lobs = False  # CLOB -> str, BLOB -> bytes
    wallet = os.environ.get("ORACLE_WALLET_DIR") or os.environ["TNS_ADMIN"]
    dsn = os.environ.get("ORACLE_CONNECT_STRING") or os.environ["ORACLE_DSN"]
    return oracledb.connect(
        user=os.environ["ORACLE_USER"],
        password=os.environ["ORACLE_PASSWORD"],
        dsn=dsn,
        config_dir=wallet,
        wallet_location=wallet,
        wallet_password=os.environ.get("ORACLE_WALLET_PASSWORD") or None,
    )


def _rows(cur, sql, **binds):
    cur.execute(sql, binds)
    return cur.fetchall()


def load_tables(conn, owner):
    cur = conn.cursor()
    tables = {}
    for (name,) in _rows(
        cur,
        """SELECT table_name FROM all_tables
           WHERE owner = :o AND temporary = 'N' AND nested = 'NO'
             AND secondary = 'N' AND (iot_type IS NULL OR iot_type = 'IOT')
           ORDER BY table_name""",
        o=owner,
    ):
        if "$" in name:
            continue
        tables[name] = Table(name)

    for r in _rows(
        cur,
        """SELECT table_name, column_name, data_type, data_length,
                  data_precision, data_scale, nullable
           FROM all_tab_cols
           WHERE owner = :o AND hidden_column = 'NO' AND virtual_column = 'NO'
           ORDER BY table_name, column_id""",
        o=owner,
    ):
        if r[0] in tables:
            tables[r[0]].columns.append(Column(r[1], r[2], r[3], r[4], r[5], r[6] == "Y"))

    cons_cols = defaultdict(list)
    for cname, col in _rows(
        cur,
        "SELECT constraint_name, column_name FROM all_cons_columns "
        "WHERE owner = :o ORDER BY constraint_name, position",
        o=owner,
    ):
        cons_cols[cname].append(col)

    constraints = _rows(
        cur,
        """SELECT constraint_name, table_name, constraint_type, r_owner,
                  r_constraint_name, delete_rule, index_name
           FROM all_constraints
           WHERE owner = :o AND constraint_type IN ('P','U','R') AND status = 'ENABLED'""",
        o=owner,
    )
    owners = {c[0]: c[1] for c in constraints}
    backing_indexes = set()
    for cname, tname, ctype, r_owner, r_cname, rule, idx in constraints:
        t = tables.get(tname)
        if t is None:
            continue
        if idx:
            backing_indexes.add(idx)
        if ctype == "P":
            t.pk = cons_cols[cname]
        elif ctype == "U":
            t.uniques.append(cons_cols[cname])
        elif ctype == "R" and r_owner == owner and owners.get(r_cname) in tables:
            t.fks.append(
                ForeignKey(cname, cons_cols[cname], owners[r_cname],
                           cons_cols[r_cname], rule or "NO ACTION")
            )

    expr_indexes = {
        i for (i,) in _rows(cur, "SELECT index_name FROM all_ind_expressions WHERE index_owner = :o", o=owner)
    }
    idx_cols = defaultdict(list)
    for iname, col in _rows(
        cur,
        "SELECT index_name, column_name FROM all_ind_columns "
        "WHERE index_owner = :o ORDER BY index_name, column_position",
        o=owner,
    ):
        idx_cols[iname].append(col)
    for iname, tname, uniq in _rows(
        cur,
        """SELECT index_name, table_name, uniqueness FROM all_indexes
           WHERE owner = :o AND index_type = 'NORMAL' AND table_owner = :o""",
        o=owner,
    ):
        if tname in tables and iname not in backing_indexes and iname not in expr_indexes:
            tables[tname].indexes.append(Index(iname, uniq == "UNIQUE", idx_cols[iname]))
    return tables


def load_views(conn, owner):
    cur = conn.cursor()
    return _rows(cur, "SELECT view_name, text FROM all_views WHERE owner = :o ORDER BY view_name", o=owner)
