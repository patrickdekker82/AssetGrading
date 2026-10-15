"""Nightly back-up and the restore test (phase 10).

- `backup`: pg_dump in PostgreSQL's custom format to a folder outside the containers, with a SHA-256 file
  next to it, checked by reading its table of contents back. Keeps the last N dumps plus one per month.
- `restore_test`: restore the newest dump into an empty, temporary database and recompute every grade
  snapshot in it from its stored input and model version (the same check as `cli verify`). It also compares
  the grade columns of the restored snapshots with the live database: snapshots are append-only, so every
  restored row must be identical. The temporary database is dropped afterwards.
"""

import hashlib
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.ingest.report import Report

NAME = re.compile(r"^graadmeter-(\d{8}T\d{6}Z)\.dump$")
GRADE_CHECKSUM = """
    SELECT count(*), md5(string_agg(concat_ws('|', id, asset_id, as_of, model_version_id, status, score, letter,
                                              coverage, peg_safety), ',' ORDER BY id))
    FROM grade_snapshot WHERE id <= :max_id
"""


@dataclass
class Conn:
    host: str
    port: int
    user: str
    password: str | None
    database: str

    @classmethod
    def from_url(cls, url: str) -> "Conn":
        u = make_url(url)
        return cls(u.host or "localhost", u.port or 5432, u.username or "postgres", u.password, u.database or "")

    def env(self) -> dict:
        env = {k: v for k, v in os.environ.items() if k in ("PATH", "LANG", "LC_ALL", "HOME", "TZ")}
        if self.password:
            env["PGPASSWORD"] = self.password
        return env

    def args(self, database: str | None = None) -> list[str]:
        return ["-h", self.host, "-p", str(self.port), "-U", self.user, "-d", database or self.database]

    def url(self, database: str | None = None) -> str:
        return make_url(f"postgresql+psycopg://{self.host}:{self.port}").set(
            username=self.user, password=self.password, database=database or self.database).render_as_string(
            hide_password=False)


def _run(cmd: list[str], conn: Conn) -> None:
    res = subprocess.run(cmd, env=conn.env(), capture_output=True, text=True, timeout=3600)
    if res.returncode != 0:
        # pg tools never print the password; keep the message short.
        raise RuntimeError(f"{Path(cmd[0]).name} mislukt: {(res.stderr or res.stdout).strip()[-500:]}")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def backup(database_url: str, folder: Path, keep_daily: int, keep_monthly: int,
           now: datetime | None = None) -> tuple[Path, Report]:
    now = now or datetime.now(UTC)
    report = Report()
    conn = Conn.from_url(database_url)
    folder.mkdir(parents=True, exist_ok=True)
    if not os.access(folder, os.W_OK):
        raise RuntimeError(f"Back-upmap {folder} is niet schrijfbaar voor de server (zie README, Back-up).")
    final = folder / f"graadmeter-{now:%Y%m%dT%H%M%SZ}.dump"
    tmp = final.with_suffix(".dump.part")
    _run(["pg_dump", "-Fc", "--no-owner", "--no-privileges", "-f", str(tmp), *conn.args()], conn)
    _run(["pg_restore", "--list", str(tmp)], conn)          # the dump can be read back
    digest = sha256(tmp)
    tmp.rename(final)
    final.with_suffix(".dump.sha256").write_text(f"{digest}  {final.name}\n", encoding="utf-8")
    report.add("backup_bytes", final.stat().st_size)
    report.notes.append(f"Back-up: {final.name} ({final.stat().st_size / 1e6:.1f} MB)")
    report.add("backups_removed", prune(folder, keep_daily, keep_monthly))
    return final, report


def dumps(folder: Path) -> list[Path]:
    return sorted((p for p in folder.glob("graadmeter-*.dump") if NAME.match(p.name)), key=lambda p: p.name)


def prune(folder: Path, keep_daily: int, keep_monthly: int) -> int:
    """Keep the newest `keep_daily` dumps and the first dump of each of the newest `keep_monthly` months."""
    files = dumps(folder)
    keep = set(files[-keep_daily:])
    first_of_month: dict[str, Path] = {}
    for p in files:
        first_of_month.setdefault(NAME.match(p.name).group(1)[:6], p)
    keep |= set(sorted(first_of_month.values(), key=lambda p: p.name)[-keep_monthly:])
    removed = 0
    for p in files:
        if p not in keep:
            p.unlink()
            p.with_suffix(".dump.sha256").unlink(missing_ok=True)
            removed += 1
    return removed


def restore_test(database_url: str, folder: Path, test_database: str) -> Report:
    """Restore the newest dump into an empty database and prove it gives the same grades."""
    from app.grading.recompute import verify_all

    report = Report()
    files = dumps(folder)
    if not files:
        raise RuntimeError(f"Geen back-up gevonden in {folder}.")
    dump = files[-1]
    side = dump.with_suffix(".dump.sha256")
    if side.exists() and side.read_text().split()[0] != sha256(dump):
        raise RuntimeError(f"{dump.name}: controlegetal klopt niet; het bestand is beschadigd.")
    conn = Conn.from_url(database_url)
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", test_database) or test_database == conn.database:
        raise RuntimeError("Ongeldige naam voor de testdatabase.")
    admin = create_engine(conn.url("postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{test_database}" WITH (FORCE)'))
            c.execute(text(f'CREATE DATABASE "{test_database}"'))
        _run(["pg_restore", "--no-owner", "--no-privileges", "--exit-on-error", *conn.args(test_database),
              str(dump)], conn)
        restored = create_engine(conn.url(test_database))
        live = create_engine(database_url)
        try:
            with restored.connect() as c:
                max_id = c.execute(text("SELECT coalesce(max(id), 0) FROM grade_snapshot")).scalar()
                count_r, sum_r = c.execute(text(GRADE_CHECKSUM), {"max_id": max_id}).one()
            with live.connect() as c:
                count_l, sum_l = c.execute(text(GRADE_CHECKSUM), {"max_id": max_id}).one()
            with sessionmaker(bind=restored)() as session:
                checks = verify_all(session, None)
        finally:
            restored.dispose()
            live.dispose()
        exact = sum(1 for ch in checks if ch.ok)
        report.add("snapshots_restored", int(count_r))
        report.add("snapshots_recomputed", len(checks))
        report.add("snapshots_exact", exact)
        report.notes.append(f"Hersteltest {dump.name}: {count_r} grades teruggezet, {exact} van {len(checks)} "
                            f"opnieuw berekend en exact gelijk.")
        if (count_r, sum_r) != (count_l, sum_l):
            report.error(f"Teruggezette grades wijken af van de live database ({count_r} tegen {count_l} rijen).")
        if exact != len(checks):
            report.error(f"{len(checks) - exact} grades geven na herstel een andere uitkomst.")
    finally:
        with admin.connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{test_database}" WITH (FORCE)'))
        admin.dispose()
    return report
