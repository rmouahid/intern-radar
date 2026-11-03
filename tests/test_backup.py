import gzip
import sqlite3
from datetime import date

import pytest
from typer.testing import CliRunner

from intern_radar import cli
from intern_radar.backup import BackupError, backup, backup_name, prune
from intern_radar.store import Store
from tests.factories import make_job

DAY = date(2026, 11, 3)


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "radar.db"
    store = Store(str(path))
    store.add(make_job(id="a"), "pending", cli.utcnow())
    store.add(make_job(id="b"), "rejected", cli.utcnow())
    store.close()
    return path


def restored_rows(path, tmp_path):
    plain = tmp_path / "restored.db"
    plain.write_bytes(gzip.decompress(path.read_bytes()))
    with sqlite3.connect(plain) as copy:
        assert copy.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        return copy.execute("SELECT count(*) FROM jobs").fetchone()[0]


def test_backup_is_a_checked_gzip_copy_named_after_the_day(db, tmp_path):
    dest = tmp_path / "backups"
    path = backup(db, dest, keep=7, today=DAY)
    assert path == dest / "intern-radar-2026-11-03.db.gz"
    assert restored_rows(path, tmp_path) == 2
    # Nothing but the backup is left behind (no raw copy, no partial file).
    assert [p.name for p in dest.iterdir()] == [path.name]


def test_rerun_the_same_day_replaces_the_backup(db, tmp_path):
    dest = tmp_path / "backups"
    backup(db, dest, keep=7, today=DAY)
    store = Store(str(db))
    store.add(make_job(id="c"), "pending", cli.utcnow())
    store.close()
    path = backup(db, dest, keep=7, today=DAY)
    assert len(list(dest.iterdir())) == 1
    assert restored_rows(path, tmp_path) == 3


def test_only_the_newest_backups_are_kept(db, tmp_path):
    dest = tmp_path / "backups"
    for day in range(1, 10):
        backup(db, dest, keep=3, today=date(2026, 11, day))
    assert sorted(p.name for p in dest.iterdir()) == [
        backup_name(date(2026, 11, day)) for day in (7, 8, 9)
    ]


def test_prune_leaves_other_files_alone(tmp_path):
    for name in ("intern-radar-2026-11-01.db.gz", "intern-radar-2026-11-02.db.gz",
                 "notes.txt", "intern-radar.db.bak-125"):  # fmt: skip
        (tmp_path / name).write_bytes(b"x")
    removed = prune(tmp_path, keep=1)
    assert [p.name for p in removed] == ["intern-radar-2026-11-01.db.gz"]
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "intern-radar-2026-11-02.db.gz",
        "intern-radar.db.bak-125",
        "notes.txt",
    ]


def test_a_corrupt_database_is_refused(tmp_path):
    broken = tmp_path / "broken.db"
    broken.write_bytes(b"not a database at all" * 100)
    dest = tmp_path / "backups"
    with pytest.raises(BackupError):
        backup(broken, dest, keep=7, today=DAY)
    assert list(dest.iterdir()) == []


def test_missing_database_and_bad_keep(tmp_path):
    with pytest.raises(BackupError, match="no such database"):
        backup(tmp_path / "absent.db", tmp_path / "b", keep=7, today=DAY)
    with pytest.raises(ValueError):
        backup(tmp_path / "absent.db", tmp_path / "b", keep=0, today=DAY)


def test_cli_backup(db, tmp_path):
    dest = tmp_path / "backups"
    result = CliRunner().invoke(
        cli.app, ["backup", "--db", str(db), "--dest", str(dest), "--keep", "2"]
    )
    assert result.exit_code == 0, result.output
    assert "Backup written" in result.output
    assert len(list(dest.glob("intern-radar-*.db.gz"))) == 1


def test_cli_backup_failure_exits_non_zero(tmp_path):
    result = CliRunner().invoke(
        cli.app, ["backup", "--db", str(tmp_path / "absent.db"),
                  "--dest", str(tmp_path / "b")],
    )  # fmt: skip
    assert result.exit_code == 1
    assert "Backup failed" in result.output
