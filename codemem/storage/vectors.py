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


def _raw():
    """Collection de delete/count (KHONG cung cap ef -> khong load model, khong ghi de ef config).
    Dung get_collection (retrieve), neu chua ton tai -> None (khong co gi de xoa)."""
    try:
        import chromadb
        ensure_dirs()
        client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        return client.get_collection(CHROMA_COLLECTION)
    except Exception:
        return None


def health():
    """Trang thai cho /api/health: chroma co dung khong (khong ep load embedding)."""
    return {"chroma": _raw() is not None, "embedding_failed": _embed_failed, "error": _last_error}


def available():
    return _raw() is not None


def delete_file(path):
    col = _raw()
    if col is None:
        return
    try:
        col.delete(where={"file_path": path})
    except Exception as e:
        print(f"[warn] vector delete_file loi: {e}")


def delete_project(project_id):
    col = _raw()
    if col is None:
        return
    try:
        col.delete(where={"project_id": project_id})
    except Exception as e:
        print(f"[warn] vector delete_project loi: {e}")


def clear_all():
    """Xoa collection (khong load embedding, KHONG tao lai voi ef 'default').
    Lan get_collection() sau se tao lai voi embedding function dung."""
    global _collection, _raw_col, _embed_failed, _raw_failed
    try:
        import chromadb
        ensure_dirs()
        client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        try:
            client.delete_collection(CHROMA_COLLECTION)
        except Exception:
            pass
    except Exception as e:
        print(f"[warn] vector clear_all loi: {e}")
    _collection = None
    _raw_col = None
    _embed_failed = False     # reset de thu lai
    _raw_failed = False


def index_file(path, lang, skeleton, symbols, project_id=None):
    col = get_collection()
    if col is None:
        return False                       # lexical mode: bo qua vector (van index SQLite)
    delete_file(path)
    docs, metas, ids = [], [], []
    base = {"file_path": path, "lang": lang, "project_id": project_id}
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


def index_summary(path, lang, summary, project_id=None):
    col = get_collection()
    if col is None or not summary:
        return
    sid = f"{project_id}::{path}::summary"
    try:
        col.delete(ids=[sid])
        col.add(documents=[summary],
                metadatas=[{"file_path": path, "lang": lang, "kind": "summary",
                            "name": path, "project_id": project_id}],
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
