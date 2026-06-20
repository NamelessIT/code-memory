"""SQLite: multi-project memory. Moi project co project_id; query scope theo project active."""
import sqlite3
from datetime import datetime

from ..config import DB_PATH, SCHEMA_VERSION, ensure_dirs


def _conn():
    ensure_dirs()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _active_pid(conn):
    r = conn.execute("SELECT value FROM meta WHERE key='active_project_id'").fetchone()
    return int(r["value"]) if r and r["value"] else None


def init_db():
    conn = _conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            root TEXT UNIQUE,
            name TEXT,
            created_at TEXT,
            last_indexed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS files (
            path TEXT PRIMARY KEY,
            project_id INTEGER,
            lang TEXT, hash TEXT, skeleton TEXT, indexed_at TEXT, summary TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS symbols (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER, file_path TEXT NOT NULL,
            kind TEXT, name TEXT, signature TEXT,
            start_line INTEGER, end_line INTEGER, parent TEXT,
            exported INTEGER DEFAULT 0, tag TEXT DEFAULT '', doc TEXT DEFAULT '', body TEXT DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_sym_name ON symbols(project_id, name);
        CREATE INDEX IF NOT EXISTS idx_sym_file ON symbols(file_path);
        CREATE TABLE IF NOT EXISTS edges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER, file_path TEXT NOT NULL, caller TEXT, callee TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_edge_caller ON edges(project_id, caller);
        CREATE INDEX IF NOT EXISTS idx_edge_callee ON edges(project_id, callee);
        CREATE TABLE IF NOT EXISTS routes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER, file_path TEXT NOT NULL,
            method TEXT, path TEXT, handler TEXT, line INTEGER
        );
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
    """)
    # Migration cot cho DB cu (truoc multi-project)
    for stmt in (
        "ALTER TABLE symbols ADD COLUMN tag TEXT DEFAULT ''",
        "ALTER TABLE symbols ADD COLUMN doc TEXT DEFAULT ''",
        "ALTER TABLE symbols ADD COLUMN body TEXT DEFAULT ''",
        "ALTER TABLE files ADD COLUMN summary TEXT DEFAULT ''",
        "ALTER TABLE files ADD COLUMN project_id INTEGER",
        "ALTER TABLE symbols ADD COLUMN project_id INTEGER",
        "ALTER TABLE edges ADD COLUMN project_id INTEGER",
        "ALTER TABLE routes ADD COLUMN project_id INTEGER",
    ):
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError:
            pass

    # Migrate du lieu single-project cu -> 1 project
    has_proj = conn.execute("SELECT COUNT(*) c FROM projects").fetchone()["c"]
    nfiles = conn.execute("SELECT COUNT(*) c FROM files").fetchone()["c"]
    if has_proj == 0 and nfiles > 0:
        root_row = conn.execute("SELECT value FROM meta WHERE key='project_root'").fetchone()
        root = root_row["value"] if root_row else "legacy-project"
        now = datetime.now().isoformat()
        conn.execute("INSERT INTO projects(root,name,created_at,last_indexed_at) VALUES (?,?,?,?)",
                     (root, _name_from_root(root), now, now))
        pid = conn.execute("SELECT id FROM projects WHERE root=?", (root,)).fetchone()["id"]
        for t in ("files", "symbols", "edges", "routes"):
            conn.execute(f"UPDATE {t} SET project_id=? WHERE project_id IS NULL", (pid,))
        conn.execute("INSERT INTO meta(key,value) VALUES('active_project_id',?) "
                     "ON CONFLICT(key) DO UPDATE SET value=?", (str(pid), str(pid)))

    # Doi schema version -> invalidate overview/summary cu (hallucination legacy)
    row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    if (row["value"] if row else None) != SCHEMA_VERSION:
        conn.execute("DELETE FROM meta WHERE key LIKE 'overview%'")
        conn.execute("UPDATE files SET summary=''")
        conn.execute("INSERT INTO meta(key,value) VALUES('schema_version',?) "
                     "ON CONFLICT(key) DO UPDATE SET value=?", (SCHEMA_VERSION, SCHEMA_VERSION))
    conn.commit()
    conn.close()


def _name_from_root(root):
    import os
    return os.path.basename(os.path.normpath(root)) or root


# ============================================================
# PROJECTS
# ============================================================
def get_or_create_project(root, name=None):
    conn = _conn()
    now = datetime.now().isoformat()
    row = conn.execute("SELECT id FROM projects WHERE root=?", (root,)).fetchone()
    if row:
        pid = row["id"]
    else:
        conn.execute("INSERT INTO projects(root,name,created_at,last_indexed_at) VALUES (?,?,?,?)",
                     (root, name or _name_from_root(root), now, now))
        pid = conn.execute("SELECT id FROM projects WHERE root=?", (root,)).fetchone()["id"]
    conn.commit()
    conn.close()
    return pid


def list_projects():
    conn = _conn()
    active = _active_pid(conn)
    rows = conn.execute("SELECT * FROM projects ORDER BY name").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["active"] = (r["id"] == active)
        d["files"] = conn.execute("SELECT COUNT(*) c FROM files WHERE project_id=?", (r["id"],)).fetchone()["c"]
        out.append(d)
    conn.close()
    return out


def set_active_project(pid):
    set_meta("active_project_id", str(pid))


def get_active_project():
    conn = _conn()
    pid = _active_pid(conn)
    row = conn.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone() if pid else None
    conn.close()
    return dict(row) if row else None


def get_active_root():
    p = get_active_project()
    return p["root"] if p else None


def active_project_id():
    conn = _conn()
    pid = _active_pid(conn)
    conn.close()
    return pid


def touch_project(pid):
    conn = _conn()
    conn.execute("UPDATE projects SET last_indexed_at=? WHERE id=?",
                 (datetime.now().isoformat(), pid))
    conn.commit()
    conn.close()


def delete_project(pid):
    """Xoa 1 project + toan bo du lieu cua no (KHONG dung den project khac)."""
    conn = _conn()
    for t in ("files", "symbols", "edges", "routes"):
        conn.execute(f"DELETE FROM {t} WHERE project_id=?", (pid,))
    conn.execute("DELETE FROM projects WHERE id=?", (pid,))
    conn.execute("DELETE FROM meta WHERE key=?", (f"overview:{pid}",))
    if _active_pid(conn) == pid:
        conn.execute("DELETE FROM meta WHERE key='active_project_id'")
    conn.commit()
    conn.close()


# ============================================================
# FILES / SYMBOLS (scope theo project)
# ============================================================
def get_indexed_hashes(project_id) -> dict:
    conn = _conn()
    rows = conn.execute("SELECT path, hash FROM files WHERE project_id=?", (project_id,)).fetchall()
    conn.close()
    return {r["path"]: r["hash"] for r in rows}


def upsert_file(path, lang, file_hash, skeleton, symbols, edges=None, routes=None, project_id=None):
    conn = _conn()
    now = datetime.now().isoformat()
    conn.execute(
        "INSERT INTO files(path, project_id, lang, hash, skeleton, indexed_at, summary) "
        "VALUES (?,?,?,?,?,?,'') "
        "ON CONFLICT(path) DO UPDATE SET project_id=?, lang=?, hash=?, skeleton=?, indexed_at=?, summary=''",
        (path, project_id, lang, file_hash, skeleton, now, project_id, lang, file_hash, skeleton, now),
    )
    conn.execute("DELETE FROM symbols WHERE file_path=?", (path,))
    conn.executemany(
        "INSERT INTO symbols(project_id, file_path, kind, name, signature, start_line, end_line, parent, exported, tag, doc, body) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [(project_id, path, s["kind"], s["name"], s["signature"], s["start_line"], s["end_line"],
          s.get("parent"), 1 if s.get("exported") else 0, s.get("tag", ""), s.get("doc", ""), s.get("body", ""))
         for s in symbols],
    )
    conn.execute("DELETE FROM edges WHERE file_path=?", (path,))
    if edges:
        conn.executemany("INSERT INTO edges(project_id, file_path, caller, callee) VALUES (?,?,?,?)",
                         [(project_id, path, e["caller"], e["callee"]) for e in edges])
    conn.execute("DELETE FROM routes WHERE file_path=?", (path,))
    if routes:
        conn.executemany("INSERT INTO routes(project_id, file_path, method, path, handler, line) VALUES (?,?,?,?,?,?)",
                         [(project_id, path, r["method"], r["path"], r.get("handler", ""), r.get("line")) for r in routes])
    conn.commit()
    conn.close()


def delete_file(path):
    conn = _conn()
    for t in ("symbols", "edges", "routes"):
        conn.execute(f"DELETE FROM {t} WHERE file_path=?", (path,))
    conn.execute("DELETE FROM files WHERE path=?", (path,))
    conn.commit()
    conn.close()


def search_symbols(keyword, limit=20, project_id=None):
    conn = _conn()
    pid = project_id if project_id is not None else _active_pid(conn)
    k = f"%{keyword}%"
    rows = conn.execute(
        "SELECT * FROM symbols WHERE project_id=? AND (name LIKE ? OR signature LIKE ?) "
        "ORDER BY exported DESC, length(name) ASC LIMIT ?",
        (pid, k, k, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_symbols_by_name(name, limit=10, project_id=None):
    conn = _conn()
    pid = project_id if project_id is not None else _active_pid(conn)
    rows = conn.execute("SELECT * FROM symbols WHERE project_id=? AND name=? LIMIT ?",
                        (pid, name, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_symbol_in_file(name, file_path):
    conn = _conn()
    row = conn.execute("SELECT * FROM symbols WHERE name=? AND file_path=? LIMIT 1",
                       (name, file_path)).fetchone()
    conn.close()
    return dict(row) if row else None


def symbol_exists(name, project_id=None):
    conn = _conn()
    pid = project_id if project_id is not None else _active_pid(conn)
    row = conn.execute("SELECT 1 FROM symbols WHERE project_id=? AND name=? LIMIT 1",
                       (pid, name)).fetchone()
    conn.close()
    return row is not None


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


def get_status(project_id=None):
    conn = _conn()
    pid = project_id if project_id is not None else _active_pid(conn)
    nf = conn.execute("SELECT COUNT(*) c FROM files WHERE project_id=?", (pid,)).fetchone()["c"]
    ns = conn.execute("SELECT COUNT(*) c FROM symbols WHERE project_id=?", (pid,)).fetchone()["c"]
    by_lang = {r["lang"]: r["c"] for r in conn.execute(
        "SELECT lang, COUNT(*) c FROM files WHERE project_id=? GROUP BY lang", (pid,)).fetchall()}
    by_kind = {r["kind"]: r["c"] for r in conn.execute(
        "SELECT kind, COUNT(*) c FROM symbols WHERE project_id=? GROUP BY kind", (pid,)).fetchall()}
    prow = conn.execute("SELECT root FROM projects WHERE id=?", (pid,)).fetchone() if pid else None
    conn.close()
    return {"files": nf, "symbols": ns, "by_language": by_lang, "by_kind": by_kind,
            "project_root": prow["root"] if prow else None, "project_id": pid}


def get_structure(limit=400, project_id=None):
    conn = _conn()
    pid = project_id if project_id is not None else _active_pid(conn)
    rows = conn.execute(
        "SELECT f.path, f.lang, COUNT(s.id) n FROM files f LEFT JOIN symbols s ON s.file_path=f.path "
        "WHERE f.project_id=? GROUP BY f.path ORDER BY f.path LIMIT ?", (pid, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_callees(name, limit=15, project_id=None):
    conn = _conn()
    pid = project_id if project_id is not None else _active_pid(conn)
    rows = conn.execute("SELECT DISTINCT callee FROM edges WHERE project_id=? AND caller=? LIMIT ?",
                        (pid, name, limit)).fetchall()
    conn.close()
    return [r["callee"] for r in rows]


def get_callers(name, limit=15, project_id=None):
    conn = _conn()
    pid = project_id if project_id is not None else _active_pid(conn)
    rows = conn.execute("SELECT DISTINCT caller FROM edges WHERE project_id=? AND callee=? LIMIT ?",
                        (pid, name, limit)).fetchall()
    conn.close()
    return [r["caller"] for r in rows]


def get_routes(limit=300, project_id=None):
    conn = _conn()
    pid = project_id if project_id is not None else _active_pid(conn)
    rows = conn.execute(
        "SELECT method, path, handler, file_path, line FROM routes WHERE project_id=? ORDER BY path LIMIT ?",
        (pid, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def clear_all():
    """Xoa SACH toan bo (moi project). Dung cho /api/clear va test."""
    init_db()
    conn = _conn()
    for t in ("symbols", "edges", "routes", "files", "projects", "meta"):
        conn.execute(f"DELETE FROM {t}")
    conn.commit()
    conn.execute("VACUUM")
    conn.close()


def set_meta(key, value):
    conn = _conn()
    conn.execute("INSERT INTO meta(key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=?",
                 (key, value, value))
    conn.commit()
    conn.close()


def get_meta(key):
    conn = _conn()
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else None


# ---- Overview per-project ----
def set_overview(text, project_id=None):
    conn = _conn()
    pid = project_id if project_id is not None else _active_pid(conn)
    conn.close()
    set_meta(f"overview:{pid}", text)


def get_overview(project_id=None):
    conn = _conn()
    pid = project_id if project_id is not None else _active_pid(conn)
    conn.close()
    return get_meta(f"overview:{pid}") or ""


# ---- Tom tat (scope project) ----
def set_file_summary(path, summary):
    conn = _conn()
    conn.execute("UPDATE files SET summary=? WHERE path=?", (summary, path))
    conn.commit()
    conn.close()


def files_needing_summary(project_id=None):
    conn = _conn()
    pid = project_id if project_id is not None else _active_pid(conn)
    rows = conn.execute(
        "SELECT path, lang, skeleton FROM files WHERE project_id=? AND COALESCE(summary,'')='' ORDER BY path",
        (pid,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_file_summary(path):
    conn = _conn()
    row = conn.execute("SELECT summary FROM files WHERE path=?", (path,)).fetchone()
    conn.close()
    return (row["summary"] if row else "") or ""


def all_file_summaries(limit=400, project_id=None):
    conn = _conn()
    pid = project_id if project_id is not None else _active_pid(conn)
    rows = conn.execute(
        "SELECT path, summary FROM files WHERE project_id=? AND COALESCE(summary,'')<>'' ORDER BY path LIMIT ?",
        (pid, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def summary_counts(project_id=None):
    conn = _conn()
    pid = project_id if project_id is not None else _active_pid(conn)
    total = conn.execute("SELECT COUNT(*) c FROM files WHERE project_id=?", (pid,)).fetchone()["c"]
    done = conn.execute("SELECT COUNT(*) c FROM files WHERE project_id=? AND COALESCE(summary,'')<>''",
                        (pid,)).fetchone()["c"]
    conn.close()
    return {"total": total, "summarized": done}
