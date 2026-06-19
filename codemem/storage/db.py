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
            FOREIGN KEY (file_path) REFERENCES files(path)
        );
        CREATE INDEX IF NOT EXISTS idx_sym_name ON symbols(name);
        CREATE INDEX IF NOT EXISTS idx_sym_file ON symbols(file_path);
        CREATE INDEX IF NOT EXISTS idx_sym_kind ON symbols(kind);

        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );
    """)
    conn.commit()
    conn.close()


def get_indexed_hashes() -> dict:
    """Map {path: hash} cua cac file da index -> de biet file nao doi/them/xoa."""
    conn = _conn()
    rows = conn.execute("SELECT path, hash FROM files").fetchall()
    conn.close()
    return {r["path"]: r["hash"] for r in rows}


def upsert_file(path, lang, file_hash, skeleton, symbols):
    """Ghi file + thay toan bo symbol cua file (xoa cu, them moi)."""
    conn = _conn()
    now = datetime.now().isoformat()
    conn.execute(
        "INSERT INTO files(path, lang, hash, skeleton, indexed_at) VALUES (?,?,?,?,?) "
        "ON CONFLICT(path) DO UPDATE SET lang=?, hash=?, skeleton=?, indexed_at=?",
        (path, lang, file_hash, skeleton, now, lang, file_hash, skeleton, now),
    )
    conn.execute("DELETE FROM symbols WHERE file_path=?", (path,))
    conn.executemany(
        "INSERT INTO symbols(file_path, kind, name, signature, start_line, end_line, parent, exported) "
        "VALUES (?,?,?,?,?,?,?,?)",
        [
            (path, s["kind"], s["name"], s["signature"], s["start_line"],
             s["end_line"], s.get("parent"), 1 if s.get("exported") else 0)
            for s in symbols
        ],
    )
    conn.commit()
    conn.close()


def delete_file(path):
    conn = _conn()
    conn.execute("DELETE FROM symbols WHERE file_path=?", (path,))
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


def clear_all():
    """Xoa toan bo index (file + symbol + meta) khoi SQLite."""
    conn = _conn()
    conn.execute("DELETE FROM symbols")
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
