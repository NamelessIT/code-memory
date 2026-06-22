"""Summarizer grounding: KHONG luu chuoi loi lam summary."""
import codemem.indexer.summarizer as sm


class _Raise:
    def chat(self, *a, **k):
        raise RuntimeError("ollama down")


class _Ok:
    def chat(self, *a, **k):
        return {"message": {"content": "Tom tat hop le."}}


def test_ask_returns_none_on_error(monkeypatch):
    monkeypatch.setattr(sm, "_client", _Raise())
    assert sm.summarize_file("FILE: x\nSYMBOLS:") is None   # khong tra chuoi loi


def test_ask_returns_text_when_ok(monkeypatch):
    monkeypatch.setattr(sm, "_client", _Ok())
    out = sm.summarize_file("FILE: x")
    assert out == "Tom tat hop le."


def test_run_summarize_commits_when_gen_matches(tmp_path, monkeypatch):
    # #P0-6 happy path: gen file van bang snapshot -> ghi summary + vector summary voi gen do
    import codemem.storage.db as db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "ok.db")
    db.init_db()
    pid = db.get_or_create_project("/r", "R")
    g = db.upsert_file("/r/x.py", "python", "h", "skel", [], project_id=pid)
    monkeypatch.setattr(sm, "summarize_file", lambda skel: "TÓM TẮT")
    monkeypatch.setattr(sm.db, "active_project_id", lambda: pid)
    idx = []
    monkeypatch.setattr(sm.vectors, "index_summary", lambda *a, **k: idx.append(k.get("generation")))
    sm.run_summarize(make_overview=False)
    assert db.get_file_summary("/r/x.py", project_id=pid) == "TÓM TẮT"
    assert idx == [g]                                   # vector summary ghi voi gen snapshot


def test_run_summarize_drops_when_file_regenerated(tmp_path, monkeypatch):
    # #P0-6: file bi re-index khi summarizer dang goi LLM (vector_gen doi) -> drop summary cu
    import codemem.storage.db as db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "drop.db")
    db.init_db()
    pid = db.get_or_create_project("/r", "R")
    db.upsert_file("/r/x.py", "python", "h", "skel", [], project_id=pid)
    monkeypatch.setattr(sm, "summarize_file", lambda skel: "TÓM TẮT")
    monkeypatch.setattr(sm.db, "active_project_id", lambda: pid)
    monkeypatch.setattr(sm.db, "file_vector_state", lambda path, project_id=None: (999, 1))  # gen lech
    idx = []
    monkeypatch.setattr(sm.vectors, "index_summary", lambda *a, **k: idx.append(1))
    sm.run_summarize(make_overview=False)
    assert idx == []                                    # gen lech -> khong ghi vector summary
    assert db.get_file_summary("/r/x.py", project_id=pid) == ""   # khong ghi summary cu


def test_run_summarize_stops_when_project_deleted(tmp_path, monkeypatch):
    # #P0-6: project bi xoa giua job -> drop, khong ghi summary/vector/overview mo coi
    import codemem.storage.db as db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "del.db")
    db.init_db()
    pid = db.get_or_create_project("/r", "R")
    db.upsert_file("/r/x.py", "python", "h", "skel", [], project_id=pid)
    monkeypatch.setattr(sm, "summarize_file", lambda skel: "TÓM TẮT")
    monkeypatch.setattr(sm.db, "active_project_id", lambda: pid)
    monkeypatch.setattr(sm.db, "project_exists", lambda p: False)   # project da xoa giua job
    idx = []
    monkeypatch.setattr(sm.vectors, "index_summary", lambda *a, **k: idx.append(1))
    sm.run_summarize(make_overview=True)
    assert idx == []
    assert db.get_file_summary("/r/x.py", project_id=pid) == ""
