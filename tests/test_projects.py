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


def test_nested_projects_no_overwrite(tmp_path, monkeypatch):
    # Project long nhau: cung file tuyet doi index o A va B -> KHONG cuop cua nhau (#8)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "n.db")
    db.init_db()
    a = db.get_or_create_project("/repo/sub", "A")
    b = db.get_or_create_project("/repo", "B")
    p = "/repo/sub/x.py"
    db.upsert_file(p, "python", "h1", "skelA", [_sym("fa")], project_id=a)
    db.upsert_file(p, "python", "h2", "skelB", [_sym("fb")], project_id=b)
    assert db.get_status(a)["files"] == 1          # A khong bi B cuop file
    assert db.get_status(b)["files"] == 1
    assert db.get_skeleton(p, project_id=a) == "skelA"
    assert db.get_skeleton(p, project_id=b) == "skelB"
    assert [s["name"] for s in db.search_symbols("fa", project_id=a)] == ["fa"]
    assert [s["name"] for s in db.search_symbols("fb", project_id=b)] == ["fb"]


def test_overview_invalidated_on_file_change(tmp_path, monkeypatch):
    # File doi -> overview project bi xoa (#3)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "o.db")
    db.init_db()
    a = db.get_or_create_project("/r", "A")
    db.upsert_file("/r/x.py", "python", "h", "s", [_sym("f")], project_id=a)
    db.set_overview("OVERVIEW CU", project_id=a)
    assert db.get_overview(a) == "OVERVIEW CU"
    db.upsert_file("/r/x.py", "python", "h2", "s2", [_sym("f")], project_id=a)
    assert db.get_overview(a) == ""                 # invalidate


def test_set_active_invalid_project(tmp_path, monkeypatch):
    # set_active project khong ton tai -> False (#9)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "i.db")
    db.init_db()
    assert db.set_active_project(999999) is False
    assert db.project_exists(999999) is False


def test_delete_active_picks_next(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "d.db")
    db.init_db()
    a = db.get_or_create_project("/a", "A")
    b = db.get_or_create_project("/b", "B")
    db.set_active_project(a)
    db.delete_project(a)
    assert db.active_project_id() == b               # tu chon project con lai


def test_indexed_hashes_scoped(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t2.db")
    db.init_db()
    a = db.get_or_create_project("/r/a", "A")
    b = db.get_or_create_project("/r/b", "B")
    db.upsert_file("/r/a/f.py", "python", "ha", "s", [], project_id=a)
    db.upsert_file("/r/b/f.py", "python", "hb", "s", [], project_id=b)
    assert db.get_indexed_hashes(a) == {"/r/a/f.py": "ha"}
    assert db.get_indexed_hashes(b) == {"/r/b/f.py": "hb"}
