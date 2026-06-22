"""P0-6: watcher bind project_id + generation guard (khong ghi vao project moi sau switch)."""
import codemem.indexer.watcher as w


def test_stale_flush_skipped(monkeypatch):
    calls = []
    monkeypatch.setattr(w, "index_single_file", lambda path, project_id=None: calls.append(path))
    monkeypatch.setattr(w, "remove_file", lambda path, project_id=None: calls.append(("del", path)))
    m = w.WatcherManager()
    m.generation = 5
    m.project_id = 2
    m._pending = {"/p/x.py": False}
    m._flush(gen=4)                 # generation cu (da switch) -> bo qua
    assert calls == []


def test_stale_flush_does_not_clear_current_pending(monkeypatch):
    # #P0-6 repro: timer cu (gen 1) chay khi generation da la 2 voi pending moi -> KHONG duoc clear
    # pending cua generation hien tai (truoc day stale branch goi _pending.clear() -> mat du lieu).
    calls = []
    monkeypatch.setattr(w, "index_single_file", lambda path, project_id=None: calls.append(path))
    m = w.WatcherManager()
    m.generation = 2
    m.project_id = 5
    m._pending = {"/new-generation.py": False}   # pending cua generation hien tai (2)
    m._flush(gen=1)                              # stale timer gen 1
    assert m._pending == {"/new-generation.py": False}   # van con nguyen
    assert calls == []                           # stale -> khong ghi


def test_flush_binds_project_id(monkeypatch):
    calls = []
    monkeypatch.setattr(w, "index_single_file", lambda path, project_id=None: calls.append((path, project_id)))
    monkeypatch.setattr(w.db, "project_exists", lambda pid: True)
    m = w.WatcherManager()
    m.generation = 5
    m.project_id = 7
    m._pending = {"/p/x.py": False}
    m._flush(gen=5)                 # dung generation + project ton tai -> dung project_id da bind
    assert calls == [("/p/x.py", 7)]


def test_flush_delete_binds_project_id(monkeypatch):
    calls = []
    monkeypatch.setattr(w, "remove_file", lambda path, project_id=None: calls.append((path, project_id)))
    monkeypatch.setattr(w.db, "project_exists", lambda pid: True)
    m = w.WatcherManager()
    m.generation = 3
    m.project_id = 9
    m._pending = {"/p/y.py": True}
    m._flush(gen=3)
    assert calls == [("/p/y.py", 9)]


def test_flush_drops_when_project_deleted(monkeypatch):
    # #P0-6: generation khop nhung project da bi xoa giua luc copy pending va luc ghi -> KHONG ghi
    calls = []
    monkeypatch.setattr(w, "index_single_file", lambda path, project_id=None: calls.append(path))
    monkeypatch.setattr(w, "remove_file", lambda path, project_id=None: calls.append(("del", path)))
    monkeypatch.setattr(w.db, "project_exists", lambda pid: False)   # project da xoa
    m = w.WatcherManager()
    m.generation = 2
    m.project_id = 5
    m._pending = {"/p/x.py": False}
    m._flush(gen=2)                 # gen khop nhung project gone -> re-check trong INDEX_LOCK drop
    assert calls == []


def test_flush_drops_when_generation_advances_after_copy(monkeypatch):
    # #P0-6: generation tang (stop/switch) ngay truoc khi ghi -> re-check trong lock bo, khong ghi.
    calls = []
    monkeypatch.setattr(w, "index_single_file", lambda path, project_id=None: calls.append(path))
    monkeypatch.setattr(w.db, "project_exists", lambda pid: True)
    m = w.WatcherManager()
    m.generation = 4
    m.project_id = 6
    m._pending = {"/p/x.py": False}

    # mo phong: ngay sau khi copy pending (first check pass), co stop/switch -> generation++.
    real_lock = w.INDEX_LOCK

    class _BumpLock:
        def __enter__(self):
            m.generation += 1          # switch xay ra truoc khi vao vung ghi
            return real_lock.__enter__()

        def __exit__(self, *a):
            return real_lock.__exit__(*a)
    monkeypatch.setattr(w, "INDEX_LOCK", _BumpLock())
    m._flush(gen=4)                    # gen khop o first check, nhung lech khi re-check trong lock
    assert calls == []
