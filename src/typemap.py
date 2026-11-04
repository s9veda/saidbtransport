"""Oracle -> SQLite type and value mapping."""
import base64
import datetime as dt
import decimal
import uuid


def is_uuid(data_type, data_length):
    """RAW(16) columns (e.g. SYS_GUID() ids) are mapped to UUID text."""
    return data_type.upper() == "RAW" and data_length == 16


def uuid_to_text(value):
    if value is None:
        return None
    return str(uuid.UUID(bytes=bytes(value)))


def sqlite_type(data_type, precision, scale):
    t = data_type.upper()
    if t in ("NUMBER", "FLOAT"):
        if t == "NUMBER" and scale == 0 and precision is not None and precision <= 18:
            return "INTEGER"
        return "NUMERIC"
    if t in ("BINARY_FLOAT", "BINARY_DOUBLE"):
        return "REAL"
    if t == "BOOLEAN":
        return "INTEGER"
    # Strings, LOBs, RAW, dates, timestamps, intervals, ROWID, JSON, XMLTYPE
    # are all stored as TEXT (binary as base64, dates as ISO-8601).
    return "TEXT"


def select_expr(column, data_type):
    """Column expression used when reading from Oracle."""
    q = '"%s"' % column
    if data_type.upper().startswith("XMLTYPE"):
        return "t.%s.getClobVal()" % q
    return "t.%s" % q


def convert_value(value):
    """Convert a python-oracledb value to something SQLite can store."""
    if value is None or isinstance(value, (str, float)):
        return value
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value if -(2**63) <= value < 2**63 else str(value)
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, (bytes, bytearray)):
        return base64.b64encode(value).decode("ascii")
    if isinstance(value, dt.datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, dt.timedelta):
        return str(value)
    if hasattr(value, "read"):  # LOB fallback
        return convert_value(value.read())
    return str(value)
