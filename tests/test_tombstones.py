"""#P0-10: cleanup intent durable - dedup, clear wipe, backoff fairness, project collapse."""
import codemem.storage.db as db


def _fresh(tmp_path, monkeypatch, name="t.db"):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / name)
    db.init_db()


def test_dedup(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    db.add_tombstone("file", 1, "/p/a.py")
    db.add_tombstone("file", 1, "/p/a.py")          # trung -> bo qua
    assert len(db.due_tombstones()) == 1


def test_clear_all_wipes_tombstones(tmp_path, monkeypatch):
    # Codex repro: clear_all phai xoa tombstone (1 -> 0)
    _fresh(tmp_path, monkeypatch)
    db.add_tombstone("file", 1, "/p/a.py")
    assert db.tombstone_stats()["pending"] == 1
    db.clear_all()
    assert db.tombstone_stats()["pending"] == 0


def test_backoff_excludes_from_due(tmp_path, monkeypatch):
    # fail -> next_retry day toi tuong lai -> khong con due -> muc khac duoc xu ly (chong starvation)
    _fresh(tmp_path, monkeypatch)
    db.add_tombstone("file", 1, "/a")
    db.add_tombstone("file", 1, "/b")
    rows = db.due_tombstones()
    assert len(rows) == 2
    db.record_tombstone_failure(rows[0]["id"], "boom")
    due_ids = [d["id"] for d in db.due_tombstones()]
    assert rows[0]["id"] not in due_ids and len(due_ids) == 1


def test_delete_project_collapses_file_tombstones(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    pid = db.get_or_create_project("/r", "R")
    db.add_tombstone("file", pid, "/r/a.py")
    db.delete_project(pid)
    assert db.tombstone_stats()["pending"] == 0


def test_failure_records_attempts_and_error(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    db.add_tombstone("project", 5, "")
    tid = db.due_tombstones()[0]["id"]
    db.record_tombstone_failure(tid, "disk full")
    st = db.tombstone_stats()
    assert st["failed"] == 1 and st["last_error"] == "disk full"
