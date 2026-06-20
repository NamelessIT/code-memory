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


def test_delete_project_collapses_file_then_adds_project_intent(tmp_path, monkeypatch):
    # delete_project: collapse file-intent cu + ghi project-intent (outbox) trong cung transaction
    _fresh(tmp_path, monkeypatch)
    pid = db.get_or_create_project("/r", "R")
    db.add_tombstone("file", pid, "/r/a.py")
    db.delete_project(pid)
    due = db.due_tombstones()
    assert len(due) == 1 and due[0]["scope"] == "project" and due[0]["project_id"] == pid
    # ack -> sach
    db.ack_tombstone("project", pid)
    assert db.tombstone_stats()["pending"] == 0


def test_delete_file_writes_intent_then_ack(tmp_path, monkeypatch):
    # outbox: delete_file ghi intent atomic; ack xoa intent
    _fresh(tmp_path, monkeypatch)
    pid = db.get_or_create_project("/r", "R")
    db.upsert_file("/r/x.py", "python", "h", "s", [], project_id=pid)
    db.delete_file("/r/x.py", project_id=pid)
    due = db.due_tombstones()
    assert len(due) == 1 and due[0]["scope"] == "file" and due[0]["file_path"] == "/r/x.py"
    db.ack_tombstone("file", pid, "/r/x.py")
    assert db.tombstone_stats()["pending"] == 0


def test_schema_v1_upgrade_preserves_rows(tmp_path, monkeypatch):
    # #P0-10: nang cap bang tombstone v1 -> v2 GIU LAI row pending (Codex repro 1->1, khong mat)
    import sqlite3
    p = tmp_path / "u.db"
    monkeypatch.setattr(db, "DB_PATH", p)
    # Tao bang v1 (schema cu: khong co attempts) + 1 row
    c = sqlite3.connect(str(p))
    c.execute("CREATE TABLE vector_tombstones (id INTEGER PRIMARY KEY AUTOINCREMENT, "
              "project_id INTEGER, file_path TEXT, scope TEXT, created_at TEXT)")
    c.execute("INSERT INTO vector_tombstones(project_id,file_path,scope,created_at) VALUES (7,'/r/a.py','file','t')")
    c.commit(); c.close()
    db.init_db()                                   # upgrade v1 -> v2
    due = db.due_tombstones()
    assert len(due) == 1 and due[0]["scope"] == "file" and due[0]["project_id"] == 7  # row giu lai


def test_failure_records_attempts_and_error(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    db.add_tombstone("project", 5, "")
    tid = db.due_tombstones()[0]["id"]
    db.record_tombstone_failure(tid, "disk full")
    st = db.tombstone_stats()
    assert st["failed"] == 1 and st["last_error"] == "disk full"
