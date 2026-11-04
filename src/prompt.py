"""Per-table Y/n confirmation."""
import sys

ASSUME_YES = False


def confirm(action, table, detail=""):
    """Ask [Y/n] (Enter = yes). Auto-yes with --yes or when stdin isn't a terminal."""
    if ASSUME_YES or not sys.stdin.isatty():
        return True
    suffix = " (%s)" % detail if detail else ""
    while True:
        ans = input("%s table %s%s? [Y/n] " % (action, table, suffix)).strip().lower()
        if ans in ("", "y", "yes"):
            return True
        if ans in ("n", "no"):
            return False
