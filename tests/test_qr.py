"""#P0-QR: case thuc te 'scanner qr' - tokenizer/expand, corpus rong, source hygiene, orphan repair."""
import os

import codemem.storage.db as db
import codemem.indexer.runner as runner
import codemem.retrieval.search as search
from codemem.indexer.walker import walk_source_files


# ---------- Tokenizer / query expansion ----------

def test_tokenize_keeps_qr_and_expands():
    toks = search._tokenize("tìm cho tui hàm có chắc năng scanner qr")
    assert "qr" in toks                      # tech token 2 ky tu KHONG bi bo
    assert "scanner" in toks
    assert "scan" in toks                    # expand tu scanner/qr
    assert "tim" not in toks and "ham" not in toks   # stopword (da bo dau) bi loai


# ---------- Walker bo cache + reindex remove ----------

def test_walker_skips_cache_dirs(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.js").write_text("export function main(){return 1}\n")
    (tmp_path / ".cache" / "page-ssr").mkdir(parents=True)
    (tmp_path / ".cache" / "page-ssr" / "b.js").write_text("export function gen(){return 2}\n")
    got = [str(p) for p, _ in walk_source_files(str(tmp_path))]
    assert any("a.js" in g for g in got)
    assert not any(".cache" in g.replace("\\", "/") for g in got)


def test_reindex_removes_cache_files(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "ri.db")
    db.init_db()
    monkeypatch.setattr(runner.vectors, "index_file", lambda *a, **k: True)
    monkeypatch.setattr(runner.vectors, "delete_file", lambda *a, **k: True)
    monkeypatch.setattr(runner.vectors, "clear_all", lambda *a, **k: True)
    proj = tmp_path / "proj"
    (proj / "src").mkdir(parents=True)
    (proj / "src" / "app.js").write_text("export function main(){return 1}\n")
    stats = runner.index_project(str(proj))
    pid = stats["project_id"]
    # gia lap mot file cache da bi index truoc khi them ignore
    cache_norm = os.path.normcase(str(proj / ".cache" / "page-ssr" / "render.js"))
    db.upsert_file(cache_norm, "javascript", "h", "skel", [], project_id=pid)
    assert any(".cache" in p for p in db.get_indexed_hashes(pid))
    runner.index_project(str(proj))          # reindex: walker bo .cache -> removed-loop xoa
    paths = db.get_indexed_hashes(pid)
    assert not any(".cache" in p for p in paths)
    assert any("app.js" in p for p in paths)   # source that van con


# ---------- Orphan project repair ----------

def test_repair_orphan_project_recreates_and_activates(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "orph.db")
    db.init_db()
    conn = db._conn()
    for p in ("C:/proj/src/a.js", "C:/proj/src/sub/b.js"):
        conn.execute("INSERT INTO files(project_id,path,lang,hash,skeleton,indexed_at,summary,vector_ok,vector_gen) "
                     "VALUES (12,?,?,?,?,?,?,1,1)", (p, "javascript", "h", "skel", "t", ""))
    conn.execute("INSERT INTO symbols(project_id,file_path,kind,name,signature,start_line,end_line) "
                 "VALUES (12,?,?,?,?,?,?)", ("C:/proj/src/a.js", "function", "foo", "function foo()", 1, 2))
    conn.commit()
    conn.close()
    db.init_db()                              # repair: 1 orphan + projects rong -> recreate + active
    assert db.project_exists(12)
    assert db.active_project_id() == 12
    assert len(db.get_symbols_by_name("foo", project_id=12)) == 1   # retrieval scoped thay symbol


def test_repair_purges_multiple_orphans(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "orph2.db")
    db.init_db()
    conn = db._conn()
    for pidx, p in ((12, "C:/a/x.js"), (13, "C:/b/y.js")):
        conn.execute("INSERT INTO files(project_id,path,lang,hash,skeleton,indexed_at,summary,vector_ok,vector_gen) "
                     "VALUES (?,?,?,?,?,?,?,1,1)", (pidx, p, "javascript", "h", "skel", "t", ""))
    conn.commit()
    conn.close()
    db.init_db()                              # nhieu orphan -> purge ca hai + project intent
    conn = db._conn()
    n = conn.execute("SELECT COUNT(*) c FROM files").fetchone()["c"]
    conn.close()
    assert n == 0
    assert db.tombstone_stats()["pending"] >= 2


def test_integrity_status_clean_after_repair(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "int.db")
    db.init_db()
    st = db.integrity_status()
    assert st["orphan_files"] == 0


# ---------- Acceptance: build_context tim dung QR scanner ----------

def _seed_qr_project(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "qr.db")
    db.init_db()
    pid = db.get_or_create_project("C:/proj", "proj")
    db.set_active_project(pid)
    monkeypatch.setattr(search.vectors, "query", lambda *a, **k: [])   # lexical-only deterministic
    db.upsert_file(
        "C:/proj/src/pages/checkin/nhanquavivu2025.js", "javascript", "h1",
        "import { QrReader } from 'react-qr-reader'\nfunction handleResult(){}",
        [{"kind": "function", "name": "handleResult", "signature": "function handleResult(result)",
          "start_line": 10, "end_line": 30, "doc": "Xu ly ket qua quet QR tu QrReader",
          "body": "const data = result?.text; openScanner();"}], project_id=pid)
    db.upsert_file(
        "C:/proj/src/pages/sukien/quayso/dot4/[id].js", "javascript", "h2",
        "import { QrReader } from 'react-qr-reader'\nfunction handleScan(){}",
        [{"kind": "function", "name": "handleScan", "signature": "function handleScan(data)",
          "start_line": 5, "end_line": 40, "doc": "Quet QR lay CCCD",
          "body": "const cccd = extractCCCDFromQR(data);"},
         {"kind": "function", "name": "extractCCCDFromQR", "signature": "function extractCCCDFromQR(qr)",
          "start_line": 42, "end_line": 60, "doc": "", "body": "return qr.split('|')[0];"}],
        project_id=pid)
    # nhieu cache noise (phai bi loai khoi context)
    db.upsert_file(
        "C:/proj/.cache/page-ssr/render.js", "javascript", "h3",
        "function QRCodeInternal(){}",
        [{"kind": "function", "name": "QRCodeInternal", "signature": "function QRCodeInternal()",
          "start_line": 1, "end_line": 5, "doc": "qr internal generated", "body": "qr internal"}],
        project_id=pid)
    return pid


def test_build_context_finds_qr_scanner(tmp_path, monkeypatch):
    _seed_qr_project(monkeypatch, tmp_path)
    text, sources = search.build_context("tìm cho tui hàm có chắc năng scanner qr")
    joined = " ".join(sources)
    assert ("nhanquavivu2025.js" in joined) or ("dot4" in joined)   # source that
    assert "page-ssr" not in joined and ".cache" not in joined       # generated bi loai
    assert ("handleScan" in text) or ("extractCCCDFromQR" in text) or ("handleResult" in text)


def test_build_context_excludes_generated_qr(tmp_path, monkeypatch):
    _seed_qr_project(monkeypatch, tmp_path)
    text, sources = search.build_context("scanner qr")
    assert "QRCodeInternal" not in text                              # icon/generated internal khong vao
