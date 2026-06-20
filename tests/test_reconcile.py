"""P0-5: vector reconciliation - file pending duoc retry; that bai -> van pending."""
import codemem.indexer.runner as runner


def test_reconcile_repairs_pending(monkeypatch):
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
    monkeypatch.setattr(runner.db, "files_pending_vector",
                        lambda pid: [{"path": "/p/a.py", "lang": "python", "skeleton": "s"}])
    monkeypatch.setattr(runner.db, "get_symbols_for_file", lambda p, project_id=None: [])
    monkeypatch.setattr(runner.vectors, "index_file", lambda *a, **k: False)  # vector van loi
    monkeypatch.setattr(runner.db, "set_vector_ok", lambda *a, **k: None)
    res = runner.reconcile_vectors(1)
    assert res["pending"] == 1 and res["repaired"] == 0
