"""Repair validated upload paths after moving DATA_DIR; back up before updating."""

import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def relocate(data_dir: Path, previous_data_dir: Path, *, apply=False):
    root = data_dir.resolve()
    if not previous_data_dir.is_absolute():
        raise ValueError("previous_data_dir must be absolute")
    databases = [root / "studyagent.db"]
    users = root / "users"
    if users.exists():
        databases.extend(users.glob("*/studyagent.db"))
    plans = []
    for database in databases:
        if not database.is_file():
            continue
        workspace = database.parent
        if not workspace.resolve().is_relative_to(root):
            raise ValueError("database outside DATA_DIR")
        old_workspace = previous_data_dir / workspace.relative_to(root)
        with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
            rows = connection.execute("SELECT id, file_type, storage_path FROM documents").fetchall()
        changes = []
        for identifier, file_type, old in rows:
            stored = Path(old)
            if stored.parent != old_workspace / "uploads":
                continue
            filename = f"{identifier}.{file_type}"
            target = workspace / "uploads" / filename
            if stored.name != filename or target.resolve().parent != (workspace / "uploads").resolve():
                raise ValueError("unexpected upload path")
            if not target.is_file():
                raise FileNotFoundError(f"relocated upload missing: {filename}")
            changes.append((str(target.resolve()), identifier, old))
        if changes:
            plans.append((database, changes))
    if apply:
        for database, changes in plans:
            backup_dir = root / "backups"
            backup_dir.mkdir(exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            backup = backup_dir / f"relocation-{stamp}-{uuid4().hex[:8]}.db"
            with sqlite3.connect(database) as connection:
                with sqlite3.connect(backup) as destination:
                    connection.backup(destination)
                connection.execute("BEGIN IMMEDIATE")
                for target, identifier, old in changes:
                    changed = connection.execute(
                        "UPDATE documents SET storage_path=? WHERE id=? AND storage_path=?",
                        (target, identifier, old),
                    ).rowcount
                    if changed != 1:
                        raise RuntimeError("document changed during relocation; transaction rolled back")
    return {"databases": len(plans), "documents": sum(len(rows) for _, rows in plans), "applied": apply}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--previous-data-dir", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(relocate(args.data_dir, args.previous_data_dir, apply=args.apply))
