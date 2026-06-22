"""P0-5: vector reconciliation - file pending duoc retry; that bai -> van pending."""
import codemem.indexer.runner as runner


def _isolate(monkeypatch):
    """Tach reconcile khoi DB that: bo qua embed-check + tombstone + coi project ton tai."""
    monkeypatch.setattr(runner, "ensure_embed_current", lambda: False)
    monkeypatch.setattr(runner, "_retry_tombstones", lambda *a, **k: 0)
    monkeypatch.setattr(runner.db, "project_exists", lambda pid: True)   # #P0-6 guard: gia lap ton tai


def test_reconcile_repairs_pending(monkeypatch):
    _isolate(monkeypatch)
    monkeypatch.setattr(runner.db, "files_pending_vector",
                        lambda pid: [{"path": "/p/a.py", "lang": "python", "skeleton": "s", "vector_gen": 5}])
    monkeypatch.setattr(runner.db, "get_symbols_for_file", lambda p, project_id=None: [])
    monkeypatch.setattr(runner.vectors, "index_file", lambda *a, **k: True)
    setok = {}
    monkeypatch.setattr(runner.db, "set_vector_ok_if_gen",
                        lambda path, pid, gen: setok.update({path: gen}) or True)
    res = runner.reconcile_vectors(1)
    assert res["repaired"] == 1 and res["pending"] == 0
    assert setok["/p/a.py"] == 5                   # set OK theo gen hien co (khong reserve lai)


def test_reconcile_still_pending_on_failure(monkeypatch):
    _isolate(monkeypatch)
    monkeypatch.setattr(runner.db, "files_pending_vector",
                        lambda pid: [{"path": "/p/a.py", "lang": "python", "skeleton": "s", "vector_gen": 3}])
    monkeypatch.setattr(runner.db, "get_symbols_for_file", lambda p, project_id=None: [])
    monkeypatch.setattr(runner.vectors, "index_file", lambda *a, **k: False)  # vector van loi
    monkeypatch.setattr(runner.db, "set_vector_ok", lambda *a, **k: None)
    res = runner.reconcile_vectors(1)
    assert res["pending"] == 1 and res["repaired"] == 0


def test_retry_tombstones_clears_on_success(monkeypatch):
    # #P0-10: retry thanh cong moi scope -> xoa khoi danh sach
    tombs = [{"id": 1, "scope": "file", "project_id": 2, "file_path": "/p/a.py", "generation": 4},
             {"id": 2, "scope": "project", "project_id": 3, "file_path": ""},
             {"id": 3, "scope": "collection", "project_id": 0, "file_path": ""}]
    monkeypatch.setattr(runner.db, "due_tombstones", lambda batch=50, scopes=None: tombs)
    monkeypatch.setattr(runner.vectors, "delete_file", lambda p, project_id=None, generation=None: True)
    monkeypatch.setattr(runner.vectors, "delete_project", lambda pid: True)
    monkeypatch.setattr(runner.vectors, "clear_all", lambda: True)
    deleted = []
    monkeypatch.setattr(runner.db, "del_tombstone", lambda tid: deleted.append(tid))
    assert runner._retry_tombstones() == 3
    assert deleted == [1, 2, 3]


def test_retry_tombstones_backoff_on_failure(monkeypatch):
    # #P0-10: fail -> record_tombstone_failure (backoff), KHONG del
    monkeypatch.setattr(runner.db, "due_tombstones",
                        lambda batch=50, scopes=None: [{"id": 1, "scope": "file", "project_id": 2, "file_path": "/p/a.py", "generation": 1}])
    monkeypatch.setattr(runner.vectors, "delete_file", lambda p, project_id=None, generation=None: False)
    failed = []
    monkeypatch.setattr(runner.db, "record_tombstone_failure", lambda tid, err="": failed.append(tid))
    monkeypatch.setattr(runner.db, "del_tombstone",
                        lambda tid: (_ for _ in ()).throw(AssertionError("khong duoc del khi fail")))
    assert runner._retry_tombstones() == 0
    assert failed == [1]


