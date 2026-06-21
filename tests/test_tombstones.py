"""#P0-10: cleanup intent durable - dedup, clear wipe, backoff fairness, project collapse."""
import codemem.storage.db as db


def _fresh(tmp_path, monkeypatch, name="t.db"):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / name)
    db.init_db()


def test_dedup(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    db.add_tombstone("file", 1, "/p/a.py")
    db.add_tombstone("file", 1, "/p/a.py")          # trung -> bo qua
    assert len(db.due_tombstones()) == 1


def test_clear_all_wipes_tombstones(tmp_path, monkeypatch):
    # Codex repro: clear_all phai xoa tombstone (1 -> 0)
    _fresh(tmp_path, monkeypatch)
    db.add_tombstone("file", 1, "/p/a.py")
    assert db.tombstone_stats()["pending"] == 1
    db.clear_all()
    assert db.tombstone_stats()["pending"] == 0


def test_backoff_excludes_from_due(tmp_path, monkeypatch):
    # fail -> next_retry day toi tuong lai -> khong con due -> muc khac duoc xu ly (chong starvation)
    _fresh(tmp_path, monkeypatch)
    db.add_tombstone("file", 1, "/a")
    db.add_tombstone("file", 1, "/b")
    rows = db.due_tombstones()
    assert len(rows) == 2
    db.record_tombstone_failure(rows[0]["id"], "boom")
    due_ids = [d["id"] for d in db.due_tombstones()]
    assert rows[0]["id"] not in due_ids and len(due_ids) == 1


def test_delete_project_collapses_file_then_adds_project_intent(tmp_path, monkeypatch):
    # delete_project: collapse file-intent cu + ghi project-intent (outbox) trong cung transaction
    _fresh(tmp_path, monkeypatch)
    pid = db.get_or_create_project("/r", "R")
    db.add_tombstone("file", pid, "/r/a.py")
    db.delete_project(pid)
    due = db.due_tombstones()
    assert len(due) == 1 and due[0]["scope"] == "project" and due[0]["project_id"] == pid
    # ack -> sach
    db.ack_tombstone("project", pid)
    assert db.tombstone_stats()["pending"] == 0


def test_delete_file_writes_intent_then_ack(tmp_path, monkeypatch):
    # outbox: delete_file ghi intent atomic; ack xoa intent
    _fresh(tmp_path, monkeypatch)
    pid = db.get_or_create_project("/r", "R")
    db.upsert_file("/r/x.py", "python", "h", "s", [], project_id=pid)
    db.delete_file("/r/x.py", project_id=pid)
    due = db.due_tombstones()
    assert len(due) == 1 and due[0]["scope"] == "file" and due[0]["file_path"] == "/r/x.py"
    db.ack_tombstone("file", pid, "/r/x.py")
    assert db.tombstone_stats()["pending"] == 0


def test_upsert_sets_vector_ok_zero(tmp_path, monkeypatch):
    # #P0-5: upsert_file set vector_ok=0 (crash-safe: chua co vector)
    _fresh(tmp_path, monkeypatch)
    pid = db.get_or_create_project("/r", "R")
    db.upsert_file("/r/x.py", "python", "h", "s", [], project_id=pid)
    assert len(db.files_pending_vector(pid)) == 1


def test_delete_intent_carries_generation(tmp_path, monkeypatch):
    # #P0-10: intent xoa mang generation; re-index bump gen cao hon -> intent cu khong dung vector moi
    _fresh(tmp_path, monkeypatch)
    pid = db.get_or_create_project("/r", "R")
    g1 = db.upsert_file("/r/x.py", "python", "h1", "s", [], project_id=pid)
    db.delete_file("/r/x.py", project_id=pid)
    t = db.due_tombstones()[0]
    assert t["scope"] == "file" and t["generation"] == g1
    g2 = db.upsert_file("/r/x.py", "python", "h2", "s", [], project_id=pid)
    assert g2 > g1


def test_clear_with_collection_intent_atomic(tmp_path, monkeypatch):
    # #P0-10: clear_all(add_collection_intent=True) wipe + ghi collection intent trong 1 transaction
    _fresh(tmp_path, monkeypatch)
    db.add_tombstone("file", 1, "/a")
    db.clear_all(add_collection_intent=True)
    due = db.due_tombstones()
    assert len(due) == 1 and due[0]["scope"] == "collection"


def test_due_scope_filter_in_sql(tmp_path, monkeypatch):
    # #P0-10: filter scope trong SQL truoc LIMIT -> collection khong bi che boi file intents
    _fresh(tmp_path, monkeypatch)
    for i in range(5):
        db.add_tombstone("file", 1, f"/a{i}")
    db.add_tombstone("collection")
    got = db.due_tombstones(limit=1, scopes={"collection"})
    assert len(got) == 1 and got[0]["scope"] == "collection"


def test_interrupted_migration_recovery(tmp_path, monkeypatch):
    # #P0-8: con bang _v1 (migration gian doan) -> init_db recovery copy row + drop _v1
    import sqlite3
    p = tmp_path / "i.db"
    monkeypatch.setattr(db, "DB_PATH", p)
    db.init_db()
    c = sqlite3.connect(str(p))
    c.execute("CREATE TABLE vector_tombstones_v1 (id INTEGER PRIMARY KEY AUTOINCREMENT, "
              "project_id INTEGER, file_path TEXT, scope TEXT, created_at TEXT)")
    c.execute("INSERT INTO vector_tombstones_v1(project_id,file_path,scope,created_at) VALUES (3,'/r/a.py','file','t')")
    c.commit(); c.close()
    db.init_db()                                   # recovery
    assert any(t["file_path"] == "/r/a.py" for t in db.due_tombstones())
    c = sqlite3.connect(str(p))
    tbls = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    c.close()
    assert "vector_tombstones_v1" not in tbls       # da drop


def test_legacy_pathpk_db_migrates_then_upsert_works(tmp_path, monkeypatch):
    # #P0-8 regression: DB files path-PK cu (khong co vector_gen) -> init_db migrate xong upsert KHONG loi
    import sqlite3
    p = tmp_path / "legacy.db"
    monkeypatch.setattr(db, "DB_PATH", p)
    c = sqlite3.connect(str(p))
    c.execute("CREATE TABLE files (path TEXT PRIMARY KEY, project_id INTEGER, lang TEXT, "
              "hash TEXT, skeleton TEXT, indexed_at TEXT)")
    c.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    c.execute("INSERT INTO files(path,project_id,lang,hash,skeleton,indexed_at) "
              "VALUES ('/r/x.py',1,'python','h','s','t')")
    c.commit(); c.close()
    db.init_db()                                   # migrate path-PK -> composite (phai gom vector_gen)
    cc = db._conn()
    cols = [r["name"] for r in cc.execute("PRAGMA table_info(files)")]
    cc.close()
    assert "vector_gen" in cols and "id" in cols
    pid = db.get_or_create_project("/r2", "R2")
    g = db.upsert_file("/r2/y.py", "python", "h2", "s", [], project_id=pid)   # khong OperationalError
    assert g >= 1


def test_legacy_gen_norm_marks_pending(tmp_path, monkeypatch):
    # #P0-10/#P0-5: file vector_gen=0 (legacy) -> normalize mark vector_ok=0 de re-embed gen that
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "n.db")
    db.init_db()
    pid = db.get_or_create_project("/r", "R")
    conn = db._conn()
    conn.execute("INSERT INTO files(project_id,path,lang,hash,skeleton,indexed_at,summary,vector_ok,vector_gen) "
                 "VALUES (?,?,?,?,?,?,?,1,0)", (pid, "/r/x.py", "python", "h", "s", "t", ""))
    conn.execute("DELETE FROM meta WHERE key='legacy_gen_norm'")
    conn.commit(); conn.close()
    db.init_db()                                   # rerun normalize
    assert len(db.files_pending_vector(pid)) == 1   # gen=0 -> vector_ok=0


