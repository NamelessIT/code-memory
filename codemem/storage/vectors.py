"""ChromaDB: vector index cho symbol + skeleton (semantic search)."""
from ..config import CHROMA_DIR, CHROMA_COLLECTION, EMBED_MODEL, ensure_dirs

_collection = None
_client = None
_ef = None


def get_collection():
    """Lazy-load (giong brain.py). Tra None neu chromadb chua cai."""
    global _collection, _client, _ef
    if _collection is None:
        try:
            import chromadb
            from chromadb.utils import embedding_functions
            ensure_dirs()
            _ef = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name=EMBED_MODEL
            )
            _client = chromadb.PersistentClient(path=str(CHROMA_DIR))
            _collection = _client.get_or_create_collection(
                CHROMA_COLLECTION, embedding_function=_ef
            )
        except ImportError:
            print("[warn] chromadb chua cai -> chi dung keyword search")
            return None
    return _collection


def clear_all():
    """Xoa toan bo vector collection (khi wipe/doi project)."""
    global _collection
    col = get_collection()
    if col is None:
        return
    try:
        _client.delete_collection(CHROMA_COLLECTION)
        _collection = _client.get_or_create_collection(
            CHROMA_COLLECTION, embedding_function=_ef
        )
    except Exception:
        pass


def delete_file(path):
    col = get_collection()
    if col is None:
        return
    try:
        col.delete(where={"file_path": path})
    except Exception:
        pass


def delete_project(project_id):
    col = get_collection()
    if col is None:
        return
    try:
        col.delete(where={"project_id": project_id})
    except Exception:
        pass


def index_file(path, lang, skeleton, symbols, project_id=None):
    """Them skeleton + tung symbol cua file vao vector index (gan project_id)."""
    col = get_collection()
    if col is None:
        return
    delete_file(path)

    docs, metas, ids = [], [], []
    base = {"file_path": path, "lang": lang, "project_id": project_id}

    docs.append(skeleton)
    metas.append({**base, "kind": "file", "name": path})
    ids.append(f"{path}::file")

    for i, s in enumerate(symbols):
        text = f"{s['kind']} {s['name']}"
        if s.get("parent"):
            text += f" in {s['parent']}"
        text += f"\n{s['signature']}"
        if s.get("doc"):
            text += f"\n{s['doc']}"
        docs.append(text)
        metas.append({**base, "kind": s["kind"], "name": s["name"], "start_line": s["start_line"]})
        ids.append(f"{path}::sym::{i}")

    if docs:
        col.add(documents=docs, metadatas=metas, ids=ids)


def index_summary(path, lang, summary, project_id=None):
    col = get_collection()
    if col is None or not summary:
        return
    sid = f"{path}::summary"
    try:
        col.delete(ids=[sid])
    except Exception:
        pass
    col.add(documents=[summary],
            metadatas=[{"file_path": path, "lang": lang, "kind": "summary",
                        "name": path, "project_id": project_id}],
            ids=[sid])


def query(text, n=12, project_id=None):
    """Semantic search trong 1 project -> list metadata (kem _distance)."""
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
    except Exception:
        return []
    metas = (res.get("metadatas") or [[]])[0] or []
    dists = (res.get("distances") or [[]])[0] or []
    out = []
    for i, m in enumerate(metas):
        m = dict(m)
        m["_distance"] = dists[i] if i < len(dists) else None
        out.append(m)
    return out


def available():
    """True neu vector store (chromadb + embedding) dung duoc -> de bao degraded mode."""
    return get_collection() is not None
