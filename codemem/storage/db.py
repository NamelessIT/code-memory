"""SQLite: luu file da index + symbol. Ho tro index tang dan."""
import sqlite3
from datetime import datetime

from ..config import DB_PATH, ensure_dirs


def _conn():
    ensure_dirs()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = _conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS files (
            path TEXT PRIMARY KEY,
            lang TEXT,
            hash TEXT,
            skeleton TEXT,
            indexed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS symbols (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT NOT NULL,
            kind TEXT,
            name TEXT,
            signature TEXT,
            start_line INTEGER,
            end_line INTEGER,
            parent TEXT,
            exported INTEGER DEFAULT 0,
            tag TEXT DEFAULT '',
            doc TEXT DEFAULT '',
            body TEXT DEFAULT '',
            FOREIGN KEY (file_path) REFERENCES files(path)
        );
        CREATE INDEX IF NOT EXISTS idx_sym_name ON symbols(name);
        CREATE INDEX IF NOT EXISTS idx_sym_file ON symbols(file_path);
        CREATE INDEX IF NOT EXISTS idx_sym_kind ON symbols(kind);

        CREATE TABLE IF NOT EXISTS edges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT NOT NULL,
            caller TEXT,
            callee TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_edge_caller ON edges(caller);
        CREATE INDEX IF NOT EXISTS idx_edge_callee ON edges(callee);

        CREATE TABLE IF NOT EXISTS routes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT NOT NULL,
            method TEXT,
            path TEXT,
            handler TEXT,
            line INTEGER
        );

        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );
    """)
    # Migration: them cot cho DB cu
    for stmt in (
        "ALTER TABLE symbols ADD COLUMN tag TEXT DEFAULT ''",
        "ALTER TABLE symbols ADD COLUMN doc TEXT DEFAULT ''",
        "ALTER TABLE symbols ADD COLUMN body TEXT DEFAULT ''",
        "ALTER TABLE files ADD COLUMN summary TEXT DEFAULT ''",
    ):
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError:
            pass

    # Doi schema version -> invalidate overview/summary cu (co the la hallucination legacy)
    from ..config import SCHEMA_VERSION
    row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    cur = row["value"] if row else None
    if cur != SCHEMA_VERSION:
        conn.execute("DELETE FROM meta WHERE key='overview'")
        conn.execute("UPDATE files SET summary=''")
        conn.execute(
            "INSERT INTO meta(key,value) VALUES('schema_version',?) "
            "ON CONFLICT(key) DO UPDATE SET value=?", (SCHEMA_VERSION, SCHEMA_VERSION))
    conn.commit()
    conn.close()


def get_indexed_hashes() -> dict:
    """Map {path: hash} cua cac file da index -> de biet file nao doi/them/xoa."""
    conn = _conn()
    rows = conn.execute("SELECT path, hash FROM files").fetchall()
    conn.close()
    return {r["path"]: r["hash"] for r in rows}


def upsert_file(path, lang, file_hash, skeleton, symbols, edges=None, routes=None):
    """Ghi file + thay toan bo symbol/edge/route cua file (xoa cu, them moi)."""
    conn = _conn()
    now = datetime.now().isoformat()
    # File doi -> summary cu thanh stale (xoa de bat sinh lai). Phase 3 grounding.
    conn.execute(
        "INSERT INTO files(path, lang, hash, skeleton, indexed_at, summary) VALUES (?,?,?,?,?,'') "
        "ON CONFLICT(path) DO UPDATE SET lang=?, hash=?, skeleton=?, indexed_at=?, summary=''",
        (path, lang, file_hash, skeleton, now, lang, file_hash, skeleton, now),
    )
    conn.execute("DELETE FROM symbols WHERE file_path=?", (path,))
    conn.executemany(
        "INSERT INTO symbols(file_path, kind, name, signature, start_line, end_line, parent, exported, tag, doc, body) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [
            (path, s["kind"], s["name"], s["signature"], s["start_line"],
             s["end_line"], s.get("parent"), 1 if s.get("exported") else 0,
             s.get("tag", ""), s.get("doc", ""), s.get("body", ""))
            for s in symbols
        ],
    )
    conn.execute("DELETE FROM edges WHERE file_path=?", (path,))
    if edges:
        conn.executemany(
            "INSERT INTO edges(file_path, caller, callee) VALUES (?,?,?)",
            [(path, e["caller"], e["callee"]) for e in edges],
        )
    conn.execute("DELETE FROM routes WHERE file_path=?", (path,))
    if routes:
        conn.executemany(
            "INSERT INTO routes(file_path, method, path, handler, line) VALUES (?,?,?,?,?)",
            [(path, r["method"], r["path"], r.get("handler", ""), r.get("line")) for r in routes],
        )
    conn.commit()
    conn.close()


def delete_file(path):
    conn = _conn()
    conn.execute("DELETE FROM symbols WHERE file_path=?", (path,))
    conn.execute("DELETE FROM edges WHERE file_path=?", (path,))
    conn.execute("DELETE FROM routes WHERE file_path=?", (path,))
    conn.execute("DELETE FROM files WHERE path=?", (path,))
    conn.commit()
    conn.close()


def search_symbols(keyword, limit=20):
    conn = _conn()
    k = f"%{keyword}%"
    rows = conn.execute(
        "SELECT * FROM symbols WHERE name LIKE ? OR signature LIKE ? "
        "ORDER BY exported DESC, length(name) ASC LIMIT ?",
        (k, k, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_symbols_by_name(name, limit=10):
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM symbols WHERE name=? LIMIT ?", (name, limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_symbol_in_file(name, file_path):
    """Lay symbol theo ten + dung file (tranh lay nham signature definition khac)."""
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM symbols WHERE name=? AND file_path=? LIMIT 1", (name, file_path)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def symbol_exists(name):
    """True neu 'name' la symbol noi bo da index (de loc built-in/external khoi call graph)."""
    conn = _conn()
    row = conn.execute("SELECT 1 FROM symbols WHERE name=? LIMIT 1", (name,)).fetchone()
    conn.close()
    return row is not None


def get_symbols_for_files(paths):
    """Lay tat ca symbol cua 1 nhom file (dung khi lap context pack)."""
    if not paths:
        return []
    conn = _conn()
    qmarks = ",".join("?" * len(paths))
    rows = conn.execute(
        f"SELECT * FROM symbols WHERE file_path IN ({qmarks}) ORDER BY start_line",
        list(paths),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_skeleton(path):
    conn = _conn()
    row = conn.execute("SELECT skeleton FROM files WHERE path=?", (path,)).fetchone()
    conn.close()
    return row["skeleton"] if row else None


def get_file_row(path):
    conn = _conn()
    row = conn.execute("SELECT * FROM files WHERE path=?", (path,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_status():
    conn = _conn()
    nf = conn.execute("SELECT COUNT(*) c FROM files").fetchone()["c"]
    ns = conn.execute("SELECT COUNT(*) c FROM symbols").fetchone()["c"]
    by_lang = {r["lang"]: r["c"] for r in conn.execute(
        "SELECT lang, COUNT(*) c FROM files GROUP BY lang").fetchall()}
    by_kind = {r["kind"]: r["c"] for r in conn.execute(
        "SELECT kind, COUNT(*) c FROM symbols GROUP BY kind").fetchall()}
    proj = conn.execute("SELECT value FROM meta WHERE key='project_root'").fetchone()
    conn.close()
    return {
        "files": nf, "symbols": ns,
        "by_language": by_lang, "by_kind": by_kind,
        "project_root": proj["value"] if proj else None,
    }


def get_structure(limit=400):
    """Cay file + so symbol moi file."""
    conn = _conn()
    rows = conn.execute(
        "SELECT f.path, f.lang, COUNT(s.id) n FROM files f "
        "LEFT JOIN symbols s ON s.file_path=f.path GROUP BY f.path ORDER BY f.path LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_callees(name, limit=15):
    """Cac ham ma 'name' goi."""
    conn = _conn()
    rows = conn.execute(
        "SELECT DISTINCT callee FROM edges WHERE caller=? LIMIT ?", (name, limit)
    ).fetchall()
    conn.close()
    return [r["callee"] for r in rows]


def get_callers(name, limit=15):
    """Cac ham goi den 'name'."""
    conn = _conn()
    rows = conn.execute(
        "SELECT DISTINCT caller FROM edges WHERE callee=? LIMIT ?", (name, limit)
    ).fetchall()
    conn.close()
    return [r["caller"] for r in rows]


def get_routes(limit=300):
    conn = _conn()
    rows = conn.execute(
        "SELECT method, path, handler, file_path, line FROM routes ORDER BY path LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def clear_all():
    """Xoa toan bo index (file + symbol + edge + route + meta) khoi SQLite."""
    init_db()  # dam bao bang ton tai
    conn = _conn()
    conn.execute("DELETE FROM symbols")
    conn.execute("DELETE FROM edges")
    conn.execute("DELETE FROM routes")
    conn.execute("DELETE FROM files")
    conn.execute("DELETE FROM meta")
    conn.commit()
    conn.execute("VACUUM")  # tra lai dung luong cho OS
    conn.close()


def set_meta(key, value):
    conn = _conn()
    conn.execute(
        "INSERT INTO meta(key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=?",
        (key, value, value),
    )
    conn.commit()
    conn.close()


def get_meta(key):
    conn = _conn()
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else None


# ---- Tom tat (Phase 3) ----
def set_file_summary(path, summary):
    conn = _conn()
    conn.execute("UPDATE files SET summary=? WHERE path=?", (summary, path))
    conn.commit()
    conn.close()


def files_needing_summary():
    """File da co skeleton nhung chua co summary."""
    conn = _conn()
    rows = conn.execute(
        "SELECT path, lang, skeleton FROM files WHERE COALESCE(summary,'')='' ORDER BY path"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_file_summary(path):
    conn = _conn()
    row = conn.execute("SELECT summary FROM files WHERE path=?", (path,)).fetchone()
    conn.close()
    return (row["summary"] if row else "") or ""


def all_file_summaries(limit=200):
    conn = _conn()
    rows = conn.execute(
        "SELECT path, summary FROM files WHERE COALESCE(summary,'')<>'' ORDER BY path LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def summary_counts():
    conn = _conn()
    total = conn.execute("SELECT COUNT(*) c FROM files").fetchone()["c"]
    done = conn.execute("SELECT COUNT(*) c FROM files WHERE COALESCE(summary,'')<>''").fetchone()["c"]
    conn.close()
    return {"total": total, "summarized": done}
