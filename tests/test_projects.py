"""Multi-project isolation: index A & B doc lap; switch/search/delete chi tac dong project chon."""
import codemem.storage.db as db


def _sym(name):
    return {"kind": "function", "name": name, "signature": f"def {name}()",
            "start_line": 1, "end_line": 2, "parent": None, "exported": False,
            "tag": "", "doc": "", "body": f"def {name}(): pass"}


def test_project_isolation(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")  # DB tam, khong dung data that
    db.init_db()

    a = db.get_or_create_project("/root/a", "A")
    b = db.get_or_create_project("/root/b", "B")
    db.upsert_file("/root/a/x.py", "python", "h1", "skel", [_sym("alpha")], project_id=a)
    db.upsert_file("/root/b/y.py", "python", "h2", "skel", [_sym("beta")], project_id=b)

    # Active A: chi thay symbol cua A
    db.set_active_project(a)
    assert db.get_status()["symbols"] == 1
    assert [s["name"] for s in db.search_symbols("alpha")] == ["alpha"]
    assert db.search_symbols("beta") == []           # symbol cua B khong lo sang A

    # Switch B
    db.set_active_project(b)
    assert [s["name"] for s in db.search_symbols("beta")] == ["beta"]

    # Hai project cung ton tai
    assert len(db.list_projects()) == 2

    # Xoa B -> A van nguyen
    db.delete_project(b)
    assert len(db.list_projects()) == 1
    assert db.get_status(a)["symbols"] == 1


def test_indexed_hashes_scoped(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t2.db")
    db.init_db()
    a = db.get_or_create_project("/r/a", "A")
    b = db.get_or_create_project("/r/b", "B")
    db.upsert_file("/r/a/f.py", "python", "ha", "s", [], project_id=a)
    db.upsert_file("/r/b/f.py", "python", "hb", "s", [], project_id=b)
    assert db.get_indexed_hashes(a) == {"/r/a/f.py": "ha"}
    assert db.get_indexed_hashes(b) == {"/r/b/f.py": "hb"}
