"""Degraded mode: vector/embedding unavailable -> KHONG crash, fallback lexical (#4)."""
import codemem.storage.vectors as vec


def test_query_returns_empty_when_no_collection(monkeypatch):
    monkeypatch.setattr(vec, "get_collection", lambda: None)
    assert vec.query("bat ky") == []


def test_index_file_noop_when_no_collection(monkeypatch):
    monkeypatch.setattr(vec, "get_collection", lambda: None)
    assert vec.index_file("/p/x.py", "python", "skel", []) is False  # bo qua, khong loi


class _FakeCol:
    def __init__(self):
        self.deleted = []

    def delete(self, where=None, ids=None):
        self.deleted.append(where)


class _FakeClient:
    def __init__(self, col=None, get_raises=False, del_raises=None):
        self._col = col or _FakeCol()
        self._get_raises = get_raises
        self._del_raises = del_raises

    def get_collection(self, name):
        if self._get_raises:
            raise RuntimeError("does not exist")
        return self._col

    def delete_collection(self, name):
        if self._del_raises:
            raise RuntimeError(self._del_raises)


def test_delete_file_scoped_by_project(monkeypatch):
    # #P0-8: delete file CO project_id -> chi xoa trong project do
    fc = _FakeCol()
    monkeypatch.setattr(vec, "_client", lambda: _FakeClient(fc))
    assert vec.delete_file("/p/x.py", project_id=2) is True
    conds = fc.deleted[0]["$and"]
    assert {"file_path": "/p/x.py"} in conds and {"project_id": 2} in conds


def test_delete_file_no_project_filter(monkeypatch):
    fc = _FakeCol()
    monkeypatch.setattr(vec, "_client", lambda: _FakeClient(fc))
    assert vec.delete_file("/p/x.py") is True
    assert fc.deleted[0] == {"file_path": "/p/x.py"}


def test_delete_unavailable_returns_false(monkeypatch):
    # #P0-10: client khong mo duoc -> KHONG dam bao da xoa -> False
    monkeypatch.setattr(vec, "_client", lambda: None)
    assert vec.delete_file("/p/x.py") is False
    assert vec.delete_project(1) is False


def test_delete_absent_collection_returns_true(monkeypatch):
    # collection khong ton tai -> khong co gi de xoa -> True
    monkeypatch.setattr(vec, "_client", lambda: _FakeClient(get_raises=True))
    assert vec.delete_file("/p/x.py") is True


def test_clear_all_real_error_returns_false(monkeypatch):
    # #P0-10: delete_collection loi that -> KHONG bao True oan
    monkeypatch.setattr(vec, "_client", lambda: _FakeClient(del_raises="disk io error"))
    assert vec.clear_all() is False


def test_clear_all_absent_returns_true(monkeypatch):
    monkeypatch.setattr(vec, "_client", lambda: _FakeClient(del_raises="Collection does not exist"))
    assert vec.clear_all() is True


def test_clear_all_unavailable_returns_false(monkeypatch):
    monkeypatch.setattr(vec, "_client", lambda: None)
    assert vec.clear_all() is False
