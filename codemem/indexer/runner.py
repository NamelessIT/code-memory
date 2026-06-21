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
    gen = db.upsert_file(spath, lang, h, skeleton, r["symbols"], r["edges"], r["routes"], project_id=pid)
    vec_ok = vectors.index_file(spath, lang, skeleton, r["symbols"], project_id=pid, generation=gen)
    db.set_vector_ok(spath, vec_ok, pid)   # vector that bai -> danh dau de reconcile sau
    if progress:
        progress(f"indexed {spath} ({len(r['symbols'])} symbols, vector={'ok' if vec_ok else 'pending'})")
    return vec_ok


def ensure_embed_current():
    """Dung chung cho startup/manual/index: doi embedding model -> mark moi vector stale (#P0-5)."""
    from ..config import EMBED_MODEL
    if db.get_meta("embed_model") != EMBED_MODEL:
        db.mark_all_vectors_stale()
        db.set_meta("embed_model", EMBED_MODEL)
        return True
    return False


def _retry_tombstones(batch=50, scopes=None):
    """Retry cleanup intent den han (fair batching + backoff). Filter scope TRONG SQL (#P0-10).
    File-scope dung generation -> khong xoa vector moi sau re-index."""
    cleared = 0
    for t in db.due_tombstones(batch, scopes=scopes):
        scope = t["scope"]
        if scope == "collection":
            ok = vectors.clear_all()
        elif scope == "project":
            ok = vectors.delete_project(t["project_id"])
        else:
            gen = t.get("generation")
            # Legacy ungated delete (gen falsy -> xoa MOI vector cua path) chi duoc bo qua khi file
            # da re-index VA vector moi da HOAN TAT: index_file (goi truoc moi add) da ungated-delete
            # vector cu -> intent legacy stale, ack. Neu gen>0 nhung vector_ok=0 (crash sau SQLite
            # upsert truoc khi ghi vector) thi vector legacy van con -> phai ungated-clean roi ack,
            # de reconcile dung lai vector moi (#P0-10 crash-window).
            if not gen:
                st = db.file_vector_state(t["file_path"], t["project_id"])
                if st is not None and st[0] and st[1]:   # gen>0 VA vector_ok=1 -> moi vector hoan tat
                    db.del_tombstone(t["id"])
                    cleared += 1
                    continue
            ok = vectors.delete_file(t["file_path"], project_id=t["project_id"], generation=gen)
        if ok:
            db.del_tombstone(t["id"])
            cleared += 1
        else:
            db.record_tombstone_failure(t["id"], vectors.last_error() or "vector delete failed")
    return cleared


@_locked
def cleanup_worker(batch=50):
    """Retry MOI cleanup intent, KHONG phu thuoc active project (#P0-10).
    Dung cho startup + /api/cleanup/retry khi khong co project active (sau clear/xoa het)."""
    return _retry_tombstones(batch=batch)


@_locked
def reconcile_vectors(pid, progress=None, include_collection=True):
    """Repair vector pending/thieu + retry tombstone (#P0-5/#P0-10).
    include_collection=False khi goi ngay sau index (fence: khong wipe collection vua ghi)."""
    ensure_embed_current()
    scopes = None if include_collection else {"file", "project"}
    tomb = _retry_tombstones(scopes=scopes)
    repaired = still_pending = 0
    for f in db.files_pending_vector(pid):
        syms = db.get_symbols_for_file(f["path"], project_id=pid)
        ok = vectors.index_file(f["path"], f["lang"], f["skeleton"] or "", syms,
                                project_id=pid, generation=f.get("vector_gen", 0))
        db.set_vector_ok(f["path"], ok, pid)
        if ok:
            repaired += 1
        else:
            still_pending += 1
    if progress and (repaired or still_pending or tomb):
        progress(f"reconcile: repaired={repaired}, pending={still_pending}, tombstones_cleared={tomb}")
    return {"repaired": repaired, "pending": still_pending, "tombstones_cleared": tomb}


@_locked
def index_project(root: str, progress=None):
    """Index project tai 'root' (incremental). KHONG wipe project khac."""
    db.init_db()
    ensure_embed_current()                 # doi embedding model -> mark stale (#P0-5)
    root = canonical_root(root)
    pid = db.get_or_create_project(root)
    db.set_active_project(pid)

    # Fence (#P0-10): xu ly MOI collection-clear intent (ke ca chua den han) TRUOC khi ghi vector,
    # neu khong index xong se bi collection-wipe xoa mat. Fail -> abort index (khong ghi vao trang thai lech).
    for t in db.tombstones_by_scope("collection"):
        if vectors.clear_all():
            db.del_tombstone(t["id"])
        else:
            raise RuntimeError("collection cleanup dang cho va xoa vector that bai; huy index de tranh lech")

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
        db.delete_file(p, project_id=pid)        # ghi intent atomic (outbox)
        if vectors.delete_file(p, project_id=pid):
            db.ack_tombstone("file", pid, p)     # vector da xoa -> ack; fail -> intent giu lai retry

    # Repair vector pending; KHONG xu ly collection o day (vua ghi vector) (#P0-10 fence)
    rec = reconcile_vectors(pid, progress, include_collection=False)
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
    db.delete_file(sp, project_id=pid)           # ghi intent atomic (outbox)
    if vectors.delete_file(sp, project_id=pid):
        db.ack_tombstone("file", pid, sp)        # fail -> intent giu lai, worker retry
