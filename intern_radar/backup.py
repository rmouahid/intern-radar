"""Nightly copies of the SQLite database.

The copy goes through SQLite's online backup API, so it is consistent even
while a run writes. It is checked (`PRAGMA integrity_check`) before being
kept, compressed with gzip, and named after the day: rerunning the same day
replaces that day's file. Only the newest `keep` backups are kept.
"""

import gzip
import re
import shutil
import sqlite3
from datetime import date
from pathlib import Path

PREFIX = "intern-radar-"
NAME_RE = re.compile(rf"^{PREFIX}\d{{4}}-\d{{2}}-\d{{2}}\.db\.gz$")


class BackupError(Exception):
    """The copy could not be made or failed its integrity check."""


def backup_name(day: date) -> str:
    return f"{PREFIX}{day.isoformat()}.db.gz"


def backup(db: Path, dest: Path, keep: int, today: date) -> Path:
    """Copy `db` into `dest`, then delete the backups beyond the newest `keep`."""
    if keep < 1:
        raise ValueError("keep must be at least 1")
    if not db.exists():
        raise BackupError(f"{db}: no such database")
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / backup_name(today)
    raw = target.with_suffix("")  # the uncompressed copy, removed below
    try:
        source = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        copy = sqlite3.connect(raw)
        try:
            source.backup(copy)
            status = copy.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            copy.close()
            source.close()
        if status != "ok":
            raise BackupError(f"{db}: integrity check failed ({status})")
        partial = target.with_name(target.name + ".part")
        with raw.open("rb") as plain, gzip.open(partial, "wb") as packed:
            shutil.copyfileobj(plain, packed)
        partial.replace(target)  # never leaves a truncated backup in place
    except sqlite3.Error as exc:
        raise BackupError(f"{db}: {exc}") from exc
    finally:
        raw.unlink(missing_ok=True)
    prune(dest, keep)
    return target


def prune(dest: Path, keep: int) -> list[Path]:
    """Delete the backups beyond the newest `keep`; other files are left alone."""
    backups = sorted(p for p in dest.iterdir() if NAME_RE.match(p.name))
    removed = backups[:-keep] if len(backups) > keep else []
    for path in removed:
        path.unlink()
    return removed