def test_retry_legacy_gen0_stale_when_recreate_complete(monkeypatch):
    # #P0-10 race: intent legacy gen=0, file da re-index VA vector hoan tat (gen>0, vector_ok=1)
    # -> ack stale, KHONG ungated-delete (re-index da don vector cu) de tranh xoa nham vector moi.
    monkeypatch.setattr(runner.db, "due_tombstones",
                        lambda batch=50, scopes=None: [{"id": 1, "scope": "file", "project_id": 2,
                                                        "file_path": "/p/a.py", "generation": 0}])
    monkeypatch.setattr(runner.db, "file_vector_state", lambda path, pid: (7, 1))   # gen 7, vector_ok=1
    called = []
    monkeypatch.setattr(runner.vectors, "delete_file", lambda *a, **k: called.append(1) or True)
    deleted = []
    monkeypatch.setattr(runner.db, "del_tombstone", lambda tid: deleted.append(tid))
    assert runner._retry_tombstones() == 1
    assert deleted == [1] and called == []           # stale -> ack, KHONG goi vector delete


def test_retry_legacy_gen0_cleans_when_recreate_incomplete(monkeypatch):
    # #P0-10 crash-window: upsert gen1 roi crash truoc vector write (vector_ok=0) -> vector legacy
    # van con. KHONG duoc ack-stale; phai ungated-clean roi ack (reconcile dung vector moi sau).
    monkeypatch.setattr(runner.db, "due_tombstones",
                        lambda batch=50, scopes=None: [{"id": 1, "scope": "file", "project_id": 2,
                                                        "file_path": "/p/a.py", "generation": 0}])
    monkeypatch.setattr(runner.db, "file_vector_state", lambda path, pid: (1, 0))   # gen 1 nhung vector_ok=0
    seen = {}
    monkeypatch.setattr(runner.vectors, "delete_file",
                        lambda p, project_id=None, generation=None: seen.update({"gen": generation}) or True)
    deleted = []
    monkeypatch.setattr(runner.db, "del_tombstone", lambda tid: deleted.append(tid))
    assert runner._retry_tombstones() == 1
    assert seen.get("gen") == 0 and deleted == [1]   # ungated-clean legacy + ack sau success


def test_retry_legacy_gen0_deletes_when_file_absent(monkeypatch):
    # #P0-10: intent legacy gen=0, file da xoa han (None) -> ungated delete (don orphan)
    monkeypatch.setattr(runner.db, "due_tombstones",
                        lambda batch=50, scopes=None: [{"id": 1, "scope": "file", "project_id": 2,
                                                        "file_path": "/p/a.py", "generation": 0}])
    monkeypatch.setattr(runner.db, "file_vector_state", lambda path, pid: None)  # file da xoa
    seen = {}
    monkeypatch.setattr(runner.vectors, "delete_file",
                        lambda p, project_id=None, generation=None: seen.update({"gen": generation}) or True)
    monkeypatch.setattr(runner.db, "del_tombstone", lambda tid: None)
    assert runner._retry_tombstones() == 1
    assert seen["gen"] == 0                           # ungated (gen falsy) van chay khi file absent


def test_cleanup_worker_independent_of_project(monkeypatch):
    # #P0-10: cleanup_worker retry moi scope, KHONG can active project
    monkeypatch.setattr(runner.db, "due_tombstones",
                        lambda batch=50, scopes=None: [{"id": 1, "scope": "project", "project_id": 9, "file_path": ""}])
    monkeypatch.setattr(runner.vectors, "delete_project", lambda pid: True)
    deleted = []
    monkeypatch.setattr(runner.db, "del_tombstone", lambda tid: deleted.append(tid))
    assert runner.cleanup_worker() == 1 and deleted == [1]


def test_retry_scopes_filter_excludes_collection(monkeypatch):
    # #P0-10 fence: scopes={'file'} -> KHONG dung clear_all (collection bo qua)
    tombs = [{"id": 1, "scope": "file", "project_id": 2, "file_path": "/a", "generation": 1},
             {"id": 2, "scope": "collection", "project_id": 0, "file_path": ""}]
    # due_tombstones filter scope trong SQL -> fake phai ton trong scopes
    monkeypatch.setattr(runner.db, "due_tombstones",
                        lambda batch=50, scopes=None: [t for t in tombs if scopes is None or t["scope"] in scopes])
    monkeypatch.setattr(runner.vectors, "delete_file", lambda p, project_id=None, generation=None: True)
    cleared_collection = []
    monkeypatch.setattr(runner.vectors, "clear_all", lambda: cleared_collection.append(1) or True)
    monkeypatch.setattr(runner.db, "del_tombstone", lambda tid: None)
    runner._retry_tombstones(scopes={"file"})
    assert cleared_collection == []                # collection KHONG bi xu ly khi fence


