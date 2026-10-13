import sqlite3

import pytest

from scripts.relocate_workspace import relocate


def make_workspace(root, old, *, file_exists=True):
    root.mkdir(parents=True)
    uploads = root / "uploads"
    uploads.mkdir()
    if file_exists:
        (uploads / "doc.docx").write_bytes(b"original file")
    database = root / "studyagent.db"
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE documents (id TEXT, file_type TEXT, storage_path TEXT)")
        db.execute("INSERT INTO documents VALUES (?, ?, ?)",
                   ("doc", "docx", str(old / "uploads/doc.docx")))
    return database


def stored_path(database):
    with sqlite3.connect(database) as db:
        return db.execute("SELECT storage_path FROM documents").fetchone()[0]


def test_relocation_dry_run_backup_and_idempotence(tmp_path):
    old, root = tmp_path / "old", tmp_path / "new"
    database = make_workspace(root, old)
    assert relocate(root, old)["documents"] == 1
    assert stored_path(database) == str(old / "uploads/doc.docx")
    assert relocate(root, old, apply=True)["documents"] == 1
    assert stored_path(database) == str(root / "uploads/doc.docx")
    backup = next((root / "backups").glob("*.db"))
    assert stored_path(backup) == str(old / "uploads/doc.docx")
    assert relocate(root, old, apply=True)["documents"] == 0
    assert (root / "uploads/doc.docx").read_bytes() == b"original file"


def test_missing_upload_prevents_all_database_updates(tmp_path):
    old, root = tmp_path / "old", tmp_path / "new"
    database = make_workspace(root, old)
    make_workspace(root / "users/student", old / "users/student", file_exists=False)
    with pytest.raises(FileNotFoundError):
        relocate(root, old, apply=True)
    assert stored_path(database) == str(old / "uploads/doc.docx")
    assert not (root / "backups").exists()
