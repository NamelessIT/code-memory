"""P0-5: vector reconciliation - file pending duoc retry; that bai -> van pending."""
import codemem.indexer.runner as runner


def _isolate(monkeypatch):
    """Tach reconcile khoi DB that: bo qua embed-check + tombstone."""
    monkeypatch.setattr(runner, "ensure_embed_current", lambda: False)
    monkeypatch.setattr(runner, "_retry_tombstones", lambda *a, **k: 0)


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
    # #P0-10: retry thanh cong moi scope -> xoa khoi danh sach
    tombs = [{"id": 1, "scope": "file", "project_id": 2, "file_path": "/p/a.py", "generation": 4},
             {"id": 2, "scope": "project", "project_id": 3, "file_path": ""},
             {"id": 3, "scope": "collection", "project_id": 0, "file_path": ""}]
    monkeypatch.setattr(runner.db, "due_tombstones", lambda batch=50, scopes=None: tombs)
    monkeypatch.setattr(runner.vectors, "delete_file", lambda p, project_id=None, generation=None: True)
    monkeypatch.setattr(runner.vectors, "delete_project", lambda pid: True)
    monkeypatch.setattr(runner.vectors, "clear_all", lambda: True)
    deleted = []
    monkeypatch.setattr(runner.db, "del_tombstone", lambda tid: deleted.append(tid))
    assert runner._retry_tombstones() == 3
    assert deleted == [1, 2, 3]


def test_retry_tombstones_backoff_on_failure(monkeypatch):
    # #P0-10: fail -> record_tombstone_failure (backoff), KHONG del
    monkeypatch.setattr(runner.db, "due_tombstones",
                        lambda batch=50, scopes=None: [{"id": 1, "scope": "file", "project_id": 2, "file_path": "/p/a.py", "generation": 1}])
    monkeypatch.setattr(runner.vectors, "delete_file", lambda p, project_id=None, generation=None: False)
    failed = []
    monkeypatch.setattr(runner.db, "record_tombstone_failure", lambda tid, err="": failed.append(tid))
    monkeypatch.setattr(runner.db, "del_tombstone",
                        lambda tid: (_ for _ in ()).throw(AssertionError("khong duoc del khi fail")))
    assert runner._retry_tombstones() == 0
    assert failed == [1]


def test_cleanup_worker_independent_of_project(monkeypatch):
    # #P0-10: cleanup_worker retry moi scope, KHONG can active project
    monkeypatch.setattr(runner.db, "due_tombstones",
                        lambda batch=50, scopes=None: [{"id": 1, "scope": "project", "project_id": 9, "file_path": ""}])
    monkeypatch.setattr(runner.vectors, "delete_project", lambda pid: True)
    deleted = []
    monkeypatch.setattr(runner.db, "del_tombstone", lambda tid: deleted.append(tid))
    assert runner.cleanup_worker() == 1 and deleted == [1]


def test_retry_scopes_filter_excludes_collection(monkeypatch):
    # #P0-10 fence: scopes={'file'} -> KHONG dung clear_all (collection bo qua)
    tombs = [{"id": 1, "scope": "file", "project_id": 2, "file_path": "/a", "generation": 1},
             {"id": 2, "scope": "collection", "project_id": 0, "file_path": ""}]
    # due_tombstones filter scope trong SQL -> fake phai ton trong scopes
    monkeypatch.setattr(runner.db, "due_tombstones",
                        lambda batch=50, scopes=None: [t for t in tombs if scopes is None or t["scope"] in scopes])
    monkeypatch.setattr(runner.vectors, "delete_file", lambda p, project_id=None, generation=None: True)
    cleared_collection = []
    monkeypatch.setattr(runner.vectors, "clear_all", lambda: cleared_collection.append(1) or True)
    monkeypatch.setattr(runner.db, "del_tombstone", lambda tid: None)
    runner._retry_tombstones(scopes={"file"})
    assert cleared_collection == []                # collection KHONG bi xu ly khi fence


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
