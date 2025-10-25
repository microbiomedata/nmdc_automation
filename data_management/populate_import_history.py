#!/usr/bin/env python3
"""Populate the import_history table using existing metadata*.json.done files."""

from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

DEFAULT_ENV = "prod"
TABLE_DDL = """
CREATE TABLE IF NOT EXISTS import_history (
  filename TEXT NOT NULL,
  env TEXT NOT NULL,
  update_time TEXT NOT NULL,
  PRIMARY KEY (filename, env)
);
"""
UPSERT_SQL = (
    "INSERT INTO import_history (filename, env, update_time) VALUES (?, ?, ?) "
    "ON CONFLICT(filename, env) DO UPDATE SET update_time=excluded.update_time;"
)


def parse_args() -> argparse.Namespace:
    script_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(
        description=(
            "Populate the import_history SQLite table based on metadata*.json.done "
            "files. Uses each file's modification time as update_time."
        )
    )
    parser.add_argument(
        "metadata_dir",
        help="Path to the directory containing metadata*.json.done files",
    )
    parser.add_argument(
        "--env",
        default=DEFAULT_ENV,
        help="Environment label to store (default: %(default)s)",
    )
    parser.add_argument(
        "--db-path",
        default=str(script_dir / "jamo_import.db"),
        help="Path to the SQLite database file (default: %(default)s)",
    )
    return parser.parse_args()


def ensure_db(conn: sqlite3.Connection) -> None:
    conn.execute(TABLE_DDL)
    conn.commit()


def iter_done_files(metadata_dir: Path) -> Iterable[Path]:
    yield from metadata_dir.glob("metadata*.json.done")


def mtime_to_iso(path: Path) -> str:
    mtime = path.stat().st_mtime
    dt = datetime.fromtimestamp(mtime, tz=timezone.utc)
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    args = parse_args()
    metadata_dir = Path(args.metadata_dir).expanduser().resolve()
    if not metadata_dir.is_dir():
        raise SystemExit(f"Error: metadata directory '{metadata_dir}' does not exist or is not a directory.")

    db_path = Path(args.db_path).expanduser().resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    try:
        ensure_db(conn)
        processed = 0
        updated = 0

        for done_file in iter_done_files(metadata_dir):
            if not done_file.is_file():
                continue

            base_name = done_file.name[:-5] if done_file.name.endswith(".done") else done_file.name
            update_time = mtime_to_iso(done_file)

            conn.execute(UPSERT_SQL, (base_name, args.env, update_time))
            processed += 1
            updated += 1
            print(f"Recorded {base_name} for environment '{args.env}' at {update_time}.")

        conn.commit()
    finally:
        conn.close()

    if processed == 0:
        print("No metadata*.json.done files found.")
    else:
        print(f"Processed {processed} file(s) for environment '{args.env}'.")


if __name__ == "__main__":
    main()