def test_file_vector_state_reflects_db(tmp_path, monkeypatch):
    # #P0-10: helper tra (gen, vector_ok) dung trang thai DB -> guard legacy cleanup quyet dinh dung
    import codemem.storage.db as db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "fv.db")
    db.init_db()
    pid = db.get_or_create_project("/r", "R")
    assert db.file_vector_state("/r/x.py", pid) is None        # chua co file
    g = db.upsert_file("/r/x.py", "python", "h", "s", [], project_id=pid)
    assert db.file_vector_state("/r/x.py", pid) == (g, 0)      # upsert -> vector_ok=0 (crash-window)
    db.set_vector_ok("/r/x.py", True, pid)
    assert db.file_vector_state("/r/x.py", pid) == (g, 1)      # vector hoan tat


def test_reconcile_legacy_gen0_allocates_real_generation(tmp_path, monkeypatch):
    # #P0-5: file legacy vector_gen=0 -> reconcile cap generation that (>0) truoc khi ghi vector,
    # set vector_ok=1 theo gen do; KHONG re-embed lai bang gen0.
    import codemem.storage.db as db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "rg.db")
    db.init_db()
    pid = db.get_or_create_project("/r", "R")
    conn = db._conn()
    conn.execute("INSERT INTO files(project_id,path,lang,hash,skeleton,indexed_at,summary,vector_ok,vector_gen) "
                 "VALUES (?,?,?,?,?,?,?,0,0)", (pid, "/r/x.py", "python", "h", "skel", "t", ""))
    conn.commit()
    conn.close()
    monkeypatch.setattr(runner, "ensure_embed_current", lambda: False)
    monkeypatch.setattr(runner, "_retry_tombstones", lambda *a, **k: 0)
    monkeypatch.setattr(runner.db, "get_symbols_for_file", lambda p, project_id=None: [])
    seen = {}
    monkeypatch.setattr(runner.vectors, "index_file",
                        lambda path, lang, skel, syms, project_id=None, generation=0:
                        seen.update({"gen": generation}) or True)
    res = runner.reconcile_vectors(pid)
    assert res["repaired"] == 1
    assert seen["gen"] >= 1                          # da cap generation that (khong con 0)
    assert db.file_vector_state("/r/x.py", pid) == (seen["gen"], 1)   # DB gen moi + vector_ok=1


def test_cleanup_scheduler_stop_keeps_reference_when_stuck(monkeypatch):
    # #P0-10: stop khi worker block -> tra False (stuck), GIU reference; start KHONG tao duplicate.
    import threading
    release = threading.Event()
    started = threading.Event()

    def stuck_worker(batch=50):
        started.set()
        release.wait(5)                              # mo phong Chroma treo
        return 0
    monkeypatch.setattr(runner, "cleanup_worker", stuck_worker)
    runner.start_cleanup_scheduler(interval=0.01, batch=5)
    try:
        assert started.wait(2.0)
        ok = runner.stop_cleanup_scheduler(timeout=0.1)
        assert ok is False                           # thread con block -> bao stuck
        assert runner._cleanup_thread is not None    # GIU reference (chong duplicate)
        t_before = runner._cleanup_thread
        t2 = runner.start_cleanup_scheduler(interval=0.01)
        assert t2 is t_before                         # khong tao thread thu hai
    finally:
        release.set()
        assert runner.stop_cleanup_scheduler(timeout=2.0) is True
    assert runner._cleanup_thread is None             # dung sach sau khi worker tha


def test_index_single_file_fails_closed_for_deleted_project(tmp_path, monkeypatch):
    # #P0-6: callback cu chay sau delete/switch -> KHONG re-tao file/vector cho project khong ton tai
    import codemem.storage.db as db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "isf.db")
    db.init_db()
    f = tmp_path / "a.py"
    f.write_text("def x():\n    return 1\n")
    called = []
    monkeypatch.setattr(runner.vectors, "index_file", lambda *a, **k: called.append(1) or True)
    assert runner.index_single_file(str(f), project_id=99999) is False
    assert called == []                                 # khong ghi vector cho project da xoa


def test_remove_file_fails_closed_for_deleted_project(tmp_path, monkeypatch):
    # #P0-6: remove cho project da xoa -> khong ghi tombstone mo coi, khong goi vector delete
    import codemem.storage.db as db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "rmf.db")
    db.init_db()
    deleted = []
    monkeypatch.setattr(runner.vectors, "delete_file", lambda *a, **k: deleted.append(1) or True)
    runner.remove_file("/r/x.py", project_id=88888)
    assert deleted == []
    assert db.tombstone_stats()["pending"] == 0


