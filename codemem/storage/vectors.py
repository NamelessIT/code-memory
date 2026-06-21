"""ChromaDB vector index. An toan degraded: vector loi -> app van chay lexical-only.
- Thao tac CAN embedding (add/query): get_collection() (load SentenceTransformer).
- Thao tac KHONG can embedding (delete/count/clear): _raw() (khong load model).
- Loi load (import/model/network/corrupt) deu bi catch -> tra None, KHONG propagate.
"""
from ..config import CHROMA_DIR, CHROMA_COLLECTION, EMBED_MODEL, ensure_dirs

_collection = None     # collection co embedding function (add/query)
_raw_col = None        # collection khong embedding (delete/count/clear)
_embed_failed = False
_raw_failed = False
_last_error = None


def get_collection():
    """Collection co embedding. None neu vector/embedding khong dung duoc (-> lexical mode)."""
    global _collection, _embed_failed, _last_error
    if _collection is not None:
        return _collection
    if _embed_failed:
        return None
    try:
        import chromadb
        from chromadb.utils import embedding_functions
        ensure_dirs()
        ef = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=EMBED_MODEL)
        client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        _collection = client.get_or_create_collection(CHROMA_COLLECTION, embedding_function=ef)
        return _collection
    except Exception as e:                 # import/model/network/corrupt -> degraded
        _embed_failed = True
        _last_error = f"embedding/vector unavailable: {e}"
        print(f"[warn] {_last_error} -> chay lexical-only")
        return None


def _is_absent(exc) -> bool:
    """True neu exception nghia la 'collection khong ton tai' (KHONG phai loi IO/corrupt).
    Phan biet bang loai exception, khong catch-all (#P0-10)."""
    try:
        import chromadb.errors as ce
        not_found = getattr(ce, "NotFoundError", None)
        if not_found is not None and isinstance(exc, not_found):
            return True
    except Exception:
        pass
    name = type(exc).__name__.lower()
    if "notfound" in name:
        return True
    if isinstance(exc, ValueError):   # chroma cu: ValueError("Collection ... does not exist")
        msg = str(exc).lower()
        return "does not exist" in msg or "not found" in msg or "no such" in msg
    return False                      # RuntimeError/IO/khac -> KHONG coi la absent


def _client():
    """PersistentClient hoac None neu chroma khong mo duoc (corrupt/import loi)."""
    try:
        import chromadb
        ensure_dirs()
        return chromadb.PersistentClient(path=str(CHROMA_DIR))
    except Exception as e:
        global _last_error
        _last_error = f"chroma client unavailable: {e}"
        return None


def _raw():
    """Collection de delete/count (khong cung cap ef). None neu absent HOAC unavailable."""
    cl = _client()
    if cl is None:
        return None
    try:
        return cl.get_collection(CHROMA_COLLECTION)
    except Exception:
        return None


def health():
    """Trang thai cho /api/health (khong ep load embedding)."""
    cl = _client()
    chroma_ok = cl is not None
    return {"chroma": chroma_ok, "embedding_failed": _embed_failed, "error": _last_error}


def available():
    return _client() is not None


def last_error():
    return _last_error


def _delete_where(where):
    """Tra ve True (da xoa hoac khong co gi de xoa) / False (unavailable hoac loi that)."""
    cl = _client()
    if cl is None:
        return False                       # unavailable -> KHONG dam bao da xoa
    global _last_error
    try:
        col = cl.get_collection(CHROMA_COLLECTION)
    except Exception as e:
        if _is_absent(e):
            return True                    # collection thuc su khong co -> khong gi de xoa = OK
        _last_error = f"get_collection: {e}"
        print(f"[warn] vector get_collection loi (KHONG phai absent): {e}")
        return False                       # loi IO/corrupt -> bao that bai that
    try:
        col.delete(where=where)
        return True
    except Exception as e:
        _last_error = f"delete: {e}"
        print(f"[warn] vector delete loi: {e}")
        return False


