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


def test_generation_monotonic_after_stale_meta(tmp_path, monkeypatch):
    # #P0-10: meta.vec_gen_seq mat/thap (vd sau restore) nhung files/tombstones gen cao -> gen moi
    # PHAI > max(file,tombstone); neu khong, tombstone $lte cu se xoa nham vector moi.
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "g.db")
    db.init_db()
    pid = db.get_or_create_project("/r", "R")
    conn = db._conn()
    conn.execute("INSERT INTO files(project_id,path,lang,hash,skeleton,indexed_at,summary,vector_ok,vector_gen) "
                 "VALUES (?,?,?,?,?,?,?,1,90)", (pid, "/r/old.py", "python", "h", "s", "t", ""))
    conn.execute("INSERT INTO vector_tombstones(scope,project_id,file_path,next_retry,created_at,generation) "
                 "VALUES ('file',?,?,?,?,75)", (pid, "/r/gone.py", "t", "t"))
    conn.execute("DELETE FROM meta WHERE key='vec_gen_seq'")          # meta mat
    conn.commit()
    conn.close()
    g = db.upsert_file("/r/new.py", "python", "h2", "s", [], project_id=pid)
    assert g > 90                                                     # khong tut duoi file gen cu
    g2 = db.reserve_file_generation("/r/old.py", pid)
    assert g2 > g                                                     # van monotonic


def test_generation_unique_under_concurrency(tmp_path, monkeypatch):
    # #P0-10: nhieu connection goi upsert_file dong thoi -> generation DUY NHAT, tang nghiem ngat
    # (repro cu tra [1,1,1,1,2,2,2,2]). allocate_generation BEGIN IMMEDIATE serialize doc-sua-ghi.
    import threading
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "c.db")
    db.init_db()
    pid = db.get_or_create_project("/r", "R")
    gens = []
    lock = threading.Lock()
    barrier = threading.Barrier(8)

    def worker(i):
        barrier.wait()                           # ep 8 thread ghi gan nhu cung luc
        g = db.upsert_file(f"/r/f{i}.py", "python", "h", "s", [], project_id=pid)
        with lock:
            gens.append(g)
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(gens) == 8
    assert len(set(gens)) == 8                    # khong tai su dung gen
    assert max(gens) - min(gens) == 7            # lien tuc tang (khong nhay/trung)


def test_upsert_same_file_concurrent_newest_gen_wins(tmp_path, monkeypatch):
    # #P0-10 (Batch A): hai writer cung /r/same.py -> allocation+mutation trong 1 transaction
    # IMMEDIATE nen khong interleave; writer gen cao commit sau cung => row cuoi la cua gen cao
    # (newest wins, gen thap KHONG ghi de). Repro cu cho ra hash gen-thap + vector_gen lui.
    import threading
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "sf.db")
    db.init_db()
    pid = db.get_or_create_project("/r", "R")
    results = {}
    lock = threading.Lock()
    barrier = threading.Barrier(2)

    def w(name):
        barrier.wait()
        g = db.upsert_file("/r/same.py", "python", f"hash-{name}", f"skel-{name}", [], project_id=pid)
        with lock:
            results[name] = g
    ta = threading.Thread(target=w, args=("A",))
    tb = threading.Thread(target=w, args=("B",))
    ta.start(); tb.start(); ta.join(); tb.join()
    assert sorted(results.values()) == [1, 2]          # gen duy nhat, lien tuc
    winner = max(results, key=results.get)             # writer nhan gen cao nhat
    row = db.get_file_row("/r/same.py", project_id=pid)
    assert row["vector_gen"] == 2                       # gen khong lui
    assert row["hash"] == f"hash-{winner}"             # content = writer gen cao (newest wins)


