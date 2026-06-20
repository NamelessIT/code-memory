"""Dieu phoi index: walker -> parser -> SQLite + ChromaDB. Index tang dan theo hash."""
import os
from pathlib import Path

from .walker import walk_source_files, file_hash, read_text, detect_lang
from .parser import parse_file, build_skeleton
from ..storage import db, vectors


def index_project(root: str, progress=None):
    """
    Index toan bo project tai 'root'. Chi xu ly file moi/thay doi; xoa file da bien mat.
    progress: callable(msg) tuy chon de bao tien do.
    Tra ve thong ke.
    """
    db.init_db()
    root = str(Path(root).resolve())

    # Doi sang project khac -> wipe index cu de khong cong don (tranh SQLite/Chroma phinh)
    prev = db.get_status().get("project_root")
    if prev and prev != root:
        db.clear_all()
        vectors.clear_all()

    existing = db.get_indexed_hashes()      # {path: hash}
    seen = set()

    n_new = n_upd = n_skip = n_err = 0

    for path, lang in walk_source_files(root):
        spath = str(path)
        seen.add(spath)
        try:
            h = file_hash(path)
        except OSError:
            continue

        if existing.get(spath) == h:
            n_skip += 1
            continue

        try:
            content = read_text(path)
            rel = os.path.relpath(spath, root).replace("\\", "/")  # rel path: tag/skeleton chinh xac
            r = parse_file(content, lang, rel)
            skeleton = build_skeleton(rel, r["symbols"], r["imports"])
            db.upsert_file(spath, lang, h, skeleton, r["symbols"], r["edges"], r["routes"])
            vectors.index_file(spath, lang, skeleton, r["symbols"])
            if spath in existing:
                n_upd += 1
            else:
                n_new += 1
            if progress:
                progress(f"indexed {spath} ({len(r['symbols'])} symbols)")
        except Exception as e:
            n_err += 1
            if progress:
                progress(f"[err] {spath}: {e}")

    # File da bi xoa khoi disk -> go khoi index
    removed = [p for p in existing if p not in seen and p.startswith(root)]
    for p in removed:
        db.delete_file(p)
        vectors.delete_file(p)

    db.set_meta("project_root", root)

    return {
        "project_root": root,
        "new": n_new, "updated": n_upd, "skipped": n_skip,
        "removed": len(removed), "errors": n_err,
    }


def index_single_file(path: str):
    """Index lai 1 file (dung cho watcher khi file thay doi)."""
    p = Path(path)
    lang = detect_lang(p)
    if not lang or not p.is_file():
        return False
    try:
        content = read_text(p)
        root = db.get_meta("project_root") or str(p.parent)
        rel = os.path.relpath(str(p), root).replace("\\", "/")
        r = parse_file(content, lang, rel)
        skeleton = build_skeleton(rel, r["symbols"], r["imports"])
        h = file_hash(p)
        db.upsert_file(str(p), lang, h, skeleton, r["symbols"], r["edges"], r["routes"])
        vectors.index_file(str(p), lang, skeleton, r["symbols"])
        return True
    except Exception:
        return False


def remove_file(path: str):
    """Go 1 file khoi index (file bi xoa)."""
    db.delete_file(str(Path(path)))
    vectors.delete_file(str(Path(path)))
