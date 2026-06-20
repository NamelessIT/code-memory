"""Retrieval grounding: insufficient evidence, nguong distance, call-graph loc noi bo."""
import codemem.retrieval.search as search


def _common(monkeypatch):
    monkeypatch.setattr(search.db, "active_project_id", lambda: 1)
    monkeypatch.setattr(search.db, "get_overview", lambda *a, **k: "")
    monkeypatch.setattr(search.db, "get_active_root", lambda: "/p")


def test_insufficient_evidence(monkeypatch):
    _common(monkeypatch)
    monkeypatch.setattr(search.vectors, "query", lambda *a, **k: [])
    monkeypatch.setattr(search.db, "search_symbols", lambda *a, **k: [])
    text, sources = search.build_context("bat ky cau hoi nao")
    assert text == "" and sources == []


def test_semantic_distance_threshold(monkeypatch):
    _common(monkeypatch)
    far = [{"file_path": "/p/a.py", "name": "foo", "kind": "function",
            "start_line": 1, "_distance": 5.0}]
    monkeypatch.setattr(search.vectors, "query", lambda *a, **k: far)
    monkeypatch.setattr(search.db, "search_symbols", lambda *a, **k: [])
    text, sources = search.build_context("hoi gi do khong lien quan")
    assert text == "" and sources == []


def test_context_built_when_relevant(monkeypatch):
    _common(monkeypatch)
    near = [{"file_path": "/p/a.py", "name": "foo", "kind": "function",
             "start_line": 3, "_distance": 0.2}]
    monkeypatch.setattr(search.vectors, "query", lambda *a, **k: near)
    monkeypatch.setattr(search.db, "search_symbols", lambda *a, **k: [])
    monkeypatch.setattr(search.db, "get_symbol_in_file",
                        lambda n, f: {"signature": "def foo():", "start_line": 3,
                                      "body": "def foo(): return bar()", "doc": "lam foo"})
    monkeypatch.setattr(search.db, "get_skeleton", lambda f: "FILE: a.py\nSYMBOLS:\n [function] foo")
    monkeypatch.setattr(search.db, "get_file_summary", lambda f: "")
    monkeypatch.setattr(search.db, "get_callees", lambda n, k=12: ["bar", "print"])
    monkeypatch.setattr(search.db, "get_callers", lambda n, k=12: [])
    monkeypatch.setattr(search.db, "symbol_exists", lambda n: n == "bar")  # loai built-in print
    monkeypatch.setattr(search.db, "get_meta", lambda k: "/p" if k == "project_root" else None)

    text, sources = search.build_context("foo lam gi")
    assert "foo" in text
    assert "a.py" in sources
    assert "bar" in text and "print" not in text   # call graph chi giu noi bo
    assert "EVIDENCE" in text
