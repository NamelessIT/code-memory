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


def index_file(path, lang, skeleton, symbols):
    """Them skeleton + tung symbol cua file vao vector index."""
    col = get_collection()
    if col is None:
        return
    delete_file(path)

    docs, metas, ids = [], [], []

    # 1 doc cho skeleton ca file
    docs.append(skeleton)
    metas.append({"file_path": path, "lang": lang, "kind": "file", "name": path})
    ids.append(f"{path}::file")

    # 1 doc moi symbol
    for i, s in enumerate(symbols):
        text = f"{s['kind']} {s['name']}"
        if s.get("parent"):
            text += f" in {s['parent']}"
        text += f"\n{s['signature']}"
        docs.append(text)
        metas.append({
            "file_path": path, "lang": lang, "kind": s["kind"],
            "name": s["name"], "start_line": s["start_line"],
        })
        ids.append(f"{path}::sym::{i}")

    if docs:
        col.add(documents=docs, metadatas=metas, ids=ids)


def index_summary(path, lang, summary):
    """Them/cap nhat doc tom tat cua file vao vector index."""
    col = get_collection()
    if col is None or not summary:
        return
    sid = f"{path}::summary"
    try:
        col.delete(ids=[sid])
    except Exception:
        pass
    col.add(
        documents=[summary],
        metadatas=[{"file_path": path, "lang": lang, "kind": "summary", "name": path}],
        ids=[sid],
    )


def query(text, n=12):
    """Semantic search -> list metadata (kem file_path, name, kind...)."""
    col = get_collection()
    if col is None:
        return []
    try:
        count = col.count()
        if count == 0:
            return []
        res = col.query(query_texts=[text], n_results=min(n, count))
    except Exception:
        return []
    metas = res.get("metadatas", [[]])[0]
    return metas or []