def test_files_needing_summary_includes_vector_gen(tmp_path, monkeypatch):
    # #P0-5: summarizer ghi generation tu f["vector_gen"]; query PHAI SELECT vector_gen
    # (truoc day thieu -> summary luon ghi generation=0).
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "s.db")
    db.init_db()
    pid = db.get_or_create_project("/r", "R")
    g = db.upsert_file("/r/x.py", "python", "h", "skel", [], project_id=pid)
    rows = db.files_needing_summary(project_id=pid)
    assert len(rows) == 1 and rows[0]["vector_gen"] == g and g >= 1


def test_schema_v1_upgrade_preserves_rows(tmp_path, monkeypatch):
    # #P0-10: nang cap bang tombstone v1 -> v2 GIU LAI row pending (Codex repro 1->1, khong mat)
    import sqlite3
    p = tmp_path / "u.db"
    monkeypatch.setattr(db, "DB_PATH", p)
    # Tao bang v1 (schema cu: khong co attempts) + 1 row
    c = sqlite3.connect(str(p))
    c.execute("CREATE TABLE vector_tombstones (id INTEGER PRIMARY KEY AUTOINCREMENT, "
              "project_id INTEGER, file_path TEXT, scope TEXT, created_at TEXT)")
    c.execute("INSERT INTO vector_tombstones(project_id,file_path,scope,created_at) VALUES (7,'/r/a.py','file','t')")
    c.commit(); c.close()
    db.init_db()                                   # upgrade v1 -> v2
    due = db.due_tombstones()
    assert len(due) == 1 and due[0]["scope"] == "file" and due[0]["project_id"] == 7  # row giu lai


def test_failure_records_attempts_and_error(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    db.add_tombstone("project", 5, "")
    tid = db.due_tombstones()[0]["id"]
    db.record_tombstone_failure(tid, "disk full")
    st = db.tombstone_stats()
    assert st["failed"] == 1 and st["last_error"] == "disk full"
