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