def test_reconcile_vectors_fails_closed_for_deleted_project(tmp_path, monkeypatch):
    # #P0-6: reconcile thread stale pid -> guard truoc ensure_embed_current/Chroma
    import codemem.storage.db as db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "rcv.db")
    db.init_db()
    calls = []
    monkeypatch.setattr(runner, "ensure_embed_current", lambda: calls.append("embed"))
    monkeypatch.setattr(runner.vectors, "index_file", lambda *a, **k: calls.append("idx") or True)
    res = runner.reconcile_vectors(77777)
    assert res.get("skipped") == "project gone"
    assert calls == []                                  # khong dung Chroma cho pid da xoa


def test_cleanup_scheduler_status_detects_stuck(monkeypatch):
    # #P0-10: health phan biet running/healthy vs stuck (busy qua nguong)
    import threading
    release = threading.Event()
    started = threading.Event()

    def stuck_worker(batch=50):
        started.set()
        release.wait(5)
        return 0
    monkeypatch.setattr(runner, "cleanup_worker", stuck_worker)
    runner.start_cleanup_scheduler(interval=0.01, batch=5)
    try:
        assert started.wait(2.0)
        st = runner.cleanup_scheduler_status(stuck_after=0)        # nguong 0 + dang busy -> stuck
        assert st["running"] is True and st["busy"] is True and st["stuck"] is True
        assert runner.cleanup_scheduler_status(stuck_after=120)["stuck"] is False  # nguong cao
    finally:
        release.set()
        runner.stop_cleanup_scheduler(timeout=2.0)
    assert runner.cleanup_scheduler_status()["running"] is False


def test_reconcile_all_projects_covers_every_project(monkeypatch):
    # #P0-5/#P0-10: reconcile MOI project (khong chi active); collection-scope chi xu ly 1 lan
    monkeypatch.setattr(runner, "ensure_embed_current", lambda: False)
    monkeypatch.setattr(runner.db, "list_projects", lambda: [{"id": 1}, {"id": 2}, {"id": 3}])
    seen = []

    def fake_reconcile(pid, progress=None, include_collection=True):
        seen.append((pid, include_collection))
        return {"repaired": 1, "pending": 0, "tombstones_cleared": 2}
    monkeypatch.setattr(runner, "reconcile_vectors", fake_reconcile)
    res = runner.reconcile_all_projects()
    assert [s[0] for s in seen] == [1, 2, 3]                       # tat ca project
    assert seen[0][1] is True and seen[1][1] is False and seen[2][1] is False  # collection 1 lan
    assert res["projects"] == 3 and res["repaired"] == 3 and res["tombstones_cleared"] == 6


def test_reconcile_all_projects_empty_runs_global_cleanup(monkeypatch):
    # #P0-10: khong co project -> van xu ly collection/global intent con ton (vd sau clear)
    monkeypatch.setattr(runner, "ensure_embed_current", lambda: False)
    monkeypatch.setattr(runner.db, "list_projects", lambda: [])
    monkeypatch.setattr(runner, "_retry_tombstones", lambda *a, **k: 4)
    res = runner.reconcile_all_projects()
    assert res["projects"] == 0 and res["tombstones_cleared"] == 4


def test_cleanup_scheduler_runs_repeatedly_then_stops(monkeypatch):
    # #P0-10: scheduler chay cleanup_worker lap lai (khac one-shot truoc day) + stop sach
    import threading
    import time
    calls = {"n": 0}
    done = threading.Event()

    def fake_worker(batch=50):
        calls["n"] += 1
        if calls["n"] >= 3:
            done.set()
        return 0
    monkeypatch.setattr(runner, "cleanup_worker", fake_worker)
    runner.start_cleanup_scheduler(interval=0.01, batch=5)
    try:
        assert done.wait(2.0)                  # chay >=3 lan -> dung la recurring
    finally:
        runner.stop_cleanup_scheduler()
    assert runner._cleanup_thread is None      # stop sach
    n_after = calls["n"]
    time.sleep(0.05)
    assert calls["n"] == n_after               # da dung han, khong tang nua


def test_ensure_embed_current_marks_stale(tmp_path, monkeypatch):
    # #P0-5: doi embedding model -> mark moi vector stale; goi lai -> no-op
    import codemem.storage.db as db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "e.db")
    db.init_db()
    a = db.get_or_create_project("/r", "A")
    db.upsert_file("/r/x.py", "python", "h", "s", [], project_id=a)
    db.set_meta("embed_model", "OLD-MODEL")
    assert runner.ensure_embed_current() is True
    assert len(db.files_pending_vector(a)) == 1     # da mark vector_ok=0
    assert runner.ensure_embed_current() is False   # meta == config -> no-op
