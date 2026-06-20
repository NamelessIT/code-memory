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


def test_flush_binds_project_id(monkeypatch):
    calls = []
    monkeypatch.setattr(w, "index_single_file", lambda path, project_id=None: calls.append((path, project_id)))
    m = w.WatcherManager()
    m.generation = 5
    m.project_id = 7
    m._pending = {"/p/x.py": False}
    m._flush(gen=5)                 # dung generation -> dung project_id da bind
    assert calls == [("/p/x.py", 7)]


def test_flush_delete_binds_project_id(monkeypatch):
    calls = []
    monkeypatch.setattr(w, "remove_file", lambda path, project_id=None: calls.append((path, project_id)))
    m = w.WatcherManager()
    m.generation = 3
    m.project_id = 9
    m._pending = {"/p/y.py": True}
    m._flush(gen=3)
    assert calls == [("/p/y.py", 9)]