def test_upsert_rolls_back_on_failure(tmp_path, monkeypatch):
    # #P0-10 (Batch A): loi giua allocation va write (symbol thieu key) -> ROLLBACK toan bo:
    # gen KHONG bi consume, file loi khong ghi 1 phan, DB khong bi khoa (upsert sau van chay).
    import pytest
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "rb.db")
    db.init_db()
    pid = db.get_or_create_project("/r", "R")
    before = db.upsert_file("/r/a.py", "python", "h", "s", [], project_id=pid)   # gen 1
    with pytest.raises(KeyError):
        db.upsert_file("/r/b.py", "python", "h", "s", [{"name": "x"}], project_id=pid)  # thieu 'kind'
    conn = db._conn()
    seq = int(conn.execute("SELECT value FROM meta WHERE key='vec_gen_seq'").fetchone()["value"])
    b = conn.execute("SELECT 1 FROM files WHERE project_id=? AND path='/r/b.py'", (pid,)).fetchone()
    conn.close()
    assert seq == before                                # gen da rollback (khong tang)
    assert b is None                                    # file loi khong duoc ghi
    after = db.upsert_file("/r/c.py", "python", "h", "s", [], project_id=pid)
    assert after == before + 1                          # DB khong khoa, monotonic lien tuc


def test_reserve_and_upsert_concurrent_unique_gens(tmp_path, monkeypatch):
    # #P0-10 (Batch A): reserve_file_generation dua voi upsert_file -> gen van duy nhat
    import threading
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "ru.db")
    db.init_db()
    pid = db.get_or_create_project("/r", "R")
    db.upsert_file("/r/x.py", "python", "h", "s", [], project_id=pid)   # co row cho reserve update
    gens = []
    lock = threading.Lock()
    bar = threading.Barrier(2)

    def up():
        bar.wait()
        g = db.upsert_file("/r/y.py", "python", "h", "s", [], project_id=pid)
        with lock:
            gens.append(g)

    def res():
        bar.wait()
        g = db.reserve_file_generation("/r/x.py", pid)
        with lock:
            gens.append(g)
    t1 = threading.Thread(target=up)
    t2 = threading.Thread(target=res)
    t1.start(); t2.start(); t1.join(); t2.join()
    assert len(gens) == 2 and len(set(gens)) == 2       # khong trung gen


def test_init_repairs_malformed_generation_meta(tmp_path, monkeypatch):
    # #P0-10: vec_gen_seq='broken' -> init_db KHONG raise ValueError, repair tu max thuc te
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "mal.db")
    db.init_db()
    pid = db.get_or_create_project("/r", "R")
    conn = db._conn()
    conn.execute("INSERT INTO files(project_id,path,lang,hash,skeleton,indexed_at,summary,vector_ok,vector_gen) "
                 "VALUES (?,?,?,?,?,?,?,1,40)", (pid, "/r/x.py", "python", "h", "s", "t", ""))
    conn.execute("INSERT INTO meta(key,value) VALUES('vec_gen_seq','broken') "
                 "ON CONFLICT(key) DO UPDATE SET value='broken'")
    conn.commit()
    conn.close()
    db.init_db()                                 # KHONG duoc raise; repair vec_gen_seq -> 40
    seqconn = db._conn()
    seq = seqconn.execute("SELECT value FROM meta WHERE key='vec_gen_seq'").fetchone()["value"]
    seqconn.close()
    assert int(seq) == 40                         # repair tu MAX(file gen)
    g = db.upsert_file("/r/y.py", "python", "h", "s", [], project_id=pid)
    assert g > 40                                 # gen moi monotonic


def test_init_repairs_generation_invariant(tmp_path, monkeypatch):
    # #P0-10: init repair meta.vec_gen_seq >= max(file gen, tombstone gen) khi meta stale/thap
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "gi.db")
    db.init_db()
    pid = db.get_or_create_project("/r", "R")
    conn = db._conn()
    conn.execute("INSERT INTO files(project_id,path,lang,hash,skeleton,indexed_at,summary,vector_ok,vector_gen) "
                 "VALUES (?,?,?,?,?,?,?,1,120)", (pid, "/r/x.py", "python", "h", "s", "t", ""))
    conn.execute("INSERT INTO meta(key,value) VALUES('vec_gen_seq','3') "
                 "ON CONFLICT(key) DO UPDATE SET value='3'")          # meta thap (stale)
    conn.commit()
    conn.close()
    db.init_db()                                                      # repair invariant
    conn = db._conn()
    seq = int(conn.execute("SELECT value FROM meta WHERE key='vec_gen_seq'").fetchone()["value"])
    conn.close()
    assert seq >= 120


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
