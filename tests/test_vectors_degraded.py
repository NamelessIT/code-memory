"""Degraded mode: vector/embedding unavailable -> KHONG crash, fallback lexical (#4)."""
import codemem.storage.vectors as vec


def test_query_returns_empty_when_no_collection(monkeypatch):
    monkeypatch.setattr(vec, "get_collection", lambda: None)
    assert vec.query("bat ky") == []


def test_index_file_noop_when_no_collection(monkeypatch):
    monkeypatch.setattr(vec, "get_collection", lambda: None)
    assert vec.index_file("/p/x.py", "python", "skel", []) is False  # bo qua, khong loi


def test_delete_does_not_crash_when_no_raw(monkeypatch):
    monkeypatch.setattr(vec, "_raw", lambda: None)
    vec.delete_file("/p/x.py")          # khong raise
    vec.delete_project(1)               # khong raise


class _FakeCol:
    def __init__(self):
        self.deleted = []

    def delete(self, where=None, ids=None):
        self.deleted.append(where)


def test_delete_file_scoped_by_project(monkeypatch):
    # #P0-8: delete file CO project_id -> chi xoa trong project do
    fc = _FakeCol()
    monkeypatch.setattr(vec, "_raw", lambda: fc)
    vec.delete_file("/p/x.py", project_id=2)
    assert "$and" in fc.deleted[0]
    conds = fc.deleted[0]["$and"]
    assert {"file_path": "/p/x.py"} in conds and {"project_id": 2} in conds


def test_delete_file_no_project_filter(monkeypatch):
    fc = _FakeCol()
    monkeypatch.setattr(vec, "_raw", lambda: fc)
    vec.delete_file("/p/x.py")
    assert fc.deleted[0] == {"file_path": "/p/x.py"}
