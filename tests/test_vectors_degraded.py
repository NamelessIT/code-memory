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


# Chroma thuc te raise ValueError/NotFoundError khi absent; RuntimeError khi loi IO/corrupt.
_ABSENT = ValueError("Collection does not exist")
_IOERR = RuntimeError("disk io error")


class _FakeClient:
    def __init__(self, col=None, get_exc=None, del_exc=None):
        self._col = col or _FakeCol()
        self._get_exc = get_exc
        self._del_exc = del_exc

    def get_collection(self, name):
        if self._get_exc:
            raise self._get_exc
        return self._col

    def delete_collection(self, name):
        if self._del_exc:
            raise self._del_exc


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


def test_delete_file_with_generation_filter(monkeypatch):
    # #P0-10: generation -> chi xoa vector gen <= generation (intent cu khong xoa vector moi)
    fc = _FakeCol()
    monkeypatch.setattr(vec, "_client", lambda: _FakeClient(fc))
    vec.delete_file("/p/x.py", project_id=2, generation=5)
    conds = fc.deleted[0]["$and"]
    assert {"generation": {"$lte": 5}} in conds and {"project_id": 2} in conds


def test_delete_file_generation_zero_no_gate(monkeypatch):
    # #P0-10 legacy: generation=0 (vector legacy khong co field 'generation') -> KHONG gate $lte
    # -> xoa het, tranh orphan-but-acked. Chi gate khi gen>=1.
    fc = _FakeCol()
    monkeypatch.setattr(vec, "_client", lambda: _FakeClient(fc))
    vec.delete_file("/p/x.py", project_id=2, generation=0)
    conds = fc.deleted[0]["$and"]
    assert {"file_path": "/p/x.py"} in conds and {"project_id": 2} in conds
    assert all("generation" not in c for c in conds)   # khong co dieu kien generation


def test_delete_unavailable_returns_false(monkeypatch):
    # #P0-10: client khong mo duoc -> KHONG dam bao da xoa -> False
    monkeypatch.setattr(vec, "_client", lambda: None)
    assert vec.delete_file("/p/x.py") is False
    assert vec.delete_project(1) is False


def test_delete_absent_collection_returns_true(monkeypatch):
    # collection khong ton tai (ValueError) -> khong co gi de xoa -> True
    monkeypatch.setattr(vec, "_client", lambda: _FakeClient(get_exc=_ABSENT))
    assert vec.delete_file("/p/x.py") is True


def test_delete_io_error_returns_false(monkeypatch):
    # #P0-10: get_collection loi IO (RuntimeError) KHONG duoc coi la absent -> False
    monkeypatch.setattr(vec, "_client", lambda: _FakeClient(get_exc=_IOERR))
    assert vec.delete_file("/p/x.py") is False
    assert vec.delete_project(3) is False


def test_clear_all_real_error_returns_false(monkeypatch):
    # #P0-10: delete_collection loi that (RuntimeError) -> KHONG bao True oan
    monkeypatch.setattr(vec, "_client", lambda: _FakeClient(del_exc=_IOERR))
    assert vec.clear_all() is False


def test_clear_all_absent_returns_true(monkeypatch):
    monkeypatch.setattr(vec, "_client", lambda: _FakeClient(del_exc=_ABSENT))
    assert vec.clear_all() is True


def test_clear_all_unavailable_returns_false(monkeypatch):
    monkeypatch.setattr(vec, "_client", lambda: None)
    assert vec.clear_all() is False
