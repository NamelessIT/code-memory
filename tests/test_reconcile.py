"""P0-5: vector reconciliation - file pending duoc retry; that bai -> van pending."""
import codemem.indexer.runner as runner


def _isolate(monkeypatch):
    """Tach reconcile khoi DB that: bo qua embed-check + tombstone."""
    monkeypatch.setattr(runner, "ensure_embed_current", lambda: False)
    monkeypatch.setattr(runner, "_retry_tombstones", lambda: 0)


def test_reconcile_repairs_pending(monkeypatch):
    _isolate(monkeypatch)
    monkeypatch.setattr(runner.db, "files_pending_vector",
                        lambda pid: [{"path": "/p/a.py", "lang": "python", "skeleton": "s"}])
    monkeypatch.setattr(runner.db, "get_symbols_for_file", lambda p, project_id=None: [])
    monkeypatch.setattr(runner.vectors, "index_file", lambda *a, **k: True)
    setok = {}
    monkeypatch.setattr(runner.db, "set_vector_ok", lambda path, ok, pid: setok.update({path: ok}))
    res = runner.reconcile_vectors(1)
    assert res["repaired"] == 1 and res["pending"] == 0
    assert setok["/p/a.py"] is True


def test_reconcile_still_pending_on_failure(monkeypatch):
    _isolate(monkeypatch)
    monkeypatch.setattr(runner.db, "files_pending_vector",
                        lambda pid: [{"path": "/p/a.py", "lang": "python", "skeleton": "s"}])
    monkeypatch.setattr(runner.db, "get_symbols_for_file", lambda p, project_id=None: [])
    monkeypatch.setattr(runner.vectors, "index_file", lambda *a, **k: False)  # vector van loi
    monkeypatch.setattr(runner.db, "set_vector_ok", lambda *a, **k: None)
    res = runner.reconcile_vectors(1)
    assert res["pending"] == 1 and res["repaired"] == 0


def test_retry_tombstones_clears_on_success(monkeypatch):
    # #P0-10: tombstone retry thanh cong -> xoa khoi danh sach
    tombs = [{"id": 1, "project_id": 2, "file_path": "/p/a.py", "scope": "file"},
             {"id": 2, "project_id": 3, "file_path": None, "scope": "project"}]
    monkeypatch.setattr(runner.db, "list_tombstones", lambda: tombs)
    monkeypatch.setattr(runner.vectors, "delete_file", lambda p, project_id=None: True)
    monkeypatch.setattr(runner.vectors, "delete_project", lambda pid: True)
    deleted = []
    monkeypatch.setattr(runner.db, "del_tombstone", lambda tid: deleted.append(tid))
    assert runner._retry_tombstones() == 2
    assert deleted == [1, 2]


def test_retry_tombstones_keeps_on_failure(monkeypatch):
    monkeypatch.setattr(runner.db, "list_tombstones",
                        lambda: [{"id": 1, "project_id": 2, "file_path": "/p/a.py", "scope": "file"}])
    monkeypatch.setattr(runner.vectors, "delete_file", lambda p, project_id=None: False)
    deleted = []
    monkeypatch.setattr(runner.db, "del_tombstone", lambda tid: deleted.append(tid))
    assert runner._retry_tombstones() == 0
    assert deleted == []                    # giu lai de retry sau


def test_ensure_embed_current_marks_stale(tmp_path, monkeypatch):
    # #P0-5: doi embedding model -> mark moi vector stale; goi lai -> no-op
    import codemem.storage.db as db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "e.db")
    db.init_db()
    a = db.get_or_create_project("/r", "A")
    db.upsert_file("/r/x.py", "python", "h", "s", [], project_id=a)
    db.set_meta("embed_model", "OLD-MODEL")
    assert runner.ensure_embed_current() is True
    assert len(db.files_pending_vector(a)) == 1     # da mark vector_ok=0
    assert runner.ensure_embed_current() is False   # meta == config -> no-op