def delete_file(path, project_id=None, generation=None):
    """Xoa vector 1 file. project_id -> chi trong project do (#P0-8); generation -> CHI xoa vector
    gen <= generation (intent cu khong xoa vector moi sau re-index #P0-10)."""
    conds = [{"file_path": path}]
    if project_id is not None:
        conds.append({"project_id": project_id})
    if generation:                          # CHI gate khi gen>=1; gen 0/None (legacy) -> xoa het, khong orphan
        conds.append({"generation": {"$lte": generation}})
    where = conds[0] if len(conds) == 1 else {"$and": conds}
    return _delete_where(where)


def delete_project(project_id):
    return _delete_where({"project_id": project_id})


def clear_all():
    """Xoa collection (khong load embedding). True chi khi that su xoa duoc/absent."""
    global _collection, _raw_col, _embed_failed, _raw_failed
    cl = _client()
    if cl is None:
        return False                       # khong mo duoc chroma -> bao that bai that
    ok = True
    try:
        cl.delete_collection(CHROMA_COLLECTION)
    except Exception as e:
        if _is_absent(e):
            ok = True                      # khong co collection = da sach
        else:
            globals()["_last_error"] = f"clear_all: {e}"
            print(f"[warn] vector clear_all delete_collection loi: {e}")
            ok = False                     # loi that -> KHONG bao True oan
    _collection = None
    _raw_col = None
    _embed_failed = False
    _raw_failed = False
    return ok


def index_file(path, lang, skeleton, symbols, project_id=None, generation=0):
    col = get_collection()
    if col is None:
        return False                       # lexical mode: bo qua vector (van index SQLite)
    delete_file(path, project_id=project_id)   # chi xoa vector cu cua dung project nay
    docs, metas, ids = [], [], []
    base = {"file_path": path, "lang": lang, "project_id": project_id, "generation": generation}
    docs.append(skeleton)
    metas.append({**base, "kind": "file", "name": path})
    ids.append(f"{project_id}::{path}::file")
    for i, s in enumerate(symbols):
        text = f"{s['kind']} {s['name']}"
        if s.get("parent"):
            text += f" in {s['parent']}"
        text += f"\n{s['signature']}"
        if s.get("doc"):
            text += f"\n{s['doc']}"
        docs.append(text)
        metas.append({**base, "kind": s["kind"], "name": s["name"], "start_line": s["start_line"]})
        ids.append(f"{project_id}::{path}::sym::{i}")
    try:
        col.add(documents=docs, metadatas=metas, ids=ids)
        return True
    except Exception as e:
        print(f"[warn] vector index_file loi: {e}")
        return False


def index_summary(path, lang, summary, project_id=None, generation=0):
    col = get_collection()
    if col is None or not summary:
        return
    sid = f"{project_id}::{path}::summary"
    try:
        col.delete(ids=[sid])
        col.add(documents=[summary],
                metadatas=[{"file_path": path, "lang": lang, "kind": "summary",
                            "name": path, "project_id": project_id, "generation": generation}],
                ids=[sid])
    except Exception as e:
        print(f"[warn] vector index_summary loi: {e}")


def query(text, n=12, project_id=None):
    col = get_collection()
    if col is None:
        return []
    try:
        count = col.count()
        if count == 0:
            return []
        kw = {"query_texts": [text], "n_results": min(n, count),
              "include": ["metadatas", "distances"]}
        if project_id is not None:
            kw["where"] = {"project_id": project_id}
        res = col.query(**kw)
    except Exception as e:
        print(f"[warn] vector query loi: {e}")
        return []
    metas = (res.get("metadatas") or [[]])[0] or []
    dists = (res.get("distances") or [[]])[0] or []
    out = []
    for i, m in enumerate(metas):
        m = dict(m)
        m["_distance"] = dists[i] if i < len(dists) else None
        out.append(m)
    return out
