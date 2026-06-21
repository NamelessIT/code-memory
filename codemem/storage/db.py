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
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER, path TEXT,
            lang TEXT, hash TEXT, skeleton TEXT, indexed_at TEXT, summary TEXT DEFAULT '',
            vector_ok INTEGER DEFAULT 1, vector_gen INTEGER DEFAULT 0,
            UNIQUE(project_id, path)
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
        -- Cleanup intent ben vung: vector delete that bai -> retry idempotent (#P0-10)
        -- scope: file|project|collection. NULL tranh dung de UNIQUE dedup duoc.
        CREATE TABLE IF NOT EXISTS vector_tombstones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scope TEXT NOT NULL,
            project_id INTEGER NOT NULL DEFAULT 0,
            file_path TEXT NOT NULL DEFAULT '',
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT DEFAULT '',
            next_retry TEXT DEFAULT '',
            generation INTEGER NOT NULL DEFAULT 0,
            created_at TEXT,
            UNIQUE(scope, project_id, file_path)
        );
    """)
    # Upgrade vector_tombstones v1 -> v2 GIU row pending, ATOMIC trong transaction init_db (#P0-10/#P0-8).
    # KHONG dung executescript (auto-commit giua cau) de crash khong de bang lech.
    now = datetime.now().isoformat()
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    # Recovery: migration truoc bi gian doan -> con bang _v1. Copy not vao v2 roi drop.
    if "vector_tombstones_v1" in tables:
        conn.execute(
            "INSERT OR IGNORE INTO vector_tombstones(scope, project_id, file_path, next_retry, created_at) "
            "SELECT COALESCE(scope,'file'), COALESCE(project_id,0), COALESCE(file_path,''), ?, COALESCE(created_at,?) "
            "FROM vector_tombstones_v1", (now, now))
        conn.execute("DROP TABLE vector_tombstones_v1")
    tcols = [r["name"] for r in conn.execute("PRAGMA table_info(vector_tombstones)")]
    if "attempts" not in tcols:        # bang hien tai con schema v1 -> nang cap atomic
        conn.execute("ALTER TABLE vector_tombstones RENAME TO vector_tombstones_v1")
        conn.execute("""
            CREATE TABLE vector_tombstones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scope TEXT NOT NULL,
                project_id INTEGER NOT NULL DEFAULT 0,
                file_path TEXT NOT NULL DEFAULT '',
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT DEFAULT '',
                next_retry TEXT DEFAULT '',
                generation INTEGER NOT NULL DEFAULT 0,
                created_at TEXT,
                UNIQUE(scope, project_id, file_path)
            )""")
        conn.execute(
            "INSERT OR IGNORE INTO vector_tombstones(scope, project_id, file_path, next_retry, created_at) "
            "SELECT COALESCE(scope,'file'), COALESCE(project_id,0), COALESCE(file_path,''), ?, COALESCE(created_at,?) "
            "FROM vector_tombstones_v1", (now, now))
        conn.execute("DROP TABLE vector_tombstones_v1")
    # Migration cot cho DB cu (truoc multi-project)
    for stmt in (
        "ALTER TABLE symbols ADD COLUMN tag TEXT DEFAULT ''",
        "ALTER TABLE symbols ADD COLUMN doc TEXT DEFAULT ''",
        "ALTER TABLE symbols ADD COLUMN body TEXT DEFAULT ''",
        "ALTER TABLE files ADD COLUMN summary TEXT DEFAULT ''",
        "ALTER TABLE files ADD COLUMN vector_ok INTEGER DEFAULT 1",
        "ALTER TABLE files ADD COLUMN vector_gen INTEGER DEFAULT 0",
        "ALTER TABLE files ADD COLUMN project_id INTEGER",
        "ALTER TABLE vector_tombstones ADD COLUMN generation INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE symbols ADD COLUMN project_id INTEGER",
        "ALTER TABLE edges ADD COLUMN project_id INTEGER",
        "ALTER TABLE routes ADD COLUMN project_id INTEGER",
    ):
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError:
            pass

    # Migrate files PK path-global (cu) -> composite (project_id, path). ATOMIC (conn.execute trong
    # transaction init_db, KHONG executescript). files_new PHAI gom vector_ok + vector_gen (#P0-8 regression).
    fcols = [r["name"] for r in conn.execute("PRAGMA table_info(files)")]
    if "id" not in fcols:
        conn.execute("""
            CREATE TABLE files_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER, path TEXT,
                lang TEXT, hash TEXT, skeleton TEXT, indexed_at TEXT, summary TEXT DEFAULT '',
                vector_ok INTEGER DEFAULT 1, vector_gen INTEGER DEFAULT 0,
                UNIQUE(project_id, path)
            )""")
        conn.execute(
            "INSERT INTO files_new(project_id, path, lang, hash, skeleton, indexed_at, summary, vector_ok, vector_gen) "
            "SELECT project_id, path, lang, hash, skeleton, indexed_at, COALESCE(summary,''), "
            "COALESCE(vector_ok,1), COALESCE(vector_gen,0) FROM files")
        conn.execute("DROP TABLE files")
        conn.execute("ALTER TABLE files_new RENAME TO files")

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

    # Canonicalize + merge project trung canonical-root (Windows casing/separator) - #P0-8.
    # Marker v2: DB da chay v1 (ban loi) van phai re-run ban da sua.
    rc = conn.execute("SELECT value FROM meta WHERE key='roots_canon_v2'").fetchone()
    if not rc or rc["value"] != "1":
        _migrate_canonical_roots(conn)
        conn.execute("INSERT INTO meta(key,value) VALUES('roots_canon_v2','1') "
                     "ON CONFLICT(key) DO UPDATE SET value='1'")

    # Doi schema version -> invalidate overview/summary cu (hallucination legacy)
    row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    if (row["value"] if row else None) != SCHEMA_VERSION:
        conn.execute("DELETE FROM meta WHERE key LIKE 'overview%'")
        conn.execute("UPDATE files SET summary=''")
        conn.execute("INSERT INTO meta(key,value) VALUES('schema_version',?) "
                     "ON CONFLICT(key) DO UPDATE SET value=?", (SCHEMA_VERSION, SCHEMA_VERSION))

    # Post-migration schema assertion/repair: dam bao files co vector_gen/vector_ok (#P0-8)
    fcols2 = [r["name"] for r in conn.execute("PRAGMA table_info(files)")]
    for col, ddl in (("vector_gen", "ALTER TABLE files ADD COLUMN vector_gen INTEGER DEFAULT 0"),
                     ("vector_ok", "ALTER TABLE files ADD COLUMN vector_ok INTEGER DEFAULT 1")):
        if col not in fcols2:
            conn.execute(ddl)

    # Normalize legacy: file vector_gen=0 (index truoc khi co generation) -> mark pending de re-embed
    # voi generation that. Tranh vector generation-unknown + delete-orphan (#P0-10/#P0-5). Chay 1 lan.
    lg = conn.execute("SELECT value FROM meta WHERE key='legacy_gen_norm'").fetchone()
    if not lg or lg["value"] != "1":
        conn.execute("UPDATE files SET vector_ok=0 WHERE COALESCE(vector_gen,0)=0")
        conn.execute("INSERT INTO meta(key,value) VALUES('legacy_gen_norm','1') "
                     "ON CONFLICT(key) DO UPDATE SET value='1'")
    conn.commit()
    conn.close()


def _name_from_root(root):
    import os
    return os.path.basename(os.path.normpath(root)) or root


def _canon(root):
    import os
    try:
        return os.path.normcase(os.path.normpath(os.path.realpath(str(root))))
    except Exception:
        return os.path.normcase(os.path.normpath(str(root)))


def _migrate_canonical_roots(conn):
    """Gop project trung canonical-root + dedup file theo normcase path (#P0-8). Chay 1 lan.
    Merge theo (canonical project, normcase path); xung dot -> giu indexed_at moi nhat;
    moi path/project doi -> vector_ok=0 (re-embed) va don vector cu."""
    import os
    rows = conn.execute("SELECT id, root FROM projects ORDER BY id").fetchall()
    active = _active_pid(conn)
    vec_cleanup = []     # (project_id, path, generation) vector cu can xoa
    dup_pids = []

    groups = {}
    for r in rows:
        groups.setdefault(_canon(r["root"]), []).append(r["id"])

    def _del_file(pidx, path):
        for t in ("symbols", "edges", "routes"):
            conn.execute(f"DELETE FROM {t} WHERE project_id=? AND file_path=?", (pidx, path))
        conn.execute("DELETE FROM files WHERE project_id=? AND path=?", (pidx, path))

    for canon, ids in groups.items():
        keep = ids[0]
        group_changed = len(ids) > 1     # co dup project -> chac chan merge
        # Gom tat ca file trong nhom (moi project id); giu vector_gen de carry vao intent (#P0-8)
        files = []
        for pidx in ids:
            for f in conn.execute("SELECT path, indexed_at, vector_gen FROM files WHERE project_id=?",
                                  (pidx,)).fetchall():
                files.append((pidx, f["path"], f["indexed_at"] or "", f["vector_gen"] or 0))

        # Chon survivor cho moi normcase-key (indexed_at moi nhat)
        best = {}
        for (pidx, path, ts, vgen) in files:
            nkey = os.path.normcase(path)
            cur = best.get(nkey)
            if cur is None or ts >= cur[2]:
                best[nkey] = (pidx, path, ts, vgen)
        survivors = {(b[0], b[1]) for b in best.values()}

        # Xoa cac ban khong phai survivor
        for (pidx, path, ts, vgen) in files:
            if (pidx, path) not in survivors:
                _del_file(pidx, path)
                vec_cleanup.append((pidx, path, vgen))
                group_changed = True

        # Dua survivor ve (keep, nkey)
        for nkey, (pidx, path, ts, vgen) in best.items():
            if (pidx, path) == (keep, nkey):
                continue
            for t in ("symbols", "edges", "routes"):
                conn.execute(f"UPDATE {t} SET project_id=?, file_path=? WHERE project_id=? AND file_path=?",
                             (keep, nkey, pidx, path))
            conn.execute("UPDATE files SET project_id=?, path=?, vector_ok=0 WHERE project_id=? AND path=?",
                         (keep, nkey, pidx, path))
            vec_cleanup.append((pidx, path, vgen))   # vector ID cu (pidx, path) khac (keep, nkey)
            group_changed = True

        # Xoa cac dup project + overview
        for dup in ids[1:]:
            conn.execute("DELETE FROM meta WHERE key=?", (f"overview:{dup}",))
            conn.execute("DELETE FROM projects WHERE id=?", (dup,))
            dup_pids.append(dup)
            if active == dup:
                active = keep
        # Canonicalize root keep
        cur = conn.execute("SELECT root FROM projects WHERE id=?", (keep,)).fetchone()
        if cur and cur["root"] != canon:
            conn.execute("UPDATE projects SET root=? WHERE id=?", (canon, keep))
            group_changed = True
        # Bat ky merge/move/root-change -> overview cu da stale
        if group_changed:
            conn.execute("DELETE FROM meta WHERE key=?", (f"overview:{keep}",))

    if active is not None:
        conn.execute("INSERT INTO meta(key,value) VALUES('active_project_id',?) "
                     "ON CONFLICT(key) DO UPDATE SET value=?", (str(active), str(active)))

    # Ghi cleanup intent (tombstone) trong CUNG transaction migration -> durable, worker retry sau.
    # KHONG goi Chroma o day (side-effect khong ben trong transaction) - #P0-8/#P0-10.
    items = [("project", dp, "", 0) for dp in dup_pids] + \
            [("file", pidx, path, vgen) for (pidx, path, vgen) in vec_cleanup]
    if items:
        add_tombstones_bulk(conn, items)


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


def project_exists(pid):
    conn = _conn()
    ok = conn.execute("SELECT 1 FROM projects WHERE id=?", (pid,)).fetchone() is not None
    conn.close()
    return ok


def set_active_project(pid):
    """Chi set active neu project ton tai. Tra True/False."""
    if not project_exists(pid):
        return False
    set_meta("active_project_id", str(pid))
    return True


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
    """Xoa 1 project + toan bo du lieu cua no (KHONG dung den project khac).
    Neu xoa project active -> tu chon project con lai (neu co)."""
    conn = _conn()
    was_active = (_active_pid(conn) == pid)
    for t in ("files", "symbols", "edges", "routes"):
        conn.execute(f"DELETE FROM {t} WHERE project_id=?", (pid,))
    conn.execute("DELETE FROM projects WHERE id=?", (pid,))
    conn.execute("DELETE FROM meta WHERE key=?", (f"overview:{pid}",))
    # Collapse intent file cu + ghi intent project-scope trong CUNG transaction (outbox #P0-10)
    conn.execute("DELETE FROM vector_tombstones WHERE project_id=? AND scope='file'", (pid,))
    now = datetime.now().isoformat()
    conn.execute("INSERT OR IGNORE INTO vector_tombstones(scope, project_id, file_path, next_retry, created_at) "
                 "VALUES ('project',?,'',?,?)", (pid, now, now))
    if was_active:
        nxt = conn.execute("SELECT id FROM projects ORDER BY id LIMIT 1").fetchone()
        if nxt:
            conn.execute("INSERT INTO meta(key,value) VALUES('active_project_id',?) "
                         "ON CONFLICT(key) DO UPDATE SET value=?", (str(nxt["id"]), str(nxt["id"])))
        else:
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
    """Ghi file vao SQLite. vector_ok=0 + bump vector_gen TRONG CUNG transaction (#P0-5/#P0-10):
    - crash giua upsert va embedding -> vector_ok=0 (reconcile se sua), khong bao gia 'da co vector'.
    - vector_gen tang don dieu -> intent xoa cu (gen thap) khong xoa vector moi (gen cao).
    Tra ve generation de caller tag vector."""
    conn = _conn()
    now = datetime.now().isoformat()
    grow = conn.execute("SELECT value FROM meta WHERE key='vec_gen_seq'").fetchone()
    gen = (int(grow["value"]) if grow and grow["value"] else 0) + 1
    conn.execute("INSERT INTO meta(key,value) VALUES('vec_gen_seq',?) "
                 "ON CONFLICT(key) DO UPDATE SET value=?", (str(gen), str(gen)))
    # Identity = (project_id, path) -> project long nhau khong ghi de nhau
    conn.execute(
        "INSERT INTO files(project_id, path, lang, hash, skeleton, indexed_at, summary, vector_ok, vector_gen) "
        "VALUES (?,?,?,?,?,?,'',0,?) "
        "ON CONFLICT(project_id, path) DO UPDATE SET lang=?, hash=?, skeleton=?, indexed_at=?, "
        "summary='', vector_ok=0, vector_gen=?",
        (project_id, path, lang, file_hash, skeleton, now, gen, lang, file_hash, skeleton, now, gen),
    )
    conn.execute("DELETE FROM symbols WHERE project_id=? AND file_path=?", (project_id, path))
    conn.executemany(
        "INSERT INTO symbols(project_id, file_path, kind, name, signature, start_line, end_line, parent, exported, tag, doc, body) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [(project_id, path, s["kind"], s["name"], s["signature"], s["start_line"], s["end_line"],
          s.get("parent"), 1 if s.get("exported") else 0, s.get("tag", ""), s.get("doc", ""), s.get("body", ""))
         for s in symbols],
    )
    conn.execute("DELETE FROM edges WHERE project_id=? AND file_path=?", (project_id, path))
    if edges:
        conn.executemany("INSERT INTO edges(project_id, file_path, caller, callee) VALUES (?,?,?,?)",
                         [(project_id, path, e["caller"], e["callee"]) for e in edges])
    conn.execute("DELETE FROM routes WHERE project_id=? AND file_path=?", (project_id, path))
    if routes:
        conn.executemany("INSERT INTO routes(project_id, file_path, method, path, handler, line) VALUES (?,?,?,?,?,?)",
                         [(project_id, path, r["method"], r["path"], r.get("handler", ""), r.get("line")) for r in routes])
    # File doi -> overview cua project thanh stale
    conn.execute("DELETE FROM meta WHERE key=?", (f"overview:{project_id}",))
    conn.commit()
    conn.close()
    return gen


def delete_file(path, project_id=None):
    """Xoa file khoi SQLite + ghi cleanup intent vector (kem generation) trong CUNG transaction (outbox #P0-10).
    Caller goi vectors.delete_file roi ack_tombstone khi thanh cong."""
    conn = _conn()
    pid = project_id if project_id is not None else _active_pid(conn)
    grow = conn.execute("SELECT vector_gen FROM files WHERE project_id=? AND path=?", (pid, path)).fetchone()
    gen = grow["vector_gen"] if grow else 0
    for t in ("symbols", "edges", "routes"):
        conn.execute(f"DELETE FROM {t} WHERE project_id=? AND file_path=?", (pid, path))
    conn.execute("DELETE FROM files WHERE project_id=? AND path=?", (pid, path))
    if pid is not None:
        conn.execute("DELETE FROM meta WHERE key=?", (f"overview:{pid}",))  # invalidate overview
    now = datetime.now().isoformat()
    # Intent kem generation: retry chi xoa vector co gen <= gen nay (khong xoa vector moi sau re-index)
    conn.execute("INSERT INTO vector_tombstones(scope, project_id, file_path, next_retry, created_at, generation) "
                 "VALUES ('file',?,?,?,?,?) "
                 "ON CONFLICT(scope,project_id,file_path) DO UPDATE SET generation=MAX(generation,excluded.generation), "
                 "next_retry=excluded.next_retry, attempts=0",
                 (pid or 0, path, now, now, gen))
    conn.commit()
    conn.close()


def ack_tombstone(scope, project_id=0, file_path=""):
    """Xoa intent khi vector delete da thanh cong (#P0-10 outbox ack)."""
    conn = _conn()
    conn.execute("DELETE FROM vector_tombstones WHERE scope=? AND project_id=? AND file_path=?",
                 (scope, project_id or 0, file_path or ""))
    conn.commit()
    conn.close()


def get_symbols_for_file(path, project_id=None):
    conn = _conn()
    pid = project_id if project_id is not None else _active_pid(conn)
    rows = conn.execute(
        "SELECT * FROM symbols WHERE project_id=? AND file_path=? ORDER BY start_line",
        (pid, path)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def set_vector_ok(path, ok, project_id):
    conn = _conn()
    conn.execute("UPDATE files SET vector_ok=? WHERE project_id=? AND path=?",
                 (1 if ok else 0, project_id, path))
    conn.commit()
    conn.close()


_RETRY_BASE = 5          # giay
_RETRY_CAP = 3600        # 1 gio


def add_tombstone(scope, project_id=0, file_path=""):
    """Ghi cleanup intent (dedup theo (scope,project_id,file_path)). Due ngay (#P0-10)."""
    conn = _conn()
    now = datetime.now().isoformat()
    conn.execute(
        "INSERT OR IGNORE INTO vector_tombstones(scope, project_id, file_path, next_retry, created_at) "
        "VALUES (?,?,?,?,?)", (scope, project_id or 0, file_path or "", now, now))
    conn.commit()
    conn.close()


def add_tombstones_bulk(conn, items):
    """Ghi nhieu tombstone trong CUNG transaction (dung trong migration).
    items: [(scope,pid,path)] hoac [(scope,pid,path,generation)] (#P0-8: carry generation
    cua vector cu -> retry chi xoa vector gen <= do, khong xoa vector moi sau re-index)."""
    now = datetime.now().isoformat()
    rows = []
    for it in items:
        s, p, fp = it[0], it[1], it[2]
        g = it[3] if len(it) > 3 else 0
        rows.append((s, p or 0, fp or "", now, now, g or 0))
    conn.executemany(
        "INSERT INTO vector_tombstones(scope, project_id, file_path, next_retry, created_at, generation) "
        "VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(scope,project_id,file_path) DO UPDATE SET "
        "generation=MAX(generation, excluded.generation)",
        rows)


def due_tombstones(limit=50, scopes=None):
    """Intent den han (next_retry <= now), uu tien han som nhat. Filter scope TRONG SQL truoc LIMIT
    -> intent scope khac khong che mat scope can (#P0-10)."""
    conn = _conn()
    now = datetime.now().isoformat()
    sql = "SELECT * FROM vector_tombstones WHERE next_retry <= ?"
    params = [now]
    if scopes:
        sql += " AND scope IN (%s)" % ",".join("?" * len(scopes))
        params += list(scopes)
    sql += " ORDER BY next_retry, id LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def tombstones_by_scope(scope):
    """TAT CA intent cua scope (KE CA chua den han) -> dung cho fence (#P0-10)."""
    conn = _conn()
    rows = conn.execute("SELECT * FROM vector_tombstones WHERE scope=? ORDER BY id", (scope,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def record_tombstone_failure(tid, error=""):
    """Tang attempts + backoff next_retry (exponential, cap 1h) + last_error."""
    conn = _conn()
    row = conn.execute("SELECT attempts FROM vector_tombstones WHERE id=?", (tid,)).fetchone()
    attempts = (row["attempts"] if row else 0) + 1
    delay = min(_RETRY_CAP, _RETRY_BASE * (2 ** min(attempts, 20)))
    from datetime import timedelta
    nxt = (datetime.now() + timedelta(seconds=delay)).isoformat()
    conn.execute("UPDATE vector_tombstones SET attempts=?, last_error=?, next_retry=? WHERE id=?",
                 (attempts, (error or "")[:300], nxt, tid))
    conn.commit()
    conn.close()


def del_tombstone(tid):
    conn = _conn()
    conn.execute("DELETE FROM vector_tombstones WHERE id=?", (tid,))
    conn.commit()
    conn.close()


def tombstone_stats():
    conn = _conn()
    pending = conn.execute("SELECT COUNT(*) c FROM vector_tombstones").fetchone()["c"]
    failed = conn.execute("SELECT COUNT(*) c FROM vector_tombstones WHERE attempts>0").fetchone()["c"]
    le = conn.execute("SELECT last_error FROM vector_tombstones WHERE attempts>0 "
                      "ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    return {"pending": pending, "failed": failed, "last_error": le["last_error"] if le else None}


def mark_all_vectors_stale(project_id=None):
    """Danh dau vector can re-embed (vd doi embedding model) -> reconcile se sua."""
    conn = _conn()
    if project_id is None:
        conn.execute("UPDATE files SET vector_ok=0")
    else:
        conn.execute("UPDATE files SET vector_ok=0 WHERE project_id=?", (project_id,))
    conn.commit()
    conn.close()


def files_pending_vector(project_id):
    """File co trong SQLite nhung vector chua thanh cong -> can repair (#P0-5)."""
    conn = _conn()
    rows = conn.execute(
        "SELECT path, lang, skeleton, vector_gen FROM files WHERE project_id=? AND COALESCE(vector_ok,1)=0",
        (project_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def file_vector_state(path, project_id=None):
    """(vector_gen, vector_ok) cua file, hoac None neu file khong con trong DB (#P0-10).
    Dung de quyet dinh legacy cleanup: chi coi intent gen0 la stale (ack, khong xoa) khi
    vector moi da HOAN TAT (gen>0 VA vector_ok=1 -> index_file da don vector cu). Neu gen>0
    nhung vector_ok=0 (crash truoc khi ghi vector) thi van phai ungated-clean legacy orphan."""
    conn = _conn()
    pid = project_id if project_id is not None else _active_pid(conn)
    row = conn.execute("SELECT vector_gen, vector_ok FROM files WHERE project_id=? AND path=?",
                       (pid, path)).fetchone()
    conn.close()
    return (row["vector_gen"], row["vector_ok"]) if row else None


def get_project_root(pid):
    conn = _conn()
    row = conn.execute("SELECT root FROM projects WHERE id=?", (pid,)).fetchone()
    conn.close()
    return row["root"] if row else None


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


def get_symbol_in_file(name, file_path, project_id=None):
    conn = _conn()
    pid = project_id if project_id is not None else _active_pid(conn)
    row = conn.execute("SELECT * FROM symbols WHERE project_id=? AND name=? AND file_path=? LIMIT 1",
                       (pid, name, file_path)).fetchone()
    conn.close()
    return dict(row) if row else None


def symbol_exists(name, project_id=None):
    conn = _conn()
    pid = project_id if project_id is not None else _active_pid(conn)
    row = conn.execute("SELECT 1 FROM symbols WHERE project_id=? AND name=? LIMIT 1",
                       (pid, name)).fetchone()
    conn.close()
    return row is not None


def get_skeleton(path, project_id=None):
    conn = _conn()
    pid = project_id if project_id is not None else _active_pid(conn)
    row = conn.execute("SELECT skeleton FROM files WHERE project_id=? AND path=?", (pid, path)).fetchone()
    conn.close()
    return row["skeleton"] if row else None


def get_file_row(path, project_id=None):
    conn = _conn()
    pid = project_id if project_id is not None else _active_pid(conn)
    row = conn.execute("SELECT * FROM files WHERE project_id=? AND path=?", (pid, path)).fetchone()
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
    pending = conn.execute("SELECT COUNT(*) c FROM files WHERE project_id=? AND COALESCE(vector_ok,1)=0",
                           (pid,)).fetchone()["c"]
    prow = conn.execute("SELECT root FROM projects WHERE id=?", (pid,)).fetchone() if pid else None
    conn.close()
    return {"files": nf, "symbols": ns, "by_language": by_lang, "by_kind": by_kind,
            "project_root": prow["root"] if prow else None, "project_id": pid,
            "vector_pending": pending}


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


def clear_all(add_collection_intent=False):
    """Xoa SACH toan bo (moi project). add_collection_intent: ghi collection-intent TRONG CUNG
    transaction voi wipe (outbox atomic cho /api/clear #P0-10)."""
    init_db()
    conn = _conn()
    for t in ("symbols", "edges", "routes", "files", "projects", "meta", "vector_tombstones"):
        conn.execute(f"DELETE FROM {t}")
    if add_collection_intent:
        now = datetime.now().isoformat()
        conn.execute("INSERT INTO vector_tombstones(scope, project_id, file_path, next_retry, created_at) "
                     "VALUES ('collection',0,'',?,?)", (now, now))
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
def set_file_summary(path, summary, project_id=None):
    conn = _conn()
    pid = project_id if project_id is not None else _active_pid(conn)
    conn.execute("UPDATE files SET summary=? WHERE project_id=? AND path=?", (summary, pid, path))
    conn.commit()
    conn.close()


def files_needing_summary(project_id=None):
    conn = _conn()
    pid = project_id if project_id is not None else _active_pid(conn)
    rows = conn.execute(
        "SELECT path, lang, skeleton, vector_gen FROM files WHERE project_id=? AND COALESCE(summary,'')='' ORDER BY path",
        (pid,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_file_summary(path, project_id=None):
    conn = _conn()
    pid = project_id if project_id is not None else _active_pid(conn)
    row = conn.execute("SELECT summary FROM files WHERE project_id=? AND path=?", (pid, path)).fetchone()
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
