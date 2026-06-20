"""Dieu phoi index: walker -> parser -> SQLite + ChromaDB. Index tang dan theo hash.
Vector la derived index: SQLite la source of truth, vector co the repair (reconcile)."""
import os
import threading
from pathlib import Path

from .walker import walk_source_files, file_hash, read_text, detect_lang
from .parser import parse_file, build_skeleton
from ..storage import db, vectors

# Serialize moi thao tac ghi nang (#P0-6): index/reconcile/single-file/delete/clear.
# RLock -> cho phep reconcile_vectors duoc goi long trong index_project cung thread.
INDEX_LOCK = threading.RLock()


def _locked(fn):
    import functools

    @functools.wraps(fn)
    def wrap(*a, **k):
        with INDEX_LOCK:
            return fn(*a, **k)
    return wrap


def canonical_root(root: str) -> str:
    """Chuan hoa root (Windows: drive/case/separator/symlink) de cung thu muc -> 1 project."""
    return os.path.normcase(os.path.normpath(os.path.realpath(str(root))))


def _index_one(spath, lang, h, root, pid, progress=None):
    """Parse + ghi SQLite + vector cho 1 file. Tra ve True neu vector ok."""
    content = read_text(Path(spath))
    rel = os.path.relpath(spath, root).replace("\\", "/")
    r = parse_file(content, lang, rel)
    skeleton = build_skeleton(rel, r["symbols"], r["imports"])
    db.upsert_file(spath, lang, h, skeleton, r["symbols"], r["edges"], r["routes"], project_id=pid)
    vec_ok = vectors.index_file(spath, lang, skeleton, r["symbols"], project_id=pid)
    db.set_vector_ok(spath, vec_ok, pid)   # vector that bai -> danh dau de reconcile sau
    if progress:
        progress(f"indexed {spath} ({len(r['symbols'])} symbols, vector={'ok' if vec_ok else 'pending'})")
    return vec_ok


@_locked
def reconcile_vectors(pid, progress=None):
    """Repair vector cho file co trong SQLite nhung vector pending/thieu (#P0-5)."""
    repaired = still_pending = 0
    for f in db.files_pending_vector(pid):
        syms = db.get_symbols_for_file(f["path"], project_id=pid)
        ok = vectors.index_file(f["path"], f["lang"], f["skeleton"] or "", syms, project_id=pid)
        db.set_vector_ok(f["path"], ok, pid)
        if ok:
            repaired += 1
        else:
            still_pending += 1
    if progress and (repaired or still_pending):
        progress(f"reconcile vector: repaired={repaired}, pending={still_pending}")
    return {"repaired": repaired, "pending": still_pending}


@_locked
def index_project(root: str, progress=None):
    """Index project tai 'root' (incremental). KHONG wipe project khac."""
    db.init_db()
    # Doi embedding model -> moi vector stale, danh dau de reconcile (#P0-5)
    from ..config import EMBED_MODEL
    if db.get_meta("embed_model") != EMBED_MODEL:
        db.mark_all_vectors_stale()
        db.set_meta("embed_model", EMBED_MODEL)

    root = canonical_root(root)
    pid = db.get_or_create_project(root)
    db.set_active_project(pid)

    existing = db.get_indexed_hashes(pid)
    seen = set()
    n_new = n_upd = n_skip = n_err = 0

    for path, lang in walk_source_files(root):
        spath = os.path.normcase(str(path))   # khop voi root da normcase
        seen.add(spath)
        try:
            h = file_hash(path)
        except OSError:
            continue
        if existing.get(spath) == h:
            n_skip += 1
            continue
        try:
            _index_one(spath, lang, h, root, pid, progress)
            n_upd += 1 if spath in existing else 0
            n_new += 0 if spath in existing else 1
        except Exception as e:
            n_err += 1
            if progress:
                progress(f"[err] {spath}: {e}")

    # File da bi xoa khoi disk -> go khoi index (trong project nay)
    removed = [p for p in existing if p not in seen]
    for p in removed:
        db.delete_file(p, project_id=pid)
        vectors.delete_file(p, project_id=pid)

    # Repair vector pending (ke ca file unchanged nhung vector tung loi)
    rec = reconcile_vectors(pid, progress)
    db.touch_project(pid)

    return {
        "project_root": root, "project_id": pid,
        "new": n_new, "updated": n_upd, "skipped": n_skip,
        "removed": len(removed), "errors": n_err,
        "vector_repaired": rec["repaired"], "vector_pending": rec["pending"],
    }


@_locked
def index_single_file(path: str, project_id=None):
    """Index lai 1 file (watcher). Bind project_id CO DINH (khong doc active toan cuc - #P0-6)."""
    p = Path(path)
    lang = detect_lang(p)
    if not lang or not p.is_file():
        return False
    pid = project_id if project_id is not None else db.active_project_id()
    if pid is None:
        return False
    root = db.get_project_root(pid) or str(p.parent)
    try:
        h = file_hash(p)
        return _index_one(os.path.normcase(str(p)), lang, h, root, pid)
    except Exception as e:
        print(f"[warn] index_single_file {path}: {e}")
        return False


@_locked
def remove_file(path: str, project_id=None):
    """Go 1 file khoi index (file bi xoa). Bind project_id co dinh."""
    pid = project_id if project_id is not None else db.active_project_id()
    sp = os.path.normcase(str(Path(path)))
    db.delete_file(sp, project_id=pid)
    vectors.delete_file(sp, project_id=pid)
